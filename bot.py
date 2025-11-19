import os
import time
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# --- CẤU HÌNH ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PAGE_ID = os.environ.get("PAGE_ID")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")

# Bộ nhớ gom ảnh
album_storage = {}

# --- WEB SERVER ẢO (Giữ bot sống) ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot phien ban 13.7 dang chay!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- LOGIC ĐĂNG FACEBOOK ---
def post_to_facebook(media_group_id, chat_id, context):
    """Gom ảnh và đăng"""
    group_data = album_storage.get(media_group_id)
    if not group_data: return

    images = group_data['images']
    caption = group_data['caption']
    
    context.bot.send_message(chat_id=chat_id, text=f"⏳ Đã gom {len(images)} ảnh. Đang up Facebook...")

    try:
        fb_media_ids = []
        # 1. Upload từng ảnh
        for img_url in images:
            img_data = requests.get(img_url).content
            url_upload = f"https://graph.facebook.com/{PAGE_ID}/photos"
            payload = {'published': 'false', 'access_token': PAGE_ACCESS_TOKEN}
            files = {'source': img_data}
            r = requests.post(url_upload, data=payload, files=files)
            res = r.json()
            if 'id' in res:
                fb_media_ids.append(res['id'])
        
        # 2. Đăng bài Feed
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
                context.bot.send_message(chat_id=chat_id, text=f"✅ XONG! Link: https://fb.com/{res['id']}")
            else:
                context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi FB: {res}")
    except Exception as e:
        context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi Code: {e}")
    
    # Xóa bộ nhớ
    if media_group_id in album_storage:
        del album_storage[media_group_id]

# --- XỬ LÝ TIN NHẮN ẢNH ---
def handle_photo(update: Update, context: CallbackContext):
    msg = update.message
    if not msg.photo: return

    # Lấy ảnh nét nhất
    file_id = msg.photo[-1].file_id
    caption = msg.caption or ""
    chat_id = msg.chat_id
    
    # Lấy link ảnh (Logic bản 13.7)
    new_file = context.bot.get_file(file_id)
    image_url = new_file.file_path
    
    group_id = msg.media_group_id
    # Nếu là ảnh lẻ -> tạo group giả
    if not group_id: group_id = f"single_{msg.message_id}"
    
    if group_id not in album_storage:
        album_storage[group_id] = {'images': [], 'caption': '', 'timer': None}
    
    album_storage[group_id]['images'].append(image_url)
    if caption: album_storage[group_id]['caption'] = caption

    # Reset đồng hồ
    if album_storage[group_id]['timer']:
        album_storage[group_id]['timer'].cancel()
    
    # Chờ 3 giây để gom
    # Lưu ý: Truyền context vào để hàm post_to_facebook có thể gửi tin nhắn lại
    t = threading.Timer(3.0, post_to_facebook, args=[group_id, chat_id, context])
    album_storage[group_id]['timer'] = t
    t.start()

# --- CHẠY BOT ---
if __name__ == '__main__':
    # 1. Chạy Web Server ở luồng riêng
    threading.Thread(target=run_web_server).start()
    
    # 2. Chạy Bot Telegram (Bản 13.7)
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dispatcher = updater.dispatcher
    
    # Đăng ký hàm xử lý ảnh
    dispatcher.add_handler(MessageHandler(Filters.photo, handle_photo))
    
    print("Bot v13.7 dang chay...")
    updater.start_polling()
    updater.idle()
