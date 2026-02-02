import MetaTrader5 as mt5
from telegram_bot import log, flush_logs
from datetime import datetime, timedelta

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
        
        # Luu tru thong tin tung ET
        # Format: {magic: {'entry': x, 'sl': y, 'tp': z, 'ticket': t}}
        self.et_info = {}
        
        # Theo doi ET nao da dong (TP hoac SL)
        self.closed_ets = set()
        
        # Theo doi ET nao da tung mo (de phan biet voi pending chua khop)
        self.opened_ets = set()
        
        # Huong cua cluster hien tai (buy/sell)
        self.cluster_direction = None
        
        # Tong loi/lo cua cluster
        self.cluster_profit = 0
        
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
    
    def check_closed_at_tp(self, magic):
        """
        Kiem tra xem position da dong tai TP hay khong.
        Tim deal theo position_id (ticket).
        """
        # Lay ticket cua position tu et_info
        ticket = self.et_info.get(magic, {}).get('ticket', 0)
        if ticket == 0:
            log(f"  [DEBUG] Khong tim thay ticket cho magic={magic}")
            return False
        
        now = datetime.now()
        from_date = now - timedelta(days=1)  # Mo rong 1 ngay
        
        # Yeu cau MT5 load history truoc
        mt5.history_deals_get(position=ticket)
        
        # Lay deals theo position ticket
        deals = mt5.history_deals_get(position=ticket)
        
        if deals is None or len(deals) == 0:
            # Thu tim trong tat ca deals
            all_deals = mt5.history_deals_get(from_date, now)
            if all_deals:
                log(f"  [DEBUG] Tong so deals trong 1 ngay: {len(all_deals)}")
                # Log 5 deals gan nhat de debug
                for d in list(all_deals)[-5:]:
                    log(f"    - pos_id={d.position_id}, entry={d.entry}, reason={d.reason}, profit={d.profit}")
            log(f"  [DEBUG] Khong tim thay deal voi position={ticket}")
            return False
        
        # Tim deal OUT (dong lenh)
        out_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        
        if not out_deals:
            log(f"  [DEBUG] Khong co deal OUT trong {len(deals)} deals cua position {ticket}")
            return False
        
        # Lay deal dong lenh
        deal = out_deals[-1]
        deal_time = datetime.fromtimestamp(deal.time)
        
        # Kiem tra reason
        reason_names = {
            0: "TP",
            1: "SL", 
            2: "PENDING",
            3: "CLIENT",
            4: "MOBILE",
            5: "WEB",
            6: "EXPERT",
        }
        reason_name = reason_names.get(deal.reason, f"UNKNOWN({deal.reason})")
        
        log(f"  [DEBUG] Deal ticket={ticket}: reason={reason_name}, profit={deal.profit}, time={deal_time}")
        
        # Tra ve True neu dong tai TP
        if deal.reason == mt5.DEAL_REASON_TP:
            return True
        
        return False
    
    def get_deal_profit(self, magic):
        """
        Lay profit cua deal vua dong.
        Tim theo position ticket.
        """
        # Lay ticket tu et_info
        ticket = self.et_info.get(magic, {}).get('ticket', 0)
        if ticket == 0:
            return 0
        
        # Lay deals theo position ticket
        deals = mt5.history_deals_get(position=ticket)
        
        if deals is None or len(deals) == 0:
            return 0
        
        # Tim deal OUT (dong lenh)
        out_deals = [d for d in deals if d.entry == mt5.DEAL_ENTRY_OUT]
        
        if not out_deals:
            return 0
        
        deal = out_deals[-1]
        return deal.profit + deal.commission + deal.swap
    
    def check_and_manage_be(self):
        """
        Kiem tra va keo BE khi can thiet.
        Goi ham nay trong vong lap chinh.
        Chi keo BE khi ET dong o TP (co loi), khong keo khi dong o SL.
        """
        # Lay tat ca positions hien tai
        current_positions = self.get_all_et_positions()
        current_magics = set(p.magic for p in current_positions)
        
        # Theo doi cac ET dang mo va luu thong tin
        for magic in current_magics:
            if magic not in self.opened_ets:
                et_num = magic - 1000
                pos = [p for p in current_positions if p.magic == magic][0]
                
                # Luu thong tin ET
                self.et_info[magic] = {
                    'entry': pos.price_open,
                    'sl': pos.sl,
                    'tp': pos.tp,
                    'ticket': pos.ticket
                }
                
                log(f"[BE] ET{et_num} da mo: entry={pos.price_open}, SL={pos.sl}, TP={pos.tp}")
                self.opened_ets.add(magic)
                
                # Xac dinh huong cluster tu position dau tien
                if self.cluster_direction is None:
                    self.cluster_direction = 'buy' if pos.type == mt5.POSITION_TYPE_BUY else 'sell'
        
        # Neu khong co position nao, reset va ghi nhan ket qua
        if not current_positions:
            if self.opened_ets:
                # Import ham ghi nhan ket qua
                from trade import record_cluster_result
                
                # Tinh tong loi/lo cua cluster
                is_profit = self.cluster_profit > 0
                direction = self.cluster_direction or 'unknown'
                
                log(f"[BE] Cluster {direction.upper()} da dong het - Profit: ${self.cluster_profit:.2f}")
                record_cluster_result(direction, is_profit)
                
                # Reset trang thai
                self.et_info = {}
                self.closed_ets = set()
                self.opened_ets = set()
                self.cluster_direction = None
                self.cluster_profit = 0
            return
        
        # Xac dinh loai lenh (buy/sell) tu position dau tien
        first_pos = current_positions[0]
        is_buy = first_pos.type == mt5.POSITION_TYPE_BUY
        
        # Kiem tra tung ET da chot chua
        for i, magic in enumerate(self.magic_numbers):
            et_num = i + 1
            
            # Neu ET nay da duoc xu ly roi, bo qua
            if magic in self.closed_ets:
                continue
            
            # Chi xu ly neu ET nay da tung mo (khong phai pending chua khop)
            if magic not in self.opened_ets:
                continue
            
            # Neu ET nay khong con trong positions (da dong)
            if magic not in current_magics:
                # Danh dau da dong
                self.closed_ets.add(magic)
                
                # Lay profit cua deal vua dong
                profit = self.get_deal_profit(magic)
                self.cluster_profit += profit
                
                # Kiem tra xem dong o TP hay SL (dung deal.reason)
                if self.check_closed_at_tp(magic):
                    log(f"[BE] ET{et_num} CHOT TAI TP! (profit=${profit:.2f})")
                    # Keo BE khi dong o TP
                    self._apply_be_logic(et_num, is_buy, current_positions)
                    flush_logs()
                else:
                    log(f"[BE] ET{et_num} dong tai SL/Manual (profit=${profit:.2f}) - khong keo BE")
    
    def _apply_be_logic(self, closed_et, is_buy, current_positions):
        """
        Ap dung logic keo BE sau khi 1 ET chot loi tai TP
        
        - ET1 chot TP -> Keo SL cua ET2,3,4 ve BE (entry price cua tung ET)
        - ET2 chot TP -> Keo SL cua ET3,4 ve TP1 (gia TP cua ET1)
        - ET3 chot TP -> Keo SL cua ET4 ve TP2 (gia TP cua ET2)
        
        TP cua cac ET van giu nguyen!
        """
        remaining_positions = [p for p in current_positions 
                              if p.magic not in self.closed_ets]
        
        if not remaining_positions:
            return
        
        # Lay gia TP da luu cua ET1, ET2
        tp1_price = self.et_info.get(1001, {}).get('tp', 0)  # TP cua ET1
        tp2_price = self.et_info.get(1002, {}).get('tp', 0)  # TP cua ET2
        
        for pos in remaining_positions:
            et_num = pos.magic - 1000  # 1001->1, 1002->2, etc.
            current_sl = pos.sl
            
            if closed_et == 1:
                # ET1 chot TP -> Keo SL ve BE (entry price cua chinh no)
                new_sl = pos.price_open
                action = f"BE ({new_sl})"
                
            elif closed_et == 2:
                # ET2 chot TP -> Keo SL ve TP1 (gia TP cua ET1)
                new_sl = tp1_price
                action = f"TP1 ({new_sl})"
                
            elif closed_et == 3:
                # ET3 chot TP -> Keo SL ve TP2 (gia TP cua ET2)
                new_sl = tp2_price
                action = f"TP2 ({new_sl})"
                
            else:
                # ET4 la cuoi cung, khong can lam gi
                continue
            
            # Kiem tra new_sl hop le
            if new_sl == 0:
                log(f"  [BE] ET{et_num}: Khong co gia TP de keo, bo qua")
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
                    log(f"  [BE] ET{et_num}: SL da tot hon roi ({current_sl} >= {new_sl})")
            else:
                # Sell: SL moi phai thap hon SL cu
                if new_sl < current_sl:
                    if self.modify_sl(pos, new_sl):
                        log(f"  [BE] ET{et_num}: SL {current_sl} -> {new_sl} ({action})")
                    else:
                        log(f"  [BE] ET{et_num}: FAILED to move SL to {new_sl}")
                else:
                    log(f"  [BE] ET{et_num}: SL da tot hon roi ({current_sl} <= {new_sl})")


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

