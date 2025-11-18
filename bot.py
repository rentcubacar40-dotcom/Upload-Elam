import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time
import re
import json
import hashlib
import sqlite3
from datetime import datetime
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import bs4

# ============================
# CONFIGURACIÓN
# ============================
class Config:
    def __init__(self):
        self.BOT_TOKEN = "8502790665:AAHuanhfYIe5ptUliYQBP7ognVOTG0uQoKk"
        self.MOODLE_URL = "https://aulacened.uci.cu"
        self.MOODLE_USERNAME = "eliel21"
        self.MOODLE_PASSWORD = "ElielThali2115."
        self.MAX_FILE_SIZE_MB = 50
        self.ADMIN_IDS = [4432]
        self.DATABASE_PATH = "bot_database.db"
        self.LOG_LEVEL = "INFO"

config = Config()

# ============================
# LOGGING
# ============================
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, config.LOG_LEVEL))
    
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    file_handler = logging.FileHandler('bot_aulacened.log', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    return logger

logger = setup_logging()

# ============================
# MOODLE MANAGER CON USUARIO/CONTRASEÑA
# ============================
class MoodleManager:
    def __init__(self):
        self.session = requests.Session()
        self.user_id = None
        self.logged_in = False
        self.setup_session()
        
    def setup_session(self):
        """Configurar sesión para aulacened.uci.cu"""
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'es-ES,es;q=0.9,en;q=0.8',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        })
        
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
    
    def login(self):
        """Login a aulacened.uci.cu usando usuario y contraseña"""
        try:
            logger.info("🔑 Iniciando sesión en aulacened.uci.cu...")
            
            # Primero obtener la página de login para extraer el token
            login_url = f"{config.MOODLE_URL}/login/index.php"
            response = self.session.get(login_url, timeout=10)
            
            if response.status_code != 200:
                logger.error(f"❌ Error accediendo a login: {response.status_code}")
                return False
            
            # Extraer el logintoken del formulario
            soup = bs4.BeautifulSoup(response.content, 'html.parser')
            logintoken_input = soup.find('input', {'name': 'logintoken'})
            
            if not logintoken_input:
                logger.error("❌ No se pudo encontrar el token de login")
                return False
            
            logintoken = logintoken_input.get('value', '')
            
            # Preparar datos del login
            login_data = {
                'username': config.MOODLE_USERNAME,
                'password': config.MOODLE_PASSWORD,
                'logintoken': logintoken,
                'anchor': ''
            }
            
            # Enviar formulario de login
            response = self.session.post(login_url, data=login_data, timeout=15)
            
            if response.status_code != 200:
                logger.error(f"❌ Error en login POST: {response.status_code}")
                return False
            
            # Verificar si el login fue exitoso
            if "login" in response.url or "invalidlogin" in response.text.lower():
                logger.error("❌ Credenciales incorrectas o login fallido")
                return False
            
            # Obtener el user_id desde la página de perfil
            user_id = self._get_user_id()
            if user_id:
                self.user_id = user_id
                self.logged_in = True
                logger.info(f"✅ Login exitoso - User ID: {self.user_id}")
                return True
            else:
                logger.error("❌ No se pudo obtener el User ID después del login")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error en login: {e}")
            return False
    
    def _get_user_id(self):
        """Obtener el ID del usuario desde el perfil"""
        try:
            # Intentar obtener el user_id desde diferentes páginas
            profile_url = f"{config.MOODLE_URL}/user/profile.php"
            response = self.session.get(profile_url, timeout=10)
            
            if response.status_code == 200:
                # Buscar el user_id en la URL o en el contenido
                soup = bs4.BeautifulSoup(response.content, 'html.parser')
                
                # Buscar en enlaces que contengan user id
                user_links = soup.find_all('a', href=re.compile(r'user\?id=\d+'))
                for link in user_links:
                    match = re.search(r'user\?id=(\d+)', link.get('href', ''))
                    if match:
                        return int(match.group(1))
                
                # Buscar en la URL actual
                if '?id=' in response.url:
                    match = re.search(r'id=(\d+)', response.url)
                    if match:
                        return int(match.group(1))
            
            return None
            
        except Exception as e:
            logger.error(f"Error obteniendo user_id: {e}")
            return None
    
    def upload_to_draft(self, file_content, filename):
        """Subir archivo al área draft del usuario"""
        try:
            if not self.logged_in and not self.login():
                raise Exception("No se pudo autenticar en Moodle")
            
            logger.info(f"📤 Subiendo archivo a draft: {filename}")
            
            # Obtener la página de archivos para extraer tokens
            files_url = f"{config.MOODLE_URL}/user/files.php"
            response = self.session.get(files_url, timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"No se pudo acceder a archivos: {response.status_code}")
            
            soup = bs4.BeautifulSoup(response.content, 'html.parser')
            
            # Buscar el formulario de upload
            upload_form = soup.find('form', {'enctype': 'multipart/form-data'})
            if not upload_form:
                raise Exception("No se encontró el formulario de upload")
            
            # Extraer datos necesarios del formulario
            sesskey_input = soup.find('input', {'name': 'sesskey'})
            sesskey = sesskey_input.get('value') if sesskey_input else ''
            
            if not sesskey:
                raise Exception("No se pudo obtener sesskey")
            
            # URL de upload (puede ser relativa o absoluta)
            action_url = upload_form.get('action', '')
            if action_url.startswith('/'):
                upload_url = f"{config.MOODLE_URL}{action_url}"
            elif not action_url.startswith('http'):
                upload_url = f"{config.MOODLE_URL}/{action_url}"
            else:
                upload_url = action_url
            
            # Preparar datos para el upload
            files = {
                'repo_upload_file': (filename, file_content, 'application/octet-stream')
            }
            
            data = {
                'sesskey': sesskey,
                'client_id': '',
                'itemid': 0,  # Draft area
                'repo_id': 4,  # Upload repository
                'ctx_id': 1,   # Context ID (puede variar)
                'author': '',
                'savepath': '/',
                'title': filename,
                'maxbytes': config.MAX_FILE_SIZE_MB * 1024 * 1024,
                'areamaxbytes': -1,
                'license': 'allrightsreserved'
            }
            
            # Realizar upload
            response = self.session.post(upload_url, files=files, data=data, timeout=30)
            
            if response.status_code != 200:
                raise Exception(f"Error en upload: {response.status_code}")
            
            # Verificar si el upload fue exitoso
            if 'success' in response.text.lower() or filename in response.text:
                logger.info(f"✅ Archivo subido exitosamente: {filename}")
                
                # Obtener información del archivo subido
                file_info = self._get_file_info(filename)
                return file_info
            else:
                raise Exception("Upload falló - respuesta del servidor indica error")
                
        except Exception as e:
            logger.error(f"❌ Error en upload_to_draft: {e}")
            raise
    
    def _get_file_info(self, filename):
        """Obtener información del archivo subido"""
        try:
            # Esta función necesitaría analizar la respuesta o hacer otra solicitud
            # Para simplificar, retornamos datos básicos
            return {
                'filename': filename,
                'itemid': int(time.time()),  # Temporal - debería obtenerse del response
                'contextid': 1,  # Temporal
                'url': f"{config.MOODLE_URL}/draftfile.php/1/user/draft/0/{urllib.parse.quote(filename)}"
            }
        except Exception as e:
            logger.error(f"Error obteniendo file info: {e}")
            return {
                'filename': filename,
                'itemid': int(time.time()),
                'contextid': 1,
                'url': f"{config.MOODLE_URL}/draftfile.php/1/user/draft/0/{urllib.parse.quote(filename)}"
            }
    
    def create_calendar_event(self, event_name, description, file_url=None):
        """Crear evento en el calendario de aulacened"""
        try:
            if not self.logged_in and not self.login():
                raise Exception("No se pudo autenticar en Moodle")
            
            logger.info(f"📅 Creando evento: {event_name}")
            
            # Acceder a la página de nuevo evento
            calendar_url = f"{config.MOODLE_URL}/calendar/event.php"
            response = self.session.get(calendar_url, timeout=10)
            
            if response.status_code != 200:
                raise Exception(f"No se pudo acceder al calendario: {response.status_code}")
            
            soup = bs4.BeautifulSoup(response.content, 'html.parser')
            
            # Extraer tokens del formulario
            sesskey_input = soup.find('input', {'name': 'sesskey'})
            sesskey = sesskey_input.get('value') if sesskey_input else ''
            
            if not sesskey:
                raise Exception("No se pudo obtener sesskey")
            
            # Preparar datos del evento
            event_data = {
                'sesskey': sesskey,
                '_qf__core_calendar_local_event_forms_create': 1,
                'name': event_name,
                'timestart[day]': datetime.now().day,
                'timestart[month]': datetime.now().month,
                'timestart[year]': datetime.now().year,
                'timestart[hour]': datetime.now().hour,
                'timestart[minute]': datetime.now().minute,
                'description[text]': description,
                'description[format]': 1,  # HTML
                'eventtype': 'user',
                'submitbutton': 'Guardar'
            }
            
            # Si hay archivo, agregar referencia en la descripción
            if file_url:
                event_data['description[text]'] = f"{description}\n\n🔗 Archivo: {file_url}"
            
            # Enviar formulario
            response = self.session.post(calendar_url, data=event_data, timeout=20)
            
            if response.status_code != 200:
                raise Exception(f"Error creando evento: {response.status_code}")
            
            # Verificar si el evento se creó exitosamente
            if 'eventcreated' in response.text.lower() or 'event' in response.url:
                logger.info("✅ Evento creado exitosamente")
                return True
            else:
                raise Exception("No se pudo crear el evento - verificar respuesta")
                
        except Exception as e:
            logger.error(f"❌ Error en create_calendar_event: {e}")
            raise

# ============================
# BOT MANAGER
# ============================
class BotManager:
    def __init__(self):
        self.bot = telebot.TeleBot(config.BOT_TOKEN, parse_mode='HTML')
        self.moodle = MoodleManager()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Configurar handlers del bot"""
        
        @self.bot.message_handler(commands=['start', 'help'])
        def handle_start(message):
            self.command_start(message)
        
        @self.bot.message_handler(commands=['draft'])
        def handle_draft(message):
            self.command_draft(message)
        
        @self.bot.message_handler(commands=['calendar'])
        def handle_calendar(message):
            self.command_calendar(message)
        
        @self.bot.message_handler(commands=['login'])
        def handle_login(message):
            self.command_login(message)
        
        @self.bot.message_handler(content_types=['document', 'photo', 'video', 'audio', 'voice'])
        def handle_files(message):
            self.handle_file_upload(message)
        
        @self.bot.message_handler(func=lambda message: True)
        def handle_other(message):
            self.handle_other_messages(message)
    
    def command_start(self, message):
        """Comando /start"""
        try:
            # Intentar login a Moodle
            moodle_status = "🟢 CONECTADO" if self.moodle.login() else "🔴 DESCONECTADO"
            
            welcome_text = f"""
<b>🤖 Bot AulaCENED - UCI</b>

<b>Estado del sistema:</b>
🌐 Moodle: {moodle_status}
🔗 URL: <code>{config.MOODLE_URL}</code>
👤 Usuario: <code>{config.MOODLE_USERNAME}</code>
📏 Límite: {config.MAX_FILE_SIZE_MB} MB

<b>Comandos disponibles:</b>
/draft - Subir archivo a área personal
/calendar - Crear evento con archivo
/login - Reautenticar en Moodle

<b>Características:</b>
✅ Autenticación usuario/contraseña
✅ Subida a archivos personales
✅ Eventos en calendario
✅ Sistema robusto

<i>Envía un archivo o usa un comando para comenzar...</i>
            """
            
            self.bot.reply_to(message, welcome_text)
            
        except Exception as e:
            logger.error(f"Error en command_start: {e}")
            self.bot.reply_to(message, "❌ Error inicializando el bot")
    
    def command_draft(self, message):
        """Comando /draft"""
        response_text = """
📁 <b>Modo ARCHIVOS PERSONALES</b>

El próximo archivo se subirá a tu área personal de Moodle.

<b>Ventajas:</b>
• Archivo en tu espacio personal
• Acceso directo desde Moodle
• Sistema confiable

<b>Instrucciones:</b>
1. Envía el archivo ahora
2. Espera la confirmación
3. Recibe tu enlace de descarga

<i>¡Envía tu archivo ahora!</i>
        """
        self.bot.reply_to(message, response_text)
    
    def command_calendar(self, message):
        """Comando /calendar"""
        response_text = """
📅 <b>Modo CALENDARIO</b>

El próximo archivo creará un evento en tu calendario de Moodle.

<b>Ventajas:</b>
• Evento organizado por fecha
• Enlace en la descripción
• Fácil acceso desde calendario

<b>Instrucciones:</b>
1. Envía el archivo ahora
2. Se creará un evento en calendario
3. El evento tendrá el enlace de descarga

<i>¡Envía tu archivo ahora!</i>
        """
        self.bot.reply_to(message, response_text)
    
    def command_login(self, message):
        """Comando /login - Reautenticar"""
        try:
            self.bot.reply_to(message, "🔄 Reautenticando en Moodle...")
            
            if self.moodle.login():
                self.bot.reply_to(message, "✅ Reautenticación exitosa")
            else:
                self.bot.reply_to(message, "❌ Error en reautenticación")
                
        except Exception as e:
            logger.error(f"Error en command_login: {e}")
            self.bot.reply_to(message, f"❌ Error: {str(e)}")
    
    def handle_file_upload(self, message):
        """Manejar subida de archivos"""
        try:
            # Determinar tipo de archivo y nombre
            if message.document:
                file_obj = message.document
                file_name = file_obj.file_name or f"document_{message.message_id}.bin"
            elif message.photo:
                file_obj = message.photo[-1]
                file_name = f"photo_{message.message_id}.jpg"
            elif message.video:
                file_obj = message.video
                file_name = file_obj.file_name or f"video_{message.message_id}.mp4"
            elif message.audio:
                file_obj = message.audio
                file_name = file_obj.file_name or f"audio_{message.message_id}.mp3"
            elif message.voice:
                file_obj = message.voice
                file_name = f"voice_{message.message_id}.ogg"
            else:
                self.bot.reply_to(message, "❌ Tipo de archivo no soportado")
                return
            
            # Verificar tamaño
            file_size = file_obj.file_size
            if file_size > config.MAX_FILE_SIZE_MB * 1024 * 1024:
                self.bot.reply_to(
                    message, 
                    f"❌ Archivo demasiado grande. Máximo: {config.MAX_FILE_SIZE_MB}MB"
                )
                return
            
            # Determinar modo
            upload_mode = 'draft'
            if message.text and '/calendar' in message.text:
                upload_mode = 'calendar'
            
            # Mensaje de estado
            status_msg = self.bot.reply_to(
                message,
                f"⏳ <b>Procesando archivo...</b>\n\n"
                f"📄 <b>Archivo:</b> <code>{file_name}</code>\n"
                f"💾 <b>Tamaño:</b> {file_size / 1024 / 1024:.2f} MB\n"
                f"🔧 <b>Modo:</b> {upload_mode.upper()}\n"
                f"🔄 <b>Estado:</b> Descargando...",
            )
            
            # Descargar archivo
            file_info = self.bot.get_file(file_obj.file_id)
            file_content = self.bot.download_file(file_info.file_path)
            
            # Actualizar estado
            self.bot.edit_message_text(
                f"⏳ <b>Procesando archivo...</b>\n\n"
                f"📄 <b>Archivo:</b> <code>{file_name}</code>\n"
                f"💾 <b>Tamaño:</b> {len(file_content) / 1024 / 1024:.2f} MB\n"
                f"🔧 <b>Modo:</b> {upload_mode.upper()}\n"
                f"🔄 <b>Estado:</b> Subiendo a Moodle...",
                message.chat.id,
                status_msg.message_id
            )
            
            # Subir según modo
            if upload_mode == 'draft':
                result = self._upload_draft(file_content, file_name)
            else:
                result = self._upload_calendar(file_content, file_name)
            
            # Mostrar resultado
            self.bot.edit_message_text(
                result['message'],
                message.chat.id,
                status_msg.message_id
            )
            
        except Exception as e:
            logger.error(f"Error en handle_file_upload: {e}")
            try:
                self.bot.edit_message_text(
                    f"❌ <b>Error procesando archivo</b>\n\n"
                    f"<code>{str(e)}</code>\n\n"
                    f"💡 <i>Intenta con /login o más tarde</i>",
                    message.chat.id,
                    status_msg.message_id
                )
            except:
                self.bot.reply_to(message, f"❌ Error: {str(e)}")
    
    def _upload_draft(self, file_content, file_name):
        """Subir archivo a área personal"""
        try:
            file_info = self.moodle.upload_to_draft(file_content, file_name)
            
            success_message = f"""
🎉 <b>¡ARCHIVO SUBIDO EXITOSAMENTE!</b>

📄 <b>Archivo:</b> <code>{file_name}</code>
💾 <b>Tamaño:</b> {len(file_content) / 1024 / 1024:.2f} MB
📁 <b>Ubicación:</b> Archivos personales

🔗 <b>Enlace de descarga:</b>
<code>{file_info['url']}</code>

💡 <i>Accede desde Moodle → Archivos personales</i>
            """
            
            return {'success': True, 'message': success_message}
            
        except Exception as e:
            error_message = f"""
❌ <b>ERROR AL SUBIR ARCHIVO</b>

📄 <b>Archivo:</b> <code>{file_name}</code>
💾 <b>Tamaño:</b> {len(file_content) / 1024 / 1024:.2f} MB

⚠️ <b>Error:</b> <code>{str(e)}</code>

💡 <i>Usa /login para reautenticar o intenta más tarde</i>
            """
            return {'success': False, 'message': error_message}
    
    def _upload_calendar(self, file_content, file_name):
        """Subir archivo vía calendario"""
        try:
            # Primero subir a draft
            file_info = self.moodle.upload_to_draft(file_content, file_name)
            
            # Crear evento en calendario
            event_name = f"📎 {file_name}"
            description = f"""
<p>Archivo compartido: <strong>{file_name}</strong></p>
<p>Tamaño: {len(file_content) / 1024 / 1024:.2f} MB</p>
<p>Enlace de descarga: <a href="{file_info['url']}">Descargar archivo</a></p>
<p>Subido el: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
            """
            
            self.moodle.create_calendar_event(event_name, description, file_info['url'])
            
            success_message = f"""
🎉 <b>¡EVENTO CREADO EXITOSAMENTE!</b>

📄 <b>Archivo:</b> <code>{file_name}</code>
💾 <b>Tamaño:</b> {len(file_content) / 1024 / 1024:.2f} MB
📅 <b>Ubicación:</b> Calendario de Moodle

🔗 <b>Enlace de descarga:</b>
<code>{file_info['url']}</code>

💡 <i>El archivo está disponible en tu calendario de Moodle</i>
            """
            
            return {'success': True, 'message': success_message}
            
        except Exception as e:
            error_message = f"""
❌ <b>ERROR AL CREAR EVENTO</b>

📄 <b>Archivo:</b> <code>{file_name}</code>
💾 <b>Tamaño:</b> {len(file_content) / 1024 / 1024:.2f} MB

⚠️ <b>Error:</b> <code>{str(e)}</code>

💡 <i>Intenta con /draft para subida simple</i>
            """
            return {'success': False, 'message': error_message}
    
    def handle_other_messages(self, message):
        """Manejar otros mensajes"""
        help_text = """
🤖 <b>Bot AulaCENED - Ayuda</b>

<b>Comandos disponibles:</b>
/start - Iniciar bot y ver estado
/draft - Subir archivo a archivos personales  
/calendar - Crear evento con archivo
/login - Reautenticar en Moodle

<b>Para subir archivos:</b>
1. Usa un comando o envía directamente el archivo
2. Elige el modo de subida
3. Recibe tu enlace de descarga

<b>Características:</b>
✅ Autenticación con usuario/contraseña
✅ Soporte para múltiples formatos
✅ Límite: 50MB por archivo
✅ Sistema específico para aulacened.uci.cu

<i>Envía un archivo o usa un comando para comenzar...</i>
        """
        self.bot.reply_to(message, help_text)
    
    def start_bot(self):
        """Iniciar el bot"""
        try:
            logger.info("🚀 Iniciando Bot AulaCENED...")
            
            # Verificar configuración
            if not config.BOT_TOKEN:
                logger.error("❌ Faltan variables de configuración")
                return
            
            # Verificar Telegram
            bot_info = self.bot.get_me()
            logger.info(f"✅ Bot iniciado: @{bot_info.username}")
            
            # Verificar Moodle
            if self.moodle.login():
                logger.info(f"✅ Moodle conectado - UserID: {self.moodle.user_id}")
            else:
                logger.warning("⚠️ No se pudo conectar con Moodle inicialmente")
            
            # Iniciar polling
            logger.info("🔄 Iniciando polling...")
            self.bot.infinity_polling(timeout=60, long_polling_timeout=60)
            
        except Exception as e:
            logger.error(f"❌ Error iniciando bot: {e}")
            logger.info("🔄 Reiniciando en 5 segundos...")
            time.sleep(5)
            self.start_bot()

# ============================
# EJECUCIÓN
# ============================
if __name__ == "__main__":
    try:
        bot_manager = BotManager()
        bot_manager.start_bot()
    except KeyboardInterrupt:
        logger.info("⏹️ Bot detenido por el usuario")
    except Exception as e:
        logger.error(f"❌ Error fatal: {e}")
