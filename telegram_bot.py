import requests
from datetime import datetime
import threading
import time

# Telegram Bot Configuration
BOT_TOKEN = "8429353540:AAGNIPh-Lje4KAl_Ko57OS8TBWfgzpgaJWM"

# Danh sach cac chat se nhan thong bao (ca nhan + nhom)
CHAT_IDS = [
    5638732845,      # Private chat - Alex
    -1003467971094,  # Group chat
]

# Buffer để gom nhiều log lại gửi 1 lần (tránh spam Telegram)
_log_buffer = []
_buffer_lock = threading.Lock()
_last_send_time = 0
BUFFER_DELAY = 3  # Gom log trong 3 giây rồi gửi 1 lần

def get_chat_id():
    """
    Lấy Chat ID từ tin nhắn gần nhất gửi đến bot.
    Bước 1: Gửi tin nhắn bất kỳ đến bot trên Telegram
    Bước 2: Chạy hàm này để lấy Chat ID
    """
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    try:
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if data.get("ok") and data.get("result"):
            for update in data["result"]:
                if "message" in update:
                    chat = update["message"]["chat"]
                    chat_id = chat["id"]
                    name = chat.get("first_name", "") or chat.get("title", "Unknown")
                    print(f"[OK] Tim thay Chat ID: {chat_id} (tu: {name})")
                    return chat_id
            print("[X] Khong tim thay tin nhan. Hay gui tin nhan den bot truoc!")
        else:
            print("[X] Khong co updates:", data)
    except Exception as e:
        print(f"[X] Loi: {e}")
    return None


def send_telegram(message, chat_id=None):
    """
    Gui tin nhan den Telegram.
    Neu khong chi dinh chat_id, se gui den tat ca CHAT_IDS.
    """
    # Neu chi dinh 1 chat_id cu the
    if chat_id:
        targets = [chat_id]
    else:
        targets = CHAT_IDS
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    success = False
    
    for target in targets:
        payload = {
            "chat_id": target,
            "text": message,
            "parse_mode": "HTML"
        }
        
        try:
            response = requests.post(url, json=payload, timeout=10)
            if response.status_code == 200:
                success = True
        except:
            pass
    
    return success


def _flush_buffer():
    """Gửi tất cả log trong buffer lên Telegram."""
    global _log_buffer, _last_send_time
    
    with _buffer_lock:
        if not _log_buffer:
            return
        
        # Gom tất cả log thành 1 message
        message = "\n".join(_log_buffer)
        _log_buffer = []
        _last_send_time = time.time()
    
    # Gửi lên Telegram (không block)
    if message.strip():
        send_telegram(f"<pre>{message}</pre>")


def _buffer_sender():
    """Thread gửi buffer định kỳ."""
    global _last_send_time
    while True:
        time.sleep(1)
        with _buffer_lock:
            if _log_buffer and (time.time() - _last_send_time) >= BUFFER_DELAY:
                pass  # Will flush below
            else:
                continue
        _flush_buffer()


# Start buffer sender thread
_sender_thread = threading.Thread(target=_buffer_sender, daemon=True)
_sender_thread.start()


def log(*args, flush_now=False, **kwargs):
    """
    Thay thế print() - vừa in ra console vừa gửi lên Telegram.
    
    Args:
        *args: Nội dung cần log (giống print)
        flush_now: Gửi ngay lên Telegram không đợi buffer
    """
    # In ra console như bình thường
    message = " ".join(str(arg) for arg in args)
    print(message, **kwargs)
    
    # Thêm vào buffer để gửi Telegram
    with _buffer_lock:
        _log_buffer.append(message)
    
    # Nếu cần gửi ngay (ví dụ: khi có lệnh trade)
    if flush_now:
        _flush_buffer()


def flush_logs():
    """Gửi ngay tất cả log đang đợi trong buffer."""
    _flush_buffer()


def format_trade_message(action, cluster_info, orders_info):
    """
    Format tin nhắn trade đẹp hơn cho Telegram.
    """
    timestamp = datetime.now().strftime("%H:%M:%S %d/%m")
    
    msg = f"🔔 <b>{action} SIGNAL</b> - {timestamp}\n"
    msg += f"━━━━━━━━━━━━━━━━━\n"
    msg += f"{cluster_info}\n"
    msg += f"━━━━━━━━━━━━━━━━━\n"
    
    for order in orders_info:
        msg += f"{order}\n"
    
    return msg


def format_score_message(buy_score, sell_score, accumulated_buy, accumulated_sell):
    """
    Format tin nhắn điểm tích lũy.
    """
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    msg = f"📊 <b>Score Update</b> - {timestamp}\n"
    msg += f"Nến này: Buy +{buy_score} | Sell +{sell_score}\n"
    msg += f"<b>TÍCH LŨY: Buy = {accumulated_buy} | Sell = {accumulated_sell}</b>"
    
    return msg


# ========== TEST ==========
if __name__ == "__main__":
    print("Dang tim Chat ID...")
    print("Neu chua co, hay mo Telegram va gui tin nhan bat ky den bot cua ban!")
    print()
    
    chat_id = get_chat_id()
    
    if chat_id:
        print(f"\nChat ID cua ban: {chat_id}")
        print(f"Hay cap nhat CHAT_ID trong file nay!")
        
        # Test gửi tin nhắn
        test = input("\nGui tin nhan test? (y/n): ")
        if test.lower() == 'y':
            if send_telegram("Bot XAUUSD da ket noi thanh cong!", chat_id):
                print("Da gui tin nhan test!")
            else:
                print("Gui that bai!")


