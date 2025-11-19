import os
import time
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters

# --- CẤU HÌNH ---
TELEGRAM_TOKEN = os.environ.get(8434809055:AAEO6AQoRUqN4cSpOppfSGOJHoOPF9NuwxM)
PAGE_ID = os.environ.get(584599948078305)
PAGE_ACCESS_TOKEN = os.environ.get(EAAVmnqZCromIBP66TB5asI3nDuAkTZAGqYfUjYuIPR5mCl3J5sfZBueF8g55UDlnCI3ch58VxEPbQ5ZCYykncFySKGI5OV3dsKf1qcOmNT1LHpC03XV1RfhMOVT7q7AX1xBmKPeC9HnVb569ddPjivkjmvLQbgro0UQ4p3UZBWoZAtIZAYr8yBSel5eC64ULcj8epsH)

album_storage = {}

# --- WEB SERVER ẢO (Để Render không tắt Bot) ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot dang chay ngon lanh!"

def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

# --- XỬ LÝ FACEBOOK ---
def post_to_facebook(media_group_id, chat_id):
    group_data = album_storage.get(media_group_id)
    if not group_data: return

    images = group_data['images']
    caption = group_data['caption']
    
    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={'chat_id': chat_id, 'text': f"⏳ Đang up {len(images)} ảnh lên Face..."})

    try:
        fb_media_ids = []
        # Upload từng ảnh
        for img_url in images:
            img_data = requests.get(img_url).content
            url_upload = f"https://graph.facebook.com/{PAGE_ID}/photos"
            payload = {'published': 'false', 'access_token': PAGE_ACCESS_TOKEN}
            files = {'source': img_data}
            r = requests.post(url_upload, data=payload, files=files)
            res = r.json()
            if 'id' in res:
                fb_media_ids.append(res['id'])
        
        # Đăng bài
        if fb_media_ids:
            url_feed = f"https://graph.facebook.com/{PAGE_ID}/feed"
            attached_media = [f'{{"media_fbid":"{mid}"}}' for mid in fb_media_ids]
            payload = {
                'message': caption,
                'attached_media': '[' + ','.join(attached_media) + ']',
                'access_token': PAGE_ACCESS_TOKEN
            }
            r = requests.post(url_feed, data=payload)
            res = r.json()
            
            if 'id' in res:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={'chat_id': chat_id, 'text': f"✅ XONG! Link: https://fb.com/{res['id']}"})
            else:
                requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={'chat_id': chat_id, 'text': f"❌ Lỗi FB: {res}"})
    except Exception as e:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={'chat_id': chat_id, 'text': f"❌ Lỗi Code: {e}"})
    
    if media_group_id in album_storage:
        del album_storage[media_group_id]

# --- XỬ LÝ TELEGRAM ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg.photo: return

    file_id = msg.photo[-1].file_id
    caption = msg.caption or ""
    chat_id = msg.chat_id
    
    f = await context.bot.get_file(file_id)
    image_url = f.file_path
    
    group_id = msg.media_group_id
    if not group_id: group_id = f"single_{msg.message_id}"
    
    if group_id not in album_storage:
        album_storage[group_id] = {'images': [], 'caption': '', 'timer': None}
    
    album_storage[group_id]['images'].append(image_url)
    if caption: album_storage[group_id]['caption'] = caption

    if album_storage[group_id]['timer']:
        album_storage[group_id]['timer'].cancel()
    
    # Chờ 3 giây để gom ảnh
    t = threading.Timer(3.0, post_to_facebook, args=[group_id, chat_id])
    album_storage[group_id]['timer'] = t
    t.start()

if __name__ == '__main__':
    threading.Thread(target=run_web_server).start()
    app_bot = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app_bot.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    print("Bot khoi dong...")

    app_bot.run_polling()

