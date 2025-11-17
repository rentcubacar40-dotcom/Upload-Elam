import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time
import re
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
import tempfile

# ============================
# TOKENS Y CONFIGURACIÓN
# ============================
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

# ============================
# ESCAPE MARKDOWNV2
# ============================
def escape_md(text: str) -> str:
    if text is None:
        return ''
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

# ============================
# PROXIES CUBANOS
# ============================
CUBAN_PROXIES = [
    "http://190.6.82.94:8080",
    "http://190.6.81.150:8080",
    "http://152.206.125.20:8080",
    "http://152.206.135.55:8080"
]
ACTIVE_PROXY = None

def test_proxy(proxy: str) -> bool:
    try:
        proxies = {"http": proxy, "https": proxy}
        r = requests.get(f"{MOODLE_URL}/login/index.php", proxies=proxies, timeout=12)
        return r.status_code == 200
    except:
        return False

def get_active_proxy() -> str:
    global ACTIVE_PROXY
    if ACTIVE_PROXY:
        return ACTIVE_PROXY
    for p in CUBAN_PROXIES:
        if test_proxy(p):
            ACTIVE_PROXY = p
            logger.info(f"[OK] Proxy cubano detectado: {p}")
            return p
    raise Exception("No hay proxies cubanos funcionales.")

def cuban_request(url: str, method="GET", data=None, files=None):
    proxy = get_active_proxy()
    proxies = {"http": proxy, "https": proxy}
    if method == "GET":
        return requests.get(url, proxies=proxies, timeout=45)
    else:
        return requests.post(url, proxies=proxies, data=data, files=files, timeout=45)

# ============================
# CREAR SESIÓN WEB
# ============================
def crear_sesion_aulaelam():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Origin': MOODLE_URL,
        'Referer': f'{MOODLE_URL}/',
    })
    retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[429,500,502,503,504], allowed_methods=False)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

_session_global = crear_sesion_aulaelam()

# ============================
# PRECARGA COOKIES
# ============================
def precargar_sesion_avanzada(session):
    urls_prueba = ["/", "/index.php", "/login/index.php", "/my/", "/webservice/rest/server.php", "/webservice/info.php"]
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

try:
    precargar_sesion_avanzada(_session_global)
except Exception as e:
    logger.warning(f"Precarga inicial falló: {e}")

# ============================
# SUBIDA A MOODLE
# ============================
def _debug_upload_response(resp):
    try:
        txt = resp.text[:1000]
    except:
        txt = "<no text>"
    logger.info(f"Upload response status={resp.status_code}, len(content)={len(resp.content)}, text_preview={txt!r}")

def subir_archivo_web_real(file_content: bytes, file_name: str):
    for attempt in range(1, MAX_RETRIES_UPLOAD + 1):
        try:
            logger.info(f"🌐 Intento {attempt} - Subiendo: {file_name}")
            session = _session_global
            cookies = session.cookies.get_dict()
            if not cookies:
                precargar_sesion_avanzada(session)

            info_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {'wstoken': MOODLE_TOKEN, 'wsfunction': 'core_webservice_get_site_info', 'moodlewsrestformat': 'json'}
            info_resp = cuban_request(info_url, method="GET")
            if info_resp.status_code != 200:
                raise Exception(f"Error conexión site_info: {info_resp.status_code}")
            site_info = info_resp.json()
            user_id = site_info.get('userid')
            logger.info(f"👤 Usuario ID: {user_id}")

            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            files = {'file': (file_name, file_content)}
            data = {'token': MOODLE_TOKEN, 'filearea': 'draft', 'itemid': 0}
            upload_resp = cuban_request(upload_url, method="POST", data=data, files=files)
            _debug_upload_response(upload_resp)

            if upload_resp.status_code != 200 or len(upload_resp.content) == 0:
                raise Exception(f"Error inesperado en upload.php: status={upload_resp.status_code}, len={len(upload_resp.content)}")

            upload_result = upload_resp.json()
            if not upload_result or len(upload_result) == 0:
                raise Exception("upload.php devolvió array vacío")

            file_data = upload_result[0]
            itemid = file_data.get('itemid')
            contextid = file_data.get('contextid')
            if not itemid:
                raise Exception("No se obtuvo itemid del upload_result")
            logger.info(f"📁 Archivo subido: itemid={itemid} contextid={contextid}")

            file_name_encoded = urllib.parse.quote(f"inline; {file_name}")
            enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{contextid}/calendar/event_description/{itemid}/{file_name_encoded}?token={MOODLE_TOKEN}"

            enlace_verificado = False
            try:
                verify = cuban_request(enlace_final, method="GET")
                enlace_verificado = (verify.status_code == 200)
            except:
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
                try:
                    precargar_sesion_avanzada(_session_global)
                except:
                    pass
                continue
            else:
                return {'exito': False, 'error': str(e)}

# ============================
# PROCESAR Y SUBIR FILE
# ============================
def procesar_y_subir_file(chat_id, message_obj, file_id, file_name, file_size):
    try:
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
        mensaje = bot.reply_to(message_obj, f"🌐 *{escape_md(file_name)}*\n🔄 Conectando con AulaElam web...", parse_mode='MarkdownV2')
        resultado = subir_archivo_web_real(downloaded, file_name)
        if resultado['exito']:
            status = "✅ Verificado" if resultado.get('enlace_verificado') else "⚠️ Por verificar"
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
            bot.send_message(chat_id, f"📎 Enlace exacto:\n{resultado['enlace']}")
        else:
            bot.edit_message_text(chat_id=chat_id, message_id=mensaje.message_id, text=f"❌ Error al subir archivo\n\nArchivo: {escape_md(file_name)}\nError: {escape_md(resultado.get('error',''))}", parse_mode='MarkdownV2')
    except Exception as e:
        bot.reply_to(message_obj, f"❌ **Error:** {str(e)}", parse_mode=None)

# ============================
# HANDLERS TELEGRAM
# ============================
@bot.message_handler(commands=['start'])
def handle_start(message):
    text = (
        "🤖 *BOT AULAELAM - WEB REAL* 🤖\n\n"
        "✅ Envía cualquier archivo (foto, video, audio, document, voice, animation).\n"
        "✅ Se subirá a Moodle y recibirás un enlace directo.\n"
    )
    bot.send_message(message.chat.id, text, parse_mode='MarkdownV2')

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    file_id = message.document.file_id
    file_name = message.document.file_name
    file_size = message.document.file_size
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
        return
    procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)

@bot.message_handler(content_types=['photo'])
def manejar_foto(message):
    best = message.photo[-1]
    file_id = best.file_id
    file_name = f"photo_{message.from_user.id}_{int(time.time())}.jpg"
    file_size = best.file_size or 0
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
        return
    procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)

@bot.message_handler(content_types=['video'])
def manejar_video(message):
    file_id = message.video.file_id
    file_name = message.video.file_name or f"video_{message.from_user.id}_{int(time.time())}.mp4"
    file_size = message.video.file_size or 0
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
        return
    procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)

@bot.message_handler(content_types=['audio'])
def manejar_audio(message):
    file_id = message.audio.file_id
    file_name = message.audio.file_name or f"audio_{message.from_user.id}_{int(time.time())}.mp3"
    file_size = message.audio.file_size or 0
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
        return
    procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)

@bot.message_handler(content_types=['voice'])
def manejar_voice(message):
    file_id = message.voice.file_id
    file_name = f"voice_{message.from_user.id}_{int(time.time())}.ogg"
    file_size = message.voice.file_size or 0
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
        return
    procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)

@bot.message_handler(content_types=['animation'])
def manejar_animation(message):
    file_id = message.animation.file_id
    file_name = message.animation.file_name or f"anim_{message.from_user.id}_{int(time.time())}.gif"
    file_size = message.animation.file_size or 0
    if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
        return
    procesar_y_subir_file(message.chat.id, message, file_id, file_name, file_size)

# ============================
# MAIN
# ============================
def main():
    logger.info("🚀 BOT AULAELAM - WEB REAL - INICIANDO")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
