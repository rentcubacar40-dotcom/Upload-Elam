import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time
import re
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

bot = telebot.TeleBot(BOT_TOKEN)

# ============================
# PROXIES CUBANOS
# ============================
CUBAN_PROXIES = [
    "http://190.6.82.94:8080",
    "http://190.6.81.150:8080",
    "http://152.206.125.20:8080",
    "http://152.206.135.55:8080",
    "http://201.204.44.161:3128",
    "http://190.90.24.74:999",
    "http://190.90.24.87:999",
    None  # Último recurso: sin proxy
]

ACTIVE_PROXY = None
PROXY_LAST_TEST = 0
PROXY_TEST_INTERVAL = 300  # 5 minutos

def test_proxy(proxy_url):
    """Probar si un proxy funciona con Moodle"""
    try:
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        start_time = time.time()
        response = requests.get(
            f"{MOODLE_URL}/login/index.php", 
            proxies=proxies, 
            timeout=10
        )
        response_time = time.time() - start_time
        
        if response.status_code == 200:
            logger.info(f"✅ Proxy funcional: {proxy_url} ({(response_time):.1f}s)")
            return True
        else:
            logger.warning(f"❌ Proxy falló - Status {response.status_code}: {proxy_url}")
            return False
    except Exception as e:
        logger.debug(f"❌ Proxy error {proxy_url}: {e}")
        return False

def get_working_proxy():
    """Obtener un proxy funcional con cache inteligente"""
    global ACTIVE_PROXY, PROXY_LAST_TEST
    
    # Si tenemos un proxy activo y no ha pasado mucho tiempo, reutilizar
    current_time = time.time()
    if ACTIVE_PROXY and (current_time - PROXY_LAST_TEST) < PROXY_TEST_INTERVAL:
        return ACTIVE_PROXY
    
    logger.info("🔍 Buscando proxy cubano funcional...")
    
    # Probar proxies en orden
    for proxy in CUBAN_PROXIES:
        if test_proxy(proxy):
            ACTIVE_PROXY = proxy
            PROXY_LAST_TEST = current_time
            return proxy
    
    # Si ningún proxy funciona, usar sin proxy como último recurso
    logger.warning("⚠️ Ningún proxy funcionó, usando conexión directa")
    ACTIVE_PROXY = None
    PROXY_LAST_TEST = current_time
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
    except requests.exceptions.ProxyError as e:
        logger.error(f"❌ Error de proxy: {e}")
        # Marcar proxy como inválido y reintentar
        global ACTIVE_PROXY
        ACTIVE_PROXY = None
        raise Exception(f"Error de proxy: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Error en request: {e}")
        raise

# ============================
# MANEJO AVANZADO DE COOKIES Y SESIÓN
# ============================
class MoodleSessionManager:
    def __init__(self):
        self.session = requests.Session()
        self.setup_session()
        self.last_login = 0
        self.login_interval = 1800  # 30 minutos
        
    def setup_session(self):
        """Configurar sesión con headers realistas"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
        })
        
        # Configurar reintentos
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def ensure_valid_session(self):
        """Asegurar que tenemos una sesión válida"""
        current_time = time.time()
        
        # Si ha pasado mucho tiempo desde el último login, renovar
        if current_time - self.last_login > self.login_interval:
            logger.info("🔄 Renovando sesión Moodle...")
            return self.login_to_moodle()
        
        # Verificar si la sesión actual es válida
        if self.test_session():
            return True
        else:
            logger.info("🔐 Sesión inválida, iniciando nuevo login...")
            return self.login_to_moodle()
    
    def test_session(self):
        """Verificar si la sesión actual es válida"""
        try:
            test_url = f"{MOODLE_URL}/my/"
            response = make_cuban_request(test_url, timeout=10)
            
            # Usar BeautifulSoup para analizar si estamos logueados
            soup = BeautifulSoup(response.text, 'lxml')
            
            # Buscar indicadores de sesión válida
            logout_link = soup.find('a', string=re.compile(r'logout|salir|cerrar', re.IGNORECASE))
            user_menu = soup.find('div', class_=re.compile(r'usermenu|user-menu'))
            dashboard = soup.find('h1', string=re.compile(r'mis cursos|dashboard|panel', re.IGNORECASE))
            
            if logout_link or user_menu or dashboard:
                logger.info("✅ Sesión Moodle válida detectada")
                return True
            
            # También verificar por texto en la respuesta
            if "mis cursos" in response.text.lower() or "logout" in response.text.lower():
                return True
                
            return False
        except Exception as e:
            logger.warning(f"❌ Error testeando sesión: {e}")
            return False
    
    def login_to_moodle(self):
        """Iniciar sesión en Moodle usando token de webservice"""
        try:
            logger.info("🔑 Iniciando sesión en Moodle via WebService...")
            
            # Primero obtener la página de login para cookies iniciales
            login_page = f"{MOODLE_URL}/login/index.php"
            response = make_cuban_request(login_page, timeout=10)
            
            # Analizar la página de login con BeautifulSoup
            soup = BeautifulSoup(response.text, 'lxml')
            logger.info(f"📄 Página de login obtenida. Título: {soup.title.string if soup.title else 'No title'}")
            
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
                    
                    # Actualizar cookies en la sesión
                    if response.cookies:
                        self.session.cookies.update(response.cookies)
                    
                    # Verificar cookies obtenidas
                    cookies = self.session.cookies.get_dict()
                    logger.info(f"🍪 Cookies obtenidas: {list(cookies.keys())}")
                    
                    return True
                elif 'error' in result:
                    logger.error(f"❌ Error en login: {result['error']}")
                    return False
            
            logger.error(f"❌ Falló el login via WebService. Status: {response.status_code}")
            return False
            
        except Exception as e:
            logger.error(f"❌ Error en login: {e}")
            return False
    
    def make_moodle_request(self, url, method="GET", data=None, files=None, timeout=30):
        """Hacer request a Moodle con manejo automático de sesión y proxies"""
        # Asegurar sesión válida antes de cada request importante
        if "upload.php" in url or "webservice" in url:
            if not self.ensure_valid_session():
                raise Exception("No se pudo establecer sesión válida con Moodle")
        
        # Usar make_cuban_request que maneja los proxies
        return make_cuban_request(url, method, data, files, timeout)

# Instancia global del gestor de sesión
moodle_session = MoodleSessionManager()

# ============================
# FUNCIÓN DE SUBIDA MEJORADA CON PROXIES
# ============================
def subir_archivo_moodle(file_content: bytes, file_name: str):
    """Subir archivo a Moodle con manejo adecuado de sesión y proxies"""
    for attempt in range(1, 4):  # 3 intentos
        try:
            logger.info(f"🔄 Intento {attempt} - Subiendo: {file_name}")
            
            # 1. Verificar que tenemos sesión válida
            if not moodle_session.ensure_valid_session():
                raise Exception("No se pudo establecer sesión con Moodle")
            
            # 2. Obtener información del usuario
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_webservice_get_site_info',
                'moodlewsrestformat': 'json'
            }
            
            response = moodle_session.make_moodle_request(ws_url, method="POST", data=params)
            
            if response.status_code != 200:
                raise Exception(f"Error en site_info: {response.status_code}")
            
            site_info = response.json()
            if 'error' in site_info:
                raise Exception(f"Error Moodle: {site_info['error']}")
            
            user_id = site_info.get('userid')
            logger.info(f"👤 Usuario ID: {user_id}")
            
            # 3. Subir archivo al área draft
            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            
            files = {
                'file': (file_name, file_content, 'application/octet-stream')
            }
            
            data = {
                'token': MOODLE_TOKEN,
                'filearea': 'draft',
                'itemid': 0,
                'component': 'user',
                'filepath': '/',
                'contextlevel': 'user',
                'instanceid': user_id
            }
            
            # Log del proxy actual
            current_proxy = get_working_proxy()
            logger.info(f"🔗 Usando proxy: {current_proxy or 'DIRECTO'}")
            
            upload_response = moodle_session.make_moodle_request(
                upload_url, method="POST", data=data, files=files, timeout=60
            )
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Status code upload: {upload_response.status_code}")
                logger.error(f"❌ Response: {upload_response.text[:500]}")
                raise Exception(f"Error en upload: {upload_response.status_code}")
            
            # Procesar respuesta
            try:
                upload_result = upload_response.json()
            except ValueError as e:
                logger.error(f"❌ No se pudo parsear JSON: {upload_response.text[:500]}")
                raise Exception("Respuesta inválida de Moodle")
            
            if not upload_result:
                raise Exception("Respuesta vacía de Moodle")
            
            file_data = upload_result[0]
            
            if 'error' in file_data:
                raise Exception(f"Error Moodle: {file_data['error']}")
            
            # 4. Generar enlace de descarga
            itemid = file_data.get('itemid')
            contextid = file_data.get('contextid', 1)
            
            if not itemid:
                raise Exception("No se obtuvo itemid del archivo")
            
            enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{contextid}/user/draft/{itemid}/{urllib.parse.quote(file_name)}?token={MOODLE_TOKEN}"
            
            logger.info(f"✅ Archivo subido exitosamente. ItemID: {itemid}")
            
            return {
                'exito': True,
                'enlace': enlace_final,
                'nombre': file_name,
                'tamaño': file_data.get('filesize', len(file_content)),
                'itemid': itemid,
                'contextid': contextid,
                'user_id': user_id,
                'proxy_used': current_proxy or 'DIRECTO'
            }
            
        except Exception as e:
            logger.warning(f"❌ Intento {attempt} fallido: {e}")
            if attempt < 3:
                time.sleep(2)
                # Limpiar sesión y reintentar
                moodle_session.session.cookies.clear()
                # Forzar nuevo proxy en el próximo intento
                global ACTIVE_PROXY
                ACTIVE_PROXY = None
                continue
            else:
                return {'exito': False, 'error': str(e)}

# ============================
# FUNCIONES AUXILIARES
# ============================
def escape_md(text: str) -> str:
    """Escapar caracteres para MarkdownV2 de Telegram"""
    if text is None:
        return ''
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', text)

def procesar_y_subir_file(chat_id, message_obj, file_id, file_name, file_size):
    """Procesar y subir archivo con manejo de errores"""
    try:
        # Verificar tamaño del archivo
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message_obj, f"❌ Máximo permitido: {MAX_FILE_SIZE_MB}MB")
            return

        # Descargar archivo de Telegram
        file_info = bot.get_file(file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        # Enviar mensaje de estado
        mensaje = bot.reply_to(message_obj, f"🌐 *{escape_md(file_name)}*\n🔄 Conectando con AulaElam...", parse_mode='MarkdownV2')
        
        # Subir a Moodle
        resultado = subir_archivo_moodle(downloaded, file_name)
        
        if resultado['exito']:
            respuesta = (
                f"🎉 *¡ARCHIVO SUBIDO!*\n\n"
                f"📄 **Archivo:** `{escape_md(resultado['nombre'])}`\n"
                f"💾 **Tamaño:** {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"👤 **Usuario ID:** `{escape_md(str(resultado.get('user_id', 'N/A')))}`\n"
                f"🆔 **ItemID:** `{escape_md(str(resultado['itemid']))}`\n"
                f"🔗 **Proxy:** `{escape_md(str(resultado.get('proxy_used', 'N/A')))}`\n\n"
                f"🔗 **ENLACE:**\n`{escape_md(resultado['enlace'])}`"
            )
            bot.edit_message_text(
                chat_id=chat_id, 
                message_id=mensaje.message_id, 
                text=respuesta, 
                parse_mode='MarkdownV2'
            )
        else:
            error_msg = (
                f"❌ Error al subir archivo\n\n"
                f"Archivo: {escape_md(file_name)}\n"
                f"Error: {escape_md(resultado.get('error',''))}"
            )
            bot.edit_message_text(
                chat_id=chat_id, 
                message_id=mensaje.message_id,
                text=error_msg, 
                parse_mode='MarkdownV2'
            )
    except Exception as e:
        logger.error(f"Error en procesar_y_subir_file: {e}")
        bot.reply_to(message_obj, f"❌ **Error interno:** {str(e)}")

# ============================
# HANDLERS DE TELEGRAM
# ============================
@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """Manejar comando /start"""
    text = (
        "🤖 *BOT AULAELAM - SUBIDA A MOODLE* 🤖\n\n"
        "📤 Envíame cualquier archivo y lo subiré a AulaElam\n"
        "✅ Formatos soportados: documentos, fotos, videos, audio\n"
        f"📏 Tamaño máximo: {MAX_FILE_SIZE_MB}MB\n"
        "🔗 *Usa proxies cubanos para conectividad*\n\n"
        "⚠️ _Asegúrate de tener conexión a Internet_"
    )
    bot.send_message(message.chat.id, text, parse_mode='MarkdownV2')

@bot.message_handler(commands=['status', 'proxy'])
def handle_status(message):
    """Verificar estado de la conexión con Moodle y proxies"""
    try:
        status_msg = bot.reply_to(message, "🔍 Verificando conexión y proxies...")
        
        # Probar proxies
        proxy_status = []
        for proxy in CUBAN_PROXIES:
            if proxy is None:
                continue
            if test_proxy(proxy):
                proxy_status.append(f"✅ {proxy}")
            else:
                proxy_status.append(f"❌ {proxy}")
        
        # Verificar Moodle
        moodle_ok = moodle_session.test_session()
        
        # Construir respuesta
        proxy_text = "\n".join(proxy_status[:4])  # Mostrar solo los primeros 4
        moodle_text = "✅ ACTIVA" if moodle_ok else "❌ FALLIDA"
        current_proxy = get_working_proxy() or "DIRECTO"
        
        respuesta = (
            f"📊 *ESTADO DEL SISTEMA*\n\n"
            f"🔗 **Moodle:** {moodle_text}\n"
            f"🔄 **Proxy Actual:** `{current_proxy}`\n\n"
            f"🌐 **Proxies Cubanos:**\n{proxy_text}"
        )
        
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=respuesta,
            parse_mode='MarkdownV2'
        )
                
    except Exception as e:
        bot.reply_to(message, f"❌ Error verificando estado: {str(e)}")

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    """Manejar documentos enviados"""
    doc = message.document
    file_name = doc.file_name or f"documento_{message.message_id}"
    procesar_y_subir_file(
        message.chat.id, 
        message, 
        doc.file_id, 
        file_name, 
        doc.file_size or 0
    )

@bot.message_handler(content_types=['photo'])
def manejar_foto(message):
    """Manejar fotos enviadas"""
    photo = message.photo[-1]  # La foto de mayor calidad
    file_name = f"foto_{message.message_id}.jpg"
    procesar_y_subir_file(
        message.chat.id, 
        message, 
        photo.file_id, 
        file_name, 
        photo.file_size or 0
    )

@bot.message_handler(content_types=['video'])
def manejar_video(message):
    """Manejar videos enviados"""
    video = message.video
    file_name = video.file_name or f"video_{message.message_id}.mp4"
    procesar_y_subir_file(
        message.chat.id, 
        message, 
        video.file_id, 
        file_name, 
        video.file_size or 0
    )

@bot.message_handler(content_types=['audio'])
def manejar_audio(message):
    """Manejar audio enviado"""
    audio = message.audio
    file_name = audio.file_name or f"audio_{message.message_id}.mp3"
    procesar_y_subir_file(
        message.chat.id, 
        message, 
        audio.file_id, 
        file_name, 
        audio.file_size or 0
    )

@bot.message_handler(content_types=['voice'])
def manejar_voice(message):
    """Manejar mensajes de voz"""
    voice = message.voice
    file_name = f"voz_{message.message_id}.ogg"
    procesar_y_subir_file(
        message.chat.id, 
        message, 
        voice.file_id, 
        file_name, 
        voice.file_size or 0
    )

@bot.message_handler(content_types=['animation'])
def manejar_animation(message):
    """Manejar GIFs/animaciones"""
    animation = message.animation
    file_name = animation.file_name or f"animacion_{message.message_id}.gif"
    procesar_y_subir_file(
        message.chat.id, 
        message, 
        animation.file_id, 
        file_name, 
        animation.file_size or 0
    )

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """Manejar otros mensajes de texto"""
    if message.text and not message.text.startswith('/'):
        bot.reply_to(
            message, 
            "📤 Envíame un archivo (documento, foto, video, audio) para subirlo a AulaElam\n\n"
            "Usa /help para más información\n"
            "Usa /status para ver el estado de conexión"
        )

# ============================
# INICIALIZACIÓN Y MAIN
# ============================
def inicializar_bot():
    """Inicializar el bot y verificar conexiones"""
    logger.info("🚀 INICIANDO BOT AULAELAM CON PROXIES CUBANOS...")
    
    # Verificar token de Telegram
    try:
        bot_info = bot.get_me()
        logger.info(f"✅ Bot de Telegram conectado: @{bot_info.username}")
    except Exception as e:
        logger.error(f"❌ Error conectando con Telegram: {e}")
        return False
    
    # Probar proxies al inicio
    logger.info("🔍 Probando proxies cubanos...")
    working_proxy = get_working_proxy()
    if working_proxy:
        logger.info(f"✅ Proxy seleccionado: {working_proxy}")
    else:
        logger.warning("⚠️ No hay proxies funcionales, usando conexión directa")
    
    # Intentar login inicial con Moodle
    logger.info("🔗 Conectando con Moodle...")
    if moodle_session.login_to_moodle():
        logger.info("✅ Sesión inicial con Moodle establecida")
        return True
    else:
        logger.warning("⚠️ No se pudo establecer sesión inicial con Moodle")
        logger.warning("⚠️ El bot funcionará pero puede fallar en subidas")
        return True  # Permitir que el bot inicie igual

def main():
    """Función principal"""
    if inicializar_bot():
        logger.info("🎉 Bot iniciado correctamente con soporte de proxies")
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except Exception as e:
            logger.error(f"❌ Error en el bot: {e}")
            logger.info("🔄 Reiniciando en 10 segundos...")
            time.sleep(10)
            main()  # Reiniciar
    else:
        logger.error("❌ No se pudo inicializar el bot")

if __name__ == "__main__":
    main()
