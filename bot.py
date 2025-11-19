import os
import time
import threading
import requests
from flask import Flask
from telegram import Update
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext

# --- CẤU HÌNH ---
# Lưu ý: Đảm bảo bạn đã điền đúng Value trong Environment Variables của Render
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PAGE_ID = os.environ.get("PAGE_ID")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")

album_storage = {}
app = Flask(__name__)

# --- WEB SERVER ---
@app.route('/')
def index():
    return "Bot dang song nhe!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- LOGIC UP FACEBOOK ---
def post_to_facebook(media_group_id, chat_id, context):
    group_data = album_storage.get(media_group_id)
    if not group_data: return

    images = group_data['images']
    caption = group_data['caption']
    
    try:
        context.bot.send_message(chat_id=chat_id, text=f"⏳ Đang đẩy {len(images)} ảnh sang Facebook...")
        
        fb_media_ids = []
        # 1. Upload ảnh
        for img_url in images:
            img_data = requests.get(img_url).content
            url_upload = f"https://graph.facebook.com/{PAGE_ID}/photos"
            payload = {'published': 'false', 'access_token': PAGE_ACCESS_TOKEN}
            files = {'source': img_data}
            r = requests.post(url_upload, data=payload, files=files)
            if 'id' in r.json():
                fb_media_ids.append(r.json()['id'])
            else:
                print("Lỗi up ảnh:", r.text)

        # 2. Đăng bài
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
                context.bot.send_message(chat_id=chat_id, text=f"✅ LÊN BÀI THÀNH CÔNG!\nLink: https://fb.com/{res['id']}")
            else:
                context.bot.send_message(chat_id=chat_id, text=f"❌ Facebook từ chối: {res}")
        else:
            context.bot.send_message(chat_id=chat_id, text="❌ Không up được ảnh nào lên FB cả.")

    except Exception as e:
        context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi Code: {e}")
    
    if media_group_id in album_storage:
        del album_storage[media_group_id]

# --- XỬ LÝ TIN NHẮN ---
def handle_message(update: Update, context: CallbackContext):
    # Hàm này để test xem Bot có nhận được tin không
    update.message.reply_text(f"👋 Bot nghe rõ! Bạn vừa nhắn: {update.message.text}")

def handle_photo(update: Update, context: CallbackContext):
    msg = update.message
    file_id = msg.photo[-1].file_id
    caption = msg.caption or ""
    
    # Báo tín hiệu ngay lập tức
    if not msg.media_group_id:
        msg.reply_text("📸 Đã nhận 1 ảnh lẻ.")
    
    new_file = context.bot.get_file(file_id)
    image_url = new_file.file_path
    
    group_id = msg.media_group_id or f"single_{msg.message_id}"
    
    if group_id not in album_storage:
        album_storage[group_id] = {'images': [], 'caption': '', 'timer': None}
    
    album_storage[group_id]['images'].append(image_url)
    if caption: album_storage[group_id]['caption'] = caption

    if album_storage[group_id]['timer']:
        album_storage[group_id]['timer'].cancel()
    
    t = threading.Timer(4.0, post_to_facebook, args=[group_id, msg.chat_id, context])
    album_storage[group_id]['timer'] = t
    t.start()

if __name__ == '__main__':
    threading.Thread(target=run_web_server).start()
    
    print("Dang ket noi Telegram...")
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    # Bắt cả tin nhắn chữ và ảnh để test
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_message))
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    
    print("Bot khoi dong THANH CONG!")
    updater.start_polling()
    updater.idle()
