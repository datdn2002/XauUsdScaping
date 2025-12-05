import MetaTrader5 as mt5

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
            print("Failed to get account info")
            return False
        _trade_manager = TradeManager(account_info.balance)
        _trade_manager.symbol = symbol
    
    # Check signal scores and execute trades
    # Ngưỡng điểm cơ bản để vào lệnh
    BASE_SCORE = 35
    
    if signal.buy_score >= BASE_SCORE and signal.buy_score >= signal.sell_score:
        print("Signal to BUY detected. Opening buy cluster...")
        _trade_manager.open_buy_cluster()
        return True
    elif signal.sell_score >= BASE_SCORE and signal.sell_score > signal.buy_score:
        print("Signal to SELL detected. Opening sell cluster...")
        _trade_manager.open_sell_cluster()
        return True
    
    return False


class TradeManager:
    """
    Handles opening clusters of orders (ET1-ET4) for buy or sell.
    ET1: Market order tại giá X
    ET2/3/4: Pending orders tại X±2, X±5, X±7 USD
    Tổng risk của 4 ET = 1% NAV
    """
    def __init__(self, initial_nav):
        self.initial_nav = initial_nav
        self.symbol = "XAUUSD"
        self.risk_percent = 0.1  # 1% NAV
        
        # Khoảng cách USD cho ET2, ET3, ET4 (so với ET1)
        # BUY: giá giảm xuống mới mở thêm (X-2, X-5, X-7 USD)
        # SELL: giá tăng lên mới mở thêm (X+2, X+5, X+7 USD)
        self.et_offsets_usd = [0, 0.2, 0.5, 0.7]  # Khoảng cách USD
        
        # SL/TP cho từng ET (USD)
        self.sl_usd = [9, 10, 11, 12]
        self.tp_usd = [3, 5, 10, 15]
        
        # Phân bổ risk: 20%, 20%, 40%, 20% của 1% NAV
        self.risk_allocation = [0.20, 0.20, 0.40, 0.20]
        
    def get_symbol_info(self):
        """Lấy thông tin symbol và stop level"""
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            return None, None, None, None
        
        min_lot = symbol_info.volume_min
        lot_step = symbol_info.volume_step
        stop_level = symbol_info.trade_stops_level  # Số point tối thiểu cho SL/TP
        point = symbol_info.point  # Giá trị 1 point (0.01 cho XAUUSD)
        
        return min_lot, lot_step, stop_level, point
        
    def calculate_lots(self):
        """
        Tính lot size để tổng risk của 4 ET = đúng 1% NAV.
        Phân bổ risk: ET1=20%, ET2=20%, ET3=40%, ET4=20%
        
        Công thức cho mỗi ET:
        - Risk_i = risk_allocation[i] × 1% × NAV
        - Lot_i = Risk_i / (SL_i × $100)
        
        Với XAUUSD: 1 USD price move = $100 profit/loss per lot
        """
        min_lot, lot_step, _, _ = self.get_symbol_info()
        if min_lot is None:
            return 0.01, 0.01, 0.02, 0.01
        
        total_risk = self.initial_nav * self.risk_percent  # 1% NAV
        usd_per_lot = 100  # $100 per 1 USD move per lot cho XAUUSD
        
        lots = []
        total_actual_risk = 0
        
        for i in range(4):
            # Risk phân bổ cho ET này
            allocated_risk = total_risk * self.risk_allocation[i]
            # Lot = Risk / (SL × $100/USD/lot)
            raw_lot = allocated_risk / (self.sl_usd[i] * usd_per_lot)
            # Làm tròn theo lot_step và đảm bảo >= min_lot
            lot = max(min_lot, round(raw_lot / lot_step) * lot_step)
            lots.append(lot)
            
            # Tính lại risk thực tế sau khi làm tròn
            actual_risk = lot * self.sl_usd[i] * usd_per_lot
            total_actual_risk += actual_risk
        
        print(f"  Risk 1% NAV = ${total_risk:.2f}")
        print(f"  Lots: ET1={lots[0]:.2f}, ET2={lots[1]:.2f}, ET3={lots[2]:.2f}, ET4={lots[3]:.2f}")
        print(f"  Total risk thực tế: ${total_actual_risk:.2f} ({total_actual_risk/self.initial_nav*100:.2f}% NAV)")
        
        return lots[0], lots[1], lots[2], lots[3]

    def open_buy_cluster(self):
        """
        Open a BUY cluster:
        - ET1: Market order tại giá hiện tại X
        - ET2: Buy Limit tại X - 2 USD
        - ET3: Buy Limit tại X - 5 USD
        - ET4: Buy Limit tại X - 7 USD
        """
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            print("Failed to get symbol tick info")
            return
        
        price_x = tick.ask  # Giá vào lệnh ET1
        lots = self.calculate_lots()
        
        _, _, stop_level, point = self.get_symbol_info()
        
        # Đảm bảo SL/TP đủ xa (stop_level thường tính bằng point)
        min_distance = max(stop_level * point if stop_level else 0, 0.5)
        
        print(f"BUY Cluster @ X={price_x}")
        
        for i in range(4):
            lot = lots[i]
            offset = self.et_offsets_usd[i]
            sl_distance = max(self.sl_usd[i], min_distance + 0.1)
            tp_distance = max(self.tp_usd[i], min_distance + 0.1)
            
            if i == 0:
                # ET1: Market order
                entry_price = price_x
                order_type = mt5.ORDER_TYPE_BUY
                action = mt5.TRADE_ACTION_DEAL
            else:
                # ET2/3/4: Buy Limit (giá thấp hơn X)
                entry_price = round(price_x - offset, 2)
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
                print(f"  ✅ ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Order #{result.order}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                print(f"  ✅ ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Order #{result.order}")
            else:
                error = result.comment if result else "No response"
                retcode = result.retcode if result else "N/A"
                print(f"  ❌ ET{i+1} ({order_type_str}): THẤT BẠI @ {entry_price} | Code={retcode} | {error}")

    def open_sell_cluster(self):
        """
        Open a SELL cluster:
        - ET1: Market order tại giá hiện tại X
        - ET2: Sell Limit tại X + 2 USD
        - ET3: Sell Limit tại X + 5 USD
        - ET4: Sell Limit tại X + 7 USD
        """
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            print("Failed to get symbol tick info")
            return
        
        price_x = tick.bid  # Giá vào lệnh ET1
        lots = self.calculate_lots()
        
        _, _, stop_level, point = self.get_symbol_info()
        
        # Đảm bảo SL/TP đủ xa
        min_distance = max(stop_level * point if stop_level else 0, 0.5)
        
        print(f"SELL Cluster @ X={price_x}")
        
        for i in range(4):
            lot = lots[i]
            offset = self.et_offsets_usd[i]
            sl_distance = max(self.sl_usd[i], min_distance + 0.1)
            tp_distance = max(self.tp_usd[i], min_distance + 0.1)
            
            if i == 0:
                # ET1: Market order
                entry_price = price_x
                order_type = mt5.ORDER_TYPE_SELL
                action = mt5.TRADE_ACTION_DEAL
            else:
                # ET2/3/4: Sell Limit (giá cao hơn X)
                entry_price = round(price_x + offset, 2)
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
                print(f"  ✅ ET{i+1} ({order_type_str}): {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Order #{result.order}")
            elif result and result.retcode == mt5.TRADE_RETCODE_PLACED:
                print(f"  ✅ ET{i+1} ({order_type_str}): Pending {lot} lots @ {entry_price} | SL={sl}, TP={tp} | Order #{result.order}")
            else:
                error = result.comment if result else "No response"
                retcode = result.retcode if result else "N/A"
                print(f"  ❌ ET{i+1} ({order_type_str}): THẤT BẠI @ {entry_price} | Code={retcode} | {error}")
