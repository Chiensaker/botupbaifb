import os
import time
import threading
import requests
import datetime
import pytz
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

# --- CẤU HÌNH ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PAGE_ID = os.environ.get("PAGE_ID")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")

# Bộ nhớ tạm
# Cấu trúc: { group_id: { images: [], caption: '', gather_timer: Timer, cleanup_timer: Timer } }
album_storage = {}
user_states = {} 

app = Flask(__name__)

@app.route('/')
def index():
    return "Bot Auto Cleanup is running!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- HÀM DỌN DẸP (TỰ HỦY) ---
def auto_cleanup(media_group_id, chat_id, context):
    """Sau 5 phút không bấm nút thì xóa dữ liệu"""
    if media_group_id in album_storage:
        del album_storage[media_group_id]
        # Gửi tin báo
        try:
            context.bot.send_message(chat_id=chat_id, text="🗑 Album đã bị hủy do quá hạn (5 phút không thao tác).")
        except:
            pass # Bỏ qua nếu không gửi được tin
    
    if chat_id in user_states:
        del user_states[chat_id]

# --- HÀM ĐĂNG BÀI ---
def execute_post_to_facebook(media_group_id, chat_id, context, schedule_timestamp=None):
    group_data = album_storage.get(media_group_id)
    if not group_data: 
        context.bot.send_message(chat_id=chat_id, text="❌ Lỗi: Dữ liệu ảnh đã quá hạn hoặc bị xóa.")
        return

    # Hủy bộ đếm dọn dẹp (vì user đã bấm nút rồi)
    if group_data.get('cleanup_timer'):
        group_data['cleanup_timer'].cancel()

    images = group_data['images']
    caption = group_data['caption']
    
    msg_type = "Đang hẹn giờ" if schedule_timestamp else "Đang đăng ngay"
    context.bot.send_message(chat_id=chat_id, text=f"⏳ {msg_type} {len(images)} ảnh lên Facebook...")

    try:
        fb_media_ids = []
        for img_url in images:
            img_data = requests.get(img_url).content
            url_upload = f"https://graph.facebook.com/{PAGE_ID}/photos"
            payload = {'published': 'false', 'access_token': PAGE_ACCESS_TOKEN}
            files = {'source': img_data}
            r = requests.post(url_upload, data=payload, files=files)
            res = r.json()
            if 'id' in res:
                fb_media_ids.append(res['id'])
        
        if fb_media_ids:
            url_feed = f"https://graph.facebook.com/{PAGE_ID}/feed"
            attached_media = [f'{{"media_fbid":"{mid}"}}' for mid in fb_media_ids]
            
            payload = {
                'message': caption,
                'attached_media': '[' + ','.join(attached_media) + ']',
                'access_token': PAGE_ACCESS_TOKEN
            }

            if schedule_timestamp:
                payload['published'] = 'false'
                payload['scheduled_publish_time'] = schedule_timestamp
            else:
                payload['published'] = 'true'

            r = requests.post(url_feed, data=payload)
            res = r.json()
            
            if 'id' in res:
                if schedule_timestamp:
                    dt_object = datetime.datetime.fromtimestamp(schedule_timestamp)
                    time_str = dt_object.strftime('%H:%M %d/%m')
                    context.bot.send_message(chat_id=chat_id, text=f"⏰ ĐÃ LÊN LỊCH!\nBài sẽ đăng lúc: {time_str}")
                else:
                    context.bot.send_message(chat_id=chat_id, text=f"✅ ĐÃ ĐĂNG NGAY!\nLink: https://fb.com/{res['id']}")
            else:
                context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi FB: {res}")
    except Exception as e:
        context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi Code: {e}")
    
    if media_group_id in album_storage:
        del album_storage[media_group_id]
    if chat_id in user_states:
        del user_states[chat_id]

# --- HỎI Ý KIẾN ---
def ask_user_action(media_group_id, chat_id, context):
    group_data = album_storage.get(media_group_id)
    if not group_data: return

    img_count = len(group_data['images'])
    
    keyboard = [
        [InlineKeyboardButton("🚀 Đăng ngay", callback_data=f"now|{media_group_id}")],
        [InlineKeyboardButton("⏰ Hẹn giờ", callback_data=f"schedule|{media_group_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    context.bot.send_message(
        chat_id=chat_id, 
        text=f"📸 Đã gom {img_count} ảnh.\nBạn có 5 phút để chọn:", 
        reply_markup=reply_markup
    )

    # BẮT ĐẦU ĐẾM NGƯỢC 5 PHÚT (300 giây)
    # Nếu sau 300s không ai làm gì -> Gọi hàm auto_cleanup
    t_clean = threading.Timer(300.0, auto_cleanup, args=[media_group_id, chat_id, context])
    group_data['cleanup_timer'] = t_clean
    t_clean.start()

# --- XỬ LÝ NÚT BẤM ---
def button_click(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    data = query.data.split('|')
    action = data[0]
    group_id = data[1]
    chat_id = query.message.chat_id

    if group_id not in album_storage:
        query.edit_message_text("⚠️ Album này đã quá hạn hoặc bị xóa.")
        return

    # Hủy timer dọn dẹp ngay khi user bấm nút
    if album_storage[group_id].get('cleanup_timer'):
        album_storage[group_id]['cleanup_timer'].cancel()

    if action == "now":
        query.edit_message_text("✅ Đã chọn: Đăng ngay.")
        execute_post_to_facebook(group_id, chat_id, context, schedule_timestamp=None)
        
    elif action == "schedule":
        query.edit_message_text("✍️ Nhập giờ muốn đăng (VD: 19:30):")
        user_states[chat_id] = {'action': 'waiting_time', 'group_id': group_id}
        # Đặt lại timer dọn dẹp thêm 2 phút cho user thong thả nhập
        t_clean = threading.Timer(120.0, auto_cleanup, args=[group_id, chat_id, context])
        album_storage[group_id]['cleanup_timer'] = t_clean
        t_clean.start()

# --- XỬ LÝ TEXT ---
def handle_text_input(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    
    if chat_id not in user_states or user_states[chat_id]['action'] != 'waiting_time':
        return
        
    group_id = user_states[chat_id]['group_id']
    
    # Hủy timer dọn dẹp khi user đã nhập liệu
    if group_id in album_storage and album_storage[group_id].get('cleanup_timer'):
        album_storage[group_id]['cleanup_timer'].cancel()
    
    try:
        tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now = datetime.datetime.now(tz)
        target_time = None
        
        try:
            parsed_time = datetime.datetime.strptime(text, '%H:%M')
            target_time = now.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)
            if target_time <= now: target_time += datetime.timedelta(days=1)
        except ValueError:
            pass

        if not target_time:
            try:
                text_with_year = f"{text}/{now.year}"
                parsed_time = datetime.datetime.strptime(text_with_year, '%H:%M %d/%m/%Y')
                target_time = tz.localize(parsed_time)
            except ValueError:
                pass

        if target_time:
            diff = (target_time - now).total_seconds()
            if diff < 600:
                update.message.reply_text("⚠️ Lỗi: Phải hẹn sau ít nhất 10 phút. Nhập lại:")
                return
                
            timestamp = int(target_time.timestamp())
            update.message.reply_text(f"✅ OK: {target_time.strftime('%H:%M %d/%m/%Y')}")
            execute_post_to_facebook(group_id, chat_id, context, schedule_timestamp=timestamp)
        else:
            update.message.reply_text("⚠️ Sai định dạng. Nhập lại (VD: 19:30):")

    except Exception as e:
        update.message.reply_text(f"❌ Lỗi: {e}")

# --- XỬ LÝ ẢNH ---
def handle_photo(update: Update, context: CallbackContext):
    msg = update.message
    if not msg.photo: return
    file_id = msg.photo[-1].file_id
    caption = msg.caption or ""
    
    new_file = context.bot.get_file(file_id)
    image_url = new_file.file_path
    
    group_id = msg.media_group_id
    if not group_id: group_id = f"single_{msg.message_id}"
    
    if group_id not in album_storage:
        # gather_timer: Timer chờ gom ảnh (3s)
        # cleanup_timer: Timer chờ user bấm nút (300s)
        album_storage[group_id] = {'images': [], 'caption': '', 'gather_timer': None, 'cleanup_timer': None}
    
    album_storage[group_id]['images'].append(image_url)
    if caption: album_storage[group_id]['caption'] = caption

    if album_storage[group_id]['gather_timer']:
        album_storage[group_id]['gather_timer'].cancel()
    
    t = threading.Timer(3.0, ask_user_action, args=[group_id, msg.chat_id, context])
    album_storage[group_id]['gather_timer'] = t
    t.start()

if __name__ == '__main__':
    threading.Thread(target=run_web_server).start()
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(CallbackQueryHandler(button_click))
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_input))
    
    print("Bot Auto Cleanup Ready...")
    updater.start_polling()
    updater.idle()
