import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from datetime import datetime
import threading
import time
import json
import MetaTrader5 as mt5

# Telegram Bot Configuration
BOT_TOKEN = "8388937091:AAFRyeKoIGeUnVxtoSskxhRc_pCS9I5QBCg"

# ========== SESSION VỚI RETRY VÀ CONNECTION POOLING ==========
def create_session():
    """Tạo session với retry và connection pooling"""
    session = requests.Session()
    
    # Cấu hình retry: thử lại 3 lần khi timeout hoặc lỗi kết nối
    retry_strategy = Retry(
        total=3,
        backoff_factor=1,  # Chờ 1s, 2s, 4s giữa các lần thử
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "POST"]
    )
    
    adapter = HTTPAdapter(
        max_retries=retry_strategy,
        pool_connections=10,
        pool_maxsize=10
    )
    
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    
    return session

# Session toàn cục
_session = create_session()
# BOT_TOKEN = "8429353540:AAGNIPh-Lje4KAl_Ko57OS8TBWfgzpgaJWM"



# Danh sach cac chat se nhan thong bao (ca nhan + nhom)
CHAT_IDS = [
   -5027471114,  # Nhom: Bot Trailing XAU
    5638732845,   # Ca nhan: t
    # -1003467971094, # nhom scaping
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
    'should_reset_bot': False, # Flag de reset bot (counter, stopped state)
    # Diem tich luy hien tai (duoc cap nhat tu main.py)
    'accumulated_buy': 0,
    'accumulated_sell': 0,
    'buy_threshold': 35,
    'sell_threshold': 35,
    # Cau hinh giao dich
    'fixed_capital': None,    # Von co dinh (None = dung balance thuc)
    'risk_percent': 0.10,     # % rui ro (0.01 = 1%, 0.10 = 10%)
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
        # Sử dụng session với retry
        response = _session.get(url, timeout=15)
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
            # Sử dụng session với retry thay vì requests trực tiếp
            response = _session.post(url, json=payload, timeout=15)
            if response.status_code == 200:
                success = True
        except requests.exceptions.Timeout:
            print(f"[TELE] Send timeout to {target}, will retry...")
        except requests.exceptions.ConnectionError:
            print(f"[TELE] Connection error to {target}")
        except Exception as e:
            print(f"[TELE] Send error: {e}")
    
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


def update_accumulated_score(buy_score, sell_score, buy_threshold=35, sell_threshold=35):
    """Cap nhat diem tich luy hien tai (goi tu main.py)"""
    with _control_lock:
        _bot_control['accumulated_buy'] = buy_score
        _bot_control['accumulated_sell'] = sell_score
        _bot_control['buy_threshold'] = buy_threshold
        _bot_control['sell_threshold'] = sell_threshold


def check_should_reset_bot():
    """Kiem tra co yeu cau reset bot khong (khi /start)"""
    with _control_lock:
        if _bot_control['should_reset_bot']:
            _bot_control['should_reset_bot'] = False
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


def close_all_positions():
    """
    Dong tat ca lenh dang mo va huy tat ca lenh pending.
    Tinh profit tu lich su deals (chinh xac hon).
    """
    from datetime import datetime, timedelta
    from trade import get_cluster_tickets, reset_cluster_info, get_current_cluster_direction, record_cluster_result
    
    symbol = "XAUUSD"
    closed_count = 0
    cancelled_count = 0
    errors = []
    position_tickets = []  # Luu lai ticket de tinh profit sau
    
    # Lay huong cluster TRUOC KHI dong lenh
    cluster_direction = get_current_cluster_direction(symbol)
    
    # Thoi diem bat dau dong lenh
    close_start_time = datetime.now()
    
    # 1. Dong tat ca positions dang mo
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        for pos in positions:
            position_tickets.append(pos.ticket)
            
            # Xac dinh loai lenh dong
            if pos.type == mt5.POSITION_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = mt5.symbol_info_tick(symbol).bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(symbol).ask
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": pos.ticket,
                "price": price,
                "deviation": 20,
                "magic": pos.magic,
                "comment": "Close All",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                closed_count += 1
            else:
                errors.append(f"#{pos.ticket}: {result.comment if result else 'Unknown error'}")
    
    # 2. Huy tat ca pending orders
    orders = mt5.orders_get(symbol=symbol)
    if orders:
        for order in orders:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                cancelled_count += 1
            else:
                errors.append(f"Pending #{order.ticket}: {result.comment if result else 'Unknown error'}")
    
    # Tao message ket qua
    if closed_count == 0 and cancelled_count == 0:
        return "Khong co lenh nao de dong."
    
    # 3. Tinh profit tu lich su deals (sau khi dong)
    import time
    time.sleep(0.5)  # Cho MT5 cap nhat lich su
    
    total_profit = 0.0
    deals_counted = 0
    
    # Lay profit tu cac position vua dong
    for ticket in position_tickets:
        deals = mt5.history_deals_get(position=ticket)
        if deals:
            for deal in deals:
                if deal.entry == mt5.DEAL_ENTRY_OUT:
                    profit = deal.profit + deal.commission + deal.swap
                    total_profit += profit
                    deals_counted += 1
    
    # Ghi nhan ket qua SL/TP va dem SL lien tiep
    if closed_count > 0:
        direction = cluster_direction or "manual"
        is_profit = total_profit > 0
        record_cluster_result(direction, is_profit, total_profit)
    
    # Reset cluster info sau khi dong het
    reset_cluster_info()
    
    msg = f"DA DONG TAT CA LENH\n"
    msg += f"-------------------\n"
    msg += f"Positions dong: {closed_count}\n"
    msg += f"Pending huy: {cancelled_count}\n"
    msg += f"Tong profit: ${total_profit:.2f}\n"
    
    if errors:
        msg += f"\nLoi: {len(errors)} lenh\n"
        for e in errors[:3]:  # Chi hien 3 loi dau
            msg += f"   - {e}\n"
    
    return msg


def close_positions_only():
    """
    Chi dong cac lenh dang mo (positions), khong huy pending.
    """
    from trade import reset_cluster_info, get_current_cluster_direction, record_cluster_result
    
    symbol = "XAUUSD"
    closed_count = 0
    errors = []
    position_tickets = []
    
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return "Khong co lenh nao dang mo."
    
    # Lay huong cluster TRUOC KHI dong lenh
    cluster_direction = get_current_cluster_direction(symbol)
    
    for pos in positions:
        position_tickets.append(pos.ticket)
        
        if pos.type == mt5.POSITION_TYPE_BUY:
            order_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(symbol).bid
        else:
            order_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(symbol).ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": order_type,
            "position": pos.ticket,
            "price": price,
            "deviation": 20,
            "magic": pos.magic,
            "comment": "Close Pos",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            closed_count += 1
        else:
            errors.append(f"#{pos.ticket}: {result.comment if result else 'Unknown error'}")
    
    # Tinh profit
    import time
    time.sleep(0.5)
    
    total_profit = 0.0
    for ticket in position_tickets:
        deals = mt5.history_deals_get(position=ticket)
        if deals:
            for deal in deals:
                if deal.entry == mt5.DEAL_ENTRY_OUT:
                    total_profit += deal.profit + deal.commission + deal.swap
    
    # Ghi nhan ket qua SL/TP va dem SL lien tiep
    if closed_count > 0:
        direction = cluster_direction or "manual"
        is_profit = total_profit > 0
        record_cluster_result(direction, is_profit, total_profit)
    
    # Check con pending khong, neu khong thi reset cluster
    orders = mt5.orders_get(symbol=symbol)
    if not orders:
        reset_cluster_info()
    
    msg = f"DA DONG POSITIONS\n"
    msg += f"-------------------\n"
    msg += f"So lenh dong: {closed_count}\n"
    msg += f"Profit: ${total_profit:.2f}\n"
    
    if errors:
        msg += f"\nLoi: {len(errors)} lenh\n"
        for e in errors[:3]:
            msg += f"   - {e}\n"
    
    return msg


def cancel_pending_only():
    """
    Chi huy cac lenh pending, khong dong positions.
    """
    from trade import reset_cluster_info
    
    symbol = "XAUUSD"
    cancelled_count = 0
    errors = []
    
    orders = mt5.orders_get(symbol=symbol)
    if not orders:
        return "Khong co lenh pending nao."
    
    for order in orders:
        request = {
            "action": mt5.TRADE_ACTION_REMOVE,
            "order": order.ticket,
        }
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            cancelled_count += 1
        else:
            errors.append(f"#{order.ticket}: {result.comment if result else 'Unknown error'}")
    
    # Check con position khong, neu khong thi reset cluster
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        reset_cluster_info()
    
    msg = f"DA HUY PENDING ORDERS\n"
    msg += f"-------------------\n"
    msg += f"So lenh huy: {cancelled_count}\n"
    
    if errors:
        msg += f"\nLoi: {len(errors)} lenh\n"
        for e in errors[:3]:
            msg += f"   - {e}\n"
    
    return msg


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
        set_bot_control(active=True, buy_active=True, sell_active=True, should_reset_bot=True)
        return "🟢 Bot da BAT. Counter da reset. Ca 2 chieu deu hoat dong."
    
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
        # Format: /set buy=20 sell=15 hoac /set buy = 20 sell = 15
        buy_score = None
        sell_score = None
        
        # Ghep tat ca args lai va loai bo dau cach xung quanh '='
        # VD: "sell = 100" -> "sell=100"
        args_str = ' '.join(args).replace(' = ', '=').replace('= ', '=').replace(' =', '=')
        parts = args_str.split()
        
        for part in parts:
            if '=' in part:
                key, val = part.split('=', 1)
                try:
                    if key.lower() == 'buy':
                        buy_score = int(val)
                    elif key.lower() == 'sell':
                        sell_score = int(val)
                except:
                    pass
            else:
                # Truong hop chi co so (VD: /set 100 50)
                try:
                    val = int(part)
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
            msg = "Da set diem cho cluster tiep theo:\n"
            if buy_score is not None:
                msg += f"   Buy: {buy_score}\n"
            if sell_score is not None:
                msg += f"   Sell: {sell_score}"
            return msg
        else:
            return "Sai format. VD: /set buy=20 sell=15"
    
    elif cmd in ['/threshold', '/nguong', '/th']:
        # Set nguong diem can thiet de mo lenh (ap dung vinh vien)
        # Format: /threshold buy=50 sell=40 hoac /threshold 50 40
        buy_thresh = None
        sell_thresh = None
        
        args_str = ' '.join(args).replace(' = ', '=').replace('= ', '=').replace(' =', '=')
        parts = args_str.split()
        
        for part in parts:
            if '=' in part:
                key, val = part.split('=', 1)
                try:
                    if key.lower() == 'buy':
                        buy_thresh = int(val)
                    elif key.lower() == 'sell':
                        sell_thresh = int(val)
                except:
                    pass
            else:
                try:
                    val = int(part)
                    if buy_thresh is None:
                        buy_thresh = val
                    elif sell_thresh is None:
                        sell_thresh = val
                except:
                    pass
        
        if buy_thresh is not None or sell_thresh is not None:
            # Lay gia tri hien tai neu khong set
            ctrl = get_bot_control()
            if buy_thresh is None:
                buy_thresh = ctrl['buy_threshold']
            if sell_thresh is None:
                sell_thresh = ctrl['sell_threshold']
            
            set_bot_control(
                buy_threshold=buy_thresh,
                sell_threshold=sell_thresh
            )
            msg = f"DA SET NGUONG DIEM\n"
            msg += f"-------------------\n"
            msg += f"Buy: {buy_thresh} diem\n"
            msg += f"Sell: {sell_thresh} diem\n"
            msg += f"(Ap dung cho tat ca lenh sau nay)"
            return msg
        else:
            ctrl = get_bot_control()
            msg = f"NGUONG DIEM HIEN TAI\n"
            msg += f"-------------------\n"
            msg += f"Buy: {ctrl['buy_threshold']} diem\n"
            msg += f"Sell: {ctrl['sell_threshold']} diem\n\n"
            msg += f"Cach set: /threshold buy=50 sell=40"
            return msg
    
    elif cmd in ['/capital', '/von', '/nav']:
        # Set von co dinh (thay vi dung balance thuc)
        # Format: /capital 10000 hoac /capital reset
        if args:
            arg = args[0].lower()
            if arg in ['reset', 'auto', '0']:
                set_bot_control(fixed_capital=None)
                return "DA RESET VON\n-------------------\nSe su dung balance thuc cua tai khoan."
            else:
                try:
                    capital = float(arg)
                    if capital > 0:
                        set_bot_control(fixed_capital=capital)
                        return f"DA SET VON CO DINH\n-------------------\nVon: ${capital:.2f}\n(Khong phu thuoc balance thuc)"
                    else:
                        return "Von phai lon hon 0"
                except:
                    return "Sai format. VD: /capital 10000"
        else:
            ctrl = get_bot_control()
            if ctrl['fixed_capital']:
                msg = f"VON HIEN TAI\n-------------------\n"
                msg += f"Von co dinh: ${ctrl['fixed_capital']:.2f}\n\n"
            else:
                msg = f"VON HIEN TAI\n-------------------\n"
                msg += f"Dang dung balance thuc\n\n"
            msg += f"Cach set: /capital 10000\n"
            msg += f"Reset: /capital reset"
            return msg
    
    elif cmd in ['/risk', '/ruiro', '/rr']:
        # Set % rui ro
        # Format: /risk 10 (= 10%) hoac /risk 0.1
        if args:
            try:
                val = float(args[0])
                # Neu nhap so nguyen lon hon 1 thi coi nhu %
                if val > 1:
                    risk = val / 100
                else:
                    risk = val
                
                if 0 < risk <= 1:
                    set_bot_control(risk_percent=risk)
                    return f"DA SET RUI RO\n-------------------\nRisk: {risk*100:.1f}% NAV"
                else:
                    return "Risk phai tu 0.01 den 1 (hoac 1% den 100%)"
            except:
                return "Sai format. VD: /risk 10 (= 10%)"
        else:
            ctrl = get_bot_control()
            msg = f"RUI RO HIEN TAI\n-------------------\n"
            msg += f"Risk: {ctrl['risk_percent']*100:.1f}% NAV\n\n"
            msg += f"Cach set: /risk 10 (= 10%)"
            return msg
    
    elif cmd in ['/status', '/trangthai']:
        from trade import get_consecutive_sl_count
        
        ctrl = get_bot_control()
        status = "DANG CHAY" if ctrl['active'] else "DA TAT"
        buy_status = "ON" if ctrl['buy_active'] else "OFF"
        sell_status = "ON" if ctrl['sell_active'] else "OFF"
        
        # Lay so lan SL lien tiep
        sl_count, sl_max = get_consecutive_sl_count()
        
        msg = f"TRANG THAI BOT\n"
        msg += f"-------------------\n"
        msg += f"Bot: {status}\n"
        msg += f"Buy: {buy_status} | Sell: {sell_status}\n"
        msg += f"SL lien tiep: {sl_count}/{sl_max}\n"
        
        # Hien thi cau hinh giao dich
        capital_str = f"${ctrl['fixed_capital']:.0f}" if ctrl['fixed_capital'] else "Auto"
        risk_str = f"{ctrl['risk_percent']*100:.0f}%"
        msg += f"Von: {capital_str} | Risk: {risk_str}\n"
        
        # Hien thi diem tich luy
        msg += f"\nDIEM TICH LUY\n"
        msg += f"-------------------\n"
        buy_score = ctrl['accumulated_buy']
        sell_score = ctrl['accumulated_sell']
        buy_thresh = ctrl['buy_threshold']
        sell_thresh = ctrl['sell_threshold']
        msg += f"Buy: {buy_score}/{buy_thresh}\n"
        msg += f"Sell: {sell_score}/{sell_thresh}\n"
        
        # Hien thi lenh dang mo
        symbol = "XAUUSD"
        positions = mt5.positions_get(symbol=symbol)
        orders = mt5.orders_get(symbol=symbol)
        
        if positions or orders:
            msg += f"\nLENH DANG MO\n"
            msg += f"-------------------\n"
            
            if positions:
                total_profit = 0.0
                for pos in positions:
                    pos_type = "BUY" if pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                    profit = pos.profit
                    total_profit += profit
                    profit_str = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
                    msg += f"#{pos.ticket} {pos_type} {pos.volume} @ {pos.price_open} | {profit_str}\n"
                msg += f"Tong: ${total_profit:.2f}\n"
            
            if orders:
                msg += f"\nPending: {len(orders)} lenh\n"
                for order in orders:
                    order_type = "BUY_LMT" if order.type == mt5.ORDER_TYPE_BUY_LIMIT else "SELL_LMT"
                    msg += f"  #{order.ticket} {order_type} {order.volume_current} @ {order.price_open}\n"
        else:
            msg += f"\nKhong co lenh nao dang mo.\n"
        
        if ctrl['next_buy_score'] or ctrl['next_sell_score']:
            msg += f"\nDiem set cho cluster tiep:\n"
            msg += f"   Buy: {ctrl['next_buy_score'] or 'N/A'}\n"
            msg += f"   Sell: {ctrl['next_sell_score'] or 'N/A'}"
        
        return msg
    
    elif cmd in ['/closeall', '/dongtatca', '/close']:
        # Dong tat ca lenh dang mo va pending
        result = close_all_positions()
        return result
    
    elif cmd in ['/closepos', '/dongpos']:
        # Chi dong positions, khong huy pending
        result = close_positions_only()
        return result
    
    elif cmd in ['/cancelpending', '/huypending', '/cancel']:
        # Chi huy pending orders
        result = cancel_pending_only()
        return result
    
    elif cmd in ['/help', '/huongdan']:
        msg = """HUONG DAN SU DUNG
-------------------

Bat/Tat bot:
/stop - Tat bot, reset score
/start - Bat bot

Bat/Tat 1 chieu:
/stop_buy, /start_buy
/stop_sell, /start_sell

Mo lenh ngay:
/buy - Mo Buy ngay
/sell - Mo Sell ngay

Dong lenh:
/closeall - Dong tat ca
/closepos - Chi dong positions
/cancelpending - Chi huy pending

Cau hinh:
/set buy=20 sell=15 (1 lan)
/threshold buy=50 sell=40
/capital 10000 (von co dinh)
/risk 10 (= 10%)

Xem trang thai:
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
    
    # Đếm số lần lỗi liên tiếp để điều chỉnh thời gian chờ
    consecutive_errors = 0
    max_wait = 60  # Tối đa chờ 60 giây khi lỗi liên tục
    
    while True:
        try:
            params = {
                "offset": _last_update_id + 1,
                "timeout": 30,  # Long polling timeout (Telegram sẽ giữ kết nối 30s)
                "allowed_updates": ["message"]
            }
            
            # Sử dụng session với retry, timeout cao hơn cho long polling
            response = _session.get(url, params=params, timeout=35)
            data = response.json()
            
            # Reset counter khi thành công
            consecutive_errors = 0
            
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
        
        except requests.exceptions.Timeout:
            # Timeout là bình thường với long polling, không cần báo lỗi
            consecutive_errors += 1
            if consecutive_errors >= 5:
                print(f"[CMD] Timeout lien tuc {consecutive_errors} lan, kiem tra mang...")
        
        except requests.exceptions.ConnectionError as e:
            consecutive_errors += 1
            print(f"[CMD] Loi ket noi (lan {consecutive_errors}): Mat mang?")
        
        except Exception as e:
            consecutive_errors += 1
            print(f"[CMD] Poll error (lan {consecutive_errors}): {e}")
        
        # Backoff khi lỗi liên tục: chờ lâu hơn
        if consecutive_errors > 0:
            wait_time = min(2 * consecutive_errors, max_wait)
            time.sleep(wait_time)
        else:
            time.sleep(1)  # Chờ ngắn khi OK


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


