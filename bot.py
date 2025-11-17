import os
import requests
import logging
import telebot
from telebot import types
import urllib.parse
import time
import re

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
# FUNCIONES CON SESIÓN WEB
# ============================

def crear_sesion_aulaelam():
    """Crear sesión con headers de navegador real"""
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'es-ES,es;q=0.9',
        'Origin': MOODLE_URL,
        'Referer': f'{MOODLE_URL}/',
    })
    return session

def subir_archivo_web_real(file_content, file_name):
    """Subir archivo usando la web real de AulaElam"""
    try:
        session = crear_sesion_aulaelam()
        logger.info(f"🌐 Conectando a AulaElam web: {file_name}")
        
        # 1. Primero obtener información de la web real
        info_url = f"{MOODLE_URL}/webservice/rest/server.php"
        params = {
            'wstoken': MOODLE_TOKEN,
            'wsfunction': 'core_webservice_get_site_info',
            'moodlewsrestformat': 'json'
        }
        
        response = session.get(info_url, params=params, timeout=15)
        if response.status_code != 200:
            return {'exito': False, 'error': f'Error conexión: {response.status_code}'}
        
        site_info = response.json()
        user_id = site_info.get('userid')
        logger.info(f"👤 Usuario ID: {user_id}")
        
        # 2. Subir archivo usando el endpoint de upload
        upload_url = f"{MOODLE_URL}/webservice/upload.php"
        
        files = {'file': (file_name, file_content)}
        data = {
            'token': MOODLE_TOKEN,
            'filearea': 'draft',
            'itemid': 0,
            'client_id': user_id
        }
        
        upload_response = session.post(upload_url, files=files, data=data, timeout=30)
        
        if upload_response.status_code != 200:
            return {'exito': False, 'error': f'Error subida: {upload_response.status_code}'}
        
        upload_result = upload_response.json()
        if not upload_result or len(upload_result) == 0:
            return {'exito': False, 'error': 'No se recibieron datos de subida'}
        
        file_data = upload_result[0]
        itemid = file_data.get('itemid')
        contextid = file_data.get('contextid')
        
        logger.info(f"📁 Archivo subido - ItemID: {itemid}, ContextID: {contextid}")
        
        if not itemid:
            return {'exito': False, 'error': 'No se obtuvo itemid'}
        
        # 3. Crear un evento REAL en el calendario
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
        
        event_response = session.post(event_url, data=event_data, timeout=20)
        logger.info(f"📅 Evento creado: {event_response.status_code}")
        
        # 4. Obtener eventos del calendario para encontrar el ID real
        calendar_url = f"{MOODLE_URL}/webservice/rest/server.php"
        calendar_params = {
            'wstoken': MOODLE_TOKEN,
            'wsfunction': 'core_calendar_get_calendar_events',
            'moodlewsrestformat': 'json',
            'options[userevents]': 1,
            'options[siteevents]': 0
        }
        
        calendar_response = session.get(calendar_url, params=calendar_params, timeout=15)
        if calendar_response.status_code == 200:
            events = calendar_response.json().get('events', [])
            # Buscar el evento que acabamos de crear
            for event in events:
                if f'Archivo: {file_name}' in event.get('name', ''):
                    event_id = event.get('id')
                    logger.info(f"🎯 Evento encontrado ID: {event_id}")
                    break
        
        # 5. Generar enlace EXACTO como AulaElam
        file_name_encoded = urllib.parse.quote(f"inline; {file_name}")
        enlace_final = (
            f"{MOODLE_URL}/webservice/pluginfile.php/"
            f"{contextid}/calendar/event_description/"
            f"{itemid}/{file_name_encoded}"
            f"?token={MOODLE_TOKEN}"
        )
        
        logger.info(f"🔗 Enlace generado: {enlace_final}")
        
        # 6. Verificar que el enlace funciona
        try:
            verify = session.head(enlace_final, timeout=10, allow_redirects=True)
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
        logger.error(f"❌ Error web real: {e}")
        return {'exito': False, 'error': str(e)}

# ============================
# MANEJADORES
# ============================

@bot.message_handler(commands=['start'])
def start_command(message):
    text = f"""
🤖 **BOT AULAELAM - WEB REAL** 🤖

✅ *Interactúa con la web real de AulaElam*
✅ *Sesiones de navegador real*
✅ *Enlaces idénticos a los originales*

🔗 **ESTRUCTURA EXACTA:**
`{MOODLE_URL}/webservice/pluginfile.php/2797/calendar/event_description/2748/inline%3B%20archivo.mp3?token=...`

🌐 **PROCESO:**
1. Conexión web real con sesión
2. Subida mediante formularios web  
3. Creación de evento real en calendario
4. Generación de enlace idéntico

📎 **¡Envía un archivo para probar!**
    """
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(content_types=['document'])
def manejar_documento(message):
    """Manejar documentos con web real"""
    try:
        file_info = bot.get_file(message.document.file_id)
        file_name = message.document.file_name
        file_size = message.document.file_size
        
        logger.info(f"📥 Recibido: {file_name}")
        
        if file_size > 50 * 1024 * 1024:
            bot.reply_to(message, "❌ Máximo 50MB", parse_mode='Markdown')
            return
        
        mensaje = bot.reply_to(message, f"🌐 *{file_name}*\n🔄 Conectando con AulaElam web...", parse_mode='Markdown')
        
        # Descargar archivo
        downloaded_file = bot.download_file(file_info.file_path)
        
        # Subir usando web real
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
            
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=mensaje.message_id,
                text=respuesta,
                parse_mode='Markdown'
            )
            
            # Enviar enlace para copiar
            bot.send_message(
                message.chat.id,
                f"📎 **Enlace exacto:**\n{resultado['enlace']}",
                parse_mode='Markdown'
            )
            
        else:
            bot.edit_message_text(
                chat_id=message.chat.id,
                message_id=mensaje.message_id,
                text=f"❌ **Error web real:** {resultado['error']}",
                parse_mode='Markdown'
            )
            
    except Exception as e:
        bot.reply_to(message, f"❌ **Error:** {str(e)}", parse_mode='Markdown')

def main():
    print("🚀 BOT AULAELAM - WEB REAL")
    print("🌐 Usando sesiones de navegador real")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
