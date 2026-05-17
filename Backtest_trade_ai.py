import time
import json
import pandas as pd
from collections import deque
import logging
import logging.config
import yaml
import os
from Build_PayLoad import TradingPayloadBuilder
from scalping_payload import ScalpingPayloadBuilder
from utils_logs import update_eqity_running
from utlls_save_history import save_trade_history_csv_files
import MetaTrader5 as mt5
from ai_client import AIClient

# Setup logging
try:
    config_path = os.path.join(os.path.dirname(__file__), "config", "backtest_trade_ai_logging.yaml")
    with open(config_path, "r") as file:
        logging_config = yaml.safe_load(file)
        logging.config.dictConfig(logging_config)
    logger = logging.getLogger("backtest_trade_ai")
    logger.info("BacktestTradeAI logging initialized successfully")
except Exception as e:
    # Fallback logging
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("backtest_trade_ai")
    logger.warning(f"Failed to load logging config: {e}, using basic logging")


class BacktestTradeAI:
    """Backtest trading using external AI model API with historical data.

    - Similar to LiveTradeAI but works with historical data
    - Builds payload via TradingPayloadBuilder with custom data
    - Calls AI endpoint to get decision with structure:
        {
          "signal": "buy"|"sell"|"hold",
          "entry_price": float | None,
          "stop_loss": float | None,
          "take_profit": float | None,
          "confidence": float
        }
    - Simulates market orders with SL/TP for backtesting
    - Applies optional R:R (rr) when TP is missing
    - Optionally checks max_loss_pct against balance
    """

    def __init__(self, symbol: str, balance: float, lot_size: float, leverage: int, 
                 ai_name_model: str, ai_endpoint: str, ai_key: str, 
                 data: pd.DataFrame = None, rr: float | None = None, 
                 max_loss_pct: float | None = None, poll_interval_sec: int = 5, 
                 timeframe_sec: int = 60, trading_type: str = "scalping",
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
        self._last_candle_ts = None  # epoch seconds (UTC+7) của nến đã xử lý gần nhất
        self.trading_type = trading_type.lower()
        self.price_open = None  
        
        # Initialize AI Client
        self.ai_client = AIClient(
            ai_endpoint=ai_endpoint,
            ai_key=ai_key,
            ai_name_model=ai_name_model,
            symbol=self.symbol,
            timeframe_sec=self.timeframe_sec,
            rr=self.rr
        )
        
        # Backtest specific attributes
        self.original_data = data  # Original historical data
        self.current_index = 0  # Start from 0 for remaining data
        self.is_trading = False  # Flag to track if symbol is currently in a trade
        
        # Initialize deque and remaining data
        self.deque_data = None
        self.remaining_data = None
        self.payload_builder = None
        # Initialize pending_timeout_sec
        self.pending_timeout_sec = 0  # Default timeout is 10 seconds
        self.order_type = None  # Track current order type (buy/sell)
        self.entry_price = None  # Track entry price for current trade
        self.stop_loss = None  # Track stop loss for current trade
        self.take_profit = None  # Track take profit for current trade
        self.time_place_order = 0  # Track time when order was placed
        self.order_success = False  # Track if last order was successful
        self.check_order_candle_current = True  # Track candle index when order was placed
        self.entry_time=None
        self.win=None
        self.profit=None
        self.lot_to_use=self.lot_size
        
        if data is not None:
            # Split data: first 200 for deque, rest for simulation
            print(f"Original data shape: {data.shape}")
            logger.info(f"Original data shape: {data.shape}")
            print(f"Symbol:{self.symbol} Data head:\n{data.head()}")
            logger.debug(f"Symbol:{self.symbol} Data head:\n{data.head()}")
            if len(data) > 200:
                # Determine required data size based on trading type
                if self.trading_type == "scalping":
                    # Scalping needs less data (100 rows for indicators)
                    required_data_size = 100
                    initial_data = data.iloc[:required_data_size].copy()
                    self.remaining_data = data.iloc[required_data_size:].copy().reset_index(drop=True)
                    self.deque_data = deque(maxlen=required_data_size)
                else:
                    # Normal trading needs 200 rows for indicators
                    required_data_size = 200
                    initial_data = data.iloc[:required_data_size].copy()
                    self.remaining_data = data.iloc[required_data_size:].copy().reset_index(drop=True)
                    self.deque_data = deque(maxlen=required_data_size)
                
                # Initialize deque with initial data
                for _, row in initial_data.iterrows():
                    self.deque_data.append(row.to_dict())
                
                # Create appropriate payload builder based on trading type
                if self.trading_type == "scalping":
                    # Convert timeframe_sec to MT5 timeframe constant for scalping
                    tf_const = mt5.TIMEFRAME_M1  # Scalping typically uses M1
                    if self.timeframe_sec == 300:
                        tf_const = mt5.TIMEFRAME_M5
                    elif self.timeframe_sec == 900:
                        tf_const = mt5.TIMEFRAME_M15
                    self.payload_builder = ScalpingPayloadBuilder(symbol=self.symbol, timeframe=tf_const, data=initial_data)
                    print(f"📊 Initialized ScalpingPayloadBuilder with {required_data_size} rows")
                    logger.info(f"Initialized ScalpingPayloadBuilder with {required_data_size} rows")
                else:
                    self.payload_builder = TradingPayloadBuilder(symbol=self.symbol, timeframe=self.timeframe_sec, data=initial_data)
                    print(f"📊 Initialized TradingPayloadBuilder with {required_data_size} rows")
                    logger.info(f"Initialized TradingPayloadBuilder with {required_data_size} rows")
                
                print(f"📊 Deque initialized with 200 rows, remaining data: {len(self.remaining_data)} rows")
                logger.info(f"Deque initialized with 200 rows, remaining data: {len(self.remaining_data)} rows")
            else:
                raise ValueError("❌ Need at least 201 rows of data (200 for indicators + 1 for simulation)")
        
        # Track saved deals to avoid duplicate writes
        self._saved_deal_ids: set[int] = set()
        # Store AI decision and payload for successful orders
        self._last_ai_decision: dict = {}
        self._last_payload: dict = {}

        print(f"🚀 BacktestTradeAI initialized: {symbol}, balance={balance}, lot={lot_size}")
        logger.info(f"BacktestTradeAI initialized: {symbol}, balance={balance}, lot={lot_size}")
        print(f"   AI: {self.ai_client.ai_name_model}, R:R={rr}, max_loss={max_loss_pct}%")
        logger.info(f"AI: {self.ai_client.ai_name_model}, R:R={rr}, max_loss={max_loss_pct}%")
        print(f"   Data mode: {'Historical' if data is not None else 'Real-time'}")
        logger.info(f"Data mode: {'Historical' if data is not None else 'Real-time'}")
        if data is not None:
            print(f"   Original data shape: {data.shape}")
            logger.debug(f"Original data shape: {data.shape}")
            print(f"   Deque size: {len(self.deque_data)}")
            logger.debug(f"Deque size: {len(self.deque_data)}")
            print(f"   Remaining data for simulation: {len(self.remaining_data)} rows")
            logger.debug(f"Remaining data for simulation: {len(self.remaining_data)} rows")
        if not mt5.initialize():
            raise RuntimeError("Cannot initialize MT5")

    def stop(self):
        """Stop the trading bot."""
        self.runflag = False
        print(f"🛑 BacktestTradeAI stopped for {self.symbol}")
        logger.info(f"BacktestTradeAI stopped for {self.symbol}")

    def is_running(self) -> bool:
        """Check if bot is still running."""
        return self.runflag

    def _should_check_new_candle(self) -> bool:
        """
        Backtest version: Check if we have more data to process
        """
        if self.remaining_data is None or self.payload_builder is None:
            return False  # No data, no processing
        return self.current_index < len(self.remaining_data)

    def _build_payload(self, news: bool = True) -> dict:
        """
        Build payload for AI decision making using deque data.
        
        Args:
            news: Include news data in payload (default True for backtest)
        """
        if self.payload_builder is None or self.deque_data is None:
            raise ValueError("❌ No payload builder or deque data available for backtest")
        
        try:
            # Convert deque back to DataFrame for payload builder
            deque_df = pd.DataFrame(list(self.deque_data))
            self.payload_builder.data = deque_df
            
            # Build payload based on trading type
            if self.trading_type == "scalping":
                payload = self.payload_builder.build_scalping_payload(price_open=self.price_open)
                print(f"🎯 Built scalping payload with {len(deque_df)} candles")
                logger.debug(f"Built scalping payload with {len(deque_df)} candles")
            else:
                payload = self.payload_builder.build_payload(news=False)
                print(f"📊 Built normal trading payload with {len(deque_df)} candles")
                logger.debug(f"Built normal trading payload with {len(deque_df)} candles")
            
            return payload
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
            risk_percent = round((potential_loss / bal * 100.0), 2)
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
            
            min_lot = float(si.volume_min)
            max_lot = float(si.volume_max)
            step = float(si.volume_step) if si.volume_step else 0.01
            
            # Thử từng lot size và tính P/L tại SL
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
                    break
            
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
                print(f"Trying lot {lot_try}: risk ok? {ok_risk}, risk percent: {rp}")
                logger.debug(f"Trying lot {lot_try}: risk ok? {ok_risk}, risk percent: {rp}")
                if ok_risk !=False:
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
    
    def place_order(self, signal: str, entry_price: float | None = None, 
                   stop_loss: float | None = None, take_profit: float | None = None ) -> bool:
        """
        Simulate order placement for backtesting.
        Different from LiveTradeAI - doesn't actually place MT5 orders.
        """
        # Nếu có max_loss_per_trade, tính lot size dựa trên đó trước
        if self.max_loss_per_trade is not None and stop_loss is not None and entry_price is not None:
            calculated_lot = self.calculate_lot_from_max_loss(signal=signal, entry_price=entry_price, stop_loss=stop_loss)
            if calculated_lot is not None:
                self.lot_size = calculated_lot
                print(f"📊 Updated lot_size to {self.lot_size} based on max_loss_per_trade ${self.max_loss_per_trade}")
                logger.info(f"Updated lot_size to {self.lot_size} based on max_loss_per_trade ${self.max_loss_per_trade}")
        
        try:
            ok_lot, self.lot_to_use = self.suggest_safe_lot(signal=signal, entry_price=entry_price, stop_loss=stop_loss)
            if not ok_lot:
                # Không thể tìm lot phù hợp → dừng bot symbol này
                return "Balance not enough"
        except Exception:
            self.lot_to_use = float(self.lot_size)

        # Apply R:R logic
        rr_valid, adjusted_tp = self.check_rr(entry_price, stop_loss, take_profit)
        if not rr_valid:
            print(f"❌ R:R validation failed")
            logger.warning("R:R validation failed")
            return False
        # Simulate order placement
        order_type = "Buy" if signal.lower() == "buy" else "Sell"
        self.order_type = order_type  # Track current order type
        print(f"📈 BACKTEST ORDER: {order_type} {self.lot_size} {self.symbol} @ {entry_price}")
        logger.info(f"BACKTEST ORDER: {order_type} {self.lot_size} {self.symbol} @ {entry_price}")
        self._last_ai_decision = {
                'signal': signal,
                'entry_price': entry_price,
                'stop_loss': stop_loss,
                'take_profit': take_profit
            }
        print(f"Order successful, saved AI decision: {self._last_ai_decision}")
        logger.info(f"Order successful, saved AI decision: {self._last_ai_decision}")
        # self._last_order = {
        #     "symbol": self.symbol,
        #     "type": order_type,
        #     "volume": self.lot_size,
        #     "price": current_price,
        #     "sl": stop_loss,
        #     "tp": take_profit,
        #     "time": datetime.now(),
        #     "index": self.current_index if self.data is not None else None
        # }      
        return True
    def check_entryprice_in_currentprice(self):
        price_open = self.remaining_data.iloc[self.current_index]['open']
        self.entry_time=self.remaining_data.iloc[self.current_index]['time']
        print(f"Checking entry price {self.entry_price} against current open price {price_open}")
        logger.debug(f"Checking entry price {self.entry_price} against current open price {price_open}")
        flag_compare = 1 if price_open > self.entry_price  else 0 if self.entry_price == price_open else -1
        print(f"flag_compare: {flag_compare}")
        logger.debug(f"flag_compare: {flag_compare}")
        if flag_compare == 1:
            print("Currently in profit.")
            logger.debug("Currently in profit.")
            price_low_current = self.remaining_data.iloc[self.current_index]['low']
            print(f"price_low_current: {price_low_current}, self.entry_price: {self.entry_price}")
            logger.debug(f"price_low_current: {price_low_current}, self.entry_price: {self.entry_price}")
            if price_low_current<=self.entry_price:
                self.is_trading = True
        elif flag_compare == 0:
            print("Currently at break-even.")
            logger.debug("Currently at break-even.")
            self.is_trading = True
        else:
            print("Currently in loss.")
            logger.debug("Currently in loss.")
            price_high_current = self.remaining_data.iloc[self.current_index]['high']
            print(f"price_high_current: {price_high_current}, self.entry_price: {self.entry_price}")
            logger.debug(f"price_high_current: {price_high_current}, self.entry_price: {self.entry_price}")
            if price_high_current>=self.entry_price:
                self.is_trading = True
        if self.is_trading:
            print("Trade is now active.")
            logger.info("Trade is now active.")
            self.time_place_order = 0
            self.pending_timeout_sec = 0
        return self.is_trading

    # Calculate equity running
    def calculate_equity_running(self):
        # Calculate equity based on current price and open position
        current_price = self.remaining_data.iloc[self.current_index]['open']
        if self.is_trading and self.entry_price is not None:
            if self.order_type == "Buy":
                order_type = mt5.ORDER_TYPE_BUY
            else:  # SELL
                order_type = mt5.ORDER_TYPE_SELL
            total_profit = mt5.order_calc_profit(order_type, self.symbol, self.lot_size, self.entry_price, current_price)
            equity = self.balance + total_profit
        else:
            equity = self.balance
        return equity
    
    #Check take profit hit
    def check_takeprofit_hit(self):
        if self.order_type=="Buy":
            print("Currently in a BUY trade.")
            print("Trade is still active.")
            price_high_current = self.remaining_data.iloc[self.current_index]['high']
            print(f"self.take_profit: {self.take_profit}, price_high_current: {price_high_current}")
            logger.debug(f"self.take_profit: {self.take_profit}, price_high_current: {price_high_current}")
            if self.take_profit<=price_high_current:
                total_profit = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, self.symbol, self.lot_size, self.entry_price, self.take_profit)
                self.balance+=total_profit
                self.profit=total_profit
                self.win=True
                self.is_trading = False
                print("🎯 Take Profit hit, trade exited.")
                return True
        elif self.order_type=="Sell":
            print("Currently in a SELL trade.")                     
            print("Trade is still active.")
            price_low_current = self.remaining_data.iloc[self.current_index]['low']
            print(f"self.take_profit: {self.take_profit}, price_low_current: {price_low_current}")
            logger.debug(f"self.take_profit: {self.take_profit}, price_low_current: {price_low_current}")
            if self.take_profit>=price_low_current:
                total_profit =mt5.order_calc_profit(mt5.ORDER_TYPE_SELL, self.symbol, self.lot_size, self.entry_price, self.take_profit)
                self.balance+=total_profit
                self.profit=total_profit
                self.win=True
                self.is_trading = False
                print("🎯 Take Profit hit, trade exited.")
                return True
        return False
    
    #Check stop loss hit
    def check_stoploss_hit(self):
        if self.order_type=="Buy":
            print("Currently in a BUY trade.")
            logger.debug("Currently in a BUY trade.")
            print("Trade is still active.")
            logger.debug("Trade is still active.")
            price_low_current = self.remaining_data.iloc[self.current_index]['low']
            print(f"self.stop_loss: {self.stop_loss}, price_low_current: {price_low_current}")
            logger.debug(f"self.stop_loss: {self.stop_loss}, price_low_current: {price_low_current}")
            if self.stop_loss>=price_low_current:
                total_loss = mt5.order_calc_profit(mt5.ORDER_TYPE_BUY, self.symbol, self.lot_size, self.entry_price, self.stop_loss)
                self.balance+=total_loss
                self.profit=total_loss
                print(f"self.profit: {self.profit}")
                logger.debug(f"self.profit: {self.profit}")
                self.win=False
                self.is_trading = False
                print("🛑 Stop Loss hit, trade exited.")
                logger.info("Stop Loss hit, trade exited.")
                return True
        elif self.order_type=="Sell":
            print("Currently in a SELL trade.")                     
            print("Trade is still active.")
            price_high_current = self.remaining_data.iloc[self.current_index]['high']
            print(f"self.stop_loss: {self.stop_loss}, price_high_current: {price_high_current}")
            logger.debug(f"self.stop_loss: {self.stop_loss}, price_high_current: {price_high_current}")
            if self.stop_loss<=price_high_current:
                total_loss = mt5.order_calc_profit(mt5.ORDER_TYPE_SELL, self.symbol, self.lot_size, self.entry_price, self.stop_loss)
                self.balance+=total_loss
                self.profit=total_loss
                self.win=False
                self.is_trading = False
                print(f"self.profit: {self.profit}")
                logger.debug(f"self.profit: {self.profit}")
                print("🛑 Stop Loss hit, trade exited.")
                logger.info("Stop Loss hit, trade exited.")
                return True
        return False
    
    # check hit and print equity running
    def check_hit_and_print_equity(self):
        flag=True
        if self.check_stoploss_hit():
            print("Trade exited after Stop Loss hit.")
            logger.info("Trade exited after Stop Loss hit.")
            self._save_recent_closed_deals()
            update_eqity_running(self.symbol, self.profit,trading_type="backtest")
            flag=False
            self.reset_trade_state()
            print(f"Updated Balance: {self.balance:.2f}")
        elif self.check_takeprofit_hit():
            print("Trade exited after Take Profit hit.")
            logger.info("Trade exited after Take Profit hit.")
            self._save_recent_closed_deals()
            update_eqity_running(self.symbol, self.profit,trading_type="backtest")
            flag=False
            self.reset_trade_state()
            print(f"Updated Balance: {self.balance:.2f}")
        
        if flag and self.is_trading==True:
            print("Trade still active after placement.")
            logger.debug("Trade still active after placement.")
            equity = self.calculate_equity_running()
            # Print current equity
            print(f"Current Equity: {equity:.2f}")
        

    def reset_trade_state(self):
        self.is_trading = False
        self.order_success = False
        self.check_order_candle_current = True
        self.time_place_order = 0
        self.pending_timeout_sec = 0
        self.entry_price = None
        self.stop_loss = None
        self.take_profit = None
        self.order_type = None
        self.entry_time=None
        self.win=None
        self.profit=None


    def run(self):
        """
        Main backtest run loop.
        Chỉ chạy khi có historical data (data is not None).
        """
        if self.remaining_data is None:
            print("❌ BACKTEST ERROR: No historical data provided")
            logger.error("BACKTEST ERROR: No historical data provided")
            print("🛑 BacktestTradeAI requires data parameter - returning immediately")
            logger.error("BacktestTradeAI requires data parameter - returning immediately")
            return
        
        print(f"🎬 Starting backtest for {self.symbol}")
        print(f"📊 Processing {len(self.remaining_data)} remaining candles")
        print(f"🔧 Deque contains {len(self.deque_data)} candles for indicators calculation")
        self.time_place_order = 0
        self.pending_timeout_sec = 0  # Default timeout is 10 seconds
        self.is_trading = False  # Reset trading flag
        self.order_success = False  # Reset order success flag
        self.check_order_candle_current = True  # Reset candle check flag
        while self.runflag and self.current_index < len(self.remaining_data):
            try:
                if not mt5.initialize():
                    print("❌ MT5 re-initialization failed inside loop, stopping backtest")
                    logger.error("MT5 re-initialization failed inside loop, stopping backtest")
                    time.sleep(10)
                    continue
                if self.order_success == False and not self.is_trading:
                    # Build payload with updated deque data
                    self.price_open = self.remaining_data.iloc[self.current_index]['open']
                    print(f"timestamp for candle {self.current_index}: {self.remaining_data.iloc[self.current_index]['time']}")
                    print(f"Current open price for candle {self.current_index}: {self.price_open}")
                    payload = self._build_payload(news=False)  # Skip news for faster testing
                    self._last_payload = payload
                    
                    # Call AI for decision
                    decision_raw = self._call_ai(payload)
                    print(f"🔍 DEBUG - Raw AI response: {decision_raw}")
                    print(f"🔍 DEBUG - Response type: {type(decision_raw)}")
                    print(f"🔍 DEBUG - Response keys: {list(decision_raw.keys()) if isinstance(decision_raw, dict) else 'Not a dict'}")
                    decision = self._validate_decision(decision_raw)
                    
                    # Extract decision components
                    signal = decision["signal"]
                    entry_price = decision.get("entry_price")
                    stop_loss = decision.get("stop_loss")
                    take_profit = decision.get("take_profit")
                    pending_timeout_sec = decision.get("pending_timeout_sec") if decision.get("pending_timeout_sec") is not None else 300
                    print(f"🤖 AI decision: signal={signal}, entry_price={entry_price}, stop_loss={stop_loss}, take_profit={take_profit}, pending_timeout_sec={pending_timeout_sec}")
                    logger.info(f"AI decision: signal={signal}, entry_price={entry_price}, stop_loss={stop_loss}, take_profit={take_profit}, pending_timeout_sec={pending_timeout_sec}")
                    print(f"📊 decision: {decision}")

                    # Place order if signal is buy/sell
                    if signal == "hold":
                        print(f"⏸️ AI suggests HOLD")
                        logger.debug("AI suggests HOLD")
                    elif (entry_price is not None and stop_loss is not None and take_profit is not None and pending_timeout_sec is not None) and 2<=abs(entry_price-stop_loss)<=4 :
                        success = self.place_order(signal, entry_price, stop_loss, take_profit)
                        print(f"Order placement success: {success}")
                        if success == True:
                            print(f"✅ Order placed successfully")
                            logger.info("Order placed successfully")
                      # Simulate order processing time
                            self.entry_price = entry_price
                            self.stop_loss = stop_loss
                            self.take_profit = take_profit
                            self.pending_timeout_sec = pending_timeout_sec
                            self.order_success = True
                            if self.check_entryprice_in_currentprice():
                                self.check_hit_and_print_equity()
                                print("Trade is now active immediately after placement.")
                                logger.debug("Trade is now active immediately after placement.")
                                
                            else:
                                print("Trade not active after placement.")
                                logger.debug("Trade not active after placement.")
                                self.time_place_order += self.timeframe_sec
                                print(f"Set time_place_order = {self.time_place_order}")
                        elif success == "Balance not enough":
                            print(f"❌ Order placement failed")
                            logger.error("Order placement failed")
                            return self.stop()
                    else:
                        print(f"❌ Incomplete AI decision for order placement")
                        logger.warning("Incomplete AI decision for order placement")
                        time.sleep(1)
                        

                # Skip if already in trade (could implement exit logic here)
                current_candle = self.remaining_data.iloc[self.current_index]
                
                # Add current candle to deque (automatically removes oldest)
                self.deque_data.popleft()
                self.deque_data.append(current_candle.to_dict())
                print(f"len(self.deque_data): {len(self.deque_data)}")
                print(f"current_candle: {current_candle.to_dict()}")
                print(f"last price in deque: {self.deque_data[-1]['close']}")
                print(f"🔍 Processing candle {self.current_index + 1}/{len(self.remaining_data)}")
                print(f"📊 Current candle close: {self.remaining_data.iloc[self.current_index]['close']}")
                if self.order_success == False :
                    self.current_index += 1
                    continue
                if self.order_success == True and self.check_order_candle_current==True:
                    self.check_order_candle_current=False
                    self.current_index+=1
                    continue

                if self.order_success == True  and self.time_place_order > self.pending_timeout_sec:
                    print("⏰ Pending timeout exceeded, exiting trade.")
                    logger.warning("Pending timeout exceeded, exiting trade.")
                    self.reset_trade_state()
                    self.current_index += 1
                    continue
                elif self.order_success == True and self.time_place_order > 0:
                    print(f"⏳ Waiting for entry, time since order: {self.time_place_order} sec")
                    
                    if self.check_entryprice_in_currentprice():
                        print("Trade is now active during wait.")
                        logger.debug("Trade is now active during wait.")
                    else:
                        self.time_place_order += self.timeframe_sec
                        print(f"Incremented time_place_order to {self.time_place_order} sec")
                        self.current_index += 1
                        continue
                if self.is_trading:
                    self.check_hit_and_print_equity()
                    self.current_index += 1
                    # Simple exit logic: exit after N candles or on SL/TP
                    # This is simplified - real backtest would need proper exit logic
                    continue
                
                # Check if we should process this candle
                # if not self._should_check_new_candle():
                #     time.sleep(self.poll_interval_sec)
                #     continue

                
            except Exception as e:
                print(f"❌ Error in backtest loop: {e}")
                self.current_index += 1
                time.sleep(1)
                continue
        
        print(f"🏁 Backtest completed for {self.symbol}")
        print(f"📈 Processed {self.current_index} candles")
    

    @staticmethod
    def _tf_to_str(tf_sec: int) -> str:
        mapping = {60: "M1", 300: "M5", 900: "M15", 1800: "M30", 3600: "H1", 14400: "H4", 86400: "D1"}
        return mapping.get(int(tf_sec), "M5")

    def _save_recent_closed_deals(self):
        
                


        try:
            # Try to find the open leg to recover entry info


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
                'Datetime_entry': self.entry_time.strftime('%Y-%m-%d %H:%M:%S'),
                'Time_frame': self._tf_to_str(self.timeframe_sec),
                'Sell/Buy': self.order_type,
                'Entry_price': self.entry_price,
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
                'Lot': self.lot_size,
                'Profit': self.profit,
                'Win': self.win,
            }]

            print(f"Saving deal to CSV: {row[0]}")
            name_ai = self.ai_client.ai_name_model or 'ai_model'
            # Thêm AI name vào row data
            row[0]['AI'] = name_ai.strip()
            save_trade_history_csv_files(self.symbol, row, name_ai,"Backtest")
            
            
        except Exception as e:
            print(f"Error saving deal: {e}")
            time.sleep(1)
            import traceback
            traceback.print_exc()
# Example usage:
# import os

# data = pd.read_csv(os.path.join(os.path.dirname(__file__), "trade_history.csv"))
# print(f"Data shape: {data.shape}")
# # Convert time column to datetime
# if 'time' in data.columns:
#     data['time'] = pd.to_datetime(data['time'])
#     print(f"✅ Converted time column to datetime: {data['time'].dtype}")
# else:
#     print("⚠️ No time column found in data")
# backtest=BacktestTradeAI(
#     symbol="XAUUSDm",
#     balance=100000.0,
#     lot_size=0.01,
#     leverage=400000,
#     ai_name_model="gpt-4o-mini",
#     ai_endpoint="https://api.openai.com/v1/chat/completions",
#     ai_key="YOUR_OPENAI_API_KEY_HERE",  # Use env var: os.getenv("OPENAI_API_KEY")
#     data=data,
#     rr=0.5,
#     max_loss_pct=2.0,
#     poll_interval_sec=1,
#     timeframe_sec=300,
# )
# backtest.run()  # Runs the backtest loop
