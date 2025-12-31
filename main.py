import time
import MetaTrader5 as mt5
from strategy import evaluate_signals, Signal
from trade import process_trade, is_bot_stopped, is_cluster_open, check_and_cancel_pending_if_past_tp4, reset_cluster_info, force_open_cluster, check_cluster_result_and_record, reset_bot
from telegram_bot import (
    log, flush_logs, 
    get_bot_control, set_bot_control, check_force_trade, check_reset_score, get_next_score_override,
    check_should_reset_bot, update_accumulated_score,
    # Trade confirmation
    request_trade_confirmation, check_confirmation_status, is_confirmation_pending,
    cancel_pending_confirmation
)
from be_manager import check_be, reset_be_manager

SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M1

# Nguong diem mac dinh (se duoc cap nhat tu Telegram /threshold)
DEFAULT_BUY_THRESHOLD = 35
DEFAULT_SELL_THRESHOLD = 35

# Khoi tao nguong ban dau
set_bot_control(buy_threshold=DEFAULT_BUY_THRESHOLD, sell_threshold=DEFAULT_SELL_THRESHOLD)

# ========== KET NOI ==========

if not mt5.initialize():
    log("Khong the ket noi MT5:", mt5.last_error())
    quit()
else:
    log("Da ket noi MT5 thanh cong!")
    acc = mt5.account_info()
    log(f"Tai khoan: {acc.login} | Balance: {acc.balance}")
    flush_logs()

# ========== VONG LAP ==========

last_candle = None
accumulated_score = Signal()
was_cluster_open = False  # Theo doi trang thai cluster
bot_stopped_logged = False  # Tranh spam log khi bot dung
pending_trade_direction = None  # Luu huong trade dang cho xac nhan

while True:
    # ========== KIEM TRA COMMANDS TU TELEGRAM ==========
    
    # Kiem tra yeu cau reset bot (khi /start)
    if check_should_reset_bot():
        reset_bot()
        bot_stopped_logged = False  # Reset flag de cho phep log lai neu dung lan nua
        log(">>> BOT DA DUOC RESET (tu /start) <<<")
        flush_logs()
    
    # Kiem tra trang thai bot va lay nguong diem
    bot_ctrl = get_bot_control()
    buy_threshold = bot_ctrl['buy_threshold']
    sell_threshold = bot_ctrl['sell_threshold']
    
    # Kiem tra yeu cau reset score
    if check_reset_score():
        log(">>> RESET SCORE (tu Telegram) <<<")
        accumulated_score = Signal()
        update_accumulated_score(0, 0, buy_threshold, sell_threshold)
        flush_logs()
    
    # Kiem tra yeu cau mo lenh ngay
    force_direction = check_force_trade()
    if force_direction and not is_cluster_open(SYMBOL):
        log(f"[CMD] Mo {force_direction.upper()} ngay tu Telegram!")
        force_open_cluster(SYMBOL, force_direction)
        flush_logs()
    
    # Kiem tra co diem override cho cluster tiep theo
    override_buy, override_sell = get_next_score_override()
    if override_buy is not None:
        accumulated_score.buy_score = override_buy
        log(f"[CMD] Set diem Buy = {override_buy}")
    if override_sell is not None:
        accumulated_score.sell_score = override_sell
        log(f"[CMD] Set diem Sell = {override_sell}")
    
    # ========== KIEM TRA TRANG THAI XAC NHAN ==========
    
    # Kiem tra xac nhan trade dang cho
    if is_confirmation_pending():
        status, direction = check_confirmation_status()
        
        if status == 'confirmed':
            # User da confirm hoac auto-confirm sau 8 phut -> Mo lenh
            log(f"[CONFIRM] Da xac nhan - Mo {direction.upper()}!")
            if not is_cluster_open(SYMBOL):
                force_open_cluster(SYMBOL, direction)
                # Reset score sau khi mo lenh
                log(">>> RESET SCORE <<<")
                accumulated_score = Signal()
                update_accumulated_score(0, 0, buy_threshold, sell_threshold)
            else:
                log(f"[CONFIRM] Cluster dang mo - khong the mo them")
            pending_trade_direction = None
            flush_logs()
        
        elif status == 'cancelled':
            # User da cancel -> Khong trade, reset score
            log(f"[CONFIRM] Da huy - Khong mo {direction.upper()}")
            log(">>> RESET SCORE <<<")
            accumulated_score = Signal()
            update_accumulated_score(0, 0, buy_threshold, sell_threshold)
            pending_trade_direction = None
            flush_logs()
        
        # Neu status == 'pending' thi tiep tuc cho
    
    # ========== KIEM TRA BOT DUNG ==========
    
    # Kiem tra bot co bi dung khong (3 lenh lien tiep hoac tu Telegram)
    if is_bot_stopped() or not bot_ctrl['active']:
        if is_bot_stopped() and not bot_stopped_logged:
            log("[MAIN] Bot da dung - 3 lan SL lien tiep. Dung /start de bat lai.")
            # Sync trang thai voi telegram_bot
            set_bot_control(active=False)
            flush_logs()
            bot_stopped_logged = True
        time.sleep(5)
        continue  # Khong break, cho phep bat lai tu Telegram
    
    # Kiem tra va keo BE neu can (ET3 chot TP -> SL ET4 = Entry +- 2.5)
    check_be()
    
    # Kiem tra cluster vua dong -> mo lenh ngay neu du diem
    cluster_open_now = is_cluster_open(SYMBOL)
    
    # Chi kiem tra huy lenh pending khi cluster dang mo
    if cluster_open_now:
        check_and_cancel_pending_if_past_tp4(SYMBOL, accumulated_score, buy_threshold, sell_threshold)
    
    if was_cluster_open and not cluster_open_now:
        # Cluster vua dong xong!
        log("[INFO] Cluster vua dong!")
        
        # Kiem tra ket qua cluster (loi/lo) va ghi nhan SL neu can
        check_cluster_result_and_record(SYMBOL)
        
        # Reset thong tin cluster va BE manager
        reset_cluster_info()
        reset_be_manager()
        log("[INFO] Kiem tra mo lenh moi...")
        
        # Kiem tra co du diem khong (va chua co pending confirmation)
        if not is_confirmation_pending():
            buy_diff = accumulated_score.buy_score - buy_threshold
            sell_diff = accumulated_score.sell_score - sell_threshold
            
            if buy_diff >= 0 or sell_diff >= 0:
                log(f"[INFO] Du diem! Buy={accumulated_score.buy_score}/{buy_threshold}, Sell={accumulated_score.sell_score}/{sell_threshold}")
                
                # Xac dinh huong trade (chieu co diem cao hon)
                # Kiem tra chieu nao dang active
                can_buy = bot_ctrl.get('buy_active', True) and buy_diff >= 0
                can_sell = bot_ctrl.get('sell_active', True) and sell_diff >= 0
                
                if can_buy and (not can_sell or buy_diff >= sell_diff):
                    pending_trade_direction = 'buy'
                elif can_sell:
                    pending_trade_direction = 'sell'
                else:
                    pending_trade_direction = None
                
                if pending_trade_direction:
                    # Gui yeu cau xac nhan qua Telegram
                    log(f"[INFO] Gui yeu cau xac nhan {pending_trade_direction.upper()}...")
                    request_trade_confirmation(
                        pending_trade_direction,
                        accumulated_score.buy_score,
                        accumulated_score.sell_score,
                        buy_threshold,
                        sell_threshold
                    )
                    flush_logs()
    
    was_cluster_open = cluster_open_now
    
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 2)
    if rates is None:
        time.sleep(1)
        continue

    candle_time = rates[-1]['time']

    if last_candle != candle_time:
        last_candle = candle_time
        log("\n=== New Candle ===")
        
        # Lay du lieu cac khung thoi gian
        rates_m15 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 1, 100)
        rates_h4 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H4, 1, 100)
        rates_h1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 1, 150)
        rates_m30 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M30, 1, 200)
        
        if rates_m15 is None or rates_h4 is None or rates_h1 is None or rates_m30 is None:
            log("Khong lay duoc du lieu nen")
            time.sleep(1)
            continue

        # Tinh diem nen hien tai
        current_signal = evaluate_signals(SYMBOL, rates_m15, rates_h4, rates_h1, rates_m30)
        
        # Tich luy diem
        accumulated_score.buy_score += current_signal.buy_score
        accumulated_score.sell_score += current_signal.sell_score
        
        # Cap nhat diem tich luy cho Telegram /status
        update_accumulated_score(accumulated_score.buy_score, accumulated_score.sell_score, buy_threshold, sell_threshold)
        
        # Hien thi diem dang xx/xx
        log(f"This candle: Buy +{current_signal.buy_score} | Sell +{current_signal.sell_score}")
        log(f"ACCUMULATED: Buy {accumulated_score.buy_score}/{buy_threshold} | Sell {accumulated_score.sell_score}/{sell_threshold}")
        
        # Hien thi trang thai cluster va bot
        if is_cluster_open(SYMBOL):
            log("[INFO] Cluster dang mo - chua mo lenh moi")
        
        if not bot_ctrl['buy_active'] or not bot_ctrl['sell_active']:
            status = []
            if not bot_ctrl['buy_active']:
                status.append("Buy: OFF")
            if not bot_ctrl['sell_active']:
                status.append("Sell: OFF")
            log(f"[INFO] {' | '.join(status)}")

        # Kiem tra du diem va gui yeu cau xac nhan (neu chua co pending)
        if not is_cluster_open(SYMBOL) and not is_confirmation_pending():
            buy_diff = accumulated_score.buy_score - buy_threshold
            sell_diff = accumulated_score.sell_score - sell_threshold
            
            if buy_diff >= 0 or sell_diff >= 0:
                log(f"[INFO] Du diem! Kiem tra chieu trade...")
                
                # Xac dinh huong trade (chieu co diem cao hon va dang active)
                can_buy = bot_ctrl.get('buy_active', True) and buy_diff >= 0
                can_sell = bot_ctrl.get('sell_active', True) and sell_diff >= 0
                
                if can_buy and (not can_sell or buy_diff >= sell_diff):
                    pending_trade_direction = 'buy'
                elif can_sell:
                    pending_trade_direction = 'sell'
                else:
                    pending_trade_direction = None
                
                if pending_trade_direction:
                    # Gui yeu cau xac nhan qua Telegram
                    log(f"[CONFIRM] Gui yeu cau xac nhan {pending_trade_direction.upper()}...")
                    request_trade_confirmation(
                        pending_trade_direction,
                        accumulated_score.buy_score,
                        accumulated_score.sell_score,
                        buy_threshold,
                        sell_threshold
                    )
        
        # Gui log len Telegram sau moi lan phan tich nen
        flush_logs()

    time.sleep(2)

# Ket thuc
mt5.shutdown()
log("[MAIN] Chuong trinh ket thuc.")
