from indicators import calculate_rsi, calculate_ema, calculate_sma
from telegram_bot import log
import math

class Signal:
    """
    Container for buy and sell scores.
    """
    def __init__(self):
        self.buy_score = 0
        self.sell_score = 0
        self.details = []  # Chi tiết các factor đã cộng điểm


# Điểm thủ công (manual bias) - có thể điều chỉnh từ -10 đến +10
MANUAL_BIAS = 0  # 0 = không thiên vị, >0 = thiên buy, <0 = thiên sell


def evaluate_signals(symbol, rates_m15, rates_h4, rates_h1, rates_m30, verbose=True):
    """
    Evaluate trading signals based on the provided historical rates.
    Returns a Signal object with buy_score and sell_score.
    """
    signal = Signal()
    
    # Extract data from rates
    closes_m15 = [bar['close'] if isinstance(bar, dict) else bar[4] for bar in rates_m15]
    highs_m15 = [bar['high'] if isinstance(bar, dict) else bar[2] for bar in rates_m15]
    lows_m15 = [bar['low'] if isinstance(bar, dict) else bar[3] for bar in rates_m15]
    
    closes_h4 = [bar['close'] if isinstance(bar, dict) else bar[4] for bar in rates_h4]
    highs_h4 = [bar['high'] if isinstance(bar, dict) else bar[2] for bar in rates_h4]
    lows_h4 = [bar['low'] if isinstance(bar, dict) else bar[3] for bar in rates_h4]
    
    closes_h1 = [bar['close'] if isinstance(bar, dict) else bar[4] for bar in rates_h1]
    
    closes_m30 = [bar['close'] if isinstance(bar, dict) else bar[4] for bar in rates_m30]
    highs_m30 = [bar['high'] if isinstance(bar, dict) else bar[2] for bar in rates_m30]
    lows_m30 = [bar['low'] if isinstance(bar, dict) else bar[3] for bar in rates_m30]
    
    len_m15 = len(closes_m15)
    len_h4 = len(closes_h4)
    len_h1 = len(closes_h1)
    len_m30 = len(closes_m30)
    
    if len_m15 == 0:
        return signal
    
    current_price = closes_m15[-1]
    i = len_m15 - 1  # Current index
    
    # Calculate RSI array for M15
    RSI = calculate_rsi_array(closes_m15, 14)
    
    # Calculate EMA arrays
    EMA9 = calculate_ema_array(closes_m15, 9)
    EMA21 = calculate_ema_array(closes_m15, 21)
    EMA21_H4 = calculate_ema_array(closes_h4, 21)
    EMA50_H4 = calculate_ema_array(closes_h4, 50)
    EMA100_H1 = calculate_ema_array(closes_h1, 100)
    
    # ========== FACTOR 1: Fibonacci M15 ==========
    if len_m15 >= 100:
        start_idx = len_m15 - 100
        end_idx = len_m15 - 2
        
        window_high = -float('inf')
        window_low = float('inf')
        idx_high = start_idx
        idx_low = start_idx
        
        for k in range(start_idx, end_idx + 1):
            if closes_m15[k] > window_high:
                window_high = closes_m15[k]
                idx_high = k
            if closes_m15[k] < window_low:
                window_low = closes_m15[k]
                idx_low = k
        
        trending_up = idx_high > idx_low
        trending_down = idx_low > idx_high
        range_val = abs(window_high - window_low)
        
        if range_val > 0:
            fib_tol = max(0.1, 0.02 * range_val)
            
            if trending_up:
                A = window_low
                B = window_high
                # Các mức Fib
                fib_levels = {
                    0.236: B - 0.236 * range_val,
                    0.382: B - 0.382 * range_val,
                    1.0: A,
                    0.618: B - 0.618 * range_val,
                    0.786: B - 0.786 * range_val,
                    1.618: A + 1.618 * range_val,
                    2.618: A + 2.618 * range_val,
                }
                # Uptrend Buy
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 2
                        signal.details.append(f"F1: Fib M15 uptrend {lvl} -> Buy +2")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 2
                        signal.details.append(f"F1: Fib M15 uptrend {lvl} -> Buy +2")
                for lvl in [1.618, 2.618]:
                    if current_price >= fib_levels[lvl] - fib_tol:
                        signal.buy_score += 4
                        signal.details.append(f"F1: Fib M15 uptrend ext {lvl} -> Buy +4")
                # Uptrend Sell
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 2
                        signal.details.append(f"F1: Fib M15 uptrend {lvl} -> Sell +2")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 3
                        signal.details.append(f"F1: Fib M15 uptrend {lvl} -> Sell +3")
                for lvl in [1.618, 2.618]:
                    if current_price >= fib_levels[lvl] - fib_tol:
                        signal.sell_score += 5
                        signal.details.append(f"F1: Fib M15 uptrend ext {lvl} -> Sell +5")
            
            elif trending_down:
                A = window_high
                B = window_low
                # Các mức Fib
                fib_levels = {
                    0.236: B + 0.236 * range_val,
                    0.382: B + 0.382 * range_val,
                    1.0: A,
                    0.618: B + 0.618 * range_val,
                    0.786: B + 0.786 * range_val,
                    1.618: B - 0.618 * range_val,
                    2.618: B - 1.618 * range_val,
                }
                # Downtrend Buy
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 2
                        signal.details.append(f"F1: Fib M15 downtrend {lvl} -> Buy +2")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 3
                        signal.details.append(f"F1: Fib M15 downtrend {lvl} -> Buy +3")
                for lvl in [1.618, 2.618]:
                    if current_price <= fib_levels[lvl] + fib_tol:
                        signal.buy_score += 5
                        signal.details.append(f"F1: Fib M15 downtrend ext {lvl} -> Buy +5")
                # Downtrend Sell
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 2
                        signal.details.append(f"F1: Fib M15 downtrend {lvl} -> Sell +2")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 2
                        signal.details.append(f"F1: Fib M15 downtrend {lvl} -> Sell +2")
                for lvl in [1.618, 2.618]:
                    if current_price <= fib_levels[lvl] + fib_tol:
                        signal.sell_score += 4
                        signal.details.append(f"F1: Fib M15 downtrend ext {lvl} -> Sell +4")
    
    # ========== FACTOR 2: Fibonacci H4 ==========
    if len_h4 >= 100:
        start_idx = len_h4 - 100
        end_idx = len_h4 - 2
        
        window_high = -float('inf')
        window_low = float('inf')
        idx_high = start_idx
        idx_low = start_idx
        
        for k in range(start_idx, end_idx + 1):
            if closes_h4[k] > window_high:
                window_high = closes_h4[k]
                idx_high = k
            if closes_h4[k] < window_low:
                window_low = closes_h4[k]
                idx_low = k
        
        trending_up = idx_high > idx_low
        trending_down = idx_low > idx_high
        range_val = abs(window_high - window_low)
        
        if range_val > 0:
            fib_tol = max(0.5, 0.02 * range_val)
            
            if trending_up:
                A = window_low
                B = window_high
                fib_levels = {
                    0.236: B - 0.236 * range_val,
                    0.382: B - 0.382 * range_val,
                    1.0: A,
                    0.618: B - 0.618 * range_val,
                    0.786: B - 0.786 * range_val,
                    1.618: A + 1.618 * range_val,
                    2.618: A + 2.618 * range_val,
                }
                # Uptrend Buy
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 5
                        signal.details.append(f"F2: Fib H4 uptrend {lvl} -> Buy +5")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 7
                        signal.details.append(f"F2: Fib H4 uptrend {lvl} -> Buy +7")
                for lvl in [1.618, 2.618]:
                    if current_price >= fib_levels[lvl] - fib_tol:
                        signal.buy_score += 9
                        signal.details.append(f"F2: Fib H4 uptrend ext {lvl} -> Buy +9")
                # Uptrend Sell
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 7
                        signal.details.append(f"F2: Fib H4 uptrend {lvl} -> Sell +7")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 9
                        signal.details.append(f"F2: Fib H4 uptrend {lvl} -> Sell +9")
                for lvl in [1.618, 2.618]:
                    if current_price >= fib_levels[lvl] - fib_tol:
                        signal.sell_score += 15
                        signal.details.append(f"F2: Fib H4 uptrend ext {lvl} -> Sell +15")
            
            elif trending_down:
                A = window_high
                B = window_low
                fib_levels = {
                    0.236: B + 0.236 * range_val,
                    0.382: B + 0.382 * range_val,
                    1.0: A,
                    0.618: B + 0.618 * range_val,
                    0.786: B + 0.786 * range_val,
                    1.618: B - 0.618 * range_val,
                    2.618: B - 1.618 * range_val,
                }
                # Downtrend Buy
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 7
                        signal.details.append(f"F2: Fib H4 downtrend {lvl} -> Buy +7")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.buy_score += 9
                        signal.details.append(f"F2: Fib H4 downtrend {lvl} -> Buy +9")
                for lvl in [1.618, 2.618]:
                    if current_price <= fib_levels[lvl] + fib_tol:
                        signal.buy_score += 15
                        signal.details.append(f"F2: Fib H4 downtrend ext {lvl} -> Buy +15")
                # Downtrend Sell
                for lvl in [0.236, 0.382, 1.0]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 5
                        signal.details.append(f"F2: Fib H4 downtrend {lvl} -> Sell +5")
                for lvl in [0.618, 0.786]:
                    if abs(current_price - fib_levels[lvl]) <= fib_tol:
                        signal.sell_score += 7
                        signal.details.append(f"F2: Fib H4 downtrend {lvl} -> Sell +7")
                for lvl in [1.618, 2.618]:
                    if current_price <= fib_levels[lvl] + fib_tol:
                        signal.sell_score += 9
                        signal.details.append(f"F2: Fib H4 downtrend ext {lvl} -> Sell +9")
    
    # ========== FACTOR 3: RSI(14) M15 ==========
    if len_m15 >= 15 and RSI[i] is not None:
        rsi_val = RSI[i]
        
        # RSI < 30 (quá bán)
        if rsi_val < 30:
            signal.buy_score += 5
            signal.details.append(f"F3: RSI={rsi_val:.1f} < 30 -> Buy +5")
            
            # 2 đáy RSI
            if i >= 6:
                rsi_window = RSI[max(0, i - 6):i + 1]
                first_low = None
                second_low = None
                for j in range(1, len(rsi_window) - 1):
                    if rsi_window[j] is not None and rsi_window[j-1] is not None and rsi_window[j+1] is not None:
                        if rsi_window[j] < rsi_window[j - 1] and rsi_window[j] < rsi_window[j + 1]:
                            if first_low is None:
                                first_low = {'value': rsi_window[j], 'idx': j}
                            elif second_low is None:
                                second_low = {'value': rsi_window[j], 'idx': j}
                
                if first_low and second_low and second_low['idx'] > first_low['idx'] and second_low['value'] < first_low['value']:
                    signal.buy_score += 7
                    signal.details.append("F3: RSI 2-bottom -> Buy +7")
            
            # RSI < 20 trong 2 nến
            if i >= 1 and RSI[i] < 20 and RSI[i - 1] is not None and RSI[i - 1] < 20:
                signal.buy_score += 10
                signal.details.append("F3: RSI < 20 for 2 candles -> Buy +10")
        
        # RSI > 70 (quá mua)
        if rsi_val > 70:
            signal.sell_score += 3
            signal.details.append(f"F3: RSI={rsi_val:.1f} > 70 -> Sell +3")
            
            # 2 đỉnh RSI
            if i >= 6:
                rsi_window = RSI[max(0, i - 6):i + 1]
                first_high = None
                second_high = None
                for j in range(1, len(rsi_window) - 1):
                    if rsi_window[j] is not None and rsi_window[j-1] is not None and rsi_window[j+1] is not None:
                        if rsi_window[j] > rsi_window[j - 1] and rsi_window[j] > rsi_window[j + 1]:
                            if first_high is None:
                                first_high = {'value': rsi_window[j], 'idx': j}
                            elif second_high is None:
                                second_high = {'value': rsi_window[j], 'idx': j}
                
                if first_high and second_high and second_high['idx'] > first_high['idx'] and second_high['value'] > first_high['value']:
                    signal.sell_score += 5
                    signal.details.append("F3: RSI 2-top -> Sell +5")
            
            # RSI > 80 trong 2 nến
            if i >= 1 and RSI[i] > 80 and RSI[i - 1] is not None and RSI[i - 1] > 80:
                signal.sell_score += 10
                signal.details.append("F3: RSI > 80 for 2 candles -> Sell +10")
    
    # ========== FACTOR 4: Cản tĩnh ngang 100 nến M15 ==========
    if len_m15 >= 100:
        recent_closes = closes_m15[len_m15 - 100:len_m15]
        max_close = max(recent_closes)
        min_close = min(recent_closes)
        tol = 0.5
        
        if abs(current_price - min_close) <= tol:
            signal.buy_score += 5
            signal.details.append("F4: Price at M15 100-low -> Buy +5")
        if abs(current_price - max_close) <= tol:
            signal.sell_score += 5
            signal.details.append("F4: Price at M15 100-high -> Sell +5")
    
    # ========== FACTOR 5: Cản tĩnh ngang 100 nến H4 ==========
    if len_h4 >= 100:
        recent_closes = closes_h4[len_h4 - 100:len_h4]
        max_close = max(recent_closes)
        min_close = min(recent_closes)
        tol = 0.8
        
        if abs(current_price - min_close) <= tol:
            signal.buy_score += 8
            signal.details.append("F5: Price at H4 100-low -> Buy +8")
        if abs(current_price - max_close) <= tol:
            signal.sell_score += 8
            signal.details.append("F5: Price at H4 100-high -> Sell +8")
    
    # ========== FACTOR 6: Cản tĩnh ngang 600 nến H4 ==========
    if len_h4 >= 600:
        recent_closes = closes_h4[len_h4 - 600:len_h4]
        max_close = max(recent_closes)
        min_close = min(recent_closes)
        tol = 2.0
        
        if abs(current_price - min_close) <= tol:
            signal.buy_score += 15
            signal.details.append("F6: Price at H4 600-low -> Buy +15")
        if abs(current_price - max_close) <= tol:
            signal.sell_score += 15
            signal.details.append("F6: Price at H4 600-high -> Sell +15")
    
    # ========== FACTOR 7: Phiên Á, Âu, Mỹ ==========
    if len_m15 >= 192:
        bars_per_day = 96
        prev_day_start = len_m15 - 192
        
        asia_start = prev_day_start
        asia_end = prev_day_start + 31
        euro_start = prev_day_start + 32
        euro_end = prev_day_start + 63
        us_start = prev_day_start + 64
        us_end = prev_day_start + 95
        
        asia_high = max(highs_m15[asia_start:asia_end + 1])
        asia_low = min(lows_m15[asia_start:asia_end + 1])
        euro_high = max(highs_m15[euro_start:euro_end + 1])
        euro_low = min(lows_m15[euro_start:euro_end + 1])
        us_high = max(highs_m15[us_start:us_end + 1])
        us_low = min(lows_m15[us_start:us_end + 1])
        
        # Asia
        if current_price >= asia_high:
            signal.buy_score += 5
            signal.sell_score += 3
            signal.details.append("F7: Price >= Asia high -> Buy +5, Sell +3")
        if current_price <= asia_low:
            signal.buy_score += 3
            signal.sell_score += 5
            signal.details.append("F7: Price <= Asia low -> Buy +3, Sell +5")
        
        # Europe
        if current_price >= euro_high:
            signal.buy_score += 7
            signal.sell_score += 5
            signal.details.append("F7: Price >= Euro high -> Buy +7, Sell +5")
        if current_price <= euro_low:
            signal.buy_score += 5
            signal.sell_score += 7
            signal.details.append("F7: Price <= Euro low -> Buy +5, Sell +7")
        
        # US
        if current_price >= us_high:
            signal.buy_score += 9
            signal.sell_score += 7
            signal.details.append("F7: Price >= US high -> Buy +9, Sell +7")
        if current_price <= us_low:
            signal.buy_score += 7
            signal.sell_score += 9
            signal.details.append("F7: Price <= US low -> Buy +7, Sell +9")
    
    # ========== FACTOR 8: Kênh giá 200 nến M30 ==========
    if len_m30 >= 200:
        start = len_m30 - 200
        end = len_m30 - 1
        n = end - start + 1
        
        sum_x = sum(range(n))
        sum_y = sum(closes_m30[start:end + 1])
        sum_xy = sum(x * closes_m30[start + x] for x in range(n))
        sum_x2 = sum(x * x for x in range(n))
        
        slope = (n * sum_xy - sum_x * sum_y) / (n * sum_x2 - sum_x * sum_x)
        intercept = (sum_y - slope * sum_x) / n
        
        max_dev_above = 0
        max_dev_below = 0
        for j in range(start, end + 1):
            x = j - start
            expected = intercept + slope * x
            dev_above = highs_m30[j] - expected
            dev_below = expected - lows_m30[j]
            if dev_above > max_dev_above:
                max_dev_above = dev_above
            if dev_below > max_dev_below:
                max_dev_below = dev_below
        
        x_curr = end - start
        mid_curr = intercept + slope * x_curr
        top_line = mid_curr + max_dev_above
        bottom_line = mid_curr - max_dev_below
        tol = 0.001 * mid_curr
        
        # Xác định loại kênh
        if slope > 0.0001:
            channel_type = "uptrend"
        elif slope < -0.0001:
            channel_type = "downtrend"
        else:
            channel_type = "sideway"
        
        # Chạm biên dưới
        if current_price <= bottom_line + tol:
            if channel_type == "uptrend":
                signal.buy_score += 10
                signal.details.append("F8: Channel uptrend lower -> Buy +10")
            else:
                signal.buy_score += 5
                signal.details.append(f"F8: Channel {channel_type} lower -> Buy +5")
        
        # Chạm biên trên
        if current_price >= top_line - tol:
            if channel_type == "downtrend":
                signal.sell_score += 10
                signal.details.append("F8: Channel downtrend upper -> Sell +10")
            else:
                signal.sell_score += 5
                signal.details.append(f"F8: Channel {channel_type} upper -> Sell +5")
    
    # ========== FACTOR 9: Tam giác giảm (break up) ==========
    if len_m30 >= 100:
        start = len_m30 - 100
        mid = start + 49
        end = len_m30 - 1
        
        high1 = max(highs_m30[start:mid + 1])
        high2 = max(highs_m30[mid + 1:end + 1])
        low1 = min(lows_m30[start:mid + 1])
        low2 = min(lows_m30[mid + 1:end + 1])
        
        # Tam giác giảm: cạnh dưới ngang, cạnh trên giảm
        if abs(low2 - low1) < 1 and high2 < high1:
            bottom_line = (low1 + low2) / 2
            slope_top = (high2 - high1) / 50
            top_line_current = high1 + slope_top * (end - start)
            tol = 0.5
            
            m30_idx = end - start
            is_first_half = m30_idx < 50
            
            if abs(current_price - bottom_line) <= tol:
                if is_first_half:
                    signal.buy_score += 4
                    signal.details.append("F9: Triangle down, first half -> Buy +4")
                else:
                    signal.buy_score += 7
                    signal.details.append("F9: Triangle down, second half -> Buy +7")
            
            if abs(current_price - top_line_current) <= tol and is_first_half:
                signal.sell_score += 2
                signal.details.append("F9: Triangle down, top first half -> Sell +2")
            
            # Breakout + retest
            if len_m30 >= 2:
                prev_close = closes_m30[-2]
                if prev_close < top_line_current and current_price > top_line_current:
                    if lows_m30[-1] <= top_line_current + tol:
                        signal.buy_score += 9
                        signal.details.append("F9: Triangle breakout + retest -> Buy +9")
    
    # ========== FACTOR 10: Tam giác tăng (break down) ==========
    if len_m30 >= 100:
        start = len_m30 - 100
        mid = start + 49
        end = len_m30 - 1
        
        high1 = max(highs_m30[start:mid + 1])
        high2 = max(highs_m30[mid + 1:end + 1])
        low1 = min(lows_m30[start:mid + 1])
        low2 = min(lows_m30[mid + 1:end + 1])
        
        # Tam giác tăng: cạnh trên ngang, cạnh dưới tăng
        if abs(high2 - high1) < 1 and low2 > low1:
            top_line = (high1 + high2) / 2
            slope_bottom = (low2 - low1) / 50
            bottom_line_current = low1 + slope_bottom * (end - start)
            tol = 0.5
            
            m30_idx = end - start
            is_first_half = m30_idx < 50
            
            if abs(current_price - top_line) <= tol:
                if is_first_half:
                    signal.sell_score += 4
                    signal.details.append("F10: Triangle up, first half -> Sell +4")
                else:
                    signal.sell_score += 7
                    signal.details.append("F10: Triangle up, second half -> Sell +7")
            
            if abs(current_price - bottom_line_current) <= tol and is_first_half:
                signal.buy_score += 2
                signal.details.append("F10: Triangle up, bottom first half -> Buy +2")
            
            # Breakdown + retest
            if len_m30 >= 2:
                prev_close = closes_m30[-2]
                if prev_close > bottom_line_current and current_price < bottom_line_current:
                    if highs_m30[-1] >= bottom_line_current - tol:
                        signal.sell_score += 9
                        signal.details.append("F10: Triangle breakdown + retest -> Sell +9")
    
    # ========== FACTOR 11: EMA9 cắt EMA21 (M15) ==========
    if len_m15 >= 22 and i >= 1:
        if EMA9[i-1] is not None and EMA21[i-1] is not None and EMA9[i] is not None and EMA21[i] is not None:
            prev_diff = EMA9[i - 1] - EMA21[i - 1]
            curr_diff = EMA9[i] - EMA21[i]
            
            if prev_diff < 0 and curr_diff > 0:
                signal.buy_score += 7
                signal.details.append("F11: EMA9 cross up EMA21 (M15) -> Buy +7")
            if prev_diff > 0 and curr_diff < 0:
                signal.sell_score += 7
                signal.details.append("F11: EMA9 cross down EMA21 (M15) -> Sell +7")
    
    # ========== FACTOR 12: EMA21 cắt EMA50 (H4) ==========
    if len_h4 >= 51:
        h4_idx = len_h4 - 1
        if h4_idx >= 1 and EMA21_H4[h4_idx-1] is not None and EMA50_H4[h4_idx-1] is not None:
            if EMA21_H4[h4_idx - 1] < EMA50_H4[h4_idx - 1] and EMA21_H4[h4_idx] > EMA50_H4[h4_idx]:
                signal.buy_score += 5
                signal.details.append("F12: EMA21 cross up EMA50 (H4) -> Buy +5")
            if EMA21_H4[h4_idx - 1] > EMA50_H4[h4_idx - 1] and EMA21_H4[h4_idx] < EMA50_H4[h4_idx]:
                signal.sell_score += 5
                signal.details.append("F12: EMA21 cross down EMA50 (H4) -> Sell +5")
    
    # ========== FACTOR 13: EMA100 H1 (giá > EMA100 trong 3 nến & > 10 điểm) ==========
    if len_h1 >= 103:
        h1_idx = len_h1 - 1
        if EMA100_H1[h1_idx] is not None and EMA100_H1[h1_idx-1] is not None and EMA100_H1[h1_idx-2] is not None:
            ema_val = EMA100_H1[h1_idx]
            diff = abs(current_price - ema_val)
            
            # Kiểm tra 3 nến liên tục
            above_3_candles = (closes_h1[-1] > EMA100_H1[-1] and 
                              closes_h1[-2] > EMA100_H1[-2] and 
                              closes_h1[-3] > EMA100_H1[-3])
            below_3_candles = (closes_h1[-1] < EMA100_H1[-1] and 
                              closes_h1[-2] < EMA100_H1[-2] and 
                              closes_h1[-3] < EMA100_H1[-3])
            
            if above_3_candles and diff >= 1.0:  # > 10 points = 1.0 USD
                signal.buy_score += 5
                signal.details.append(f"F13: Price > EMA100(H1) 3 candles, diff={diff:.1f} -> Buy +5")
            elif below_3_candles and diff >= 1.0:
                signal.sell_score += 5
                signal.details.append(f"F13: Price < EMA100(H1) 3 candles, diff={diff:.1f} -> Sell +5")
    
    # ========== FACTOR 14: SMA25 H4 (khoảng cách) ==========
    if len_h4 >= 25:
        sma25 = calculate_sma(closes_h4, 25)
        if sma25 is not None:
            diff = current_price - sma25
            
            if diff < 0:  # Giá dưới SMA25
                if abs(diff) >= 10:  # >= 100 pips = 10 USD
                    signal.buy_score += 10
                    signal.details.append(f"F14: Price below SMA25(H4) {abs(diff):.1f}$ -> Buy +10")
                elif abs(diff) >= 6:  # >= 60 pips
                    signal.buy_score += 5
                    signal.details.append(f"F14: Price below SMA25(H4) {abs(diff):.1f}$ -> Buy +5")
            else:  # Giá trên SMA25
                if diff >= 10:
                    signal.sell_score += 10
                    signal.details.append(f"F14: Price above SMA25(H4) {diff:.1f}$ -> Sell +10")
                elif diff >= 6:
                    signal.sell_score += 5
                    signal.details.append(f"F14: Price above SMA25(H4) {diff:.1f}$ -> Sell +5")
    
    # ========== FACTOR 15: Manual Bias ==========
    if MANUAL_BIAS > 0:
        signal.buy_score += min(MANUAL_BIAS, 10)
        signal.details.append(f"F15: Manual bias -> Buy +{min(MANUAL_BIAS, 10)}")
    elif MANUAL_BIAS < 0:
        signal.sell_score += min(abs(MANUAL_BIAS), 10)
        signal.details.append(f"F15: Manual bias -> Sell +{min(abs(MANUAL_BIAS), 10)}")
    
    # In chi tiết nếu có điểm
    if verbose and signal.details:
        log("  [Score details]:")
        for detail in signal.details:
            log(f"    - {detail}")
    
    return signal


def calculate_rsi_array(prices, period=14):
    """Calculate RSI array for all prices."""
    length = len(prices)
    rsi = [None] * length
    
    if length < period + 1:
        return rsi
    
    gain_sum = 0
    loss_sum = 0
    for k in range(1, period + 1):
        diff = prices[k] - prices[k - 1]
        if diff >= 0:
            gain_sum += diff
        else:
            loss_sum += -diff
    
    avg_gain = gain_sum / period
    avg_loss = loss_sum / period
    
    if avg_loss == 0:
        rsi[period] = 100
    elif avg_gain == 0:
        rsi[period] = 0
    else:
        rsi[period] = 100 - 100 / (1 + avg_gain / avg_loss)
    
    for i in range(period + 1, length):
        diff = prices[i] - prices[i - 1]
        gain = diff if diff > 0 else 0
        loss = -diff if diff < 0 else 0
        
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        
        if avg_loss == 0:
            rsi[i] = 100
        elif avg_gain == 0:
            rsi[i] = 0
        else:
            rsi[i] = 100 - 100 / (1 + avg_gain / avg_loss)
    
    return rsi


def calculate_ema_array(prices, period):
    """Calculate EMA array for all prices."""
    length = len(prices)
    if length == 0:
        return []
    
    ema = [None] * length
    alpha = 2 / (period + 1)
    
    ema[0] = prices[0]
    for i in range(1, length):
        ema[i] = ema[i - 1] + alpha * (prices[i] - ema[i - 1])
    
    return ema
