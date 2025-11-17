import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time
import re
import json
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

# Limpiar instancias anteriores
try:
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook", timeout=5)
    requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/close", timeout=5)
    time.sleep(3)
except:
    pass

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# ============================
# SISTEMA MEJORADO DE PROXIES
# ============================
CUBAN_PROXIES = [
    "http://190.6.82.94:8080",
    "http://190.6.81.150:8080", 
    "http://152.206.125.20:8080",
    "http://152.206.135.55:8080",
    "http://201.222.131.18:999",
    "http://190.90.24.74:999",
    "http://190.90.24.87:999",
    "http://190.90.24.85:999",
    None  # Conexión directa
]

PROXY_STATUS = {}
ACTIVE_PROXY = None

def diagnosticar_proxies():
    """Diagnóstico completo de todos los proxies"""
    logger.info("🔍 INICIANDO DIAGNÓSTICO DE PROXIES...")
    resultados = []
    
    for proxy in CUBAN_PROXIES:
        if proxy is None:
            nombre = "SIN PROXY"
        else:
            nombre = proxy.split('//')[1] if '//' in proxy else proxy
        
        inicio = time.time()
        try:
            proxies = {"http": proxy, "https": proxy} if proxy else None
            response = requests.get(
                f"{MOODLE_URL}/login/index.php",
                proxies=proxies,
                timeout=15
            )
            tiempo = round(time.time() - inicio, 2)
            
            if response.status_code == 200:
                estado = "✅ CONECTADO"
                PROXY_STATUS[proxy] = {
                    'estado': 'activo',
                    'tiempo': tiempo,
                    'url': proxy
                }
            else:
                estado = f"❌ ERROR {response.status_code}"
                PROXY_STATUS[proxy] = {'estado': 'error', 'tiempo': tiempo}
                
        except requests.exceptions.Timeout:
            estado = "⏰ TIMEOUT"
            PROXY_STATUS[proxy] = {'estado': 'timeout', 'tiempo': 15}
        except Exception as e:
            estado = f"❌ ERROR: {str(e)[:30]}"
            PROXY_STATUS[proxy] = {'estado': 'error', 'tiempo': 0}
        
        resultados.append(f"{estado} - {nombre} ({PROXY_STATUS[proxy]['tiempo']}s)")
        logger.info(f"  {estado} - {nombre}")
    
    return resultados

def obtener_mejor_proxy():
    """Seleccionar el mejor proxy disponible"""
    global ACTIVE_PROXY
    
    # Si ya tenemos uno activo y funciona, mantenerlo
    if ACTIVE_PROXY and test_proxy_rapido(ACTIVE_PROXY):
        return ACTIVE_PROXY
    
    # Buscar el mejor proxy
    for proxy in CUBAN_PROXIES:
        if proxy and test_proxy_rapido(proxy):
            ACTIVE_PROXY = proxy
            logger.info(f"🎯 Proxy seleccionado: {proxy}")
            return proxy
    
    # Si ningún proxy funciona, usar conexión directa
    logger.warning("⚠️ Usando conexión directa (sin proxy)")
    ACTIVE_PROXY = None
    return None

def test_proxy_rapido(proxy_url):
    """Test rápido de proxy"""
    try:
        proxies = {"http": proxy_url, "https": proxy_url} if proxy_url else None
        response = requests.get(
            f"{MOODLE_URL}/", 
            proxies=proxies, 
            timeout=8
        )
        return response.status_code == 200
    except:
        return False

# ============================
# SISTEMA DE SESIÓN MEJORADO (INSPIRADO EN LA WEB)
# ============================
class MoodleSessionManager:
    def __init__(self):
        self.session = requests.Session()
        self.setup_session()
        self.user_id = None
        self.last_activity = time.time()
        
    def setup_session(self):
        """Configurar sesión como un navegador real"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        })
        
        # Estrategia de reintentos mejorada
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=10, pool_maxsize=10)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def login_moodle_webservice(self):
        """Login usando WebService Token (método actual)"""
        try:
            logger.info("🔑 Autenticando via WebService...")
            
            proxy = obtener_mejor_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            
            # Verificar token primero
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_webservice_get_site_info',
                'moodlewsrestformat': 'json'
            }
            
            response = self.session.post(ws_url, data=params, timeout=20, proxies=proxies)
            
            if response.status_code != 200:
                raise Exception(f"Error HTTP {response.status_code}")
            
            result = response.json()
            
            if 'exception' in result:
                error_msg = result.get('message', 'Error desconocido en WebService')
                raise Exception(f"WebService Error: {error_msg}")
            
            if 'userid' not in result:
                raise Exception("No se pudo obtener userid del WebService")
            
            self.user_id = result['userid']
            self.last_activity = time.time()
            
            logger.info(f"✅ Autenticado - User ID: {self.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en autenticación WebService: {e}")
            return False
    
    def verificar_sesion_activa(self):
        """Verificar si la sesión sigue activa"""
        try:
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_webservice_get_site_info',
                'moodlewsrestformat': 'json'
            }
            
            proxy = obtener_mejor_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            
            response = self.session.post(ws_url, data=params, timeout=10, proxies=proxies)
            return response.status_code == 200 and 'userid' in response.json()
        except:
            return False

# Instancia global
moodle_session = MoodleSessionManager()

# ============================
# SISTEMA DE SUBIDA MEJORADO
# ============================
def subir_archivo_moodle(file_content: bytes, file_name: str):
    """Subir archivo con diagnóstico detallado"""
    logger.info(f"🔄 INICIANDO SUBIDA: {file_name} ({len(file_content)} bytes)")
    
    for intento in range(1, 4):
        try:
            logger.info(f"📦 Intento {intento} de 3")
            
            # 1. Verificar/Autenticar
            if not moodle_session.verificar_sesion_activa():
                logger.info("🔄 Sesión expirada, reautenticando...")
                if not moodle_session.login_moodle_webservice():
                    raise Exception("No se pudo autenticar con Moodle")
            
            # 2. Obtener información del usuario (ya debería estar en la sesión)
            if not moodle_session.user_id:
                raise Exception("No hay user_id disponible")
            
            # 3. Preparar upload
            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            files = {'file': (file_name, file_content)}
            data = {
                'token': MOODLE_TOKEN,
                'filearea': 'draft',
                'itemid': 0,
                'component': 'user',
                'filepath': '/',
                'contextlevel': 'user',
                'instanceid': moodle_session.user_id
            }
            
            proxy = obtener_mejor_proxy()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            logger.info(f"🔗 Proxy usado: {proxy or 'DIRECTO'}")
            
            # 4. Subir archivo
            upload_response = moodle_session.session.post(
                upload_url, 
                data=data, 
                files=files, 
                timeout=60,
                proxies=proxies
            )
            
            logger.info(f"📤 Response status: {upload_response.status_code}")
            logger.info(f"📤 Response length: {len(upload_response.content)}")
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Error en upload: {upload_response.text[:200]}")
                raise Exception(f"Error HTTP {upload_response.status_code} en upload")
            
            # 5. Procesar respuesta
            try:
                upload_result = upload_response.json()
            except json.JSONDecodeError as e:
                logger.error(f"❌ No se pudo decodificar JSON: {upload_response.text[:200]}")
                raise Exception("Respuesta no es JSON válido")
            
            if not upload_result:
                raise Exception("Respuesta vacía de Moodle")
            
            if isinstance(upload_result, dict) and 'error' in upload_result:
                raise Exception(f"Error Moodle: {upload_result['error']}")
            
            file_data = upload_result[0] if isinstance(upload_result, list) else upload_result
            
            itemid = file_data.get('itemid')
            contextid = file_data.get('contextid', 1)
            
            if not itemid:
                raise Exception("No se obtuvo itemid del archivo")
            
            # 6. Generar enlace
            enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{contextid}/user/draft/{itemid}/{urllib.parse.quote(file_name)}"
            
            logger.info(f"✅ SUBIDA EXITOSA - ItemID: {itemid}, ContextID: {contextid}")
            
            return {
                'exito': True,
                'enlace': enlace_final,
                'nombre': file_name,
                'tamaño': file_data.get('filesize', len(file_content)),
                'itemid': itemid,
                'contextid': contextid,
                'user_id': moodle_session.user_id,
                'proxy_used': proxy or 'DIRECTO',
                'intento': intento
            }
            
        except Exception as e:
            logger.error(f"❌ Intento {intento} fallido: {e}")
            if intento < 3:
                logger.info(f"⏳ Reintento en 3 segundos...")
                time.sleep(3)
                # Limpiar cookies y reintentar
                moodle_session.session.cookies.clear()
                continue
            else:
                return {
                    'exito': False, 
                    'error': str(e),
                    'intento': intento
                }

# ============================
# FUNCIONES AUXILIARES
# ============================
def escape_md(text: str) -> str:
    """Escapar caracteres para MarkdownV2"""
    if text is None:
        return ''
    escape_chars = r'\_*[]()~`>#+-=|{}.!'
    return re.sub(f'([{re.escape(escape_chars)}])', r'\\\1', str(text))

# ============================
# HANDLERS MEJORADOS
# ============================
@bot.message_handler(commands=['start'])
def handle_start(message):
    """Manejar comando /start con diagnóstico completo"""
    logger.info(f"🎯 Start recibido de {message.from_user.id}")
    
    # Realizar diagnóstico completo
    proxy_results = diagnosticar_proxies()
    
    # Verificar conexión con Moodle
    moodle_status = "🟢 CONECTADO" if moodle_session.login_moodle_webservice() else "🔴 DESCONECTADO"
    
    # Construir mensaje de estado
    proxy_info = "\n".join(proxy_results[:6])  # Mostrar primeros 6 resultados
    
    text = (
        f"🤖 *BOT AULAELAM - DIAGNÓSTICO COMPLETO* 🤖\n\n"
        f"🌐 *Estado Moodle:* {moodle_status}\n"
        f"🔗 *URL:* `{MOODLE_URL}`\n"
        f"👤 *User ID:* `{moodle_session.user_id or 'No autenticado'}`\n\n"
        f"📊 *PROXIES DISPONIBLES:*\n{proxy_info}\n\n"
        f"💡 *Instrucciones:*\n"
        f"• Envía cualquier archivo para subir\n" 
        f"• Usa /proxy para ver todos los proxies\n"
        f"• Usa /status para estado actual\n"
        f"• Tamaño máximo: {MAX_FILE_SIZE_MB}MB"
    )
    
    bot.send_message(message.chat.id, text, parse_mode='MarkdownV2')

@bot.message_handler(commands=['proxy'])
def handle_proxy(message):
    """Mostrar diagnóstico completo de proxies"""
    logger.info("🔍 Solicitado diagnóstico de proxies")
    
    proxy_results = diagnosticar_proxies()
    proxy_active = obtener_mejor_proxy() or "DIRECTO"
    
    text = (
        f"🌐 *DIAGNÓSTICO DE PROXIES*\n\n"
        f"🎯 *Proxy activo:* `{proxy_active}`\n\n"
        f"📋 *Todos los proxies:*\n" + "\n".join(proxy_results)
    )
    
    bot.send_message(message.chat.id, text, parse_mode='MarkdownV2')

@bot.message_handler(commands=['status'])
def handle_status(message):
    """Estado actual del sistema"""
    proxy_active = obtener_mejor_proxy() or "DIRECTO"
    moodle_ok = moodle_session.verificar_sesion_activa()
    
    text = (
        f"📊 *ESTADO ACTUAL*\n\n"
        f"🤖 *Bot:* 🟢 OPERATIVO\n"
        f"🌐 *Moodle:* {'🟢 CONECTADO' if moodle_ok else '🔴 DESCONECTADO'}\n"
        f"🔗 *Proxy activo:* `{proxy_active}`\n"
        f"👤 *User ID:* `{moodle_session.user_id or 'No autenticado'}`\n"
        f"⏰ *Última actividad:* {time.strftime('%H:%M:%S')}"
    )
    
    bot.send_message(message.chat.id, text, parse_mode='MarkdownV2')

@bot.message_handler(content_types=['document', 'photo', 'video', 'audio', 'voice'])
def handle_files(message):
    """Manejar archivos con feedback detallado"""
    try:
        # Determinar tipo de archivo
        if message.document:
            file_obj = message.document
            file_name = file_obj.file_name or f"documento_{message.message_id}"
            tipo = "documento"
        elif message.photo:
            file_obj = message.photo[-1]
            file_name = f"foto_{message.message_id}.jpg"
            tipo = "foto"
        elif message.video:
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
            tipo = "voz de audio"
        else:
            bot.reply_to(message, "❌ Tipo de archivo no soportado")
            return

        file_size = file_obj.file_size or 0
        
        # Verificar tamaño
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ Archivo muy grande. Máximo: {MAX_FILE_SIZE_MB}MB")
            return

        # Mensaje inicial con diagnóstico
        proxy_actual = obtener_mejor_proxy() or "DIRECTO"
        status_msg = bot.reply_to(
            message, 
            f"📤 *Iniciando subida...*\n\n"
            f"📄 *Archivo:* `{escape_md(file_name)}`\n"
            f"💾 *Tamaño:* {file_size / 1024 / 1024:.2f} MB\n"
            f"🔗 *Proxy:* `{escape_md(proxy_actual)}`\n"
            f"🔄 *Preparando...*",
            parse_mode='MarkdownV2'
        )

        # Descargar archivo de Telegram
        file_info = bot.get_file(file_obj.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        # Actualizar mensaje
        bot.edit_message_text(
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            text=f"📤 *Subiendo archivo...*\n\n"
                 f"📄 `{escape_md(file_name)}`\n"
                 f"💾 {len(downloaded) / 1024 / 1024:.2f} MB\n"
                 f"🔗 `{escape_md(proxy_actual)}`\n"
                 f"🔄 *Conectando con Moodle...*",
            parse_mode='MarkdownV2'
        )
        
        # Subir a Moodle
        resultado = subir_archivo_moodle(downloaded, file_name)
        
        if resultado['exito']:
            respuesta = (
                f"🎉 *¡ARCHIVO SUBIDO EXITOSAMENTE!*\n\n"
                f"📄 *Archivo:* `{escape_md(resultado['nombre'])}`\n"
                f"💾 *Tamaño:* {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"👤 *User ID:* `{escape_md(str(resultado['user_id']))}`\n"
                f"🆔 *Item ID:* `{escape_md(str(resultado['itemid']))}`\n"
                f"🔗 *Proxy usado:* `{escape_md(resultado['proxy_used'])}`\n"
                f"🔄 *Intento:* {resultado['intento']}/3\n\n"
                f"🔗 *ENLACE DIRECTO:*\n`{escape_md(resultado['enlace'])}`"
            )
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=respuesta,
                parse_mode='MarkdownV2'
            )
        else:
            error_msg = (
                f"❌ *ERROR AL SUBIR ARCHIVO*\n\n"
                f"📄 *Archivo:* `{escape_md(file_name)}`\n"
                f"💾 *Tamaño:* {len(downloaded) / 1024 / 1024:.2f} MB\n"
                f"🔄 *Intento:* {resultado.get('intento', 1)}/3\n\n"
                f"⚠️ *Error:* `{escape_md(resultado['error'])}`\n\n"
                f"💡 *Sugerencia:*\n"
                f"• Verifica tu conexión\n"
                f"• Usa /status para diagnóstico\n"
                f"• Intenta con otro archivo"
            )
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                text=error_msg,
                parse_mode='MarkdownV2'
            )
            
    except Exception as e:
        logger.error(f"❌ Error general manejando archivo: {e}")
        bot.reply_to(message, f"❌ *Error interno del bot:* `{str(e)}`", parse_mode='MarkdownV2')

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """Manejar otros mensajes"""
    if message.text and not message.text.startswith('/'):
        bot.reply_to(
            message, 
            "📤 Envíame un archivo para subirlo a AulaElam\n\n"
            "💡 *Comandos disponibles:*\n"
            "/start - Diagnóstico completo\n" 
            "/status - Estado actual\n"
            "/proxy - Ver todos los proxies",
            parse_mode='MarkdownV2'
        )

# ============================
# MAIN
# ============================
def main():
    logger.info("🚀 INICIANDO BOT AULAELAM MEJORADO...")
    
    # Diagnóstico inicial
    diagnosticar_proxies()
    
    # Verificar token de Telegram
    try:
        bot_info = bot.get_me()
        logger.info(f"✅ BOT CONECTADO: @{bot_info.username}")
    except Exception as e:
        logger.error(f"❌ Error con token Telegram: {e}")
        return
    
    # Verificar Moodle
    if moodle_session.login_moodle_webservice():
        logger.info(f"✅ MOODLE CONECTADO - User ID: {moodle_session.user_id}")
    else:
        logger.error("❌ No se pudo conectar con Moodle")
    
    # Iniciar polling
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout=60)
    except Exception as e:
        logger.error(f"❌ Error en polling: {e}")
        time.sleep(10)
        main()

if __name__ == "__main__":
    main()
