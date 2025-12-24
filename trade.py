import MetaTrader5 as mt5
import time
from telegram_bot import log, flush_logs

# Global TradeManager instance
_trade_manager = None

# Theo doi so lan Stop Loss lien tiep
_consecutive_sl = {
    'count': 0  # So lan SL lien tiep (reset khi co TP)
}

# Trang thai bot
_bot_stopped = False

# Gioi han so lan SL lien tiep truoc khi dung bot
MAX_CONSECUTIVE_SL = 3

# Luu thoi gian mo cluster va TP4
_cluster_info = {
    'open_time': None,
    'direction': None,
    'tp4_price': None,
    'entry_price': None  # Gia vao ET1
}

# Luu ticket ID cua cac ET khi mo cluster
_cluster_tickets = {
    'et1': None,  # Market order - position ticket
    'et2': None,  # Pending order ticket (se chuyen thanh position khi khop)
    'et3': None,
    'et4': None,
    'open_time': None  # Thoi gian mo cluster de loc deal history
}

# Thoi gian timeout cluster (6 tieng = 21600 giay)
CLUSTER_TIMEOUT_SECONDS = 6 * 60 * 60


def is_cluster_open(symbol="XAUUSD"):
    """Kiem tra co cluster nao dang mo khong (positions hoac pending orders)"""
    magic_numbers = [1001, 1002, 1003, 1004]
    
    # Check positions dang mo
    positions = mt5.positions_get(symbol=symbol)
    if positions:
        for pos in positions:
            if pos.magic in magic_numbers:
                return True
    
    # Check pending orders
    orders = mt5.orders_get(symbol=symbol)
    if orders:
        for order in orders:
            if order.magic in magic_numbers:
                return True
    
    return False


def reset_cluster_info():
    """Reset thong tin cluster khi cluster dong het"""
    global _cluster_info, _cluster_tickets
    _cluster_info['open_time'] = None
    _cluster_info['direction'] = None
    _cluster_info['tp4_price'] = None
    _cluster_info['entry_price'] = None
    # Reset tickets
    _cluster_tickets['et1'] = None
    _cluster_tickets['et2'] = None
    _cluster_tickets['et3'] = None
    _cluster_tickets['et4'] = None
    _cluster_tickets['open_time'] = None


def get_cluster_tickets():
    """Lay danh sach ticket cua cluster hien tai"""
    return _cluster_tickets.copy()


def get_cluster_profit_from_history():
    """
    Tinh tong profit cua cluster tu lich su deals.
    Chi tinh nhung deals thuoc cluster hien tai (theo thoi gian mo).
    """
    from datetime import datetime, timedelta
    
    open_time = _cluster_tickets.get('open_time')
    if not open_time:
        return 0.0
    
    # Lay lich su deals tu thoi diem mo cluster
    now = datetime.now()
    
    # Tim deals theo magic numbers
    magic_numbers = [1001, 1002, 1003, 1004]
    total_profit = 0.0
    deals_found = 0
    
    deals = mt5.history_deals_get(open_time, now)
    if deals:
        for deal in deals:
            # Chi lay deals OUT (dong lenh) va magic phu hop
            if deal.magic in magic_numbers and deal.entry == mt5.DEAL_ENTRY_OUT:
                profit = deal.profit + deal.commission + deal.swap
                total_profit += profit
                deals_found += 1
    
    return total_profit, deals_found


def check_cluster_result_and_record(symbol="XAUUSD"):
    """
    Kiem tra ket qua cluster vua dong va ghi nhan SL neu can.
    Goi ham nay khi phat hien cluster vua dong.
    
    Returns: (direction, is_profit, total_profit)
    """
    from datetime import datetime, timedelta
    
    # Lay huong va thoi gian mo cluster truoc khi reset
    direction = _cluster_info.get('direction')
    cluster_open_time = _cluster_info.get('open_time')
    
    if not direction:
        return None, None, 0
    
    # Lay lich su deals
    now = datetime.now()
    from_date = now - timedelta(days=1)
    
    deals = mt5.history_deals_get(from_date, now)
    if deals is None:
        log("[SL_CHECK] Khong lay duoc history deals")
        return direction, False, 0
    
    # Loc deals cua cluster (magic 1001-1004)
    magic_numbers = [1001, 1002, 1003, 1004]
    cluster_deals = [d for d in deals 
                     if d.magic in magic_numbers 
                     and d.symbol == symbol
                     and d.entry == mt5.DEAL_ENTRY_OUT]  # Chi lay deals dong lenh
    
    if not cluster_deals:
        log("[SL_CHECK] Khong tim thay deals dong cua cluster")
        return direction, False, 0
    
    # Chi lay deals SAU KHI cluster nay mo
    if cluster_open_time:
        recent_deals = [d for d in cluster_deals 
                        if d.time >= cluster_open_time]
    else:
        # Fallback: lay 4 deals gan nhat (1 cluster co toi da 4 ET)
        recent_deals = sorted(cluster_deals, key=lambda d: d.time, reverse=True)[:4]
    
    if not recent_deals:
        log("[SL_CHECK] Khong co deals nao cua cluster nay")
        return direction, False, 0
    
    # Tinh tong profit cua cluster nay
    total_profit = sum(d.profit for d in recent_deals)
    is_profit = total_profit > 0
    
    log(f"[SL_CHECK] Cluster {direction.upper()} dong: {len(recent_deals)} deals, profit=${total_profit:.2f}")
    
    # Ghi nhan ket qua (va check 3 SL lien tiep)
    record_cluster_result(direction, is_profit, total_profit)
    
    return direction, is_profit, total_profit


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


def record_trade_opened(direction):
    """
    Ghi nhan khi mo lenh moi (chi log, khong anh huong counter).
    """
    log(f"[TRADE] Mo lenh {direction.upper()}")


def record_cluster_result(direction, is_profit, total_profit=0):
    """
    Ghi nhan ket qua cluster (loi/lo).
    Neu 3 lan SL (profit < 0) lien tiep -> dung bot.
    """
    global _consecutive_sl, _bot_stopped
    
    if is_profit:
        # Chot loi -> reset counter
        _consecutive_sl['count'] = 0
        log(f"[TRADE] Cluster {direction.upper()} CHOT LOI (${total_profit:.2f}) - Reset SL counter")
    else:
        # Chot lo -> tang counter
        _consecutive_sl['count'] += 1
        log(f"[TRADE] Cluster {direction.upper()} CHOT LO (${total_profit:.2f}) - SL lien tiep: {_consecutive_sl['count']}/{MAX_CONSECUTIVE_SL}")
        
        # Kiem tra 3 lan SL lien tiep
        if _consecutive_sl['count'] >= MAX_CONSECUTIVE_SL:
            _bot_stopped = True
            log(f"[TRADE] !!! BOT DUNG LAI - {MAX_CONSECUTIVE_SL} lan SL lien tiep !!!")
            flush_logs()


def is_bot_stopped():
    """Kiem tra bot co bi dung khong"""
    return _bot_stopped


def get_consecutive_sl_count():
    """Lay so lan SL lien tiep hien tai"""
    return _consecutive_sl['count'], MAX_CONSECUTIVE_SL


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
    _consecutive_sl = {'count': 0}
    log("[TRADE] Bot da duoc reset - SL counter = 0")


def force_open_cluster(symbol, direction):
    """
    Mo cluster ngay lap tuc theo lenh tu Telegram.
    
    Args:
        symbol: Symbol (XAUUSD)
        direction: 'buy' hoac 'sell'
    
    Returns: True neu thanh cong
    """
    global _trade_manager, _cluster_info
    
    # Luon tao moi TradeManager de lay capital va risk moi nhat
    account_info = mt5.account_info()
    if account_info is None:
        log("[FORCE] Failed to get account info")
        return False
    
    # Su dung fixed_capital neu co, khong thi dung balance thuc
    from telegram_bot import get_bot_control
    ctrl = get_bot_control()
    fixed_cap = ctrl.get('fixed_capital')
    nav = fixed_cap if fixed_cap else account_info.balance
    
    log(f"[DEBUG] fixed_capital={fixed_cap}, balance={account_info.balance}, using NAV={nav}")
    
    _trade_manager = TradeManager(nav)
    _trade_manager.symbol = symbol
    
    if direction == 'buy':
        log("[FORCE] Mo BUY cluster theo lenh Telegram")
        entry_price, tp4_price = _trade_manager.open_buy_cluster()
    else:
        log("[FORCE] Mo SELL cluster theo lenh Telegram")
        entry_price, tp4_price = _trade_manager.open_sell_cluster()
    
    # Luu thong tin cluster
    _cluster_info['open_time'] = time.time()
    _cluster_info['direction'] = direction
    _cluster_info['tp4_price'] = tp4_price
    _cluster_info['entry_price'] = entry_price
    
    # Ghi nhan lenh mo - kiem tra 3 lan lien tiep
    record_trade_opened(direction)
    
    flush_logs()
    return True


def process_trade(symbol, signal, buy_threshold=35, sell_threshold=35, bot_ctrl=None):
    """
    Process trading signal and execute trades if conditions are met.
    
    - Khong mo de lenh neu con cluster dang mo (tru khi da qua 6 tieng)
    - So sanh hieu diem khi ca 2 chieu deu du diem
    - Ngat bot sau 3 SL lien tiep cung chieu
    - Ton trong buy_active/sell_active tu Telegram
    
    Returns: (trade_executed, should_reset_score)
    """
    global _trade_manager, _cluster_info
    
    # Kiem tra bot co bi dung khong
    if _bot_stopped:
        return False, False
    
    # Default bot control neu khong truyen vao
    if bot_ctrl is None:
        bot_ctrl = {'active': True, 'buy_active': True, 'sell_active': True}
    
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
    
    # Tinh hieu diem - chi tinh neu chieu do dang active
    buy_excess = -999
    sell_excess = -999
    
    if bot_ctrl.get('buy_active', True) and signal.buy_score >= buy_threshold:
        buy_excess = signal.buy_score - buy_threshold
    
    if bot_ctrl.get('sell_active', True) and signal.sell_score >= sell_threshold:
        sell_excess = signal.sell_score - sell_threshold
    
    # Neu ca 2 chieu deu chua du diem hoac bi tat
    if buy_excess < 0 and sell_excess < 0:
        return False, False
    
    # Tao TradeManager moi voi capital va risk moi nhat
    account_info = mt5.account_info()
    if account_info is None:
        log("Failed to get account info")
        return False, False
    
    from telegram_bot import get_bot_control
    ctrl = get_bot_control()
    fixed_cap = ctrl.get('fixed_capital')
    nav = fixed_cap if fixed_cap else account_info.balance
    
    log(f"[DEBUG] fixed_capital={fixed_cap}, balance={account_info.balance}, using NAV={nav}")
    
    _trade_manager = TradeManager(nav)
    _trade_manager.symbol = symbol
    
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
        
        # Ghi nhan lenh mo - kiem tra 3 lan lien tiep
        record_trade_opened('buy')
        
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
        
        # Ghi nhan lenh mo - kiem tra 3 lan lien tiep
        record_trade_opened('sell')
        
        flush_logs()
        return True, True


class TradeManager:
    """
    Handles opening clusters of orders (ET1-ET4) for buy or sell.
    """
    def __init__(self, initial_nav):
        self.initial_nav = initial_nav
        self.symbol = "XAUUSD"
        
        # Lay risk_percent tu bot_control
        from telegram_bot import get_bot_control
        ctrl = get_bot_control()
        self.risk_percent = ctrl.get('risk_percent', 0.10)  # Mac dinh 10%
        
        # Khoang cach USD cho ET2, ET3, ET4
        self.et_offsets_usd = [0, 0.5, 1, 1.5]
        
        # SL/TP cho tung ET (USD)
        self.sl_usd = [9, 10, 11, 12]
        self.tp_usd = [3, 5, 7, 11]
        
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
        global _cluster_tickets
        from datetime import datetime
        
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
        
        # TP4 tinh tu ET1 (market order) voi khoang cach xa nhat
        # BUY: TP cao hon entry, nen TP4 = ask + max(tp_usd)
        max_tp_distance = max(self.tp_usd)
        tp4_price = round(price_ask + max_tp_distance, 2)
        log(f"  TP4 (furthest target) = {tp4_price}")
        
        # Luu thoi gian mo cluster
        _cluster_tickets['open_time'] = datetime.now()
        
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
            et_key = f"et{i+1}"
            
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                # Market order - luu deal ticket (position)
                _cluster_tickets[et_key] = result.deal if result.deal else result.order
                log(f"  [OK] ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Ticket #{_cluster_tickets[et_key]}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                # Pending order - luu order ticket
                _cluster_tickets[et_key] = result.order
                log(f"  [OK] ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Order #{result.order}")
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
        global _cluster_tickets
        from datetime import datetime
        
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
        
        # TP4 tinh tu ET1 (market order) voi khoang cach xa nhat
        # SELL: TP thap hon entry, nen TP4 = bid - max(tp_usd)
        max_tp_distance = max(self.tp_usd)
        tp4_price = round(price_bid - max_tp_distance, 2)
        log(f"  TP4 (furthest target) = {tp4_price}")
        
        # Luu thoi gian mo cluster
        _cluster_tickets['open_time'] = datetime.now()
        
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
            et_key = f"et{i+1}"
            
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                # Market order - luu deal ticket (position)
                _cluster_tickets[et_key] = result.deal if result.deal else result.order
                log(f"  [OK] ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Ticket #{_cluster_tickets[et_key]}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                # Pending order - luu order ticket
                _cluster_tickets[et_key] = result.order
                log(f"  [OK] ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Order #{result.order}")
            else:
                error = result.comment if result else "No response"
                retcode = result.retcode if result else "N/A"
                log(f"  [X] ET{i+1} ({order_type_str}): FAILED @ {entry_price} | Code={retcode} | {error}")
        
        return entry_price_et1, tp4_price
