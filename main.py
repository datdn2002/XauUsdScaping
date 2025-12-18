import time
import MetaTrader5 as mt5
from strategy import evaluate_signals, Signal
from trade import process_trade, is_bot_stopped, is_cluster_open
from telegram_bot import log, flush_logs
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

while True:
    # Kiem tra bot co bi dung khong (3 SL lien tiep)
    if is_bot_stopped():
        log("[MAIN] Bot da dung - 3 SL lien tiep. Thoat chuong trinh.")
        flush_logs()
        break
    
    # Kiem tra va keo BE neu can
    # check_be()  # TAT BE MANAGER
    
    # Kiem tra cluster vua dong -> mo lenh ngay neu du diem
    cluster_open_now = is_cluster_open(SYMBOL)
    if was_cluster_open and not cluster_open_now:
        # Cluster vua dong xong!
        log("[INFO] Cluster vua dong - kiem tra mo lenh ngay...")
        
        # Kiem tra co du diem khong
        buy_diff = accumulated_score.buy_score - BUY_THRESHOLD
        sell_diff = accumulated_score.sell_score - SELL_THRESHOLD
        
        if buy_diff >= 0 or sell_diff >= 0:
            log(f"[INFO] Du diem! Buy={accumulated_score.buy_score}, Sell={accumulated_score.sell_score}")
            trade_executed, should_reset = process_trade(SYMBOL, accumulated_score, BUY_THRESHOLD, SELL_THRESHOLD)
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
        
        log(f"This candle: Buy +{current_signal.buy_score} | Sell +{current_signal.sell_score}")
        log(f"ACCUMULATED: Buy = {accumulated_score.buy_score} | Sell = {accumulated_score.sell_score}")
        
        # Hien thi trang thai cluster
        if is_cluster_open(SYMBOL):
            log("[INFO] Cluster dang mo - chua mo lenh moi")

        # Process trade - tra ve (trade_executed, should_reset)
        trade_executed, should_reset = process_trade(SYMBOL, accumulated_score, BUY_THRESHOLD, SELL_THRESHOLD)
        
        # Reset score neu can
        if should_reset:
            log(">>> RESET SCORE <<<")
            accumulated_score = Signal()
            flush_logs()

    time.sleep(2)

# Ket thuc
mt5.shutdown()
log("[MAIN] Chuong trinh ket thuc.")
