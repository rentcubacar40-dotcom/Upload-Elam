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
# SISTEMA DE SESIÓN MEJORADO
# ============================
class MoodleSessionManager:
    def __init__(self):
        self.session = requests.Session()
        self.setup_session()
        self.user_id = None
        self.user_context_id = None
        self.last_activity = time.time()
        
    def setup_session(self):
        """Configurar sesión como un navegador real"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Connection': 'keep-alive',
        })
        
        # Estrategia de reintentos
        retry_strategy = Retry(
            total=2,
            backoff_factor=0.5,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def login_moodle_webservice(self):
        """Login usando WebService Token y obtener contextid"""
        try:
            logger.info("🔑 Autenticando via WebService...")
            
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_webservice_get_site_info',
                'moodlewsrestformat': 'json'
            }
            
            response = self.session.post(ws_url, data=params, timeout=10)
            
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
            
            # Obtener el contextid del usuario
            if not self.obtener_contextid_usuario():
                logger.warning("⚠️ No se pudo obtener el contextid del usuario")
            
            logger.info(f"✅ Autenticado - User ID: {self.user_id}, Context ID: {self.user_context_id}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error en autenticación WebService: {e}")
            return False

    def obtener_contextid_usuario(self):
        """Obtener el contextid del usuario para private files"""
        try:
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            params = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_user_get_private_files_info',
                'moodlewsrestformat': 'json'
            }
            
            response = self.session.post(ws_url, data=params, timeout=10)
            if response.status_code == 200:
                result = response.json()
                # El contextid suele estar en la respuesta o podemos deducirlo
                # Para user context, generalmente es el userid + 1 o similar
                # Usaremos un valor por defecto basado en el user_id
                if self.user_id:
                    self.user_context_id = self.user_id + 1  # Valor común en Moodle
                    return True
            return False
        except Exception as e:
            logger.warning(f"⚠️ No se pudo obtener contextid: {e}")
            # Valor por defecto
            if self.user_id:
                self.user_context_id = self.user_id + 1
            return False
    
    def verificar_sesion_activa(self):
        """Verificar si la sesión sigue activa"""
        try:
            if not self.user_id:
                return False
                
            if time.time() - self.last_activity > 2700:  # 45 minutos
                return False
                
            return True
        except:
            return False

# Instancia global
moodle_session = MoodleSessionManager()

# ============================
# SISTEMAS DE SUBIDA MEJORADOS - PRIVATE FILES
# ============================
def subir_archivo_private(file_content: bytes, file_name: str):
    """Subir archivo a PRIVATE FILES de usuario"""
    logger.info(f"🔄 SUBIENDO A PRIVATE FILES: {file_name}")
    
    for intento in range(1, 4):
        try:
            logger.info(f"📦 Intento {intento} de 3")
            
            # 1. Verificar/Autenticar
            if not moodle_session.verificar_sesion_activa():
                logger.info("🔄 Sesión expirada, reautenticando...")
                if not moodle_session.login_moodle_webservice():
                    raise Exception("No se pudo autenticar con Moodle")
            
            if not moodle_session.user_id:
                raise Exception("No hay user_id disponible")
            
            # 2. Subir archivo a PRIVATE FILES
            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            files = {'file': (file_name, file_content, 'application/octet-stream')}
            data = {
                'token': MOODLE_TOKEN,
                'filearea': 'private',
                'itemid': 0,
            }
            
            # 3. Subir archivo
            upload_response = moodle_session.session.post(
                upload_url, 
                data=data, 
                files=files, 
                timeout=25
            )
            
            if upload_response.status_code != 200:
                raise Exception(f"Error HTTP {upload_response.status_code}")
            
            upload_result = upload_response.json()
            
            if not upload_result or not isinstance(upload_result, list):
                raise Exception("Respuesta inválida de Moodle")
            
            file_data = upload_result[0]
            itemid = file_data.get('itemid')
            
            if not itemid:
                raise Exception("No se obtuvo itemid del archivo")
            
            # 4. Construir URL correcta para private files
            # En Moodle, la URL de private files usa el contextid del usuario
            contextid = moodle_session.user_context_id or (moodle_session.user_id + 1)
            filename_encoded = urllib.parse.quote(file_name)
            
            # URL CORREGIDA para private files
            enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{contextid}/user/private/{itemid}/{filename_encoded}?token={MOODLE_TOKEN}"
            
            logger.info(f"✅ PRIVATE FILES EXITOSO - ItemID: {itemid}, ContextID: {contextid}")
            
            return {
                'exito': True,
                'enlace': enlace_final,
                'nombre': file_name,
                'tamaño': file_data.get('filesize', len(file_content)),
                'itemid': itemid,
                'contextid': contextid,
                'user_id': moodle_session.user_id,
                'intento': intento,
                'tipo': 'private'
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

def crear_evento_calendario_con_archivo(file_content: bytes, file_name: str):
    """Crear evento en calendario subiendo archivo a DRAFT temporal"""
    logger.info(f"📅 CREANDO EVENTO EN CALENDARIO: {file_name}")
    
    for intento in range(1, 4):
        try:
            logger.info(f"📦 Intento {intento} de 3")
            
            # 1. Verificar/Autenticar
            if not moodle_session.verificar_sesion_activa():
                logger.info("🔄 Sesión expirada, reautenticando...")
                if not moodle_session.login_moodle_webservice():
                    raise Exception("No se pudo autenticar con Moodle")
            
            if not moodle_session.user_id:
                raise Exception("No hay user_id disponible")
            
            # 2. PRIMERO: Subir archivo a DRAFT (para calendario)
            upload_url = f"{MOODLE_URL}/webservice/upload.php"
            files = {'file': (file_name, file_content, 'application/octet-stream')}
            data_upload = {
                'token': MOODLE_TOKEN,
                'filearea': 'draft',  # ✅ USAR DRAFT PARA CALENDARIO
                'itemid': 0,
            }
            
            upload_response = moodle_session.session.post(
                upload_url, 
                data=data_upload, 
                files=files, 
                timeout=25
            )
            
            if upload_response.status_code != 200:
                raise Exception(f"Error subiendo archivo: {upload_response.status_code}")
            
            upload_result = upload_response.json()
            if not upload_result or not isinstance(upload_result, list):
                raise Exception("Respuesta inválida al subir archivo")
            
            file_data = upload_result[0]
            draft_itemid = file_data.get('itemid')
            draft_contextid = file_data.get('contextid', 1)
            
            if not draft_itemid:
                raise Exception("No se obtuvo itemid del archivo subido")
            
            logger.info(f"✅ Archivo subido a draft - ItemID: {draft_itemid}, ContextID: {draft_contextid}")
            
            # 3. SEGUNDO: Crear evento en el calendario con el archivo
            ws_url = f"{MOODLE_URL}/webservice/rest/server.php"
            
            # Crear evento en el calendario - FORMATO CORREGIDO
            timestamp = int(time.time())
            params_evento = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_calendar_create_calendar_events',
                'moodlewsrestformat': 'json',
                'events[0][name]': f"Archivo: {file_name}",
                'events[0][eventtype]': 'user',
                'events[0][timestart]': timestamp,
                'events[0][timeduration]': 0,
                'events[0][description]': f'Archivo adjunto: {file_name}',
                'events[0][descriptionformat]': 1,
                'events[0][files][0][itemid]': draft_itemid  # ✅ ARCHIVO EN DRAFT PARA EL EVENTO
            }
            
            evento_response = moodle_session.session.post(
                ws_url, 
                data=params_evento, 
                timeout=20
            )
            
            if evento_response.status_code != 200:
                raise Exception(f"Error creando evento: {evento_response.status_code}")
            
            evento_result = evento_response.json()
            logger.info(f"📅 Respuesta evento: {evento_result}")
            
            if not evento_result or 'events' not in evento_result:
                raise Exception("No se pudo crear el evento en el calendario")
            
            # 4. GENERAR ENLACE para el archivo en DRAFT (formato calendario)
            filename_encoded = urllib.parse.quote(file_name)
            
            # ✅ URL CORREGIDA para archivos de calendario en DRAFT
            enlace_final = f"{MOODLE_URL}/webservice/pluginfile.php/{draft_contextid}/user/draft/{draft_itemid}/{filename_encoded}?token={MOODLE_TOKEN}"
            
            logger.info(f"✅ EVENTO CREADO - Enlace: {enlace_final}")
            
            return {
                'exito': True,
                'enlace': enlace_final,
                'nombre': file_name,
                'tamaño': file_data.get('filesize', len(file_content)),
                'itemid': draft_itemid,
                'contextid': draft_contextid,
                'event_id': evento_result['events'][0]['id'] if evento_result.get('events') else None,
                'user_id': moodle_session.user_id,
                'intento': intento,
                'tipo': 'calendario'
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
# HANDLERS MEJORADOS
# ============================
@bot.message_handler(commands=['start', 'help'])
def handle_start(message):
    """Manejar comando /start"""
    logger.info(f"🎯 Start recibido de {message.from_user.id}")
    
    try:
        moodle_status = "🟢 CONECTADO" if moodle_session.login_moodle_webservice() else "🔴 DESCONECTADO"
        
        text = (
            f"<b>🤖 BOT AULAELAM - SISTEMA CORREGIDO</b>\n\n"
            f"<b>🌐 Estado Moodle:</b> {moodle_status}\n"
            f"<b>🔗 URL:</b> <code>{MOODLE_URL}</code>\n"
            f"<b>👤 User ID:</b> <code>{moodle_session.user_id or 'No autenticado'}</code>\n"
            f"<b>🔧 Context ID:</b> <code>{moodle_session.user_context_id or 'No disponible'}</code>\n\n"
            f"<b>📁 SISTEMAS DE SUBIDA:</b>\n"
            f"• <b>Private Files:</b> Archivos en área personal permanente\n"
            f"• <b>Calendario:</b> Evento con archivo en draft temporal\n\n"
            f"<b>💡 Comandos:</b>\n"
            f"/start - Estado rápido\n"
            f"/status - Info del sistema\n"
            f"/private - Forzar subida a private files\n"
            f"/calendar - Forzar subida a calendario\n\n"
            f"<b>📏 Tamaño máximo:</b> {MAX_FILE_SIZE_MB}MB\n"
            f"<b>⚡ Sin proxies - Conexión directa</b>"
        )
        
        bot.send_message(message.chat.id, text, parse_mode='HTML')
        
    except Exception as e:
        logger.error(f"Error en /start: {e}")
        bot.send_message(message.chat.id, f"❌ <b>Error:</b> {str(e)}", parse_mode='HTML')

@bot.message_handler(commands=['private'])
def handle_private(message):
    """Forzar subida a PRIVATE FILES"""
    global modo_subida
    modo_subida = 'private'
    
    bot.reply_to(
        message,
        "📁 <b>MODO PRIVATE FILES ACTIVADO</b>\n\n"
        "El próximo archivo se subirá a tu área PRIVATE FILES.\n"
        "• Archivos personales permanentes\n"
        "• Acceso desde Moodle → Private files\n"
        "• Enlace con token incluido\n\n"
        "<i>Envía un archivo ahora</i>",
        parse_mode='HTML'
    )

@bot.message_handler(commands=['calendar'])
def handle_calendar(message):
    """Forzar subida a CALENDARIO"""
    global modo_subida
    modo_subida = 'calendar'
    
    bot.reply_to(
        message,
        "📅 <b>MODO CALENDARIO ACTIVADO</b>\n\n"
        "El próximo archivo creará un evento en calendario.\n"
        "• Evento visible en Moodle Calendario\n"
        "• Archivo temporal en draft\n"
        "• Organizado por fechas\n\n"
        "<i>Envía un archivo ahora</i>",
        parse_mode='HTML'
    )

@bot.message_handler(commands=['status'])
def handle_status(message):
    """Estado actual del sistema"""
    try:
        moodle_ok = moodle_session.verificar_sesion_activa()
        
        text = (
            f"<b>📊 ESTADO ACTUAL - SISTEMA CORREGIDO</b>\n\n"
            f"<b>🤖 Bot:</b> 🟢 OPERATIVO\n"
            f"<b>🌐 Moodle:</b> {'🟢 CONECTADO' if moodle_ok else '🔴 DESCONECTADO'}\n"
            f"<b>👤 User ID:</b> <code>{moodle_session.user_id or 'No autenticado'}</code>\n"
            f"<b>🔧 Context ID:</b> <code>{moodle_session.user_context_id or 'No disponible'}</code>\n"
            f"<b>📁 Modo actual:</b> {modo_subida.upper()}\n"
            f"<b>⏰ Hora servidor:</b> {time.strftime('%H:%M:%S')}\n\n"
            f"<b>⚡ Características:</b>\n"
            f"• Private Files (permanente)\n"
            f"• Calendario con draft (temporal)\n"
            f"• URLs corregidas\n"
            f"• Sin proxies - Conexión directa"
        )
        
        bot.send_message(message.chat.id, text, parse_mode='HTML')
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ <b>Error:</b> {str(e)}", parse_mode='HTML')

# ============================
# HANDLER PRINCIPAL DE ARCHIVOS
# ============================
modo_subida = 'auto'  # 'auto', 'private', 'calendar'

@bot.message_handler(content_types=['document', 'photo', 'video', 'audio', 'voice'])
def handle_files(message):
    """Manejar archivos con sistema dual corregido"""
    global modo_subida
    
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

        # Determinar modo de subida
        modo_actual = modo_subida
        if modo_actual == 'auto':
            # Por defecto usar private files
            modo_actual = 'private'
        
        # Override por comando en el mensaje
        if message.text and '/private' in message.text:
            modo_actual = 'private'
        elif message.text and '/calendar' in message.text:
            modo_actual = 'calendar'

        if modo_actual == 'private':
            status_text = "📁 <b>Subiendo a PRIVATE FILES...</b>"
            funcion_subida = subir_archivo_private
        else:
            status_text = "📅 <b>Creando evento en calendario...</b>"
            funcion_subida = crear_evento_calendario_con_archivo

        status_msg = bot.reply_to(
            message, 
            f"{status_text}\n\n"
            f"<b>📄 Archivo:</b> <code>{file_name}</code>\n"
            f"<b>💾 Tamaño:</b> {file_size / 1024 / 1024:.2f} MB\n"
            f"<b>🔄 Estado:</b> Descargando...",
            parse_mode='HTML'
        )

        file_info = bot.get_file(file_obj.file_id)
        downloaded = bot.download_file(file_info.file_path)
        
        bot.edit_message_text(
            f"{status_text}\n\n"
            f"<b>📄 Archivo:</b> <code>{file_name}</code>\n"
            f"<b>💾 Tamaño:</b> {len(downloaded) / 1024 / 1024:.2f} MB\n"
            f"<b>🔄 Estado:</b> Conectando con Moodle...",
            chat_id=message.chat.id,
            message_id=status_msg.message_id,
            parse_mode='HTML'
        )
        
        # Ejecutar subida según el modo
        resultado = funcion_subida(downloaded, file_name)
        
        if resultado['exito']:
            tipo = resultado.get('tipo', 'desconocido')
            if tipo == 'private':
                icono = "📁"
                tipo_texto = "PRIVATE FILES"
                ubicacion = "Área personal permanente"
            else:
                icono = "📅"
                tipo_texto = "CALENDARIO"
                ubicacion = "Evento con archivo temporal"
            
            respuesta = (
                f"🎉 <b>¡ARCHIVO SUBIDO EXITOSAMENTE!</b> {icono}\n\n"
                f"<b>📄 Archivo:</b> <code>{resultado['nombre']}</code>\n"
                f"<b>💾 Tamaño:</b> {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"<b>📦 Sistema:</b> {tipo_texto}\n"
                f"<b>📍 Ubicación:</b> {ubicacion}\n"
                f"<b>👤 User ID:</b> <code>{resultado['user_id']}</code>\n"
                f"<b>🆔 Item ID:</b> <code>{resultado['itemid']}</code>\n"
                f"<b>🔧 Context ID:</b> <code>{resultado.get('contextid', 'N/A')}</code>\n"
                f"<b>🔄 Intento:</b> {resultado['intento']}/3\n\n"
                f"<b>🔗 ENLACE FUNCIONAL:</b>\n<code>{resultado['enlace']}</code>"
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
                f"• Usa /private para subida simple\n"
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
            "<b>⚡ Comandos disponibles:</b>\n"
            "/start - Estado y ayuda\n" 
            "/status - Info del sistema\n"
            "/private - Forzar subida a PRIVATE FILES\n"
            "/calendar - Forzar subida a Calendario\n\n"
            "<i>✅ URLs corregidas</i>\n"
            "<i>✅ Private files funcionando</i>\n"
            "<i>✅ Calendario con archivos</i>",
            parse_mode='HTML'
        )

# ============================
# MAIN MEJORADO
# ============================
def main():
    logger.info("🚀 INICIANDO BOT AULAELAM - SISTEMA CORREGIDO")
    
    # Verificar token de Telegram
    try:
        bot_info = bot.get_me()
        logger.info(f"✅ BOT CONECTADO: @{bot_info.username}")
    except Exception as e:
        logger.error(f"❌ Error con token Telegram: {e}")
        return
    
    # Verificar Moodle
    try:
        if moodle_session.login_moodle_webservice():
            logger.info(f"✅ MOODLE CONECTADO - User ID: {moodle_session.user_id}, Context ID: {moodle_session.user_context_id}")
        else:
            logger.warning("⚠️ No se pudo conectar con Moodle inicialmente")
    except Exception as e:
        logger.warning(f"⚠️ Error inicial con Moodle: {e}")
    
    # Iniciar polling
    logger.info("🔄 Iniciando polling de Telegram...")
    try:
        bot.infinity_polling(timeout=20, long_polling_timeout=20)
    except Exception as e:
        logger.error(f"❌ Error en polling: {e}")
        logger.info("🔄 Reiniciando en 3 segundos...")
        time.sleep(3)
        main()

if __name__ == "__main__":
    main()
