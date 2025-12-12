import MetaTrader5 as mt5
from telegram_bot import log, flush_logs

"""
BE Manager - Quan ly keo Break Even khi cac ET chot loi

Logic:
- ET1 chot loi (TP1) -> Keo SL cac ET con lai ve BE (gia vao lenh)
- ET2 chot loi (TP2) -> Keo SL cac ET con lai ve TP1
- ET3 chot loi (TP3) -> Keo SL cac ET con lai ve TP2
- ET4 chot loi (TP4) -> Ket thuc

Magic numbers: 1001=ET1, 1002=ET2, 1003=ET3, 1004=ET4
"""

class BEManager:
    def __init__(self, symbol="XAUUSD"):
        self.symbol = symbol
        self.magic_numbers = [1001, 1002, 1003, 1004]
        
        # Luu tru thong tin cluster dang hoat dong
        # Format: {magic: {'entry_price': x, 'tp': y, 'type': 'buy'/'sell'}}
        self.cluster_info = {}
        
        # Theo doi ET nao da chot loi
        self.closed_ets = set()
        
    def get_positions_by_magic(self, magic):
        """Lay position theo magic number"""
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return []
        return [p for p in positions if p.magic == magic]
    
    def get_all_et_positions(self):
        """Lay tat ca positions cua cluster (ET1-ET4)"""
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None:
            return []
        return [p for p in positions if p.magic in self.magic_numbers]
    
    def modify_sl(self, position, new_sl):
        """Doi SL cua 1 position"""
        request = {
            "action": mt5.TRADE_ACTION_SLTP,
            "symbol": self.symbol,
            "position": position.ticket,
            "sl": new_sl,
            "tp": position.tp,
        }
        
        result = mt5.order_send(request)
        return result and result.retcode == mt5.TRADE_RETCODE_DONE
    
    def record_cluster_open(self, magic, entry_price, tp, order_type):
        """Ghi nhan thong tin khi mo cluster"""
        self.cluster_info[magic] = {
            'entry_price': entry_price,
            'tp': tp,
            'type': order_type  # 'buy' or 'sell'
        }
    
    def check_and_manage_be(self):
        """
        Kiem tra va keo BE khi can thiet.
        Goi ham nay trong vong lap chinh.
        """
        # Lay tat ca positions hien tai
        current_positions = self.get_all_et_positions()
        current_magics = set(p.magic for p in current_positions)
        
        # Neu khong co position nao, reset
        if not current_positions:
            if self.cluster_info:
                log("[BE] Cluster da dong het, reset trang thai")
                self.cluster_info = {}
                self.closed_ets = set()
            return
        
        # Xac dinh loai lenh (buy/sell) tu position dau tien
        first_pos = current_positions[0]
        is_buy = first_pos.type == mt5.POSITION_TYPE_BUY
        
        # Kiem tra tung ET da chot loi chua
        for i, magic in enumerate(self.magic_numbers):
            et_num = i + 1
            
            # Neu ET nay da duoc xu ly roi, bo qua
            if magic in self.closed_ets:
                continue
            
            # Neu ET nay khong con trong positions (da dong)
            if magic not in current_magics:
                # Danh dau da chot loi
                self.closed_ets.add(magic)
                log(f"[BE] ET{et_num} da chot loi!")
                
                # Keo BE cho cac ET con lai
                self._apply_be_logic(et_num, is_buy, current_positions)
                flush_logs()
    
    def _apply_be_logic(self, closed_et, is_buy, current_positions):
        """
        Ap dung logic keo BE sau khi 1 ET chot loi
        
        - ET1 chot -> Keo SL cua ET2,3,4 ve BE (entry price)
        - ET2 chot -> Keo SL cua ET3,4 ve TP1 (entry +/- 3 USD)
        - ET3 chot -> Keo SL cua ET4 ve TP2 (entry +/- 5 USD)
        
        TP cua cac ET van giu nguyen!
        """
        # TP levels tu trade.py: [3, 5, 10, 15]
        tp_levels = [3, 5, 10, 15]  # TP1=3, TP2=5, TP3=10, TP4=15
        
        remaining_positions = [p for p in current_positions 
                              if p.magic not in self.closed_ets]
        
        if not remaining_positions:
            return
        
        for pos in remaining_positions:
            et_num = pos.magic - 1000  # 1001->1, 1002->2, etc.
            entry_price = pos.price_open
            current_sl = pos.sl
            
            if closed_et == 1:
                # ET1 chot -> Keo SL ve BE (entry price)
                new_sl = entry_price
                action = "BE"
                
            elif closed_et == 2:
                # ET2 chot -> Keo SL ve TP1 (entry +/- 3 USD)
                if is_buy:
                    new_sl = round(entry_price + tp_levels[0], 2)
                else:
                    new_sl = round(entry_price - tp_levels[0], 2)
                action = f"TP1 (+{tp_levels[0]})"
                
            elif closed_et == 3:
                # ET3 chot -> Keo SL ve TP2 (entry +/- 5 USD)
                if is_buy:
                    new_sl = round(entry_price + tp_levels[1], 2)
                else:
                    new_sl = round(entry_price - tp_levels[1], 2)
                action = f"TP2 (+{tp_levels[1]})"
                
            else:
                # ET4 la cuoi cung, khong can lam gi
                continue
            
            # Kiem tra SL moi co tot hon SL cu khong
            if is_buy:
                # Buy: SL moi phai cao hon SL cu (bao ve loi nhieu hon)
                if new_sl > current_sl:
                    if self.modify_sl(pos, new_sl):
                        log(f"  [BE] ET{et_num}: SL {current_sl} -> {new_sl} ({action})")
                    else:
                        log(f"  [BE] ET{et_num}: FAILED to move SL to {new_sl}")
            else:
                # Sell: SL moi phai thap hon SL cu
                if new_sl < current_sl:
                    if self.modify_sl(pos, new_sl):
                        log(f"  [BE] ET{et_num}: SL {current_sl} -> {new_sl} ({action})")
                    else:
                        log(f"  [BE] ET{et_num}: FAILED to move SL to {new_sl}")


# Global instance
_be_manager = None

def get_be_manager(symbol="XAUUSD"):
    """Lay hoac tao BE Manager"""
    global _be_manager
    if _be_manager is None:
        _be_manager = BEManager(symbol)
    return _be_manager

def check_be():
    """Ham goi trong vong lap chinh de kiem tra BE"""
    manager = get_be_manager()
    manager.check_and_manage_be()

