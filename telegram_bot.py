import requests
from datetime import datetime
import threading
import time
import json

# Telegram Bot Configuration
BOT_TOKEN = "8388937091:AAFRyeKoIGeUnVxtoSskxhRc_pCS9I5QBCg"

# Danh sach cac chat se nhan thong bao (ca nhan + nhom)
CHAT_IDS = [
   -5027471114,  # Nhom: Bot Trailing XAU
    5638732845,   # Ca nhan: t
]

# Buffer de gom nhieu log lai gui 1 lan (tranh spam Telegram)
_log_buffer = []
_buffer_lock = threading.Lock()
_last_send_time = 0
BUFFER_DELAY = 3  # Gom log trong 3 giay roi gui 1 lan

# ========== BOT CONTROL STATE ==========
_bot_control = {
    'active': True,           # Bot dang hoat dong
    'buy_active': True,       # Cho phep mo buy
    'sell_active': True,      # Cho phep mo sell
    'force_buy': False,       # Mo buy ngay lap tuc
    'force_sell': False,      # Mo sell ngay lap tuc
    'next_buy_score': None,   # Diem buy cho cluster tiep theo (None = binh thuong)
    'next_sell_score': None,  # Diem sell cho cluster tiep theo (None = binh thuong)
    'reset_score': False,     # Flag de reset score
}
_control_lock = threading.Lock()
_last_update_id = 0

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


# ========== TELEGRAM COMMAND HANDLER ==========

def get_bot_control():
    """Lay trang thai dieu khien bot (thread-safe)"""
    with _control_lock:
        return _bot_control.copy()


def set_bot_control(**kwargs):
    """Cap nhat trang thai dieu khien bot"""
    with _control_lock:
        for key, value in kwargs.items():
            if key in _bot_control:
                _bot_control[key] = value


def check_force_trade():
    """
    Kiem tra co yeu cau mo lenh ngay khong.
    Returns: 'buy', 'sell', hoac None
    """
    with _control_lock:
        if _bot_control['force_buy']:
            _bot_control['force_buy'] = False
            return 'buy'
        if _bot_control['force_sell']:
            _bot_control['force_sell'] = False
            return 'sell'
    return None


def check_reset_score():
    """Kiem tra co yeu cau reset score khong"""
    with _control_lock:
        if _bot_control['reset_score']:
            _bot_control['reset_score'] = False
            return True
    return False


def get_next_score_override():
    """
    Lay diem da set cho cluster tiep theo.
    Returns: (buy_score, sell_score) hoac (None, None) neu khong co
    """
    with _control_lock:
        buy = _bot_control['next_buy_score']
        sell = _bot_control['next_sell_score']
        # Reset sau khi lay
        _bot_control['next_buy_score'] = None
        _bot_control['next_sell_score'] = None
        return buy, sell


def _parse_command(text):
    """Parse command tu tin nhan Telegram"""
    if not text:
        return None, []
    
    text = text.strip().lower()
    parts = text.split()
    
    if not parts:
        return None, []
    
    cmd = parts[0]
    args = parts[1:] if len(parts) > 1 else []
    
    return cmd, args


def _handle_command(cmd, args, chat_id):
    """Xu ly command va tra ve response"""
    global _bot_control
    
    if cmd in ['/stop', '/off', '/tat']:
        # Tat bot, reset score
        set_bot_control(active=False, buy_active=False, sell_active=False, reset_score=True)
        return "🔴 Bot da TAT. Score da reset ve 0."
    
    elif cmd in ['/stop_buy', '/tatbuy']:
        set_bot_control(buy_active=False)
        return "🔴 Da TAT chieu BUY. (Sell van hoat dong)"
    
    elif cmd in ['/stop_sell', '/tatsell']:
        set_bot_control(sell_active=False)
        return "🔴 Da TAT chieu SELL. (Buy van hoat dong)"
    
    elif cmd in ['/start', '/on', '/bat']:
        set_bot_control(active=True, buy_active=True, sell_active=True)
        return "🟢 Bot da BAT. Ca 2 chieu deu hoat dong."
    
    elif cmd in ['/start_buy', '/batbuy']:
        set_bot_control(buy_active=True)
        return "🟢 Da BAT chieu BUY."
    
    elif cmd in ['/start_sell', '/batsell']:
        set_bot_control(sell_active=True)
        return "🟢 Da BAT chieu SELL."
    
    elif cmd in ['/buy', '/buynow', '/muangay']:
        # Check trang thai buy truoc
        ctrl = get_bot_control()
        if not ctrl['buy_active']:
            return "❌ Khong the mo BUY - chieu BUY dang TAT.\nDung /start_buy de bat lai."
        # Mo buy ngay lap tuc
        set_bot_control(force_buy=True, active=True)
        return "⚡ Se mo lenh BUY ngay lap tuc!"
    
    elif cmd in ['/sell', '/sellnow', '/banngay']:
        # Check trang thai sell truoc
        ctrl = get_bot_control()
        if not ctrl['sell_active']:
            return "❌ Khong the mo SELL - chieu SELL dang TAT.\nDung /start_sell de bat lai."
        # Mo sell ngay lap tuc
        set_bot_control(force_sell=True, active=True)
        return "⚡ Se mo lenh SELL ngay lap tuc!"
    
    elif cmd in ['/set', '/setdiem']:
        # Set diem cho cluster tiep theo
        # Format: /set buy=20 sell=15 hoac /set 20 15
        buy_score = None
        sell_score = None
        
        for arg in args:
            if '=' in arg:
                key, val = arg.split('=', 1)
                try:
                    if key.lower() == 'buy':
                        buy_score = int(val)
                    elif key.lower() == 'sell':
                        sell_score = int(val)
                except:
                    pass
            else:
                try:
                    val = int(arg)
                    if buy_score is None:
                        buy_score = val
                    elif sell_score is None:
                        sell_score = val
                except:
                    pass
        
        if buy_score is not None or sell_score is not None:
            set_bot_control(
                next_buy_score=buy_score,
                next_sell_score=sell_score,
                active=True
            )
            msg = "✅ Da set diem cho cluster tiep theo:\n"
            if buy_score is not None:
                msg += f"   Buy: {buy_score}\n"
            if sell_score is not None:
                msg += f"   Sell: {sell_score}"
            return msg
        else:
            return "❌ Sai format. VD: /set buy=20 sell=15"
    
    elif cmd in ['/status', '/trangthai']:
        ctrl = get_bot_control()
        status = "🟢 DANG CHAY" if ctrl['active'] else "🔴 DA TAT"
        buy_status = "✅" if ctrl['buy_active'] else "❌"
        sell_status = "✅" if ctrl['sell_active'] else "❌"
        
        msg = f"📊 <b>TRANG THAI BOT</b>\n"
        msg += f"━━━━━━━━━━━━━━━\n"
        msg += f"Bot: {status}\n"
        msg += f"Buy: {buy_status} | Sell: {sell_status}\n"
        
        if ctrl['next_buy_score'] or ctrl['next_sell_score']:
            msg += f"\n⏳ Diem set cho cluster tiep theo:\n"
            msg += f"   Buy: {ctrl['next_buy_score'] or 'N/A'}\n"
            msg += f"   Sell: {ctrl['next_sell_score'] or 'N/A'}"
        
        return msg
    
    elif cmd in ['/help', '/huongdan']:
        msg = """📖 <b>HUONG DAN SU DUNG</b>
━━━━━━━━━━━━━━━

<b>Bat/Tat bot:</b>
/stop - Tat bot, reset score
/start - Bat bot

<b>Bat/Tat 1 chieu:</b>
/stop_buy - Tat chieu Buy
/stop_sell - Tat chieu Sell
/start_buy - Bat chieu Buy
/start_sell - Bat chieu Sell

<b>Mo lenh ngay:</b>
/buy - Mo Buy ngay
/sell - Mo Sell ngay

<b>Set diem:</b>
/set buy=20 sell=15
(Ap dung cho cluster tiep theo)

<b>Xem trang thai:</b>
/status"""
        return msg
    
    return None  # Khong phai command


def _poll_commands():
    """
    Thread poll tin nhan tu Telegram de xu ly commands.
    Chay lien tuc, kiem tra moi 2 giay.
    """
    global _last_update_id
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
    
    while True:
        try:
            params = {
                "offset": _last_update_id + 1,
                "timeout": 10,
                "allowed_updates": ["message"]
            }
            
            response = requests.get(url, params=params, timeout=15)
            data = response.json()
            
            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    _last_update_id = update["update_id"]
                    
                    if "message" in update and "text" in update["message"]:
                        text = update["message"]["text"]
                        chat_id = update["message"]["chat"]["id"]
                        
                        # Parse va xu ly command
                        cmd, args = _parse_command(text)
                        if cmd and cmd.startswith('/'):
                            response_msg = _handle_command(cmd, args, chat_id)
                            if response_msg:
                                send_telegram(response_msg, chat_id)
                                print(f"[CMD] {cmd} -> {response_msg[:50]}...")
        
        except Exception as e:
            print(f"[CMD] Poll error: {e}")
        
        time.sleep(2)


# Start command polling thread
_cmd_thread = threading.Thread(target=_poll_commands, daemon=True)
_cmd_thread.start()
print("[BOT] Telegram command handler started")


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


