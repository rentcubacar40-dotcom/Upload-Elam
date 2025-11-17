import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time

# ============================
# CONFIGURACIÓN
# ============================

BOT_TOKEN = "8502790665:AAHuanhfYIe5ptUliYQBP7ognVOTG0uQoKk"
MOODLE_TOKEN = "784e9718073ccee20854df8a10536659"
MOODLE_URL = "https://aulaelam.sld.cu"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# ============================
# FUNCIONES MEJORADAS
# ============================

def subir_archivo_y_obtener_enlace(file_content, file_name):
    """Subir archivo y obtener enlace con itemid DINÁMICO"""
    try:
        logger.info(f"📤 Subiendo: {file_name}")
        
        # 1. Subir archivo - Moodle nos devuelve itemid y contextid NUEVOS
        files = {'file': (file_name, file_content)}
        data = {
            'token': MOODLE_TOKEN,
            'filearea': 'draft', 
            'itemid': '0'
        }
        
        response = requests.post(
            f"{MOODLE_URL}/webservice/upload.php",
            files=files,
            data=data,
            timeout=30
        )
        
        if response.status_code != 200:
            return {'exito': False, 'error': f'Error HTTP {response.status_code}'}
            
        upload_result = response.json()
        if not upload_result or len(upload_result) == 0:
            return {'exito': False, 'error': 'No se pudo subir el archivo'}
            
        file_data = upload_result[0]
        itemid = file_data.get('itemid')  # ⬅️ ESTE CAMBIA CON CADA ARCHIVO
        contextid = file_data.get('contextid')  # ⬅️ ESTE TAMBIÉN CAMBIA
        
        logger.info(f"🆔 ItemID generado: {itemid}, ContextID: {contextid}")
        
        if not itemid:
            return {'exito': False, 'error': 'No se obtuvo itemid del archivo'}
        
        # 2. Crear evento en calendario usando el NUEVO itemid
        event_data = {
            'wstoken': MOODLE_TOKEN,
            'wsfunction': 'core_calendar_submit_create_update_form',
            'moodlewsrestformat': 'json',
            'formdata': (
                f'name=Archivo: {urllib.parse.quote(file_name)}&'
                f'timestart={int(time.time()) + 3600}&'
                f'eventtype=user&'
                f'description[text]=Subido via Bot Telegram&'
                f'description[format]=1&'
                f'files[0]={itemid}'
            )
        }
        
        event_response = requests.post(
            f"{MOODLE_URL}/webservice/rest/server.php",
            data=event_data,
            timeout=30
        )
        
        logger.info(f"📅 Evento creado: {event_response.status_code}")
        
        # 3. Generar ENLACE con los NUEVOS itemid y contextid
        file_name_encoded = urllib.parse.quote(file_name)
        
        enlace_descarga = (
            f"{MOODLE_URL}/webservice/pluginfile.php/"
            f"{contextid}/calendar/event_description/"
            f"{itemid}/{file_name_encoded}"
            f"?token={MOODLE_TOKEN}"
        )
        
        logger.info(f"🔗 Enlace generado: {enlace_descarga}")
        
        return {
            'exito': True,
            'enlace': enlace_descarga,
            'nombre': file_name,
            'tamaño': file_data.get('filesize', 0),
            'itemid': itemid,
            'contextid': contextid
        }
        
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {'exito': False, 'error': str(e)}

# ============================
# MANEJADORES
# ============================

@bot.message_handler(commands=['start'])
def start_command(message):
    text = """
🤖 **BOT AULAELAM - ENLACES DINÁMICOS** 🤖

✅ *ItemID único por cada archivo*
✅ *Enlaces frescos y funcionales*
✅ *Token de autenticación incluido*

🆔 **ITEMID DINÁMICO:**
Cada archivo recibe un ID único que cambia:
• Archivo 1 → itemid=1234
• Archivo 2 → itemid=5678  
• Archivo 3 → itemid=9012

🔗 **ENLACE EJEMPLO:**
`https://aulaelam.sld.cu/.../2891/calendar/.../4523/archivo.pdf?token=...`

📎 **¡Envía un archivo para ver tu itemid único!**
    """
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    """Manejar documentos con itemid dinámico"""
    try:
        file_info = bot.get_file(message.document.file_id)
        file_name = message.document.file_name
        file_size = message.document.file_size
        
        logger.info(f"📥 Recibido: {file_name}")
        
        if file_size > 50 * 1024 * 1024:
            bot.reply_to(message, "❌ Máximo 50MB", parse_mode='Markdown')
            return
        
        bot.reply_to(message, f"📥 *{file_name}*\n🔄 Generando itemid único...", parse_mode='Markdown')
        
        # Descargar y subir archivo
        downloaded_file = bot.download_file(file_info.file_path)
        resultado = subir_archivo_y_obtener_enlace(downloaded_file, file_name)
        
        if resultado['exito']:
            # ✅ ÉXITO - Mostrar enlace con itemid único
            mensaje_exito = (
                f"🎉 *¡ARCHIVO SUBIDO EXITOSAMENTE!*\n\n"
                f"📄 **Archivo:** `{resultado['nombre']}`\n"
                f"💾 **Tamaño:** {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                f"🆔 **ItemID único:** `{resultado['itemid']}`\n"
                f"🔧 **ContextID:** `{resultado['contextid']}`\n\n"
                f"🔗 **ENLACE DE DESCARGA:**\n"
                f"`{resultado['enlace']}`"
            )
            
            bot.reply_to(message, mensaje_exito, parse_mode='Markdown')
            
            # Enviar enlace para copiar fácilmente
            bot.send_message(
                message.chat.id,
                f"📎 **Enlace directo para descargar:**\n{resultado['enlace']}",
                parse_mode='Markdown'
            )
            
            logger.info(f"✅ {file_name} - ItemID: {resultado['itemid']}")
            
        else:
            bot.reply_to(
                message, 
                f"❌ **Error:** {resultado['error']}", 
                parse_mode='Markdown'
            )
            
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}", parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def manejar_texto(message):
    """Manejar otros mensajes"""
    if not message.text.startswith('/'):
        bot.reply_to(
            message,
            "📎 *Envía un archivo para generar su itemid único*\n\n"
            "Cada archivo recibirá:\n"
            "• 🆔 ItemID único y diferente\n"
            "• 🔗 Enlace fresco con token\n"
            "• ✅ Descarga inmediata",
            parse_mode='Markdown'
        )

# ============================
# INICIO
# ============================

def main():
    print("🚀 BOT AULAELAM - ITEMID DINÁMICO")
    print("🆔 Generando itemid único por cada archivo")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
