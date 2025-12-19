import MetaTrader5 as mt5
import time
from telegram_bot import log, flush_logs

# Global TradeManager instance
_trade_manager = None

# Theo doi SL lien tiep cung chieu
_consecutive_sl = {
    'buy': 0,
    'sell': 0,
    'last_direction': None
}

# Trang thai bot
_bot_stopped = False

# Luu thoi gian mo cluster va TP4
_cluster_info = {
    'open_time': None,
    'direction': None,
    'tp4_price': None,
    'entry_price': None  # Gia vao ET1
}

# Thoi gian timeout cluster (6 tieng = 21600 giay)
CLUSTER_TIMEOUT_SECONDS = 6 * 60 * 60


def is_cluster_open(symbol="XAUUSD"):
    """Kiem tra co cluster nao dang mo khong"""
    magic_numbers = [1001, 1002, 1003, 1004]
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        return False
    
    for pos in positions:
        if pos.magic in magic_numbers:
            return True
    return False


def get_current_cluster_direction(symbol="XAUUSD"):
    """Lay huong cua cluster dang mo (buy/sell/None)"""
    magic_numbers = [1001, 1002, 1003, 1004]
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        return None
    
    for pos in positions:
        if pos.magic in magic_numbers:
            if pos.type == mt5.POSITION_TYPE_BUY:
                return 'buy'
            else:
                return 'sell'
    return None


def record_cluster_result(direction, is_profit):
    """
    Ghi nhan ket qua cluster (loi/lo).
    Neu SL 3 lan lien tiep cung chieu -> dung bot.
    """
    global _consecutive_sl, _bot_stopped
    
    if is_profit:
        # Co loi -> reset dem SL
        _consecutive_sl['buy'] = 0
        _consecutive_sl['sell'] = 0
        _consecutive_sl['last_direction'] = None
        log(f"[TRADE] Cluster {direction.upper()} co loi - reset SL counter")
    else:
        # Lo -> dem SL
        if direction == _consecutive_sl['last_direction']:
            _consecutive_sl[direction] += 1
        else:
            # Doi chieu -> reset chieu cu, bat dau dem chieu moi
            _consecutive_sl['buy'] = 0
            _consecutive_sl['sell'] = 0
            _consecutive_sl[direction] = 1
        
        _consecutive_sl['last_direction'] = direction
        
        log(f"[TRADE] Cluster {direction.upper()} SL - dem: {_consecutive_sl[direction]}/3")
        
        # Kiem tra 3 lan lien tiep
        if _consecutive_sl[direction] >= 3:
            _bot_stopped = True
            log(f"[TRADE] !!! BOT DUNG LAI - 3 lan SL lien tiep chieu {direction.upper()} !!!")
            flush_logs()


def is_bot_stopped():
    """Kiem tra bot co bi dung khong"""
    return _bot_stopped


def is_cluster_timeout(symbol="XAUUSD"):
    """
    Kiem tra cluster da mo qua 6 tieng chua.
    Neu qua 6 tieng -> cho phep mo cluster moi.
    """
    global _cluster_info
    
    if _cluster_info['open_time'] is None:
        return False
    
    elapsed = time.time() - _cluster_info['open_time']
    if elapsed > CLUSTER_TIMEOUT_SECONDS:
        hours = elapsed / 3600
        log(f"[TIMEOUT] Cluster da mo {hours:.1f} tieng - cho phep mo moi")
        return True
    return False


def check_and_cancel_pending_if_past_tp4(symbol="XAUUSD", accumulated_score=None, buy_threshold=35, sell_threshold=35):
    """
    Kiem tra neu gia vot qua TP4 -> huy tat ca lenh limit va refund 50% diem.
    
    Returns: True neu da huy lenh, False neu khong
    """
    global _cluster_info
    
    if _cluster_info['tp4_price'] is None or _cluster_info['direction'] is None:
        return False
    
    # Lay gia hien tai
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        return False
    
    current_price = tick.bid if _cluster_info['direction'] == 'sell' else tick.ask
    tp4 = _cluster_info['tp4_price']
    direction = _cluster_info['direction']
    
    # Kiem tra gia da vot qua TP4 chua
    past_tp4 = False
    if direction == 'buy' and current_price > tp4:
        past_tp4 = True
    elif direction == 'sell' and current_price < tp4:
        past_tp4 = True
    
    if not past_tp4:
        return False
    
    log(f"[CANCEL] Gia hien tai {current_price} da vot qua TP4={tp4}")
    
    # Lay tat ca lenh pending
    orders = mt5.orders_get(symbol=symbol)
    if orders is None or len(orders) == 0:
        log("[CANCEL] Khong co lenh pending nao de huy")
        return False
    
    magic_numbers = [1001, 1002, 1003, 1004]
    cancelled_count = 0
    
    for order in orders:
        if order.magic in magic_numbers:
            # Huy lenh
            cancel_request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
            }
            result = mt5.order_send(cancel_request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log(f"[CANCEL] Da huy lenh #{order.ticket} (ET{order.magic-1000})")
                cancelled_count += 1
            else:
                error = result.comment if result else "No response"
                log(f"[CANCEL] Loi huy lenh #{order.ticket}: {error}")
    
    if cancelled_count > 0:
        # Refund 50% diem
        if accumulated_score is not None:
            if direction == 'buy':
                refund = buy_threshold // 2
                accumulated_score.buy_score += refund
                log(f"[REFUND] Cong tra {refund} diem cho BUY -> Tong: {accumulated_score.buy_score}")
            else:
                refund = sell_threshold // 2
                accumulated_score.sell_score += refund
                log(f"[REFUND] Cong tra {refund} diem cho SELL -> Tong: {accumulated_score.sell_score}")
        
        # Reset cluster info
        _cluster_info['open_time'] = None
        _cluster_info['direction'] = None
        _cluster_info['tp4_price'] = None
        _cluster_info['entry_price'] = None
        
        flush_logs()
        return True
    
    return False


def reset_bot():
    """Reset bot de chay lai"""
    global _bot_stopped, _consecutive_sl
    _bot_stopped = False
    _consecutive_sl = {'buy': 0, 'sell': 0, 'last_direction': None}
    log("[TRADE] Bot da duoc reset")


def process_trade(symbol, signal, buy_threshold=35, sell_threshold=35):
    """
    Process trading signal and execute trades if conditions are met.
    
    - Khong mo de lenh neu con cluster dang mo (tru khi da qua 6 tieng)
    - So sanh hieu diem khi ca 2 chieu deu du diem
    - Ngat bot sau 3 SL lien tiep cung chieu
    
    Returns: (trade_executed, should_reset_score)
    """
    global _trade_manager, _cluster_info
    
    # Kiem tra bot co bi dung khong
    if _bot_stopped:
        return False, False
    
    # Initialize TradeManager if not already done
    if _trade_manager is None:
        account_info = mt5.account_info()
        if account_info is None:
            log("Failed to get account info")
            return False, False
        _trade_manager = TradeManager(account_info.balance)
        _trade_manager.symbol = symbol
    
    # Kiem tra co cluster dang mo khong
    cluster_open = is_cluster_open(symbol)
    cluster_timed_out = is_cluster_timeout(symbol)
    
    if cluster_open and not cluster_timed_out:
        # Dang co cluster mo va chua timeout -> khong mo de, tiep tuc tich luy
        return False, False
    
    # Neu cluster da timeout -> reset cluster info de cho phep mo moi
    if cluster_open and cluster_timed_out:
        log("[TIMEOUT] Cluster cu da qua 6 tieng - cho phep mo cluster moi")
        _cluster_info['open_time'] = None
        _cluster_info['direction'] = None
        _cluster_info['tp4_price'] = None
        _cluster_info['entry_price'] = None
    
    # Tinh hieu diem
    buy_excess = signal.buy_score - buy_threshold if signal.buy_score >= buy_threshold else -999
    sell_excess = signal.sell_score - sell_threshold if signal.sell_score >= sell_threshold else -999
    
    # Neu ca 2 chieu deu chua du diem
    if buy_excess < 0 and sell_excess < 0:
        return False, False
    
    # Chon chieu co hieu diem cao hon
    if buy_excess >= sell_excess:
        # Mo BUY
        log(f"Signal to BUY detected (excess: {buy_excess} vs {sell_excess})")
        entry_price, tp4_price = _trade_manager.open_buy_cluster()
        
        # Luu thong tin cluster
        _cluster_info['open_time'] = time.time()
        _cluster_info['direction'] = 'buy'
        _cluster_info['tp4_price'] = tp4_price
        _cluster_info['entry_price'] = entry_price
        
        flush_logs()
        return True, True
    else:
        # Mo SELL
        log(f"Signal to SELL detected (excess: {sell_excess} vs {buy_excess})")
        entry_price, tp4_price = _trade_manager.open_sell_cluster()
        
        # Luu thong tin cluster
        _cluster_info['open_time'] = time.time()
        _cluster_info['direction'] = 'sell'
        _cluster_info['tp4_price'] = tp4_price
        _cluster_info['entry_price'] = entry_price
        
        flush_logs()
        return True, True


class TradeManager:
    """
    Handles opening clusters of orders (ET1-ET4) for buy or sell.
    """
    def __init__(self, initial_nav):
        self.initial_nav = initial_nav
        self.symbol = "XAUUSD"
        self.risk_percent = 0.01  # 1% NAV
        
        # Khoang cach USD cho ET2, ET3, ET4
        self.et_offsets_usd = [0, 0.5, 1, 1.5]
        
        # SL/TP cho tung ET (USD)
        self.sl_usd = [9, 10, 11, 12]
        self.tp_usd = [3, 5, 10, 15]
        
        # Phan bo risk: 20%, 20%, 40%, 20%
        self.risk_allocation = [0.20, 0.20, 0.40, 0.20]
        
    def get_symbol_info(self):
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            return None, None, None, None
        
        min_lot = symbol_info.volume_min
        lot_step = symbol_info.volume_step
        stop_level = symbol_info.trade_stops_level
        point = symbol_info.point
        
        return min_lot, lot_step, stop_level, point
        
    def calculate_lots(self):
        min_lot, lot_step, _, _ = self.get_symbol_info()
        if min_lot is None:
            return 0.01, 0.01, 0.02, 0.01
        
        total_risk = self.initial_nav * self.risk_percent
        usd_per_lot = 100
        
        lots = []
        total_actual_risk = 0
        
        for i in range(4):
            allocated_risk = total_risk * self.risk_allocation[i]
            raw_lot = allocated_risk / (self.sl_usd[i] * usd_per_lot)
            lot = max(min_lot, round(raw_lot / lot_step) * lot_step)
            lots.append(lot)
            
            actual_risk = lot * self.sl_usd[i] * usd_per_lot
            total_actual_risk += actual_risk
        
        log(f"  Risk NAV = ${total_risk:.2f}")
        log(f"  Lots: ET1={lots[0]:.2f}, ET2={lots[1]:.2f}, ET3={lots[2]:.2f}, ET4={lots[3]:.2f}")
        log(f"  Total risk: ${total_actual_risk:.2f} ({total_actual_risk/self.initial_nav*100:.2f}% NAV)")
        
        return lots[0], lots[1], lots[2], lots[3]

    def open_buy_cluster(self):
        """
        Mo cluster BUY.
        Returns: (entry_price_et1, tp4_price)
        """
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            log("Failed to get symbol tick info")
            return None, None
        
        price_ask = tick.ask
        price_bid = tick.bid
        lots = self.calculate_lots()
        
        _, _, stop_level, point = self.get_symbol_info()
        min_distance = max(stop_level * point if stop_level else 0, 0.5)
        
        log(f"BUY Cluster @ Ask={price_ask}, Bid={price_bid}")
        
        entry_price_et1 = price_ask
        tp4_price = None
        
        for i in range(4):
            lot = lots[i]
            offset = self.et_offsets_usd[i]
            sl_distance = max(self.sl_usd[i], min_distance + 0.1)
            tp_distance = max(self.tp_usd[i], min_distance + 0.1)
            
            if i == 0:
                entry_price = price_ask
                order_type = mt5.ORDER_TYPE_BUY
                action = mt5.TRADE_ACTION_DEAL
            else:
                entry_price = round(price_bid - offset, 2)
                order_type = mt5.ORDER_TYPE_BUY_LIMIT
                action = mt5.TRADE_ACTION_PENDING
            
            sl = round(entry_price - sl_distance, 2)
            tp = round(entry_price + tp_distance, 2)
            
            # Luu TP4 (ET4)
            if i == 3:
                tp4_price = tp
            
            request = {
                "action": action,
                "symbol": self.symbol,
                "volume": lot,
                "type": order_type,
                "price": entry_price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": 1001 + i,
                "comment": f"ET{i+1} BUY",
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            result = mt5.order_send(request)
            
            order_type_str = "Market" if i == 0 else "Limit"
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log(f"  [OK] ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                log(f"  [OK] ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            else:
                error = result.comment if result else "No response"
                retcode = result.retcode if result else "N/A"
                log(f"  [X] ET{i+1} ({order_type_str}): FAILED @ {entry_price} | Code={retcode} | {error}")
        
        return entry_price_et1, tp4_price

    def open_sell_cluster(self):
        """
        Mo cluster SELL.
        Returns: (entry_price_et1, tp4_price)
        """
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            log("Failed to get symbol tick info")
            return None, None
        
        price_bid = tick.bid
        price_ask = tick.ask
        lots = self.calculate_lots()
        
        _, _, stop_level, point = self.get_symbol_info()
        min_distance = max(stop_level * point if stop_level else 0, 0.5)
        
        log(f"SELL Cluster @ Bid={price_bid}, Ask={price_ask}")
        
        entry_price_et1 = price_bid
        tp4_price = None
        
        for i in range(4):
            lot = lots[i]
            offset = self.et_offsets_usd[i]
            sl_distance = max(self.sl_usd[i], min_distance + 0.1)
            tp_distance = max(self.tp_usd[i], min_distance + 0.1)
            
            if i == 0:
                entry_price = price_bid
                order_type = mt5.ORDER_TYPE_SELL
                action = mt5.TRADE_ACTION_DEAL
            else:
                entry_price = round(price_ask + offset, 2)
                order_type = mt5.ORDER_TYPE_SELL_LIMIT
                action = mt5.TRADE_ACTION_PENDING
            
            sl = round(entry_price + sl_distance, 2)
            tp = round(entry_price - tp_distance, 2)
            
            # Luu TP4 (ET4)
            if i == 3:
                tp4_price = tp
            
            request = {
                "action": action,
                "symbol": self.symbol,
                "volume": lot,
                "type": order_type,
                "price": entry_price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": 1001 + i,
                "comment": f"ET{i+1} SELL",
                "type_filling": mt5.ORDER_FILLING_IOC,
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            result = mt5.order_send(request)
            
            order_type_str = "Market" if i == 0 else "Limit"
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log(f"  [OK] ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                log(f"  [OK] ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            else:
                error = result.comment if result else "No response"
                retcode = result.retcode if result else "N/A"
                log(f"  [X] ET{i+1} ({order_type_str}): FAILED @ {entry_price} | Code={retcode} | {error}")
        
        return entry_price_et1, tp4_price
