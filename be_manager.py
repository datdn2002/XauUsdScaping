import MetaTrader5 as mt5
from telegram_bot import log, flush_logs

"""
BE Manager - Đơn giản hóa

Logic duy nhất:
- ET3 chốt TP → Kéo SL của ET4 về Entry ± 2.5
  + BUY: SL mới = Entry - 2.5
  + SELL: SL mới = Entry + 2.5

Magic numbers: 1001=ET1, 1002=ET2, 1003=ET3, 1004=ET4
"""

# Khoảng cách SL mới khi ET3 chốt TP (USD)
NEW_SL_DISTANCE = 2.5


class BEManager:
    def __init__(self, symbol="XAUUSD"):
        self.symbol = symbol
        
        # Theo dõi ET3 đã chốt TP chưa
        self.et3_closed_at_tp = False
        
        # Lưu ticket của ET3 để kiểm tra
        self.et3_ticket = None
        
        # Đã kéo SL của ET4 chưa
        self.et4_sl_moved = False
    
    def reset(self):
        """Reset trạng thái khi cluster đóng hết"""
        self.et3_closed_at_tp = False
        self.et3_ticket = None
        self.et4_sl_moved = False
    
    def get_position_by_magic(self, magic):
        """Lấy position theo magic number"""
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return None
        for p in positions:
            if p.magic == magic:
                return p
        return None
    
    def modify_sl(self, position, new_sl):
        """Đổi SL của 1 position"""
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": position.ticket,
            "sl": round(new_sl, 2),
            "tp": position.tp,
        }
        
        result = mt5.order_send(request)
        return result and result.retcode == mt5.TRADE_RETCODE_DONE
    
    def check_et3_closed_at_tp(self):
        """Kiểm tra ET3 đã đóng tại TP chưa"""
        if self.et3_ticket is None:
            return False
        
        # Lấy deals theo position ticket
        deals = mt5.history_deals_get(position=self.et3_ticket)
        
        if deals is None or len(deals) == 0:
            return False
        
        # Tìm deal OUT (đóng lệnh)
        for deal in deals:
            if deal.entry == mt5.DEAL_ENTRY_OUT:
                if deal.reason == mt5.DEAL_REASON_TP:
                    return True
        
        return False
    
    def check_and_manage(self):
        """
        Kiểm tra và kéo SL của ET4 khi ET3 chốt TP.
        Gọi hàm này trong vòng lặp chính.
        """
        # Nếu đã kéo SL rồi, không cần làm gì nữa
        if self.et4_sl_moved:
            return
        
        # Lấy position ET3 và ET4
        et3 = self.get_position_by_magic(1003)
        et4 = self.get_position_by_magic(1004)
        
        # Lưu ticket ET3 khi còn mở
        if et3 is not None and self.et3_ticket is None:
            self.et3_ticket = et3.ticket
        
        # Kiểm tra ET4 còn mở không
        if et4 is None:
            return
        
        # Kiểm tra ET3 đã đóng chưa
        if et3 is not None:
            # ET3 vẫn còn mở, chưa cần làm gì
            return
        
        # ET3 đã đóng, kiểm tra có phải đóng tại TP không
        if self.et3_ticket is None:
            # Không có thông tin ET3
            return
        
        if not self.check_et3_closed_at_tp():
            # ET3 không đóng tại TP (đóng SL hoặc manual)
            return
        
        # ET3 đã chốt TP! Kéo SL của ET4
        is_buy = et4.type == mt5.POSITION_TYPE_BUY
        entry_price = et4.price_open
        
        if is_buy:
            new_sl = round(entry_price - NEW_SL_DISTANCE, 2)
        else:
            new_sl = round(entry_price + NEW_SL_DISTANCE, 2)
        
        old_sl = et4.sl
        
        # Kiểm tra SL mới có tốt hơn không
        if is_buy and new_sl <= old_sl:
            log(f"[BE] ET4: SL mới ({new_sl}) không tốt hơn SL cũ ({old_sl})")
            self.et4_sl_moved = True
            return
        if not is_buy and new_sl >= old_sl:
            log(f"[BE] ET4: SL mới ({new_sl}) không tốt hơn SL cũ ({old_sl})")
            self.et4_sl_moved = True
            return
        
        # Kéo SL
        if self.modify_sl(et4, new_sl):
            log(f"[BE] ET3 chốt TP -> ET4 SL: {old_sl} -> {new_sl}")
            flush_logs()
        else:
            log(f"[BE] FAILED: Không thể kéo SL ET4 từ {old_sl} -> {new_sl}")
        
        self.et4_sl_moved = True


# Global instance
_be_manager = None


def get_be_manager(symbol="XAUUSD"):
    """Lấy hoặc tạo BE Manager"""
    global _be_manager
    if _be_manager is None:
        _be_manager = BEManager(symbol)
    return _be_manager


def reset_be_manager():
    """Reset BE Manager khi cluster đóng"""
    global _be_manager
    if _be_manager is not None:
        _be_manager.reset()


def check_be():
    """Hàm gọi trong vòng lặp chính để kiểm tra BE"""
    manager = get_be_manager()
    manager.check_and_manage()
