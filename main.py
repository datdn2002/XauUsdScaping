import time
import MetaTrader5 as mt5
from strategy import evaluate_signals, Signal
from trade import process_trade

SYMBOL = "XAUUSD"
TIMEFRAME = mt5.TIMEFRAME_H1  # Khung 1 giờ

# ========== KẾT NỐI ==========

if not mt5.initialize():
    print("Không thể kết nối MT5:", mt5.last_error())
    quit()
else:
    print("Đã kết nối MT5 thành công!")
    acc = mt5.account_info()
    print(f"Tài khoản: {acc.login} | Balance: {acc.balance}")

# ========== VÒNG LẶP ==========

last_candle = None

# Điểm tích lũy - chỉ reset khi có quyết định mua/bán
accumulated_score = Signal()

while True:
    rates = mt5.copy_rates_from_pos(SYMBOL, TIMEFRAME, 0, 2)
    if rates is None:
        time.sleep(1)
        continue

    candle_time = rates[-1]['time']

    if last_candle != candle_time:
        last_candle = candle_time
        print("\n=== Nến mới đóng ===")
        
        # Lấy dữ liệu các khung thời gian
        rates_m15 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M15, 1, 100)
        rates_h4 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H4, 1, 100)
        rates_h1 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 1, 150)
        rates_m30 = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_M30, 1, 200)
        
        if rates_m15 is None or rates_h4 is None or rates_h1 is None or rates_m30 is None:
            print("Không lấy được dữ liệu nến")
            time.sleep(1)
            continue

        # Tính điểm nến hiện tại
        current_signal = evaluate_signals(SYMBOL, rates_m15, rates_h4, rates_h1, rates_m30)
        
        # Tích lũy điểm
        accumulated_score.buy_score += current_signal.buy_score
        accumulated_score.sell_score += current_signal.sell_score
        
        print(f"Nến này: Buy +{current_signal.buy_score} | Sell +{current_signal.sell_score}")
        print(f"TÍCH LŨY: Buy = {accumulated_score.buy_score} | Sell = {accumulated_score.sell_score}")

        # Xử lý giao dịch - trả về True nếu có lệnh được mở
        trade_executed = process_trade(SYMBOL, accumulated_score)
        
        # Reset điểm nếu đã vào lệnh
        if trade_executed:
            print(">>> RESET ĐIỂM <<<")
            accumulated_score = Signal()

    time.sleep(2)
