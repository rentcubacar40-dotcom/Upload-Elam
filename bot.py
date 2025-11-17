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
CONTEXTID_FIJO = "2797"  # ⬅️ ESTE ES FIJO

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

bot = telebot.TeleBot(BOT_TOKEN)

# ============================
# FUNCIONES OPTIMIZADAS
# ============================

def subir_archivo_rapido(file_content, file_name):
    """Subir archivo de forma rápida y obtener itemid"""
    try:
        logger.info(f"🚀 Subiendo rápidamente: {file_name}")
        
        # Subida más rápida con timeout reducido
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
            timeout=15  # ⬅️ Timeout más corto
        )
        
        if response.status_code != 200:
            return {'exito': False, 'error': f'Error HTTP {response.status_code}'}
            
        upload_result = response.json()
        if not upload_result or len(upload_result) == 0:
            return {'exito': False, 'error': 'No se pudo subir el archivo'}
            
        file_data = upload_result[0]
        itemid = file_data.get('itemid')  # ⬅️ SOLO ESTE CAMBIA
        
        logger.info(f"🆔 ItemID obtenido: {itemid}")
        
        if not itemid:
            return {'exito': False, 'error': 'No se obtuvo itemid'}
        
        # Generar enlace INMEDIATAMENTE con contextid FIJO
        file_name_encoded = urllib.parse.quote(file_name)
        
        enlace_descarga = (
            f"{MOODLE_URL}/webservice/pluginfile.php/"
            f"{CONTEXTID_FIJO}/calendar/event_description/"
            f"{itemid}/{file_name_encoded}"
            f"?token={MOODLE_TOKEN}"
        )
        
        # Crear evento RÁPIDO (sin esperar respuesta)
        try:
            event_data = {
                'wstoken': MOODLE_TOKEN,
                'wsfunction': 'core_calendar_submit_create_update_form',
                'moodlewsrestformat': 'json',
                'formdata': f'files[0]={itemid}&name=Archivo:{urllib.parse.quote(file_name)}&eventtype=user'
            }
            
            # Hacerlo en segundo plano sin esperar
            requests.post(
                f"{MOODLE_URL}/webservice/rest/server.php",
                data=event_data,
                timeout=5  # ⬅️ Muy rápido, no bloqueante
            )
        except:
            pass  # No importa si falla el evento
        
        return {
            'exito': True,
            'enlace': enlace_descarga,
            'nombre': file_name,
            'tamaño': file_data.get('filesize', 0),
            'itemid': itemid
        }
        
    except requests.exceptions.Timeout:
        return {'exito': False, 'error': 'Timeout: El servidor tardó demasiado'}
    except Exception as e:
        logger.error(f"❌ Error: {e}")
        return {'exito': False, 'error': str(e)}

# ============================
# MANEJADORES RÁPIDOS
# ============================

@bot.message_handler(commands=['start'])
def start_command(message):
    text = f"""
🤖 **BOT AULAELAM - RÁPIDO** 🤖

✅ *ContextID fijo: {CONTEXTID_FIJO}*
✅ *Solo ItemID cambia por archivo*
✅ *Subida optimizada y rápida*

🔧 **CONFIGURACIÓN:**
• ContextID: `{CONTEXTID_FIJO}` (SIEMPRE el mismo)
• ItemID: Cambia con cada archivo
• Token: Incluido en cada enlace

🔗 **EJEMPLO DE ENLACE:**
`{MOODLE_URL}/webservice/pluginfile.php/{CONTEXTID_FIJO}/calendar/event_description/1234/archivo.pdf?token=...`

📎 **¡Envía un archivo para probar la velocidad!**
    """
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    """Manejar documentos de forma rápida"""
    try:
        file_info = bot.get_file(message.document.file_id)
        file_name = message.document.file_name
        file_size = message.document.file_size
        
        logger.info(f"📥 Recibido: {file_name}")
        
        if file_size > 20 * 1024 * 1024:  # ⬅️ Reducido a 20MB para más velocidad
            bot.reply_to(message, "❌ Máximo 20MB para mayor velocidad", parse_mode='Markdown')
            return
        
        mensaje_espera = bot.reply_to(message, f"⚡ *{file_name}*\n🔄 Procesando rápidamente...", parse_mode='Markdown')
        
        # Descargar archivo
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Subir rápidamente
        resultado = subir_archivo_rapido(downloaded_file, file_name)
        
        if resultado['exito']:
            # Editar mensaje original para mostrar resultado
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=mensaje_espera.message_id,
                text=(
                    f"✅ *¡SUBIDO EN SEGUNDOS!*\n\n"
                    f"📄 **Archivo:** `{resultado['nombre']}`\n"
                    f"💾 **Tamaño:** {resultado['tamaño'] / 1024 / 1024:.2f} MB\n"
                    f"🆔 **ItemID:** `{resultado['itemid']}`\n\n"
                    f"🔗 **ENLACE DIRECTO:**\n"
                    f"`{resultado['enlace']}`"
                ),
                parse_mode='Markdown'
            )
            
            # Enviar enlace para copiar
            bot.send_message(
                message.chat.id,
                f"📎 **Para descargar:**\n{resultado['enlace']}",
                parse_mode='Markdown'
            )
            
        else:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=mensaje_espera.message_id,
                text=f"❌ **Error:** {resultado['error']}",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        bot.reply_to(message, f"❌ **Error rápido:** {str(e)}", parse_mode='Markdown')

@bot.message_handler(func=lambda message: True)
def manejar_texto(message):
    if not message.text.startswith('/'):
        bot.reply_to(
            message,
            f"📎 *Envía un archivo (max 20MB)*\n\n"
            f"ContextID fijo: `{CONTEXTID_FIJO}`\n"
            f"ItemID único por archivo\n"
            f"Enlaces ultra rápidos",
            parse_mode='Markdown'
        )

# ============================
# INICIO
# ============================

def main():
    print("🚀 BOT AULAELAM - CONTEXTID FIJO")
    print(f"🔧 ContextID: {CONTEXTID_FIJO}")
    print("⚡ Optimizado para velocidad")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
