import requests
import logging
import telebot
import urllib.parse
import time
import re
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

# ================
# CONFIGURACIÓN
# ================

BOT_TOKEN = "8502790665:AAHuanhfYIe5ptUliYQBP7ognVOTG0uQoKk"
MOODLE_TOKEN = "784e9718073ccee20854df8a10536659"
MOODLE_URL = "https://aulaelam.sld.cu"

MAX_FILE_SIZE_MB = 50
UPLOAD_TIMEOUT = 120
PRELOAD_TIMEOUT = 15
MAX_RETRIES_UPLOAD = 3

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# ============================================================
# UTIL: escape MarkdownV2 (uso consistente en todo el bot)
# ============================================================
def escape_md(text: str) -> str:
    if text is None:
        return ''
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# ============================================================
# SESIÓN GLOBAL (creamos adapter con retries reutilizable)
# ============================================================
def crear_sesion_base():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Origin': MOODLE_URL,
        'Referer': MOODLE_URL + "/",
        'Connection': 'keep-alive',
        'Expect': ''  # importante para algunos moodles que requieren header vacío
    })
    retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504], allowed_methods=False)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# Creamos una sesión base reutilizable
_session_global = crear_sesion_base()

# ============================================================
# PRECARGA AUTOMÁTICA DE COOKIES (detecta la URL que establece cookies)
# ============================================================
def precargar_sesion_avanzada(session):
    urls_prueba = [
        "/",                        
        "/index.php",              
        "/login/index.php",        
        "/my/",                    
        "/webservice/rest/server.php",
        "/webservice/info.php"
    ]

    logger.info("🔍 Iniciando detección automática de cookies Moodle...")
    for ruta in urls_prueba:
        url = MOODLE_URL + ruta
        try:
            r = session.get(url, timeout=PRELOAD_TIMEOUT)
            cookies = session.cookies.get_dict()
            logger.info(f"🌐 Probando: {url} → Status {r.status_code}")
            logger.info(f"🟡 Cookies recibidas: {cookies}")
            if "MoodleSession" in cookies or "MoodleSessionTest" in cookies:
                logger.info(f"🟢 COOKIE DETECTADA en: {url}")
                return True
        except Exception as e:
            logger.debug(f"Error probando {url}: {e}")
    logger.warning("⚠️ No se detectaron cookies. Se continuará sin cookies.")
    return False

# Ejecutar precarga una vez al iniciar
try:
    precargar_sesion_avanzada(_session_global)
except Exception as e:
    logger.warning(f"Precarga inicial falló: {e}")

# ============================================================
# FUNCIONES AUXILIARES DE SUBIDA/DEBUG
# ============================================================
def _debug_upload_response(resp):
    try:
        txt = resp.text[:1000]
    except Exception:
        txt = "<no text>"
    logger.info(f"Upload response status={resp.status_code}, len(content)={len(resp.content)}, text_preview={txt!r}")

# ============================================================
# SUBIDA A MOODLE (robusta, con reintentos y manejo de respuestas vacías)
# ============================================================
def subir_archivo_web_real(file_content: bytes, file_name: str):
    """
    Sube archivo usando upload.php y devuelve dict con 'exito' y datos o 'error'.
    """
    for attempt in range(1, MAX_RETRIES_UPLOAD + 1):
        try:
            logger.info(f"🌐 Intento {attempt} - Subiendo: {file_name}")

            # Aseguramos la sesión y (re)precargamos cookies si es necesario
            session = _session_global
            # intentar verificar que haya cookies; si no, intentar precargar otra vez
            cookies = session.cookies.get_dict()
            if not cookies:
                precargar_sesion_avanzada(session)

            # 1) Obtener site info para user id
            info_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {'wstoken': MOODLE_TOKEN, 'wsfunction': 'core_webservice_get_site_info', 'moodlewsrestformat': 'json'}
            info_resp = session.get(info_url, params=params, timeout=PRELOAD_TIMEOUT)
            if info_resp.status_code != 200:
                raise Exception(f"Error conexión site_info: {info_resp.status_code}")
            try:
                site_info = info_resp.json()
            except ValueError:
                raise Exception("Respuesta site_info no es JSON")
            user_id = site_info.get('userid')
            logger.info(f"👤 Usuario ID: {user_id}")

            # 2) Upload
            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            files = {'file': (file_name, file_content)}
            data = {'token': MOODLE_TOKEN, 'filearea': 'draft', 'itemid': 0}
            upload_resp = session.post(upload_url, files=files, data=data, timeout=UPLOAD_TIMEOUT)
            _debug_upload_response(upload_resp)

            # si respuesta vacía o status !=200 => reintentar o fallar
            if upload_resp.status_code != 200 or len(upload_resp.content) == 0:
                raise Exception(f"Error inesperado en upload.php: status={upload_resp.status_code}, len={len(upload_resp.content)}")

            # parsear json
            try:
                upload_result = upload_resp.json()
            except ValueError:
                preview = upload_resp.text[:800]
                raise Exception(f"Respuesta no-JSON de upload.php: {preview}")

            if not upload_result or len(upload_result) == 0:
                raise Exception("upload.php devolvió array vacío")

            file_data = upload_result[0]
            itemid = file_data.get('itemid')
            contextid = file_data.get('contextid')
            if not itemid:
                raise Exception("No se obtuvo itemid del upload_result")
            logger.info(f"📁 Archivo subido: itemid={itemid} contextid={contextid}")

            # 3) Crear evento en calendario (no fatal si falla)
            try:
                event_url = f"{MOODLE_URL}/webservice/rest/server.php"
                event_data = {
                    'wstoken': MOODLE_TOKEN,
                    'wsfunction': 'core_calendar_submit_create_update_form',
                    'moodlewsrestformat': 'json',
                    'formdata': urllib.parse.urlencode({
                        'id': 0,
                        'userid': user_id,
                        'name': f'Archivo: {file_name}',
                        'timestart': int(time.time()) + 3600,
                        'eventtype': 'user',
                        'description[text]': f'Archivo subido via Bot: {file_name}',
                        'description[format]': 1,
                        'files[0]': itemid
                    })
                }
                ev_resp = session.post(event_url, data=event_data, timeout=30)
                logger.info(f"Evento calendar status: {ev_resp.status_code}")
            except Exception as e:
                logger.warning(f"No se pudo crear evento (no fatal): {e}")

            # 4) Generar enlace pluginfile
            file_name_encoded = urllib.parse.quote(f"inline; {file_name}")
            enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{contextid}/calendar/event_description/{itemid}/{file_name_encoded}?token={MOODLE_TOKEN}"

            # 5) Verificación HEAD
            enlace_verificado = False
            try:
                verify = session.head(enlace_final, timeout=15, allow_redirects=True)
                enlace_verificado = (verify.status_code == 200)
                logger.info(f"Verificación enlace status={verify.status_code}")
            except Exception as e:
                logger.warning(f"Verificación enlace falló: {e}")
                enlace_verificado = False

            return {
                'exito': True,
                'enlace': enlace_final,
                'nombre': file_name,
                'tamaño': file_data.get('filesize', 0),
                'itemid': itemid,
                'contextid': contextid,
                'user_id': user_id,
                'enlace_verificado': enlace_verificado
            }

        except Exception as e:
            logger.warning(f"Intento {attempt} fallido: {e}")
            if attempt < MAX_RETRIES_UPLOAD:
                time.sleep(3)
                # re-precargar en caso de que la sesión haya quedado en mal estado
                try:
                    precargar_sesion_avanzada(_session_global)
                except:
                    pass
                continue
            else:
                return {'exito': False, 'error': str(e)}

# ============================================================
# FUNCIONES DE DESCARGA DESDE TELEGRAM Y PROCESO GENERAL
# ============================================================
def procesar_y_subir_file(chat_id, message_obj, file_id, file_name, file_size):
    try:
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
    except Exception as e:
        logger.error(f"Error descargando archivo desde Telegram: {e}")
        bot.reply_to(message_obj, "❌ Error descargando archivo desde Telegram. Intenta nuevamente.", parse_mode=None)
        return

    try:
        waiting_text = f"🌐 *{escape_md(file_name)}*\n🔄 Conectando con AulaElam web..."
        mensaje = bot.reply_to(message_obj, waiting_text, parse_mode='MarkdownV2')
    except Exception:
        mensaje = bot.reply_to(message_obj, f"🌐 {file_name}\n🔄 Conectando con AulaElam web...", parse_mode=None)

    resultado = subir_archivo_web_real(downloaded, file_name)

    if resultado.get('exito'):
        status = "✅ Verificado" if resultado.get('enlace_verificado') else "⚠️ Por verificar"
        try:
            respuesta = (
                f"🎉 *¡SUBIDO A WEB REAL!*\n\n"
                f"📄 **Archivo:** `{escape_md(resultado['nombre'])}`\n"
                f"💾 **Tamaño:** {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"👤 **Usuario ID:** `{escape_md(str(resultado.get('user_id', 'N/A')))}`\n"
                f"🆔 **ItemID:** `{escape_md(str(resultado['itemid']))}`\n"
                f"🔧 **ContextID:** `{escape_md(str(resultado['contextid']))}`\n"
                f"🔍 **Estado:** {status}\n\n"
                f"🔗 **ENLACE:**\n{escape_md(resultado['enlace'])}"
            )
            bot.edit_message_text(chat_id=chat_id, message_id=mensaje.message_id, text=respuesta, parse_mode='MarkdownV2')
        except Exception:
            simple = (
                f"🎉 ¡SUBIDO A WEB REAL!\nArchivo: {resultado['nombre']}\nTamaño: {resultado['tamaño'] / 1024 / 1024:.2f} MB\nItemID: {resultado['itemid']}\nContextID: {resultado['contextid']}\nEstado: {status}\nEnlace: {resultado['enlace']}"
            )
            bot.edit_message_text(chat_id=chat_id, message_id=mensaje.message_id, text=simple, parse_mode=None)
        # enviar enlace simple
        bot.send_message(chat_id, f"📎 Enlace exacto:\n{resultado['enlace']}", parse_mode=None)
    else:
        err = resultado.get('error', 'Error desconocido')
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=mensaje.message_id,
                                  text=f"❌ Error al subir archivo\n\nArchivo: {escape_md(file_name)}\nError: {escape_md(err)}\n\nIntenta nuevamente o verifica la conexión.",
                                  parse_mode='MarkdownV2')
        except Exception:
            bot.edit_message_text(chat_id=chat_id, message_id=mensaje.message_id,
                                  text=f"❌ Error al subir archivo\n\nArchivo: {file_name}\nError: {err}\n\nIntenta nuevamente o verifica la conexión.",
                                  parse_mode=None)

# ============================================================
# HANDLERS TELEGRAM (soporte foto, video, audio, voice, document, animation)
# ============================================================
@bot.message_handler(commands=['start'])
def handle_start(message):
    text = (
        "🤖 *BOT AULAELAM - WEB REAL* 🤖\n\n"
        "✅ Envía cualquier archivo (foto, video, audio, document).\n"
        "✅ Se subirá a Moodle y recibirás un enlace directo.\n"
    )
    try:
        bot.send_message(message.chat.id, text, parse_mode='MarkdownV2')
    except Exception:
        bot.send_message(message.chat.id, text, parse_mode=None)

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    try:
        file_id = message.document.file_id
        file_name = message.document.file_name or f"document_{int(time.time())}"
        file_size = message.document.file_size or 0
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return
        procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)
    except Exception as e:
        logger.error(f"Error en manejar_documento: {e}")
        bot.reply_to(message, "❌ Error procesando el documento.", parse_mode=None)

@bot.message_handler(content_types=['photo'])
def manejar_foto(message):
    try:
        best = message.photo[-1]
        file_id = best.file_id
        file_name = f"photo_{message.from_user.id}_{int(time.time())}.jpg"
        file_size = best.file_size or 0
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return
        procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)
    except Exception as e:
        logger.error(f"Error en manejar_foto: {e}")
        bot.reply_to(message, "❌ Error procesando la foto.", parse_mode=None)

@bot.message_handler(content_types=['video'])
def manejar_video(message):
    try:
        file_id = message.video.file_id
        file_name = message.video.file_name or f"video_{message.from_user.id}_{int(time.time())}.mp4"
        file_size = message.video.file_size or 0
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return
        procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)
    except Exception as e:
        logger.error(f"Error en manejar_video: {e}")
        bot.reply_to(message, "❌ Error procesando el video.", parse_mode=None)

@bot.message_handler(content_types=['audio'])
def manejar_audio(message):
    try:
        file_id = message.audio.file_id
        file_name = message.audio.file_name or f"audio_{message.from_user.id}_{int(time.time())}.mp3"
        file_size = message.audio.file_size or 0
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return
        procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)
    except Exception as e:
        logger.error(f"Error en manejar_audio: {e}")
        bot.reply_to(message, "❌ Error procesando el audio.", parse_mode=None)

@bot.message_handler(content_types=['voice'])
def manejar_voice(message):
    try:
        file_id = message.voice.file_id
        file_name = f"voice_{message.from_user.id}_{int(time.time())}.ogg"
        file_size = message.voice.file_size or 0
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return
        procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)
    except Exception as e:
        logger.error(f"Error en manejar_voice: {e}")
        bot.reply_to(message, "❌ Error procesando el voice.", parse_mode=None)

@bot.message_handler(content_types=['animation'])
def manejar_animation(message):
    try:
        file_id = message.animation.file_id
        file_name = message.animation.file_name or f"anim_{message.from_user.id}_{int(time.time())}.gif"
        file_size = message.animation.file_size or 0
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return
        procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)
    except Exception as e:
        logger.error(f"Error en manejar_animation: {e}")
        bot.reply_to(message, "❌ Error procesando la animación.", parse_mode=None)

# ============================================================
# MAIN - reinicio automático
# ============================================================
def main():
    logger.info("🚀 BOT AULAELAM - WEB REAL - INICIANDO")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Bot reiniciado por error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
