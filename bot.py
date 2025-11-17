import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time
import re
import json
import concurrent.futures
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

# Crear bot con HTML para evitar problemas de Markdown
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML')

# ============================
# SISTEMA ACELERADO DE PROXIES
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
    "http://190.90.24.86:999",
    "http://190.90.24.88:999",
    "http://201.204.44.161:3128",
    "http://190.90.24.89:999",
    None  # Conexión directa - ÚLTIMA OPCIÓN
]

PROXY_STATUS = {}
ACTIVE_PROXY = None
LAST_PROXY_SCAN = 0
PROXY_SCAN_INTERVAL = 300  # 5 minutos entre escaneos

def test_proxy_individual(proxy):
    """Test individual de proxy con timeout MUY corto"""
    if proxy is None:
        return None, True, 0  # Conexión directa siempre disponible
    
    try:
        inicio = time.time()
        proxies = {"http": proxy, "https": proxy}
        # ✅ TIMEOUT MUY CORTO: 3 segundos máximo
        response = requests.get(
            f"{MOODLE_URL}/",
            proxies=proxies,
            timeout=3  # ⚡ De 10s a 3s
        )
        tiempo = round(time.time() - inicio, 2)
        return proxy, response.status_code == 200, tiempo
    except:
        return proxy, False, 0

def buscar_proxies_rapido():
    """Búsqueda RÁPIDA de proxies en paralelo"""
    global ACTIVE_PROXY, LAST_PROXY_SCAN
    
    # ✅ USAR CACHE si el escaneo fue reciente
    current_time = time.time()
    if ACTIVE_PROXY and (current_time - LAST_PROXY_SCAN) < PROXY_SCAN_INTERVAL:
        return ACTIVE_PROXY
    
    logger.info("⚡ BÚSQUEDA RÁPIDA DE PROXIES...")
    
    proxies_disponibles = []
    
    # ✅ PROBAR EN PARALELO para máxima velocidad
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(test_proxy_individual, proxy) for proxy in CUBAN_PROXIES]
        
        for future in concurrent.futures.as_completed(futures):
            proxy, funciona, tiempo = future.result()
            if funciona:
                proxies_disponibles.append((proxy, tiempo))
                logger.info(f"   ✅ {proxy} - {tiempo}s")
    
    # ✅ ORDENAR por velocidad (más rápido primero)
    proxies_disponibles.sort(key=lambda x: x[1])
    
    if proxies_disponibles:
        ACTIVE_PROXY = proxies_disponibles[0][0]  # El más rápido
        logger.info(f"🎯 PROXY SELECCIONADO: {ACTIVE_PROXY}")
    else:
        ACTIVE_PROXY = None
        logger.info("🎯 USANDO CONEXIÓN DIRECTA")
    
    LAST_PROXY_SCAN = current_time
    return ACTIVE_PROXY

def obtener_proxy_activo():
    """Obtener proxy activo instantáneamente"""
    global ACTIVE_PROXY
    
    if ACTIVE_PROXY:
        # ✅ VERIFICACIÓN RÁPIDA del proxy actual
        try:
            proxies = {"http": ACTIVE_PROXY, "https": ACTIVE_PROXY}
            response = requests.get(f"{MOODLE_URL}/", proxies=proxies, timeout=2)
            if response.status_code == 200:
                return ACTIVE_PROXY
        except:
            pass  # Proxy falló, buscar nuevo
    
    # ✅ BÚSQUEDA RÁPIDA si no hay proxy activo
    return buscar_proxies_rapido()

def diagnosticar_proxies_rapido():
    """Diagnóstico rápido de proxies"""
    logger.info("🔍 DIAGNÓSTICO RÁPIDO DE PROXIES...")
    resultados = []
    
    # ✅ PRUEBA RÁPIDA EN PARALELO
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(test_proxy_individual, proxy) for proxy in CUBAN_PROXIES]
        
        for future in concurrent.futures.as_completed(futures):
            proxy, funciona, tiempo = future.result()
            
            if proxy is None:
                nombre = "SIN PROXY"
                estado = "✅ DISPONIBLE"
            else:
                nombre = proxy.split('//')[1] if '//' in proxy else proxy
                estado = f"✅ CONECTADO ({tiempo}s)" if funciona else "❌ FALLÓ"
            
            resultados.append(f"{estado} - {nombre}")
            logger.info(f"  {estado} - {nombre}")
    
    return resultados

# ============================
# SISTEMA DE SESIÓN MEJORADO
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
            'Connection': 'keep-alive',
        })
        
        # ✅ Estrategia de reintentos MÁS RÁPIDA
        retry_strategy = Retry(
            total=2,  # Solo 2 reintentos
            backoff_factor=0.5,  # Menos espera entre reintentos
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def login_moodle_webservice(self):
        """Login usando WebService Token - VERSIÓN RÁPIDA"""
        try:
            logger.info("🔑 Autenticando via WebService...")
            
            proxy = obtener_proxy_activo()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            
            # ✅ TIMEOUT REDUCIDO
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_webservice_get_site_info',
                'moodlewsrestformat': 'json'
            }
            
            response = self.session.post(ws_url, data=params, timeout=10, proxies=proxies)  # ⚡ 15s → 10s
            
            if response.status_code != 200:
                logger.error(f"❌ Error HTTP {response.status_code} en WebService")
                return False
            
            result = response.json()
            
            if 'exception' in result:
                error_msg = result.get('message', 'Error desconocido en WebService')
                logger.error(f"❌ WebService Error: {error_msg}")
                return False
            
            if 'userid' not in result:
                logger.error("❌ No se pudo obtener userid del WebService")
                return False
            
            self.user_id = result['userid']
            self.last_activity = time.time()
            
            logger.info(f"✅ Autenticado - User ID: {self.user_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en autenticación WebService: {e}")
            return False
    
    def verificar_sesion_activa(self):
        """Verificar si la sesión sigue activa - VERSIÓN RÁPIDA"""
        try:
            if not self.user_id:
                return False
                
            # ✅ Verificación más permisiva (45 minutos en lugar de 30)
            if time.time() - self.last_activity > 2700:  # 45 minutos
                return False
                
            return True
        except:
            return False

# Instancia global
moodle_session = MoodleSessionManager()

# ============================
# SISTEMA DE SUBIDA ACELERADO
# ============================
def subir_archivo_moodle(file_content: bytes, file_name: str):
    """Subir archivo con diagnóstico detallado - VERSIÓN RÁPIDA"""
    logger.info(f"🔄 INICIANDO SUBIDA RÁPIDA: {file_name}")
    
    for intento in range(1, 4):
        try:
            logger.info(f"📦 Intento {intento} de 3")
            
            # 1. Verificar/Autenticar RÁPIDO
            if not moodle_session.verificar_sesion_activa():
                logger.info("🔄 Sesión expirada, reautenticando...")
                if not moodle_session.login_moodle_webservice():
                    raise Exception("No se pudo autenticar con Moodle")
            
            if not moodle_session.user_id:
                raise Exception("No hay user_id disponible")
            
            # 2. Preparar upload
            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            files = {'file': (file_name, file_content, 'application/octet-stream')}
            data = {
                'token': MOODLE_TOKEN,
                'filearea': 'draft',
                'itemid': 0,
            }
            
            proxy = obtener_proxy_activo()
            proxies = {"http": proxy, "https": proxy} if proxy else None
            logger.info(f"🔗 Proxy usado: {proxy or 'DIRECTO'}")
            
            # 3. Subir archivo con TIMEOUT OPTIMIZADO
            upload_response = moodle_session.session.post(
                upload_url, 
                data=data, 
                files=files, 
                timeout=25,  # ⚡ 30s → 25s
                proxies=proxies
            )
            
            logger.info(f"📤 Response status: {upload_response.status_code}")
            
            if upload_response.status_code != 200:
                logger.error(f"❌ Error en upload: {upload_response.text[:200]}")
                raise Exception(f"Error HTTP {upload_response.status_code}")
            
            # 4. Procesar respuesta
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
            
            # 5. Generar enlace
            enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{contextid}/user/draft/{itemid}/{urllib.parse.quote(file_name)}"
            
            logger.info(f"✅ SUBIDA EXITOSA - ItemID: {itemid}")
            
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
                logger.info("⏳ Reintento en 2 segundos...")
                time.sleep(2)
                continue
            else:
                return {
                    'exito': False, 
                    'error': str(e),
                    'intento': intento
                }

# ============================
# HANDLERS ACELERADOS
# ============================
@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """Manejar comando /start - VERSIÓN RÁPIDA"""
    logger.info(f"🎯 Start recibido de {message.from_user.id}")
    
    try:
        # ✅ DIAGNÓSTICO INSTANTÁNEO sin esperar proxies
        proxy_actual = obtener_proxy_activo() or "DIRECTO"
        moodle_status = "🟢 CONECTADO" if moodle_session.login_moodle_webservice() else "🔴 DESCONECTADO"
        
        text = (
            f"<b>🤖 BOT AULAELAM - ⚡ VERSIÓN RÁPIDA</b>\n\n"
            f"<b>🌐 Estado Moodle:</b> {moodle_status}\n"
            f"<b>🔗 URL:</b> <code>{MOODLE_URL}</code>\n"
            f"<b>👤 User ID:</b> <code>{moodle_session.user_id or 'No autenticado'}</code>\n"
            f"<b>🔧 Proxy actual:</b> <code>{proxy_actual}</code>\n\n"
            f"<b>⚡ Características:</b>\n"
            f"• Búsqueda rápida de proxies\n"
            f"• Timeouts optimizados\n"
            f"• Respuesta instantánea\n\n"
            f"<b>💡 Comandos:</b>\n"
            f"/start - Estado rápido\n"
            f"/status - Info del sistema\n" 
            f"/proxy - Diagnóstico proxies\n"
            f"/fast - Solo conexión directa\n\n"
            f"<b>📏 Tamaño máximo:</b> {MAX_FILE_SIZE_MB}MB"
        )
        
        bot.send_message(message.chat.id, text, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error en /start: {e}")
        bot.send_message(message.chat.id, f"❌ <b>Error:</b> {str(e)}", parse_mode='HTML')

@bot.message_handler(commands=['fast'])
def handle_fast(message):
    """Forzar conexión directa para máxima velocidad"""
    global ACTIVE_PROXY
    ACTIVE_PROXY = None
    logger.info("🚀 Modo rápido activado - Conexión directa")
    
    bot.send_message(
        message.chat.id,
        "🚀 <b>MODO RÁPIDO ACTIVADO</b>\n\n"
        "• Usando conexión directa\n"
        "• Sin proxies intermedios\n" 
        "• Máxima velocidad posible\n\n"
        "⚠️ <i>Puede fallar si hay bloqueos</i>",
        parse_mode='HTML'
    )

@bot.message_handler(commands=['status'])
def handle_status(message):
    """Estado actual del sistema - VERSIÓN RÁPIDA"""
    try:
        proxy_active = obtener_proxy_activo() or "DIRECTO"
        moodle_ok = moodle_session.verificar_sesion_activa()
        
        text = (
            f"<b>📊 ESTADO ACTUAL - ⚡ RÁPIDO</b>\n\n"
            f"<b>🤖 Bot:</b> 🟢 OPERATIVO\n"
            f"<b>🌐 Moodle:</b> {'🟢 CONECTADO' if moodle_ok else '🔴 DESCONECTADO'}\n"
            f"<b>🔗 Proxy activo:</b> <code>{proxy_active}</code>\n"
            f"<b>👤 User ID:</b> <code>{moodle_session.user_id or 'No autenticado'}</code>\n"
            f"<b>⏰ Hora servidor:</b> {time.strftime('%H:%M:%S')}\n\n"
            f"<b>⚡ Optimizaciones:</b>\n"
            f"• Proxies en paralelo\n"
            f"• Timeouts reducidos\n"
            f"• Cache inteligente"
        )
        
        bot.send_message(message.chat.id, text, parse_mode='HTML')
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ <b>Error:</b> {str(e)}", parse_mode='HTML')

@bot.message_handler(commands=['proxy'])
def handle_proxy(message):
    """Diagnóstico de proxies - VERSIÓN RÁPIDA"""
    try:
        status_msg = bot.send_message(
            message.chat.id, 
            "🔍 <b>Búsqueda rápida de proxies...</b>\n"
            "<i>Esto tomará ~5 segundos</i>", 
            parse_mode='HTML'
        )
        
        proxy_results = diagnosticar_proxies_rapido()
        proxy_active = obtener_proxy_activo() or "DIRECTO"
        
        text = (
            f"<b>🌐 DIAGNÓSTICO DE PROXIES - ⚡ RÁPIDO</b>\n\n"
            f"<b>🎯 Proxy activo:</b> <code>{proxy_active}</code>\n\n"
            f"<b>📋 Resultados ({len(proxy_results)} proxies):</b>\n" + "\n".join(proxy_results[:10]) + 
            f"\n\n<b>💡 Consejo:</b> Usa /fast para conexión directa"
        )
        
        bot.edit_message_text(
            text, 
            chat_id=message.chat.id, 
            message_id=status_msg.message_id, 
            parse_mode='HTML'
        )
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ <b>Error:</b> {str(e)}", parse_mode='HTML')

# Los handlers de archivos se mantienen igual (ya están optimizados)
@bot.message_handler(content_types=['document', 'photo', 'video', 'audio', 'voice'])
def handle_files(message):
    """Manejar archivos con feedback detallado - YA OPTIMIZADO"""
    try:
        if message.document:
            file_obj = message.document
            file_name = file_obj.file_name or f"documento_{message.message_id}"
        elif message.photo:
            file_obj = message.photo[-1]
            file_name = f"foto_{message.message_id}.jpg"
        elif message.video:
            file_obj = message.video
            file_name = file_obj.file_name or f"video_{message.message_id}.mp4"
        elif message.audio:
            file_obj = message.audio
            file_name = file_obj.file_name or f"audio_{message.message_id}.mp3"
        elif message.voice:
            file_obj = message.voice
            file_name = f"voz_{message.message_id}.ogg"
        else:
            bot.reply_to(message, "❌ <b>Tipo de archivo no soportado</b>", parse_mode='HTML')
            return

        file_size = file_obj.file_size or 0
        
        if file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
            bot.reply_to(message, f"❌ <b>Archivo muy grande. Máximo: {MAX_FILE_SIZE_MB}MB</b>", parse_mode='HTML')
            return

        status_msg = bot.reply_to(
            message, 
            f"📤 <b>Iniciando subida RÁPIDA...</b>\n\n"
            f"<b>📄 Archivo:</b> <code>{file_name}</code>\n"
            f"<b>💾 Tamaño:</b> {file_size / 1024 / 1024:.2f} MB\n"
            f"<b>🔄 Estado:</b> Descargando...",
            parse_mode='HTML'
        )

        file_info = bot.get_file(file_obj.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        bot.edit_message_text(
            f"📤 <b>Subiendo archivo...</b>\n\n"
            f"<b>📄 Archivo:</b> <code>{file_name}</code>\n"
            f"<b>💾 Tamaño:</b> {len(downloaded) / 1024 / 1024:.2f} MB\n"
            f"<b>🔄 Estado:</b> Conectando con Moodle...",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode='HTML'
        )
        
        resultado = subir_archivo_moodle(downloaded, file_name)
        
        if resultado['exito']:
            respuesta = (
                f"🎉 <b>¡ARCHIVO SUBIDO EXITOSAMENTE!</b>\n\n"
                f"<b>📄 Archivo:</b> <code>{resultado['nombre']}</code>\n"
                f"<b>💾 Tamaño:</b> {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"<b>👤 User ID:</b> <code>{resultado['user_id']}</code>\n"
                f"<b>🆔 Item ID:</b> <code>{resultado['itemid']}</code>\n"
                f"<b>🔗 Proxy usado:</b> <code>{resultado['proxy_used']}</code>\n"
                f"<b>🔄 Intento:</b> {resultado['intento']}/3\n\n"
                f"<b>🔗 ENLACE DIRECTO:</b>\n<code>{resultado['enlace']}</code>"
            )
            bot.edit_message_text(
                respuesta,
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                parse_mode='HTML'
            )
        else:
            error_msg = (
                f"❌ <b>ERROR AL SUBIR ARCHIVO</b>\n\n"
                f"<b>📄 Archivo:</b> <code>{file_name}</code>\n"
                f"<b>💾 Tamaño:</b> {len(downloaded) / 1024 / 1024:.2f} MB\n"
                f"<b>🔄 Intento:</b> {resultado.get('intento', 1)}/3\n\n"
                f"<b>⚠️ Error:</b> <code>{resultado['error']}</code>\n\n"
                f"<b>💡 Sugerencia:</b>\n"
                f"• Usa /fast para conexión directa\n"
                f"• Verifica con /status\n"
                f"• Intenta con archivo más pequeño"
            )
            bot.edit_message_text(
                error_msg,
                chat_id=message.chat.id,
                message_id=status_msg.message_id,
                parse_mode='HTML'
            )
            
    except Exception as e:
        logger.error(f"❌ Error general manejando archivo: {e}")
        bot.reply_to(message, f"❌ <b>Error interno del bot:</b> <code>{str(e)}</code>", parse_mode='HTML')

@bot.message_handler(func=lambda message: True)
def handle_other_messages(message):
    """Manejar otros mensajes"""
    if message.text and not message.text.startswith('/'):
        bot.reply_to(
            message, 
            "📤 <b>Envíame un archivo para subirlo a AulaElam</b>\n\n"
            "<b>⚡ Comandos rápidos:</b>\n"
            "/start - Estado rápido\n" 
            "/status - Info del sistema\n"
            "/proxy - Diagnóstico proxies\n"
            "/fast - Conexión directa\n\n"
            "<i>Ahora con respuesta instantánea</i>",
            parse_mode='HTML'
        )

# ============================
# MAIN ACELERADO
# ============================
def main():
    logger.info("🚀 INICIANDO BOT AULAELAM - ⚡ VERSIÓN ACELERADA")
    
    # Búsqueda inicial RÁPIDA de proxies
    buscar_proxies_rapido()
    
    # Verificar token de Telegram
    try:
        bot_info = bot.get_me()
        logger.info(f"✅ BOT CONECTADO: @{bot_info.username}")
    except Exception as e:
        logger.error(f"❌ Error con token Telegram: {e}")
        return
    
    # Verificar Moodle RÁPIDO
    try:
        if moodle_session.login_moodle_webservice():
            logger.info(f"✅ MOODLE CONECTADO - User ID: {moodle_session.user_id}")
        else:
            logger.warning("⚠️ No se pudo conectar con Moodle inicialmente")
    except Exception as e:
        logger.warning(f"⚠️ Error inicial con Moodle: {e}")
    
    # Iniciar polling con timeout optimizado
    logger.info("🔄 Iniciando polling de Telegram...")
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)  # ⚡ 30s → 20s
    except Exception as e:
        logger.error(f"❌ Error en polling: {e}")
        logger.info("🔄 Reiniciando en 3 segundos...")
        time.sleep(3)
        main()

if __name__ == "__main__":
    main()
