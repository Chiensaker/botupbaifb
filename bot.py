import os
import time
import threading
import requests
import datetime
import pytz # Thư viện xử lý múi giờ
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, MessageHandler, Filters, CallbackContext, CallbackQueryHandler

# --- CẤU HÌNH ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
PAGE_ID = os.environ.get("PAGE_ID")
PAGE_ACCESS_TOKEN = os.environ.get("PAGE_ACCESS_TOKEN")

# Bộ nhớ tạm
album_storage = {}
user_states = {} # Lưu trạng thái người dùng (đang chờ nhập giờ hay không)

# --- WEB SERVER ẢO ---
app = Flask(__name__)

@app.route('/')
def index():
    return "Bot Hen Gio Dang Chay!"

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

# --- HÀM ĐĂNG BÀI (CORE) ---
def execute_post_to_facebook(media_group_id, chat_id, context, schedule_timestamp=None):
    """
    Hàm này thực hiện việc upload và đăng bài.
    schedule_timestamp: Nếu có (Unix timestamp), bài sẽ được hẹn giờ.
    """
    group_data = album_storage.get(media_group_id)
    if not group_data: 
        context.bot.send_message(chat_id=chat_id, text="❌ Lỗi: Dữ liệu ảnh đã bị xóa hoặc quá hạn.")
        return

    images = group_data['images']
    caption = group_data['caption']
    
    msg_type = "Đang hẹn giờ" if schedule_timestamp else "Đang đăng ngay"
    context.bot.send_message(chat_id=chat_id, text=f"⏳ {msg_type} {len(images)} ảnh lên Facebook...")

    try:
        fb_media_ids = []
        # 1. Upload từng ảnh (published=false)
        for img_url in images:
            img_data = requests.get(img_url).content
            url_upload = f"https://graph.facebook.com/{PAGE_ID}/photos"
            payload = {'published': 'false', 'access_token': PAGE_ACCESS_TOKEN}
            files = {'source': img_data}
            r = requests.post(url_upload, data=payload, files=files)
            res = r.json()
            if 'id' in res:
                fb_media_ids.append(res['id'])
        
        # 2. Đăng bài Feed (published=false nếu hẹn giờ)
        if fb_media_ids:
            url_feed = f"https://graph.facebook.com/{PAGE_ID}/feed"
            attached_media = [f'{{"media_fbid":"{mid}"}}' for mid in fb_media_ids]
            
            payload = {
                'message': caption,
                'attached_media': '[' + ','.join(attached_media) + ']',
                'access_token': PAGE_ACCESS_TOKEN
            }

            # Xử lý hẹn giờ
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
                    context.bot.send_message(chat_id=chat_id, text=f"⏰ ĐÃ LÊN LỊCH THÀNH CÔNG!\nBài sẽ đăng lúc: {time_str}")
                else:
                    context.bot.send_message(chat_id=chat_id, text=f"✅ ĐÃ ĐĂNG NGAY!\nLink: https://fb.com/{res['id']}")
            else:
                context.bot.send_message(chat_id=chat_id, text=f"❌ Facebook từ chối: {res}")
    except Exception as e:
        context.bot.send_message(chat_id=chat_id, text=f"❌ Lỗi Code: {e}")
    
    # Xóa bộ nhớ sau khi xử lý xong
    if media_group_id in album_storage:
        del album_storage[media_group_id]
    if chat_id in user_states:
        del user_states[chat_id]

# --- HỎI Ý KIẾN NGƯỜI DÙNG ---
def ask_user_action(media_group_id, chat_id, context):
    """Gom ảnh xong thì hiện nút bấm"""
    group_data = album_storage.get(media_group_id)
    img_count = len(group_data['images'])
    
    keyboard = [
        [InlineKeyboardButton("🚀 Đăng ngay lập tức", callback_data=f"now|{media_group_id}")],
        [InlineKeyboardButton("⏰ Hẹn giờ đăng", callback_data=f"schedule|{media_group_id}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    context.bot.send_message(
        chat_id=chat_id, 
        text=f"📸 Đã gom đủ {img_count} ảnh.\nBạn muốn làm gì?", 
        reply_markup=reply_markup
    )

# --- XỬ LÝ NÚT BẤM ---
def button_click(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer() # Báo cho Tele biết đã bấm
    
    data = query.data.split('|')
    action = data[0]
    group_id = data[1]
    chat_id = query.message.chat_id

    if group_id not in album_storage:
        query.edit_message_text("⚠️ Album này đã quá hạn hoặc đã bị xóa.")
        return

    if action == "now":
        query.edit_message_text("✅ Đã chọn: Đăng ngay.")
        execute_post_to_facebook(group_id, chat_id, context, schedule_timestamp=None)
        
    elif action == "schedule":
        query.edit_message_text("✍️ Vui lòng nhập giờ muốn đăng.\n\nVí dụ:\n- `19:30` (cho hôm nay)\n- `08:00 21/11` (cho ngày mai/ngày kia)")
        # Lưu trạng thái để chờ user nhập text
        user_states[chat_id] = {'action': 'waiting_time', 'group_id': group_id}

# --- XỬ LÝ NHẬP GIỜ (TEXT) ---
def handle_text_input(update: Update, context: CallbackContext):
    chat_id = update.message.chat_id
    text = update.message.text.strip()
    
    # Kiểm tra xem user này có đang chờ nhập giờ không
    if chat_id not in user_states or user_states[chat_id]['action'] != 'waiting_time':
        return # Không làm gì nếu user chat linh tinh
        
    group_id = user_states[chat_id]['group_id']
    
    # Xử lý thời gian
    try:
        tz = pytz.timezone('Asia/Ho_Chi_Minh')
        now = datetime.datetime.now(tz)
        target_time = None
        
        # Trường hợp 1: Chỉ nhập giờ (VD: 19:30) -> Hiểu là hôm nay (hoặc ngày mai nếu giờ đó qua rồi)
        try:
            parsed_time = datetime.datetime.strptime(text, '%H:%M')
            target_time = now.replace(hour=parsed_time.hour, minute=parsed_time.minute, second=0, microsecond=0)
            if target_time <= now: # Nếu giờ đã qua, tự hiểu là ngày mai
                target_time += datetime.timedelta(days=1)
        except ValueError:
            pass

        # Trường hợp 2: Nhập ngày giờ (VD: 19:30 20/11)
        if not target_time:
            try:
                # Thêm năm hiện tại vào để parse
                text_with_year = f"{text}/{now.year}"
                parsed_time = datetime.datetime.strptime(text_with_year, '%H:%M %d/%m/%Y')
                target_time = tz.localize(parsed_time)
            except ValueError:
                pass

        if target_time:
            # Facebook yêu cầu: Hẹn giờ phải cách hiện tại ít nhất 10 phút
            diff = (target_time - now).total_seconds()
            if diff < 600: # 600 giây = 10 phút
                update.message.reply_text("⚠️ Lỗi: Facebook yêu cầu hẹn giờ phải cách hiện tại ít nhất 10 phút.\nVui lòng nhập lại:")
                return
                
            # Chuyển sang Unix Timestamp
            timestamp = int(target_time.timestamp())
            update.message.reply_text(f"✅ Đã ghi nhận: {target_time.strftime('%H:%M %d/%m/%Y')}")
            
            # Gọi hàm đăng bài với timestamp
            execute_post_to_facebook(group_id, chat_id, context, schedule_timestamp=timestamp)
            
        else:
            update.message.reply_text("⚠️ Sai định dạng giờ! Hãy nhập lại theo mẫu `19:30` hoặc `08:00 21/11`")

    except Exception as e:
        update.message.reply_text(f"❌ Lỗi xử lý giờ: {e}")

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
        album_storage[group_id] = {'images': [], 'caption': '', 'timer': None}
    
    album_storage[group_id]['images'].append(image_url)
    if caption: album_storage[group_id]['caption'] = caption

    if album_storage[group_id]['timer']:
        album_storage[group_id]['timer'].cancel()
    
    # Chờ 3 giây gom ảnh -> Rồi gọi hàm hiện nút bấm (ask_user_action)
    t = threading.Timer(3.0, ask_user_action, args=[group_id, msg.chat_id, context])
    album_storage[group_id]['timer'] = t
    t.start()

if __name__ == '__main__':
    threading.Thread(target=run_web_server).start()
    
    updater = Updater(token=TELEGRAM_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    dp.add_handler(MessageHandler(Filters.photo, handle_photo))
    dp.add_handler(CallbackQueryHandler(button_click)) # Xử lý bấm nút
    dp.add_handler(MessageHandler(Filters.text & ~Filters.command, handle_text_input)) # Xử lý nhập giờ
    
    print("Bot Hen Gio v13.7 ready...")
    updater.start_polling()
    updater.idle()
