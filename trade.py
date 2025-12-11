import MetaTrader5 as mt5
from telegram_bot import log, flush_logs

# Global TradeManager instance
_trade_manager = None

def process_trade(symbol, signal):
    """
    Process trading signal and execute trades if conditions are met.
    Returns True if a trade was executed, False otherwise.
    """
    global _trade_manager
    
    # Initialize TradeManager if not already done
    if _trade_manager is None:
        account_info = mt5.account_info()
        if account_info is None:
            log("Failed to get account info")
            return False
        _trade_manager = TradeManager(account_info.balance)
        _trade_manager.symbol = symbol
    
    # Check signal scores and execute trades
    BASE_SCORE = 35
    
    if signal.buy_score >= BASE_SCORE and signal.buy_score >= signal.sell_score:
        log("Signal to BUY detected. Opening buy cluster...")
        _trade_manager.open_buy_cluster()
        flush_logs()  # Gui ngay khi co lenh
        return True
    elif signal.sell_score >= BASE_SCORE and signal.sell_score > signal.buy_score:
        log("Signal to SELL detected. Opening sell cluster...")
        _trade_manager.open_sell_cluster()
        flush_logs()  # Gui ngay khi co lenh
        return True
    
    return False


class TradeManager:
    """
    Handles opening clusters of orders (ET1-ET4) for buy or sell.
    """
    def __init__(self, initial_nav):
        self.initial_nav = initial_nav
        self.symbol = "XAUUSD"
        self.risk_percent = 0.1  # 10% NAV
        
        # Khoang cach USD cho ET2, ET3, ET4
        self.et_offsets_usd = [0, 0.2, 0.5, 0.7]
        
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
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            log("Failed to get symbol tick info")
            return
        
        price_ask = tick.ask
        price_bid = tick.bid
        lots = self.calculate_lots()
        
        _, _, stop_level, point = self.get_symbol_info()
        min_distance = max(stop_level * point if stop_level else 0, 0.5)
        
        log(f"BUY Cluster @ Ask={price_ask}, Bid={price_bid}")
        
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
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log(f"  [OK] ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                log(f"  [OK] ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            else:
                error = result.comment if result else "No response"
                retcode = result.retcode if result else "N/A"
                log(f"  [X] ET{i+1} ({order_type_str}): FAILED @ {entry_price} | Code={retcode} | {error}")

    def open_sell_cluster(self):
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            log("Failed to get symbol tick info")
            return
        
        price_bid = tick.bid
        price_ask = tick.ask
        lots = self.calculate_lots()
        
        _, _, stop_level, point = self.get_symbol_info()
        min_distance = max(stop_level * point if stop_level else 0, 0.5)
        
        log(f"SELL Cluster @ Bid={price_bid}, Ask={price_ask}")
        
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
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                log(f"  [OK] ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                log(f"  [OK] ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp}")
            else:
                error = result.comment if result else "No response"
                retcode = result.retcode if result else "N/A"
                log(f"  [X] ET{i+1} ({order_type_str}): FAILED @ {entry_price} | Code={retcode} | {error}")
