import requests
import logging
import telebot
import urllib.parse
import time

# ============================
# CONFIGURACIÓN
# ============================

# ⚠️ Tokens incluidos directamente como pediste
BOT_TOKEN = "8502790665:AAHuanhfYIe5ptUliYQBP7ognVOTG0uQoKk"
MOODLE_TOKEN = "784e9718073ccee20854df8a10536659"
MOODLE_URL = "https://aulaelam.sld.cu"

MAX_FILE_SIZE_MB = 50
MAX_RETRIES_UPLOAD = 3  # Número de reintentos de subida

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# ============================
# SESIÓN GLOBAL CON RETRIES
# ============================

def crear_sesion_aulaelam():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Origin': MOODLE_URL,
        'Referer': f'{MOODLE_URL}/',
    })
    from requests.adapters import HTTPAdapter
    from requests.packages.urllib3.util.retry import Retry
    retry_strategy = Retry(total=3, backoff_factor=1)
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    return session

session_global = crear_sesion_aulaelam()

# ============================
# FUNCIONES DE SUBIDA
# ============================

def subir_archivo_web_real(file_content, file_name):
    """Sube un archivo a Moodle con reintentos automáticos"""
    for attempt in range(1, MAX_RETRIES_UPLOAD + 1):
        try:
            logger.info(f"🌐 Intento {attempt} - Subiendo: {file_name}")

            # 1. Obtener info del sitio
            info_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_webservice_get_site_info',
                'moodlewsrestformat': 'json'
            }
            response = session_global.get(info_url, params=params, timeout=15)
            if response.status_code != 200:
                raise Exception(f'Error conexión: {response.status_code}')
            site_info = response.json()
            user_id = site_info.get('userid')
            logger.info(f"👤 Usuario ID: {user_id}")

            # 2. Subida de archivo
            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            files = {'file': (file_name, file_content)}
            data = {
                'token': MOODLE_TOKEN,
                'filearea': 'draft',
                'itemid': 0,
                'client_id': user_id
            }
            upload_response = session_global.post(upload_url, files=files, data=data, timeout=30)
            if upload_response.status_code != 200:
                raise Exception(f'Error subida: {upload_response.status_code}')

            upload_result = upload_response.json()
            if not upload_result or len(upload_result) == 0:
                raise Exception('No se recibieron datos de subida')
            file_data = upload_result[0]
            itemid = file_data.get('itemid')
            contextid = file_data.get('contextid')
            if not itemid:
                raise Exception('No se obtuvo itemid')
            logger.info(f"📁 Archivo subido - ItemID: {itemid}, ContextID: {contextid}")

            # 3. Crear evento en calendario
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
            session_global.post(event_url, data=event_data, timeout=20)

            # 4. Generar enlace final
            file_name_encoded = urllib.parse.quote(f"inline; {file_name}")
            enlace_final = (
                f"{MOODLE_URL}/webservice/pluginfile.php/"
                f"{contextid}/calendar/event_description/"
                f"{itemid}/{file_name_encoded}"
                f"?token={MOODLE_TOKEN}"
            )

            # 5. Verificación del enlace
            try:
                verify = session_global.head(enlace_final, timeout=10, allow_redirects=True)
                enlace_funciona = verify.status_code == 200
            except:
                enlace_funciona = False

            return {
                'exito': True,
                'enlace': enlace_final,
                'nombre': file_name,
                'tamaño': file_data.get('filesize', 0),
                'itemid': itemid,
                'contextid': contextid,
                'enlace_verificado': enlace_funciona,
                'user_id': user_id
            }

        except Exception as e:
            logger.warning(f"Intento {attempt} fallido: {e}")
            if attempt < MAX_RETRIES_UPLOAD:
                time.sleep(3)  # Espera antes del siguiente intento
            else:
                return {'exito': False, 'error': str(e)}

# ============================
# MANEJADORES TELEGRAM
# ============================

@bot.message_handler(commands=['start'])
def start_command(message):
    text = f"""
🤖 **BOT AULAELAM - WEB REAL** 🤖

✅ Interactúa con la web real de AulaElam  
✅ Sesiones de navegador real  
✅ Enlaces idénticos a los originales

🌐 **Proceso:**
1. Conexión web real con sesión
2. Subida mediante formularios web  
3. Creación de evento real en calendario
4. Generación de enlace idéntico

📎 **¡Envía un archivo para probar!**
"""
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    try:
        file_info = bot.get_file(message.document.file_id)
        file_name = message.document.file_name
        file_size = message.document.file_size
        logger.info(f"📥 Recibido: {file_name} ({file_size / 1024 / 1024:.2f} MB)")

        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return

        mensaje = bot.reply_to(message, f"🌐 *{file_name}*\n🔄 Conectando con AulaElam web...", parse_mode='Markdown')
        downloaded_file = bot.download_file(file_info.file_path)

        resultado = subir_archivo_web_real(downloaded_file, file_name)

        if resultado['exito']:
            status = "✅ Verificado" if resultado.get('enlace_verificado') else "⚠️ Por verificar"
            respuesta = (
                f"🎉 *¡SUBIDO A WEB REAL!*\n\n"
                f"📄 **Archivo:** `{resultado['nombre']}`\n"
                f"💾 **Tamaño:** {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"👤 **Usuario ID:** `{resultado.get('user_id', 'N/A')}`\n"
                f"🆔 **ItemID:** `{resultado['itemid']}`\n"
                f"🔧 **ContextID:** `{resultado['contextid']}`\n"
                f"🔍 **Estado:** {status}\n\n"
                f"🔗 **ENLACE IDÉNTICO A AULAELAM:**\n"
                f"`{resultado['enlace']}`"
            )
            bot.edit_message_text(chat_id=message.chat.id, message_id=mensaje.message_id, text=respuesta, parse_mode='Markdown')
            bot.send_message(message.chat.id, f"📎 **Enlace exacto:**\n{resultado['enlace']}", parse_mode='Markdown')
        else:
            bot.edit_message_text(chat_id=message.chat.id, message_id=mensaje.message_id, text=f"❌ **Error web real:** {resultado['error']}", parse_mode='Markdown')

    except Exception as e:
        logger.error(f"Error manejando documento: {e}")
        bot.reply_to(message, f"❌ **Error:** {str(e)}", parse_mode='Markdown')

# ============================
# MAIN
# ============================

def main():
    logger.info("🚀 BOT AULAELAM - WEB REAL INICIADO")
    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"Bot reiniciado por error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
