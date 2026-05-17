import time
import json
from datetime import datetime, timedelta, timezone
import re
import MetaTrader5 as mt5
import logging
import logging.config
import yaml
import os
from Build_PayLoad import TradingPayloadBuilder
from scalping_payload import ScalpingPayloadBuilder
from ai_client import AIClient
from utlls_save_history import save_trade_history_csv_files
from SYMBOLs import SYMBOLS
from utils_logs import update_eqity_running

# Setup logging
try:
    config_path = os.path.join(os.path.dirname(__file__), "config", "live_trade_ai_logging.yaml")
    with open(config_path, "r") as file:
        logging_config = yaml.safe_load(file)
        logging.config.dictConfig(logging_config)
    logger = logging.getLogger("live_trade_ai")
    logger.info("LiveTradeAI logging initialized successfully")
except Exception as e:
    # Fallback logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("live_trade_ai")
    logger.warning(f"Failed to load logging config: {e}, using basic logging")


class LiveTradeAI:
    """Live trading using external AI model API.

    - Builds payload via TradingPayloadBuilder
    - Calls AI endpoint to get decision with structure:
        {
          "signal": "buy"|"sell"|"hold",
          "entry_price": float | None,
          "stop_loss": float | None,
          "take_profit": float | None,
          "confidence": float
        }
    - Places market order with SL/TP. If entry_price provided, uses it for SL/TP distance reference.
    - Applies optional R:R (rr) when TP is missing.
    - Optionally checks max_loss_pct against balance to warn (no hard stop sizing by default).
    """

    def __init__(self, symbol: str, balance: float, lot_size: float, leverage: int, ai_name_model: str,
                 ai_endpoint: str, ai_key: str, rr: float | None = None, max_loss_pct: float | None = None,
                 poll_interval_sec: int = 5, timeframe_sec: int = 60, trading_type: str = "scalping",
                 max_loss_per_trade: float | None = None):
        self.symbol = symbol
        self.balance = float(balance)
        self.lot_size = float(lot_size)
        self.leverage = int(leverage)
        self.rr = rr
        self.max_loss_pct = max_loss_pct
        self.max_loss_per_trade = max_loss_per_trade  # USD amount for max loss per trade
        self.poll_interval_sec = poll_interval_sec
        self.timeframe_sec = int(timeframe_sec)
        self.runflag = True
        self._last_candle_ts = None  # epoch giây theo UTC+7 của nến đã xử lý gần nhất
        self.trading_type = trading_type.lower()
        self.count_save_history=0
        
        # Initialize AI Client
        self.ai_client = AIClient(
            ai_endpoint=ai_endpoint,
            ai_key=ai_key,
            ai_name_model=ai_name_model,
            symbol=self.symbol,
            timeframe_sec=self.timeframe_sec,
            rr=self.rr
        )
        # Track saved deals to avoid duplicate writes
        self._saved_deal_ids: set[int] = set()
        # Store AI decision and payload for successful orders
        self._last_ai_decision: dict = {}
        self._last_payload: dict = {}
        self.flag_oder_open=False

        if not mt5.initialize():
            raise RuntimeError("Cannot initialize MT5")

    def stop(self):
        self.runflag = False

    @staticmethod
    def _utc7_now_epoch() -> int:
        # epoch giây theo UTC+7 (avoid deprecated utcnow by using timestamp on aware UTC)
        try:
            return int((datetime.now(timezone.utc).timestamp()) + 7 * 3600)
        except Exception:
            # Fallback using timezone-aware datetime
            return int((datetime.now(timezone.utc).timestamp()) + 7 * 3600)

    @staticmethod
    def _utc7_now_dt() -> datetime:
        # datetime hiện tại theo UTC+7 (naive). Prefer timezone-aware then drop tz.
        try:
            return (datetime.now(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)
        except Exception:
            # Fallback using timezone-aware datetime
            return (datetime.now(timezone.utc) + timedelta(hours=7)).replace(tzinfo=None)

    def is_candle_close_ready(self) -> bool:
        """Kích hoạt TRƯỚC khi nến (theo timeframe_sec) đóng ở UTC+7, sớm hơn 3 giây.

        Cơ chế:
        - epoch7 = thời gian hiện tại theo UTC+7 (giây)
        - tf = timeframe (giây)
        - remainder = epoch7 % tf
        - time_until_close = tf - remainder
        - Kích hoạt khi 0 < time_until_close <= 3 và đảm bảo chỉ chạy 1 lần mỗi nến
          bằng cách đánh dấu next_close_ts (timestamp đóng nến kế tiếp).
        """
        try:
            tf = max(1, int(self.timeframe_sec))
            epoch7 = self._utc7_now_epoch()
            remainder = epoch7 % tf
            time_until_close = tf - remainder if remainder != 0 else 0

            # Timestamp đóng của nến hiện tại
            current_candle_start = epoch7 - remainder
            next_close_ts = current_candle_start + tf

            if 0 < time_until_close <= 2:
                # Đảm bảo chỉ kích hoạt 1 lần cho mỗi mốc đóng nến
                if self._last_candle_ts != next_close_ts:
                    self._last_candle_ts = next_close_ts
                    return True
            return False
        except Exception:
            # Nếu có lỗi, không chặn lệnh
            return True

    def _build_payload(self) -> dict:
        # Try to infer timeframe from attribute if available, else fallback M5
        tf = getattr(self, 'timeframe_sec', None)
        tf_const = mt5.TIMEFRAME_M5
        try:
            # Map common seconds to MT5 timeframe consts
            sec_to_tf = {60: mt5.TIMEFRAME_M1, 300: mt5.TIMEFRAME_M5, 900: mt5.TIMEFRAME_M15,
                         1800: mt5.TIMEFRAME_M30, 3600: mt5.TIMEFRAME_H1, 14400: mt5.TIMEFRAME_H4, 86400: mt5.TIMEFRAME_D1}
            if isinstance(tf, int) and tf in sec_to_tf:
                tf_const = sec_to_tf[tf]
            print(f"Using timeframe {tf_const} for payload")
            logger.info(f"Using timeframe {tf_const} for payload")
            print(tf_const==mt5.TIMEFRAME_M1)
            logger.debug(f"Timeframe M1 check: {tf_const==mt5.TIMEFRAME_M1}")
        except Exception:
            tf_const = mt5.TIMEFRAME_M5
        # Force symbol select for safety
        try:
            mt5.symbol_select(self.symbol, True)
        except Exception:
            pass
            
        # Choose builder based on trading type
        if self.trading_type == "scalping":
            builder = ScalpingPayloadBuilder(symbol=self.symbol, timeframe=tf_const)
            print(f"🚀 Using ScalpingPayloadBuilder for {self.trading_type} trading")
            logger.info(f"Using ScalpingPayloadBuilder for {self.trading_type} trading")
        else:
            builder = TradingPayloadBuilder(symbol=self.symbol, timeframe=tf_const)
            print(f"📊 Using TradingPayloadBuilder for {self.trading_type} trading")
            logger.info(f"Using TradingPayloadBuilder for {self.trading_type} trading")
            
        try:
            if self.trading_type == "scalping":
                return builder.build_scalping_payload()
            else:
                return builder.build_payload(news=False)
        except Exception as e:
            print(f"Build payload error: {e}")
            logger.error(f"Build payload error: {e}", exc_info=True)
            raise

    def _call_ai(self, payload: dict) -> dict:
        """
        Call AI using AIClient instead of direct implementation.
        """
        try:
            return self.ai_client._call_ai(payload)
        except Exception as e:
            print(f"❌ AI call failed: {e}")
            logger.error(f"AI call failed: {e}", exc_info=True)
            raise

    def _validate_decision(self, decision: dict) -> dict:
        """
        Validate AI decision using AIClient instead of static implementation.
        """
        try:
            return self.ai_client._validate_decision(decision)
        except Exception as e:
            print(f"❌ Decision validation failed: {e}")
            logger.error(f"Decision validation failed: {e}", exc_info=True)
            raise

    @staticmethod
    def _get_filling_mode(symbol: str) -> int:
        """Get appropriate filling mode for symbol based on what it supports."""
        try:
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                return mt5.ORDER_FILLING_FOK  # Default fallback
            
            # Check which filling modes are supported
            filling_mode = symbol_info.filling_mode
            
            # Priority: FOK > IOC > RETURN
            # FOK (Fill or Kill) - most compatible
            if filling_mode & 1:  # ORDER_FILLING_FOK
                return mt5.ORDER_FILLING_FOK
            # IOC (Immediate or Cancel)
            elif filling_mode & 2:  # ORDER_FILLING_IOC
                return mt5.ORDER_FILLING_IOC
            # RETURN
            else:
                return mt5.ORDER_FILLING_RETURN
        except Exception:
            return mt5.ORDER_FILLING_FOK  # Safe default

    def _place_order(self, signal: str, entry_price: float | None, stop_loss: float | None, take_profit: float | None, pending_timeout_sec: int | None = None):
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            return
        if signal.lower() == "buy":
            order_type = mt5.ORDER_TYPE_BUY
            price = tick.ask
        elif signal.lower() == "sell":
            order_type = mt5.ORDER_TYPE_SELL
            price = tick.bid
        else:
            return  # hold

        # Use current price as entry if none
        ep = float(entry_price) if entry_price else price

        # LUÔN DÙNG LỆNH THỊ TRƯỜNG để tránh lỗi 10022 (Invalid expiration)
        # Pending order có thể gây lỗi nếu không config đúng expiration
        use_pending_order =  True

        #Điều chỉnh lot tạm thời theo risk_percent > max_loss_pct bằng cách giảm theo step
        # Nếu có max_loss_per_trade, tính lot size dựa trên đó trước
        if self.max_loss_per_trade is not None and stop_loss is not None:
            calculated_lot = self.calculate_lot_from_max_loss(signal=signal, entry_price=ep, stop_loss=stop_loss)
            if calculated_lot is not None:
                self.lot_size = calculated_lot
                print(f"📊 Updated lot_size to {self.lot_size} based on max_loss_per_trade ${self.max_loss_per_trade}")
                logger.info(f"Updated lot_size to {self.lot_size} based on max_loss_per_trade ${self.max_loss_per_trade}")
        
        try:
            ok_lot, lot_to_use = self.suggest_safe_lot(signal=signal, entry_price=ep, stop_loss=stop_loss)
            if not ok_lot:
                # Không thể tìm lot phù hợp → dừng bot symbol này
                return "Balance not enough"
        except Exception:
            lot_to_use = float(self.lot_size)

        # Ước lượng nhanh margin dựa trên lot đã điều chỉnh
        try:
            est = self.estimate_pl(signal=signal, entry_price=ep, lot_override=lot_to_use)
            if est and (est.get("allowed_by_margin") is False):
                return "Margin not enough"
        except Exception:
            # Nếu ước lượng lỗi, tiếp tục luồng cũ (không chặn lệnh)
            pass

        # Derive missing TP using R:R against provided SL
        sl = float(stop_loss) if stop_loss else None
        tp = float(take_profit) if take_profit else None
        if self.check_rr(ep, sl, tp)[0] is False:
            return "RR not enough"

        # Build request
        if use_pending_order == True:
            # Đặt lệnh chờ - cần chọn đúng loại lệnh dựa trên giá
            current_price = price  # tick.ask for buy, tick.bid for sell
            entry = float(entry_price) if entry_price else current_price
            
            # Xác định loại lệnh pending phù hợp
            if signal.lower() == "buy":
                # BUY: nếu entry < current → BUY_LIMIT, nếu entry > current → BUY_STOP
                if entry < current_price:
                    pending_type = mt5.ORDER_TYPE_BUY_LIMIT
                else:
                    pending_type = mt5.ORDER_TYPE_BUY_STOP
            else:  # sell
                # SELL: nếu entry > current → SELL_LIMIT, nếu entry < current → SELL_STOP
                if entry > current_price:
                    pending_type = mt5.ORDER_TYPE_SELL_LIMIT
                else:
                    pending_type = mt5.ORDER_TYPE_SELL_STOP

            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": self.symbol,
                "volume": lot_to_use,
                "type": pending_type,
                "price": entry,
                "magic": 239991,
                "comment": "AI Live Trade Pending",
                "type_time": mt5.ORDER_TIME_GTC,
            }
            
            # Thêm SL và TP nếu có
            if sl is not None:
                request["sl"] = sl
            if tp is not None:
                request["tp"] = tp
            
            # Set expiration if AI provided pending timeout
            if pending_timeout_sec and pending_timeout_sec > 0:
                try:
                    expiration_dt = datetime.now(timezone.utc) + timedelta(seconds=int(pending_timeout_sec))
                    expiration_timestamp = int(expiration_dt.timestamp())
                    # Đảm bảo expiration là thời gian tương lai
                    current_timestamp = int(datetime.now(timezone.utc).timestamp())
                    if expiration_timestamp > current_timestamp:
                        request["type_time"] = mt5.ORDER_TIME_SPECIFIED
                        request["expiration"] = expiration_timestamp
                        print(f"📅 Set expiration: {expiration_dt} (timestamp: {expiration_timestamp})")
                    else:
                        print(f"⚠️ Invalid expiration time (past), using GTC instead")
                except Exception as e:
                    print(f"⚠️ Failed to set expiration: {e}, using GTC")
                    pass
        else:
            # Đặt lệnh thị trường
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": lot_to_use,
                "type": order_type,
                "price": price,
                "deviation": 10,
                "magic": 239991,
                "comment": "AI Live Trade",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": self._get_filling_mode(self.symbol),
            }
            if sl is not None:
                request["sl"] = sl
            if tp is not None:
                request["tp"] = tp

        # Retry gửi lệnh cho đến khi thành công
        max_retries = 60  # Giới hạn số lần thử để tránh vòng lặp vô hạn
        retry_count = 0
        result = None
        
        while retry_count < max_retries and self.runflag:
            result = mt5.order_send(request)
            
            # Kiểm tra nếu lệnh thành công
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                # Lưu thông tin AI decision khi đặt lệnh thành công
                self._last_ai_decision = {
                    'signal': signal,
                    'entry_price': entry_price,
                    'stop_loss': stop_loss,
                    'take_profit': take_profit
                }
                print(f"✅ Order successful after {retry_count + 1} attempt(s), saved AI decision: {self._last_ai_decision}")
                logger.info(f"Order successful after {retry_count + 1} attempt(s), saved AI decision: {self._last_ai_decision}")
                return result
            
            # Lệnh thất bại, log lỗi và retry
            retry_count += 1
            error_msg = result.comment if result else "No result"
            error_code = result.retcode if result else "N/A"
            print(f"⚠️ Order attempt {retry_count} failed - Code: {error_code}, Error: {error_msg}")
            logger.warning(f"Order attempt {retry_count} failed - Code: {error_code}, Error: {error_msg}")
            
            # Cập nhật lại giá hiện tại cho lần thử tiếp theo (quan trọng cho lệnh thị trường)
            if not use_pending_order:
                tick = mt5.symbol_info_tick(self.symbol)
                if tick:
                    if signal.lower() == "buy":
                        request["price"] = tick.ask
                    else:
                        request["price"] = tick.bid
            
            # Đợi một chút trước khi thử lại (tránh spam server)
            time.sleep(0.5)
        
        # Nếu vượt quá max_retries hoặc bot bị dừng
        if retry_count >= max_retries:
            print(f"❌ Order failed after {max_retries} attempts")
            logger.error(f"Order failed after {max_retries} attempts")
        else:
            print(f"⚠️ Order cancelled - bot stopped")
            logger.warning("Order cancelled - bot stopped")
        
        return result


    def estimate_pl(self, signal: str, entry_price: float, lot_override: float | None = None) -> dict:
        """Ước lượng tối giản: chỉ kiểm tra đủ/thiếu margin cho lệnh sắp đặt.

        Trả về: { 'allowed_by_margin': bool }
        """
        try:
            si = mt5.symbol_info(self.symbol)
            if si is None:
                return {}
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                return {}
            side = str(signal).lower()
            if side == 'buy':
                order_type = mt5.ORDER_TYPE_BUY
            elif side == 'sell':
                order_type = mt5.ORDER_TYPE_SELL
            else:
                return {}

            lot = float(lot_override) if lot_override is not None else float(self.lot_size)
            ep = float(entry_price)

            account = mt5.account_info()
            required_margin = mt5.order_calc_margin(order_type, self.symbol, lot, ep)
            free_margin = float(account.free_margin) if account else None

            allowed_by_margin = True
            if required_margin is not None and free_margin is not None:
                allowed_by_margin = free_margin >= required_margin

            return { 'allowed_by_margin': allowed_by_margin }
        except Exception:
            return {}

    def check_max_loss_pct(self, signal: str, entry_price: float, stop_loss: float | None, lot_override: float | None = None) -> tuple[bool, float | None]:
        """Kiểm tra % thua tối đa của lệnh có <= max_loss_pct người dùng đặt hay không.

        - lot_override: nếu cung cấp, dùng lot này để tính rủi ro; mặc định dùng self.lot_size.
        - Trả về (is_ok, risk_percent). Nếu thiếu dữ liệu hoặc lỗi → (True, None).
        """
        try:
            if self.max_loss_pct is None or stop_loss is None:
                return True, None
            side = str(signal).lower()
            if side == 'buy':
                order_type = mt5.ORDER_TYPE_BUY
            elif side == 'sell':
                order_type = mt5.ORDER_TYPE_SELL
            else:
                return True, None

            lot = float(lot_override) if lot_override is not None else float(self.lot_size)
            ep = float(entry_price)
            sl = float(stop_loss)
            pl_sl = mt5.order_calc_profit(order_type, self.symbol, lot, ep, sl)
            if pl_sl is None or self.balance is None:
                return True, None
            potential_loss = abs(pl_sl)
            bal = float(self.balance)
            if bal <= 0:
                return False, 100.0
            risk_percent = potential_loss / bal * 100.0
            print(f"Calculated risk percent = {risk_percent}% (max allowed {self.max_loss_pct}%)")
            logger.info(f"Calculated risk percent = {risk_percent}% (max allowed {self.max_loss_pct}%)")
            return (risk_percent <= float(self.max_loss_pct)), risk_percent
        except Exception:
            return True, None

    @staticmethod
    def _distance(a: float, b: float) -> float:
        return abs(float(a) - float(b))

    def check_rr(self, entry_price: float, stop_loss: float | None, take_profit: float | None) -> tuple[bool, float | None]:
        """Kiểm tra tỉ lệ R:R có >= rr người dùng đặt không.

        Trả về (is_ok, rr_value). Nếu không đủ dữ liệu (thiếu SL/TP hoặc rr chưa cấu hình) → (True, None).
        """
        try:
            if self.rr is None or stop_loss is None or take_profit is None:
                return True, None
            ep = float(entry_price)
            sl = float(stop_loss)
            tp = float(take_profit)
            risk = self._distance(ep, sl)
            if risk <= 0:
                return False, None
            reward = self._distance(tp, ep)
            rr_value = reward / risk 
            print(f"Calculated R:R = {rr_value} (required >= {self.rr})")
            logger.info(f"Calculated R:R = {rr_value} (required >= {self.rr})")
            return (rr_value >= float(self.rr)), rr_value
        except Exception:
            return True, None

    # ===== Lot sizing helpers =====
    @staticmethod
    def _round_lot_to_step(lot: float, step: float, min_lot: float) -> float:
        if step <= 0:
            return max(lot, min_lot)
        steps = int((lot - min_lot) / step + 1e-9)
        return max(min_lot, round(min_lot + steps * step, 8))
    
    def calculate_lot_from_max_loss(self, signal: str, entry_price: float, stop_loss: float) -> float | None:
        """Tính lot size dựa trên max_loss_per_trade (USD) và stop loss.
        
        Returns:
            lot size (float) nếu tính được, None nếu có lỗi
        """
        try:
            if self.max_loss_per_trade is None or stop_loss is None:
                return None
            
            si = mt5.symbol_info(self.symbol)
            if si is None:
                return None
            
            side = str(signal).lower()
            if side == 'buy':
                order_type = mt5.ORDER_TYPE_BUY
            elif side == 'sell':
                order_type = mt5.ORDER_TYPE_SELL
            else:
                return None
            
            ep = float(entry_price)
            sl = float(stop_loss)
            
            # Tính contract size cần thiết để loss = max_loss_per_trade
            # profit = (close_price - open_price) * contract_size * contract_size_per_lot
            # loss = (sl - ep) * contract_size (for buy), (ep - sl) * contract_size (for sell)
            # contract_size = max_loss_per_trade / |ep - sl| / contract_size_per_lot
            
            min_lot = float(si.volume_min)
            max_lot = float(si.volume_max)
            step = float(si.volume_step) if si.volume_step else 0.01
            
            # Thử từng lot size và tính P/L tại SL
            # Bắt đầu từ min lot, tăng dần cho đến khi loss >= max_loss_per_trade
            lot_try = min_lot
            best_lot = min_lot
            
            while lot_try <= max_lot:
                pl_at_sl = mt5.order_calc_profit(order_type, self.symbol, lot_try, ep, sl)
                if pl_at_sl is None:
                    break
                    
                potential_loss = abs(pl_at_sl)
                
                if potential_loss <= float(self.max_loss_per_trade):
                    best_lot = lot_try
                    lot_try = round(lot_try + step, 8)
                else:
                    # Vượt quá max loss, dừng lại
                    break
            
            # Round về step gần nhất
            final_lot = self._round_lot_to_step(best_lot, step, min_lot)
            print(f"💰 Calculated lot from max loss ${self.max_loss_per_trade}: {final_lot}")
            logger.info(f"Calculated lot from max loss ${self.max_loss_per_trade}: {final_lot}")
            
            return final_lot
            
        except Exception as e:
            print(f"Error calculating lot from max loss: {e}")
            logger.error(f"Error calculating lot from max loss: {e}", exc_info=True)
            return None

    def suggest_safe_lot(self, signal: str, entry_price: float, stop_loss: float | None) -> tuple[bool, float]:
        """Gợi ý lot tạm thời an toàn theo max_loss_pct, giảm theo volume_step đến tối thiểu.

        - Không thay đổi self.lot_size (giữ nguyên cấu hình người dùng cho lần chạy sau).
        - Trả về (True, lot_to_use) nếu tìm được lot thỏa điều kiện; (False, last_lot) nếu không thể.
        """
        try:
            user_lot = float(self.lot_size)
            if self.max_loss_pct is None or stop_loss is None:
                return True, user_lot
            si = mt5.symbol_info(self.symbol)
            if si is None:
                return True, user_lot
            min_lot = float(si.volume_min)
            step = float(si.volume_step) if si.volume_step else 0.01

            # Bắt đầu từ lot của người dùng → nếu rủi ro vượt quá, giảm dần theo step
            lot_try = self._round_lot_to_step(user_lot, step, min_lot)
            while lot_try >= min_lot - 1e-9:
                ok_risk, rp = self.check_max_loss_pct(signal, entry_price, stop_loss, lot_override=lot_try)
                if ok_risk:
                    return True, lot_try
                # giảm 1 step
                lot_try = round(lot_try - step, 8)
                # chặn dưới min lot
                if lot_try < min_lot:
                    break
            # không thể tìm lot thỏa điều kiện
            return False, max(min_lot, 0.0)
        except Exception:
            return True, float(self.lot_size)

    @staticmethod
    def is_symbol_trading(symbol: str) -> str:
        """Kiểm tra symbol có đang được trade (có lệnh mở hoặc lệnh chờ) hay không.

        Trả về:
          - "yes": nếu có position mở hoặc order chờ cho symbol
          - "no": ngược lại hoặc lỗi
        """
        try:
            positions = mt5.positions_get(symbol=symbol) or []
            orders = mt5.orders_get(symbol=symbol) or []
            return "yes" if (len(positions) > 0 or len(orders) > 0) else "no"
        except Exception:
            return "no"

    def run(self):
        while self.runflag :
            print(f"{self._utc7_now_dt()} - Running... Balance: {self.balance}")
            if not mt5.initialize():
                print("MT5 initialize failed, retrying in 10s...")
                logger.error("MT5 initialize failed, retrying in 10s...")
                time.sleep(10)
                continue
            logger.info(f"Running... Balance: {self.balance}")
            if self.balance <= 0:
                return "Balance not enough"
            if self.is_symbol_trading(self.symbol) == "yes":
                print(f"{self._utc7_now_dt()} - Existing position/order found for {self.symbol}, skipping this round.")
                logger.info(f"Existing position/order found for {self.symbol}, skipping this round.")
                time.sleep(1)
                continue
            if(self.flag_oder_open==True and self._save_recent_closed_deals()==True):  
                self.flag_oder_open=False
            # Chỉ chạy khi nến UTC+7 vừa kết thúc
            if not self.is_candle_close_ready():
                time.sleep(0.3)
                continue
            try:    
                payload = self._build_payload()
                print(f"{self._utc7_now_dt()} - Payload built, calling AI...")
                logger.info(f"{self._utc7_now_dt()} - Running... Balance: {self.balance}")
                logger.info("Payload built, calling AI...")
                print(f"current price: {payload['current_price']}")
                logger.debug(f"current price: {payload['current_price']}")
                # Gọi AI để lấy quyết định
                decision_raw = self._call_ai(payload)
                decision = self._validate_decision(decision_raw)
                print(f"{self._utc7_now_dt()} - AI Decision: {decision}")
                logger.info(f"AI Decision: {decision}")
                signal = decision["signal"]
                entry_price = decision.get("entry_price")
                stop_loss = decision.get("stop_loss")
                take_profit = decision.get("take_profit")
                pending_timeout_sec = decision.get("pending_timeout_sec")
                if signal=="hold":
                    print(f"{self._utc7_now_dt()} - AI decided to hold, skipping order placement.")
                    logger.info("AI decided to hold, skipping order placement.")
                    continue
                elif (entry_price is None or stop_loss is None or signal not in ['buy', 'sell'] or take_profit is None or pending_timeout_sec is None) or (2>abs(entry_price-stop_loss) or abs(entry_price-stop_loss)>4):
                    print(f"{self._utc7_now_dt()} - Incomplete decision data, skipping order placement.")
                    logger.warning("Incomplete decision data, skipping order placement.")
                    continue
                place_order_result = self._place_order(signal, entry_price, stop_loss, take_profit, pending_timeout_sec)
                print(f"{self._utc7_now_dt()} - Order placement result: {place_order_result}")
                logger.info(f"Order placement result: {place_order_result}")
                
                # Lưu payload nếu đặt lệnh thành công
                if place_order_result and hasattr(place_order_result, 'retcode') and place_order_result.retcode == mt5.TRADE_RETCODE_DONE:
                    self._last_payload = payload
                    print(f"Order successful, saved payload with indicators")
                    logger.info("Order successful, saved payload with indicators")
                    self.flag_oder_open=True
                    time.sleep(3)
                
                if place_order_result == "Balance not enough" :
                    return "Balance not enough"
                elif place_order_result == "Margin not enough":
                    return "Margin not enough"
                elif place_order_result == "RR not enough":
                    print(f"{self._utc7_now_dt()} - RR check failed, Wait request after.")
                    logger.warning("RR check failed, wait request after.")
                    continue
                # After placing order, attempt to capture any just-closed deals as well
                
            except Exception as e:
                print(f"AI trade loop error: {e}")
                logger.error(f"AI trade loop error: {e}", exc_info=True)
                time.sleep(1)
                continue
                
    



    # ===== Helpers to persist closed trades to CSV =====
    def _map_symbol_key(self) -> str | None:
        """Map current broker symbol to a logical key in SYMBOLS for any symbol.

        Strategy:
        - Exact match against SYMBOLS values → return its key
        - Compare base name (strip broker suffix like 'c','m', or any non A-Z tail) for both
        - Fallback: prefix/startswith checks on base name
        """
        try:
            # 1) Exact value match
            for key, val in SYMBOLS.items():
                if val == self.symbol:
                    return key

            # 2) Normalize to base by stripping non-capital-letter tail (broker suffix)
            def base_name(s: str) -> str:
                return re.sub(r"[^A-Z]+$", "", s or "")

            self_base = base_name(self.symbol)
            if not self_base:
                return None

            # 2a) Compare normalized bases
            for key, val in SYMBOLS.items():
                if base_name(val) == self_base:
                    return key

            # 3) Fallback prefix checks
            for key, val in SYMBOLS.items():
                vb = base_name(val)
                if vb.startswith(self_base) or self_base.startswith(vb):
                    return key
        except Exception:
            return None
        return None

    @staticmethod
    def _tf_to_str(tf_sec: int) -> str:
        mapping = {60: "M1", 300: "M5", 900: "M15", 1800: "M30", 3600: "H1", 14400: "H4", 86400: "D1"}
        return mapping.get(int(tf_sec), "M5")

    def _save_recent_closed_deals(self):
        """Only persist the most recent closed deal for this symbol (no duplicates)."""
        self.count_save_history+=1
        if self.count_save_history==10:
            self.count_save_history=0
            return True
        try:
            # Lấy lịch sử giao dịch bằng giờ UTC
            time.sleep(1)
            now_utc = datetime.now()
            since_utc = now_utc - timedelta(seconds=max(15, int(self.poll_interval_sec) * 2))
            print(f"Since UTC: {since_utc}, Now UTC: {now_utc}")
            logger.debug(f"Since UTC: {since_utc}, Now UTC: {now_utc}")
            deals = mt5.history_deals_get(since_utc, now_utc) or []
            print(f"Found {len(deals)} deals")
            logger.debug(f"Found {len(deals)} deals")
            print(deals)
            logger.debug(f"Deals: {deals}")
        except Exception as e:
            print(f"Error getting deals: {e}")
            logger.error(f"Error getting deals: {e}", exc_info=True)
            return False
            
        if not deals:
            print("No deals found")
            logger.debug("No deals found")
            return False
        # Pick the newest closed deal for this symbol
        try:
            closed = [d for d in deals if getattr(d, 'symbol', None) == self.symbol and getattr(d, 'entry', None) == mt5.DEAL_ENTRY_OUT]
            print(f"Found {len(closed)} closed deals for {self.symbol}")
            logger.debug(f"Found {len(closed)} closed deals for {self.symbol}")
        except Exception as e:
            print(f"Error filtering closed deals: {e}")
            logger.error(f"Error filtering closed deals: {e}", exc_info=True)
            closed = []
            
        if not closed:
            print("No closed deals found for this symbol")
            logger.debug("No closed deals found for this symbol")
            return False
            
        # Một số môi trường có thể không có field 'time' → fallback dùng 'time_msc' nếu có
        def _deal_time(deal):
            try:
                t = getattr(deal, 'time', None)
                if t is None:
                    t = getattr(deal, 'time_msc', None)
                return int(t) if t is not None else 0
            except Exception:
                return 0
                
        d = max(closed, key=_deal_time)
        print(f"Selected deal: ticket={getattr(d, 'ticket', 'N/A')}, profit={getattr(d, 'profit', 'N/A')}")
        logger.debug(f"Selected deal: ticket={getattr(d, 'ticket', 'N/A')}, profit={getattr(d, 'profit', 'N/A')}")

        try:
            deal_ticket = getattr(d, 'ticket', None)
            if deal_ticket is None:
                print("Deal ticket is None, skipping")
                logger.warning("Deal ticket is None, skipping")
                return
            if deal_ticket in self._saved_deal_ids:
                print(f"Deal {deal_ticket} already saved, skipping")
                logger.debug(f"Deal {deal_ticket} already saved, skipping")
                return

            # Try to find the open leg to recover entry info
            position_id = getattr(d, 'position_id', None)
            entry_price = None
            entry_time = None
            side_text = ""
            
            if position_id is not None:
                try:
                    # Tìm deals mở bằng UTC
                    deals_open = mt5.history_deals_get(now_utc - timedelta(days=7), now_utc) or []
                    opens = [x for x in deals_open if getattr(x, 'position_id', None) == position_id and getattr(x, 'entry', None) == mt5.DEAL_ENTRY_IN]
                    if opens:
                        open_leg = sorted(opens, key=_deal_time)[0]
                        entry_price = float(open_leg.price)
                        ot = getattr(open_leg, 'time', None)
                        if ot is None:
                            ot = getattr(open_leg, 'time_msc', None)
                        # Chuyển từ UTC sang UTC+7 để lưu
                        entry_time = datetime.fromtimestamp(int(ot), tz=timezone.utc) + timedelta(hours=7)
                        side_text = 'Buy' if int(open_leg.type) == mt5.DEAL_TYPE_BUY else 'Sell'
                        print(f"Found open leg: price={entry_price}, time={entry_time}, side={side_text}")
                        logger.debug(f"Found open leg: price={entry_price}, time={entry_time}, side={side_text}")
                except Exception as e:
                    print(f"Error finding open leg: {e}")
                    logger.error(f"Error finding open leg: {e}", exc_info=True)

            if entry_price is None:
                try:
                    entry_price = float(getattr(d, 'price', 0.0))
                    print(f"Using deal price as entry: {entry_price}")
                    logger.debug(f"Using deal price as entry: {entry_price}")
                except Exception:
                    entry_price = 0.0
                    
            if entry_time is None:
                dt = getattr(d, 'time', None)
                if dt is None:
                    dt = getattr(d, 'time_msc', int(now_utc.timestamp()))
                # Chuyển từ UTC sang UTC+7 để lưu
                entry_time = datetime.fromtimestamp(int(dt), tz=timezone.utc) + timedelta(hours=7)
                print(f"Using deal time as entry: {entry_time}")
                logger.debug(f"Using deal time as entry: {entry_time}")
                
            if not side_text:
                try:
                    side_text = 'Buy' if int(getattr(d, 'type', -1)) == mt5.DEAL_TYPE_BUY else 'Sell'
                    print(f"Using deal type as side: {side_text}")
                    logger.debug(f"Using deal type as side: {side_text}")
                except Exception:
                    side_text = ''

            lot = float(getattr(d, 'volume', 0.0))
            profit = float(getattr(d, 'profit', 0.0))
            self.balance += profit
            update_eqity_running(symbol=self.symbol,profit=profit,trading_type='realtime')
            win_flag = 1 if profit >= 0 else 0

            # Lấy thông tin từ AI decision và payload đã lưu
            ai_sl = self._last_ai_decision.get('stop_loss', '') if self._last_ai_decision else ''
            ai_tp = self._last_ai_decision.get('take_profit', '') if self._last_ai_decision else ''
            
            # Lấy các chỉ báo kỹ thuật từ payload
            indicators = self._last_payload.get('indicators', {}) if self._last_payload else {}
            rsi = indicators.get('RSI', '')
            macd = indicators.get('MACD', {}) if isinstance(indicators.get('MACD', {}), dict) else {}
            macd_value = macd.get('value', '')
            macd_signal = macd.get('signal', '')
            macd_histogram = macd.get('histogram', '')
            ema_50 = indicators.get('EMA_50', '')
            ema_200 = indicators.get('EMA_200', '')
            bb = indicators.get('BollingerBands', {}) if isinstance(indicators.get('BollingerBands', {}), dict) else {}
            bb_upper = bb.get('upper', '')
            bb_middle = bb.get('middle', '')
            bb_lower = bb.get('lower', '')
            atr14 = indicators.get('ATR14', '')

            row = [{
                'Datetime_entry': entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                'Time_frame': self._tf_to_str(self.timeframe_sec),
                'Sell/Buy': side_text,
                'Entry_price': entry_price,
                'Stop_loss': ai_sl,
                'Take_profit': ai_tp,
                'RSI': rsi,
                'MACD_value': macd_value,
                'MACD_signal': macd_signal,
                'MACD_histogram': macd_histogram,
                'EMA_50': ema_50,
                'EMA_200': ema_200,
                'BB_upper': bb_upper,
                'BB_middle': bb_middle,
                'BB_lower': bb_lower,
                'ATR14': atr14,
                'Lot': lot,
                'Profit': profit,
                'Win': win_flag,
            }]

            print(f"Saving deal to CSV: {row[0]}")
            logger.debug(f"Saving deal to CSV: {row[0]}")
            name_ai = self.ai_client.ai_name_model or 'ai_model'
            # Thêm AI name vào row data
            row[0]['AI'] = name_ai.strip()
            save_trade_history_csv_files(self.symbol, row, name_ai)
            self._saved_deal_ids.add(deal_ticket)
            print(f"Successfully saved deal {deal_ticket}")
            logger.info(f"Successfully saved deal {deal_ticket}")
            return True
            
        except Exception as e:
            print(f"Error saving deal: {e}")
            logger.error(f"Error saving deal: {e}", exc_info=True)
            import traceback
            traceback.print_exc()
# if __name__ == "__main__":
#     # Normal trading example - set your API key via environment variable or key_api.txt
#     trader = LiveTradeAI("BTCUSDm", 1000, 1, 100,
#                          ai_name_model="gpt-4o-mini",
#                          ai_endpoint="https://api.openai.com/v1/responses",
#                          ai_key="YOUR_OPENAI_API_KEY_HERE",  # Use env var: os.getenv("OPENAI_API_KEY")
#                          rr=1, max_loss_pct=2, timeframe_sec=60, trading_type="normal")
#     trader.run()
#
# Scalping trading example
# trader = LiveTradeAI("BTCUSDm", 1000, 0.1, 100,
#                         ai_name_model="gpt-4o-mini",
#                         ai_endpoint="https://api.openai.com/v1/responses",
#                         ai_key="YOUR_OPENAI_API_KEY_HERE",  # Use env var: os.getenv("OPENAI_API_KEY")
#                         rr=2.0, max_loss_pct=100, timeframe_sec=60, trading_type="scalping")
# trader.run()