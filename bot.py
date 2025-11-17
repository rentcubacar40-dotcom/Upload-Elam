import os
import requests
import logging
import telebot
from telebot import types

# ============================
# CONFIGURACIÓN
# ============================

# Tokens configurados
BOT_TOKEN = "8502790665:AAHuanhfYIe5ptUliYQBP7ognVOTG0uQoKk"
MOODLE_TOKEN = "784e9718073ccee20854df8a10536659"
MOODLE_URL = "https://aulaelam.sld.cu"

# Configurar logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Inicializar bot
bot = telebot.TeleBot(BOT_TOKEN)

# ============================
# FUNCIONES AULAELAM
# ============================

def subir_archivo_aulaelam(file_content, file_name):
    """Subir archivo a AulaElam y obtener enlace directo"""
    try:
        logger.info(f"📤 Subiendo archivo: {file_name}")
        
        # Preparar datos para upload
        files = {
            'file': (file_name, file_content)
        }
        data = {
            'token': MOODLE_TOKEN,
            'filearea': 'draft',
            'itemid': '0'
        }
        
        # Subir archivo
        response = requests.post(
            f"{MOODLE_URL}/webservice/upload.php",
            files=files,
            data=data,
            timeout=30
        )
        
        if response.status_code == 200:
            resultado = response.json()
            if resultado and len(resultado) > 0:
                file_data = resultado[0]
                contextid = file_data.get('contextid', '')
                itemid = file_data.get('itemid', '')
                
                if contextid and itemid:
                    # Generar enlace directo
                    import urllib.parse
                    file_name_encoded = urllib.parse.quote(file_name)
                    enlace = (
                        f"{MOODLE_URL}/webservice/pluginfile.php/"
                        f"{contextid}/calendar/event_attachment/"
                        f"{itemid}/{file_name_encoded}"
                        f"?token={MOODLE_TOKEN}"
                    )
                    
                    return {
                        'exito': True,
                        'enlace': enlace,
                        'nombre': file_name,
                        'tamaño': file_data.get('filesize', 0),
                        'itemid': itemid,
                        'contextid': contextid
                    }
        
        return {'exito': False, 'error': 'Error en la subida'}
        
    except Exception as e:
        logger.error(f"Error subiendo archivo: {e}")
        return {'exito': False, 'error': str(e)}

def crear_evento_calendario(file_name, itemid):
    """Crear evento en calendario para hacer el archivo accesible"""
    try:
        import time
        
        payload = {
            'wstoken': MOODLE_TOKEN,
            'wsfunction': 'core_calendar_submit_create_update_form',
            'moodlewsrestformat': 'json',
            'formdata': (
                f'name=Archivo: {file_name}&'
                f'timestart={int(time.time()) + 3600}&'
                f'eventtype=user&'
                f'description[text]=Subido via Bot&'
                f'description[format]=1&'
                f'files[0]={itemid}'
            )
        }
        
        response = requests.post(
            f"{MOODLE_URL}/webservice/rest/server.php",
            data=payload,
            timeout=30
        )
        
        return response.status_code == 200
        
    except Exception as e:
        logger.error(f"Error creando evento: {e}")
        return False

# ============================
# MANEJADORES DE COMANDOS
# ============================

@bot.message_handler(commands=['start'])
def start_command(message):
    """Comando /start"""
    text = """
🤖 **BOT AULAELAM - ACTIVO** 🤖

¡Hola! Soy tu asistente para subir archivos a AulaElam.

📁 **¿CÓMO FUNCIONO?**
1. Envías cualquier archivo
2. Lo subo a AulaElam automáticamente
3. Te devuelvo el **ENLACE DIRECTO** de descarga

🔗 **ENLACES 100% FUNCIONALES**
• Idénticos a los de AulaElam
• Token incluido
• Descarga inmediata

📎 **¡Envía un archivo para comenzar!**

🔧 *Comandos:*
/start - Este mensaje
/status - Ver estado
    """
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(commands=['status'])
def status_command(message):
    """Comando /status - Verificar estado"""
    try:
        # Verificar conexión con AulaElam
        response = requests.get(MOODLE_URL, timeout=10)
        if response.status_code == 200:
            estado = "🟢 Conectado"
        else:
            estado = f"🔴 Error {response.status_code}"
        
        text = f"""
✅ **BOT ACTIVO - CHOREO**

• **AulaElam:** {estado}
• **Modo:** Polling
• **Plataforma:** Choreo
• **Estado:** 🟢 Funcionando

¡Listo para recibir archivos!
        """
        bot.send_message(message.chat.id, text, parse_mode='Markdown')
        
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Error de conexión: {str(e)}")

# ============================
# MANEJADOR DE ARCHIVOS
# ============================

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    """Manejar documentos subidos"""
    try:
        file_info = bot.get_file(message.document.file_id)
        file_name = message.document.file_name
        file_size = message.document.file_size
        
        logger.info(f"📥 Archivo recibido: {file_name} ({file_size} bytes)")
        
        # Verificar tamaño (50MB máximo)
        if file_size > 50 * 1024 * 1024:
            bot.reply_to(
                message, 
                "❌ *Archivo demasiado grande*\n\n• Límite: 50MB\n• Tu archivo: {:.2f}MB".format(file_size / 1024 / 1024),
                parse_mode='Markdown'
            )
            return
        
        # Notificar recepción
        bot.reply_to(
            message, 
            f"📥 *{file_name}* recibido\n💾 *Tamaño:* {file_size / 1024 / 1024:.2f} MB\n🔄 *Subiendo a AulaElam...*",
            parse_mode='Markdown'
        )
        
        # Descargar archivo
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Subir a AulaElam
        resultado = subir_archivo_aulaelam(downloaded_file, file_name)
        
        if resultado['exito']:
            # Crear evento en calendario
            evento_creado = crear_evento_calendario(file_name, resultado['itemid'])
            
            # Éxito - Enviar enlace
            texto_exito = (
                f"✅ *¡ARCHIVO SUBIDO EXITOSAMENTE!*\n\n"
                f"📄 **Archivo:** `{resultado['nombre']}`\n"
                f"💾 **Tamaño:** {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"📅 **Evento:** {'✅ Creado' if evento_creado else '⚠️ Sin evento'}\n\n"
                f"🔗 **ENLACE DE DESCARGA DIRECTA:**\n"
                f"`{resultado['enlace']}`"
            )
            
            bot.reply_to(message, texto_exito, parse_mode='Markdown')
            bot.send_message(message.chat.id, f"📎 **Para copiar:**\n{resultado['enlace']}", parse_mode='Markdown')
            
            logger.info(f"✅ Archivo {file_name} subido exitosamente")
            
        else:
            bot.reply_to(
                message, 
                f"❌ *Error al subir archivo*\n\n**Razón:** {resultado['error']}", 
                parse_mode='Markdown'
            )
            logger.error(f"❌ Error subiendo {file_name}: {resultado['error']}")
            
    except Exception as e:
        error_msg = f"❌ *Error inesperado:* {str(e)}"
        bot.reply_to(message, error_msg, parse_mode='Markdown')
        logger.error(f"❌ Error general: {e}")

@bot.message_handler(func=lambda message: True)
def manejar_texto(message):
    """Manejar otros mensajes de texto"""
    if not message.text.startswith('/'):
        bot.reply_to(
            message,
            "📎 *Envía un archivo para subirlo a AulaElam*\n\nUsa /start para ver instrucciones.",
            parse_mode='Markdown'
        )

# ============================
# INICIALIZACIÓN
# ============================

def main():
    """Función principal"""
    logger.info("🚀 Iniciando Bot AulaElam en Choreo...")
    logger.info(f"🤖 Token Bot: {BOT_TOKEN[:10]}...")
    logger.info(f"🔑 Token Moodle: {MOODLE_TOKEN[:10]}...")
    
    print("=" * 50)
    print("🤖 BOT AULAELAM - INICIADO")
    print("🌐 Usando pyTelegramBotAPI")
    print("📁 Listo para recibir archivos...")
    print("=" * 50)
    
    # Iniciar el bot
    bot.infinity_polling()

if __name__ == "__main__":
    main()
