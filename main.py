import time
import MetaTrader5 as mt5
from strategy import evaluate_signals, Signal
from trade import process_trade, is_bot_stopped, is_cluster_open, check_and_cancel_pending_if_past_tp4, reset_cluster_info, force_open_cluster, check_cluster_result_and_record, reset_bot
from telegram_bot import (
    log, flush_logs, 
    get_bot_control, set_bot_control, check_force_trade, check_reset_score, get_next_score_override,
    check_should_reset_bot
)
from be_manager import check_be

SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_M1

# Nguong diem de mo lenh
BUY_THRESHOLD = 35
SELL_THRESHOLD = 35

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

while True:
    # ========== KIEM TRA COMMANDS TU TELEGRAM ==========
    
    # Kiem tra yeu cau reset bot (khi /start)
    if check_should_reset_bot():
        reset_bot()
        bot_stopped_logged = False  # Reset flag de cho phep log lai neu dung lan nua
        log(">>> BOT DA DUOC RESET (tu /start) <<<")
        flush_logs()
    
    # Kiem tra yeu cau reset score
    if check_reset_score():
        log(">>> RESET SCORE (tu Telegram) <<<")
        accumulated_score = Signal()
        flush_logs()
    
    # Kiem tra trang thai bot
    bot_ctrl = get_bot_control()
    
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
    
    # ========== KIEM TRA BOT DUNG ==========
    
    # Kiem tra bot co bi dung khong (3 lenh lien tiep hoac tu Telegram)
    if is_bot_stopped() or not bot_ctrl['active']:
        if is_bot_stopped() and not bot_stopped_logged:
            log("[MAIN] Bot da dung - 3 lenh lien tiep cung chieu. Dung /start de bat lai.")
            # Sync trang thai voi telegram_bot
            set_bot_control(active=False)
            flush_logs()
            bot_stopped_logged = True
        time.sleep(5)
        continue  # Khong break, cho phep bat lai tu Telegram
    
    # Kiem tra va keo BE neu can
    # check_be()  # TAT BE MANAGER
    
    # Kiem tra cluster vua dong -> mo lenh ngay neu du diem
    cluster_open_now = is_cluster_open(SYMBOL)
    
    # Chi kiem tra huy lenh pending khi cluster dang mo
    if cluster_open_now:
        check_and_cancel_pending_if_past_tp4(SYMBOL, accumulated_score, BUY_THRESHOLD, SELL_THRESHOLD)
    
    if was_cluster_open and not cluster_open_now:
        # Cluster vua dong xong!
        log("[INFO] Cluster vua dong!")
        
        # Kiem tra ket qua cluster (loi/lo) va ghi nhan SL neu can
        check_cluster_result_and_record(SYMBOL)
        
        # Reset thong tin cluster
        reset_cluster_info()
        log("[INFO] Kiem tra mo lenh moi...")
        
        # Kiem tra co du diem khong
        buy_diff = accumulated_score.buy_score - BUY_THRESHOLD
        sell_diff = accumulated_score.sell_score - SELL_THRESHOLD
        
        if buy_diff >= 0 or sell_diff >= 0:
            log(f"[INFO] Du diem! Buy={accumulated_score.buy_score}/{BUY_THRESHOLD}, Sell={accumulated_score.sell_score}/{SELL_THRESHOLD}")
            trade_executed, should_reset = process_trade(SYMBOL, accumulated_score, BUY_THRESHOLD, SELL_THRESHOLD, bot_ctrl)
            if should_reset:
                log(">>> RESET SCORE <<<")
                accumulated_score = Signal()
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
        
        # Hien thi diem dang xx/xx
        log(f"This candle: Buy +{current_signal.buy_score} | Sell +{current_signal.sell_score}")
        log(f"ACCUMULATED: Buy {accumulated_score.buy_score}/{BUY_THRESHOLD} | Sell {accumulated_score.sell_score}/{SELL_THRESHOLD}")
        
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

        # Process trade - tra ve (trade_executed, should_reset)
        trade_executed, should_reset = process_trade(SYMBOL, accumulated_score, BUY_THRESHOLD, SELL_THRESHOLD, bot_ctrl)
        
        # Reset score neu can
        if should_reset:
            log(">>> RESET SCORE <<<")
            accumulated_score = Signal()
            flush_logs()

    time.sleep(2)

# Ket thuc
mt5.shutdown()
log("[MAIN] Chuong trinh ket thuc.")
