import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time
import re
import sys
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from bs4 import BeautifulSoup

# ============================
# CONFIGURACIÓN
# ============================
BOT_TOKEN = "8502790665:AAHuanhfYIe5ptUliYQBP7ognVOTG0uQoKk"
MOODLE_TOKEN = "784e9718073ccee20854df8a10536659"
MOODLE_URL = "https://aulaelam.sld.cu"
MAX_FILE_SIZE_MB = 50

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ============================
# LIMPIAR INSTANCIAS ANTERIORES
# ============================
def limpiar_instancias_anteriores():
    """Cerrar cualquier instancia previa del bot"""
    logger.info("🔧 Limpiando instancias anteriores...")
    try:
        # Cerrar webhook previo (si existe)
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=5)
        logger.info("✅ Webhook anterior eliminado")
    except:
        logger.info("ℹ️ No había webhook activo")
    
    try:
        # Cerrar sesión de polling previa
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/close", timeout=5)
        logger.info("✅ Sesión polling anterior cerrada")
    except:
        logger.info("ℹ️ No había sesión polling activa")
    
    time.sleep(3)  # Esperar para asegurar cierre

# Ejecutar limpieza al inicio
limpiar_instancias_anteriores()

# Crear bot después de la limpieza
bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ============================
# PROXIES CUBANOS
# ============================
CUBAN_PROXIES = [
    "http://190.6.82.94:8080",
    "http://190.6.81.150:8080",
    "http://152.206.125.20:8080",
    "http://152.206.135.55:8080",
    None  # Último recurso: sin proxy
]

ACTIVE_PROXY = None

def test_proxy(proxy_url):
    """Probar si un proxy funciona con Moodle"""
    try:
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        response = requests.get(
            f"{MOODLE_URL}/login/index.php", 
            proxies=proxies, 
            timeout=10
        )
        return response.status_code == 200
    except:
        return False

def get_working_proxy():
    """Obtener un proxy funcional"""
    global ACTIVE_PROXY
    
    if ACTIVE_PROXY and test_proxy(ACTIVE_PROXY):
        return ACTIVE_PROXY
    
    logger.info("🔍 Buscando proxy cubano funcional...")
    
    for proxy in CUBAN_PROXIES:
        if test_proxy(proxy):
            ACTIVE_PROXY = proxy
            logger.info(f"✅ Proxy seleccionado: {proxy}")
            return proxy
    
    logger.warning("⚠️ Ningún proxy funcionó, usando conexión directa")
    ACTIVE_PROXY = None
    return None

def make_cuban_request(url, method="GET", data=None, files=None, timeout=30):
    """Hacer request a través de proxy cubano"""
    proxy_url = get_working_proxy()
    proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
    
    try:
        if method.upper() == "GET":
            response = requests.get(url, proxies=proxies, timeout=timeout)
        else:
            response = requests.post(url, data=data, files=files, proxies=proxies, timeout=timeout)
        return response
    except Exception as e:
        logger.error(f"❌ Error en request: {e}")
        raise

# ============================
# MANEJO DE SESIÓN MOODLE
# ============================
class MoodleSessionManager:
    def __init__(self):
        self.session = requests.Session()
        self.setup_session()
        self.last_login = 0
        
    def setup_session(self):
        """Configurar sesión"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        })
        
        retry_strategy = Retry(total=3, backoff_factor=1, status_forcelist=[500,502,503,504])
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def login_to_moodle(self):
        """Iniciar sesión en Moodle"""
        try:
            logger.info("🔑 Iniciando sesión en Moodle...")
            
            # Usar el webservice para autenticación
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_webservice_get_site_info',
                'moodlewsrestformat': 'json'
            }
            
            response = make_cuban_request(ws_url, method="POST", data=params, timeout=15)
            
            if response.status_code == 200:
                result = response.json()
                if 'userid' in result:
                    self.last_login = time.time()
                    logger.info(f"✅ Login exitoso. User ID: {result['userid']}")
                    return True
            
            logger.error("❌ Falló el login via WebService")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error en login: {e}")
            return False

# Instancia global del gestor de sesión
moodle_session = MoodleSessionManager()

# ============================
# FUNCIÓN DE SUBIDA
# ============================
def subir_archivo_moodle(file_content: bytes, file_name: str):
    """Subir archivo a Moodle"""
    try:
        logger.info(f"🔄 Subiendo: {file_name}")
        
        # 1. Login a Moodle
        if not moodle_session.login_to_moodle():
            raise Exception("No se pudo conectar con Moodle")
        
        # 2. Subir archivo
        upload_url = f"{MOODLE_URL}/webservice/upload.php"
        
        files = {'file': (file_name, file_content)}
        data = {
            'token': MOODLE_TOKEN,
            'filearea': 'draft',
            'itemid': 0,
        }
        
        upload_response = make_cuban_request(
            upload_url, method="POST", data=data, files=files, timeout=60
        )
        
        if upload_response.status_code != 200:
            raise Exception(f"Error en upload: {upload_response.status_code}")
        
        upload_result = upload_response.json()
        
        if not upload_result:
            raise Exception("Respuesta vacía de Moodle")
        
        file_data = upload_result[0]
        itemid = file_data.get('itemid')
        contextid = file_data.get('contextid', 1)
        
        if not itemid:
            raise Exception("No se obtuvo itemid del archivo")
        
        # 3. Generar enlace de descarga
        enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{contextid}/user/draft/{itemid}/{urllib.parse.quote(file_name)}?token={MOODLE_TOKEN}"
        
        logger.info(f"✅ Archivo subido exitosamente. ItemID: {itemid}")
        
        return {
            'exito': True,
            'enlace': enlace_final,
            'nombre': file_name,
            'tamaño': file_data.get('filesize', len(file_content)),
            'itemid': itemid,
        }
        
    except Exception as e:
        logger.error(f"❌ Error subiendo archivo: {e}")
        return {'exito': False, 'error': str(e)}

# ============================
# FUNCIONES AUXILIARES
# ============================
def escape_md(text: str) -> str:
    """Escapar caracteres para MarkdownV2"""
    if text is None:
        return ''
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

def safe_send_message(chat_id, text, reply_to_message_id=None, parse_mode=None):
    """Enviar mensaje con manejo seguro de errores"""
    try:
        if parse_mode:
            return bot.send_message(chat_id, text, reply_to_message_id=reply_to_message_id, parse_mode=parse_mode)
        else:
            return bot.send_message(chat_id, text, reply_to_message_id=reply_to_message_id)
    except Exception as e:
        logger.error(f"Error enviando mensaje: {e}")
        # Fallback sin formato
        return bot.send_message(chat_id, text, reply_to_message_id=reply_to_message_id)

# ============================
# HANDLERS DE TELEGRAM
# ============================
@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """Manejar comando /start"""
    logger.info(f"✅ Start recibido de {message.from_user.id}")
    
    text = (
        "🤖 *BOT AULAELAM* 🤖\n\n"
        "✅ Envía cualquier archivo para subirlo a Moodle\n"
        "📏 Tamaño máximo: 50MB\n"
        "🔗 Usa proxies cubanos para conectividad\n\n"
        "⚡ *Comandos:*\n"
        "/start - Mostrar ayuda\n"
        "/status - Estado del sistema\n"
        "/proxy - Probar proxies"
    )
    
    safe_send_message(message.chat.id, text, parse_mode='MarkdownV2')

@bot.message_handler(commands=['status'])
def handle_status(message):
    """Verificar estado"""
    try:
        proxy = get_working_proxy() or "DIRECTO"
        text = f"🟢 *Bot activo*\n🔗 *Proxy:* `{proxy}`\n⏰ *Hora:* {time.strftime('%H:%M:%S')}"
        safe_send_message(message.chat.id, text, parse_mode='MarkdownV2')
    except Exception as e:
        safe_send_message(message.chat.id, f"❌ Error: {str(e)}")

@bot.message_handler(commands=['proxy'])
def handle_proxy_test(message):
    """Probar todos los proxies"""
    try:
        status_msg = safe_send_message(message.chat.id, "🔍 Probando proxies...")
        results = []
        
        for proxy in CUBAN_PROXIES:
            if proxy is None:
                name = "SIN PROXY"
            else:
                name = proxy
                
            if test_proxy(proxy):
                results.append(f"✅ {name}")
            else:
                results.append(f"❌ {name}")
        
        result_text = "🌐 *Resultados Proxy:*\n" + "\n".join(results)
        bot.edit_message_text(
            result_text,
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode='MarkdownV2'
        )
    except Exception as e:
        safe_send_message(message.chat.id, f"❌ Error probando proxies: {str(e)}")

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    """Manejar documentos"""
    try:
        doc = message.document
        file_name = doc.file_name or f"documento_{message.message_id}"
        file_size = doc.file_size or 0
        
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            safe_send_message(message.chat.id, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return

        file_info = bot.get_file(doc.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        status_msg = safe_send_message(message.chat.id, f"📤 Subiendo {file_name}...")
        
        resultado = subir_archivo_moodle(downloaded, file_name)
        
        if resultado['exito']:
            respuesta = (
                f"✅ *Subido exitosamente*\n\n"
                f"📄 *Archivo:* `{escape_md(resultado['nombre'])}`\n"
                f"💾 *Tamaño:* {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"🔗 *Enlace:*\n`{escape_md(resultado['enlace'])}`"
            )
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=respuesta,
                parse_mode='MarkdownV2'
            )
        else:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=f"❌ *Error*\n\nArchivo: `{escape_md(file_name)}`\nError: `{escape_md(resultado['error'])}`",
                parse_mode='MarkdownV2'
            )
            
    except Exception as e:
        logger.error(f"Error manejando documento: {e}")
        safe_send_message(message.chat.id, f"❌ Error: {str(e)}")

@bot.message_handler(content_types=['photo'])
def manejar_foto(message):
    """Manejar fotos"""
    try:
        photo = message.photo[-1]
        file_name = f"foto_{message.message_id}.jpg"
        file_size = photo.file_size or 0
        
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            safe_send_message(message.chat.id, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return

        file_info = bot.get_file(photo.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        status_msg = safe_send_message(message.chat.id, f"📤 Subiendo {file_name}...")
        
        resultado = subir_archivo_moodle(downloaded, file_name)
        
        if resultado['exito']:
            respuesta = f"✅ *Foto subida*\n\n🔗 *Enlace:*\n`{escape_md(resultado['enlace'])}`"
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=respuesta,
                parse_mode='MarkdownV2'
            )
        else:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=f"❌ Error subiendo foto: `{escape_md(resultado['error'])}`",
                parse_mode='MarkdownV2'
            )
            
    except Exception as e:
        logger.error(f"Error manejando foto: {e}")
        safe_send_message(message.chat.id, f"❌ Error: {str(e)}")

@bot.message_handler(content_types=['video', 'audio', 'voice'])
def manejar_otros_archivos(message):
    """Manejar videos, audio y voz"""
    try:
        if message.video:
            file_obj = message.video
            file_name = file_obj.file_name or f"video_{message.message_id}.mp4"
            tipo = "video"
        elif message.audio:
            file_obj = message.audio
            file_name = file_obj.file_name or f"audio_{message.message_id}.mp3"
            tipo = "audio"
        elif message.voice:
            file_obj = message.voice
            file_name = f"voz_{message.message_id}.ogg"
            tipo = "voz"
        else:
            return

        file_size = file_obj.file_size or 0
        
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            safe_send_message(message.chat.id, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return

        file_info = bot.get_file(file_obj.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        status_msg = safe_send_message(message.chat.id, f"📤 Subiendo {tipo}...")
        
        resultado = subir_archivo_moodle(downloaded, file_name)
        
        if resultado['exito']:
            respuesta = f"✅ *{tipo.capitalize()} subido*\n\n🔗 *Enlace:*\n`{escape_md(resultado['enlace'])}`"
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=respuesta,
                parse_mode='MarkdownV2'
            )
        else:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=f"❌ Error subiendo {tipo}: `{escape_md(resultado['error'])}`",
                parse_mode='MarkdownV2'
            )
            
    except Exception as e:
        logger.error(f"Error manejando {tipo}: {e}")
        safe_send_message(message.chat.id, f"❌ Error: {str(e)}")

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """Manejar otros mensajes de texto"""
    if message.text and not message.text.startswith('/'):
        safe_send_message(message.chat.id, 
            "📤 Envíame un archivo (documento, foto, video, audio) para subirlo a AulaElam\n\n"
            "Usa /help para más información\n"
            "Usa /status para ver el estado")

# ============================
# MANEJO DE ERRORES GLOBAL
# ============================
def polling_error_handler(exception):
    """Manejar errores de polling"""
    logger.error(f"❌ Error en polling: {exception}")
    if "409" in str(exception):
        logger.error("🔄 Error 409: Otra instancia detectada. Esperando...")
        time.sleep(10)
    return True

# ============================
# MAIN
# ============================
def main():
    logger.info("🚀 INICIANDO BOT AULAELAM...")
    
    # Verificar token
    try:
        bot_info = bot.get_me()
        logger.info(f"✅ Bot conectado: @{bot_info.username} (ID: {bot_info.id})")
    except Exception as e:
        logger.error(f"❌ Error con token: {e}")
        return
    
    # Probar proxies
    proxy = get_working_proxy()
    logger.info(f"🔗 Proxy: {proxy or 'DIRECTO'}")
    
    # Iniciar polling con manejo de errores
    logger.info("🔄 Iniciando polling...")
    try:
        bot.infinity_polling(
            timeout=60, 
            long_polling_timeout=60,
            logger_level=logging.INFO,
            allowed_updates=None,
            restart_on_change=True
        )
    except Exception as e:
        logger.error(f"❌ Error crítico: {e}")
        logger.info("🔄 Reiniciando en 10 segundos...")
        time.sleep(10)
        main()  # Reiniciar

if __name__ == "__main__":
    main()
