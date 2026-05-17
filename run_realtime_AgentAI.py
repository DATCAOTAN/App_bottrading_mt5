"""
run_realtime_AgentAI.py - Real-time Trading sử dụng DDQN Agent

Chạy trading real-time với model DDQN (final_model.zip),
sử dụng MT5 API để lấy dữ liệu candle và thực hiện giao dịch.
Model quyết định action mỗi khi có candle mới.

Actions: 0=BUY, 1=SELL, 2=HOLD, 3=CLOSE
"""

import numpy as np
import pandas as pd
import os
import logging
import logging.config
import yaml
import time
import threading
from datetime import datetime, timedelta
from stable_baselines3 import DQN
import MetaTrader5 as mt5
from collections import deque

from utils_logs import update_eqity_running
from utlls_save_history import save_trade_history_csv_files

# ====== CONFIGURATION (giống Backtest_tradeAgentAI.py) ======
# --- Cài đặt Giao dịch ---
COMMISSION_PER_LOT_RAW = 7.0
AVG_SPREAD_GIA_RAW = 0.2
COMMISSION_PER_LOT_STANDARD = 0.0
AVG_SPREAD_GIA_STANDARD = 0.16

# --- Cài đặt Chung ---
PNL_MULTIPLIER = 100.0

# --- Cài đặt Môi trường ---
CATASTROPHE_SL_GIA = 20.0
CATASTROPHE_TP_GIA = 20.0

# --- Cài đặt Chỉ báo ---
RSI_PERIOD = 7
EMA_PERIOD = 21
ATR_PERIOD = 14
BBANDS_PERIOD = 20
VELOCITY_PERIOD = 3

# --- Số lượng candles cần để tính indicator ---
MIN_CANDLES_FOR_INDICATORS = 50

# Setup logging
try:
    config_path = os.path.join(os.path.dirname(__file__), "config", "realtime_agent_ai_logging.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as file:
            logging_config = yaml.safe_load(file)
            logging.config.dictConfig(logging_config)
        logger = logging.getLogger("realtime_agent_ai")
    else:
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("realtime_agent_ai")
    logger.info("RealtimeAgentAI logging initialized successfully")
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("realtime_agent_ai")
    logger.warning(f"Failed to load logging config: {e}, using basic logging")


def calculate_indicators(df):
    """Tính toán các chỉ báo kỹ thuật giống như trong training"""
    df = df.copy()
    
    # 1. EMA 21
    df['ema_21'] = df['close'].ewm(span=EMA_PERIOD, adjust=False).mean()
    
    # 2. RSI 7
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    loss = (-delta.where(delta < 0, 0)).ewm(alpha=1/RSI_PERIOD, adjust=False).mean()
    rs = gain / (loss + 1e-9)
    df['rsi_7'] = 100 - (100 / (1 + rs))
    
    # 3. Bollinger Bands 20 (std 2)
    sma_20 = df['close'].rolling(window=BBANDS_PERIOD).mean()
    std_20 = df['close'].rolling(window=BBANDS_PERIOD).std()
    df['BBU_20_2.0'] = sma_20 + (2 * std_20)
    df['BBL_20_2.0'] = sma_20 - (2 * std_20)
    df['bb_width'] = df['BBU_20_2.0'] - df['BBL_20_2.0']
    
    # 4. ATR 14
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges.values, axis=1)
    df['atr'] = pd.Series(true_range, index=df.index).ewm(alpha=1/ATR_PERIOD, adjust=False).mean()
    
    return df


def pre_process_data(df, type_account="Standard", lot_size: float = 0.01):
    """Tiền xử lý data giống như trong training"""
    if df is None or df.empty:
        return None
    
    logger.debug("Đang tính toán chỉ báo...")
    
    # Tính toán chỉ báo
    df = calculate_indicators(df)
    df = df.dropna()
    
    if df.empty:
        return None
    
    atr_in_gia = df['atr']
    df['price_velocity_short'] = (df['close'] - df['close'].shift(VELOCITY_PERIOD)) / (atr_in_gia + 1e-9)
    df['price_context_medium'] = (df['close'] - df['ema_21']) / (atr_in_gia + 1e-9)
    df['momentum_rsi'] = df['rsi_7'] / 100.0
    df['volatility_state'] = df['bb_width'] / (df['ema_21'] + 1e-9)
    
    if type_account == "Raw Spread":
        commission_per_lot = COMMISSION_PER_LOT_RAW
        avg_spread_gia = AVG_SPREAD_GIA_RAW
    else:
        commission_per_lot = COMMISSION_PER_LOT_STANDARD
        avg_spread_gia = AVG_SPREAD_GIA_STANDARD
    
    pnl_per_point_for_lot = PNL_MULTIPLIER * lot_size
    df['spread_cost_dollars'] = avg_spread_gia * pnl_per_point_for_lot
    commission_cost_dollars = commission_per_lot * (lot_size / 1.0)
    commission_cost_gia = commission_cost_dollars / (pnl_per_point_for_lot + 1e-9)
    total_cost_gia = avg_spread_gia + commission_cost_gia
    df['market_cost'] = total_cost_gia / (atr_in_gia + 1e-9)
    
    # Session features
    if 'time' in df.columns:
        df['hour'] = pd.to_datetime(df['time']).dt.hour
    elif 'datetime' in df.columns:
        df['hour'] = pd.to_datetime(df['datetime']).dt.hour
    else:
        df['hour'] = datetime.now().hour
        
    df['session_asia'] = ((df['hour'] >= 0) & (df['hour'] <= 7)).astype(float)
    df['session_eu'] = ((df['hour'] >= 8) & (df['hour'] <= 15)).astype(float)
    df['session_us'] = ((df['hour'] >= 16) & (df['hour'] <= 23)).astype(float)
    
    return df


class RealtimeAgentAI:
    """
    Real-time trading sử dụng DDQN Agent.
    
    - Lấy dữ liệu candle từ MT5 API
    - Model quyết định action mỗi khi có candle mới
    - Actions: 0=BUY, 1=SELL, 2=HOLD, 3=CLOSE
    - Sử dụng SL/TP cố định theo config (20 pips)
    """
    
    def __init__(self, symbol: str, balance: float, lot_size: float = 0.01,
                 type_account: str = "Standard", model_path: str = None,
                 timeframe: int = mt5.TIMEFRAME_M1, timeframe_sec: int = 60):
        
        self.symbol = symbol
        self.initial_balance = float(balance)
        self.balance = float(balance)
        self.lot_size = float(lot_size)
        self.type_account = type_account
        self.timeframe = timeframe
        self.timeframe_sec = timeframe_sec
        self.runflag = True
        
        # PnL calculation
        self.pnl_per_point = PNL_MULTIPLIER * self.lot_size
        
        # Commission
        if self.type_account == "Raw Spread":
            self.commission_cost_round_trip = COMMISSION_PER_LOT_RAW * (self.lot_size / 1.0)
            self.avg_spread = AVG_SPREAD_GIA_RAW
        else:
            self.commission_cost_round_trip = COMMISSION_PER_LOT_STANDARD * (self.lot_size / 1.0)
            self.avg_spread = AVG_SPREAD_GIA_STANDARD
        
        # SL/TP từ config (giống environment.py)
        self.sl_points = CATASTROPHE_SL_GIA
        self.tp_points = CATASTROPHE_TP_GIA
        
        # Market features columns (giống environment.py)
        self.market_features_cols = [
            'price_velocity_short', 'price_context_medium', 'momentum_rsi',
            'volatility_state', 'market_cost', 'session_asia', 'session_eu', 'session_us'
        ]
        
        # Trading state
        self.position = 0  # 0=flat, 1=long, 2=short
        self.entry_price = 0.0
        self.entry_time = None
        self.entry_time_step = 0
        self.sl_price = 0.0
        self.tp_price = 0.0
        self.current_ticket = None  # MT5 order ticket
        
        # Data buffer (lưu candles để tính indicator)
        self.candle_buffer = deque(maxlen=200)  # Giữ 200 candles gần nhất
        self.last_candle_time = None
        
        # Step counter
        self.current_step = 0
        
        # Load DDQN model
        self.model = None
        if model_path is not None:
            self._load_model(model_path)
        
        # Trade history
        self.trade_history = []
        self.total_trades = 0
        self.winning_trades = 0
        
        # Initialize MT5
        if not mt5.initialize():
            raise RuntimeError("❌ Cannot initialize MT5")
        
        # Get account info
        account_info = mt5.account_info()
        if account_info:
            self.balance = account_info.balance
            self.initial_balance = account_info.balance
            logger.info(f"📊 MT5 Account Balance: ${self.balance:.2f}")
        
        logger.info(f"🚀 RealtimeAgentAI initialized: {symbol}")
        logger.info(f"   Balance: ${self.balance:.2f}, Lot: {lot_size}, Account: {type_account}")
        logger.info(f"   Timeframe: {self._tf_to_str(timeframe_sec)}, SL: {self.sl_points} pips, TP: {self.tp_points} pips")
    
    def _load_model(self, model_path: str):
        """Load DDQN model"""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        logger.info(f"Loading DDQN model from: {model_path}")
        self.model = DQN.load(model_path)
        logger.info("✅ Model loaded successfully")
    
    def _fetch_candles(self, count: int = 200) -> pd.DataFrame:
        """Lấy candles từ MT5"""
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, count)
        if rates is None or len(rates) == 0:
            logger.error(f"❌ Failed to fetch candles for {self.symbol}")
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df = df.rename(columns={'tick_volume': 'volume'})
        return df
    
    def _update_candle_buffer(self) -> bool:
        """Cập nhật buffer candles, trả về True nếu có candle mới"""
        df = self._fetch_candles(MIN_CANDLES_FOR_INDICATORS + 10)
        if df is None or df.empty:
            return False
        
        latest_time = df['time'].iloc[-1]
        
        # Check if new candle
        if self.last_candle_time is None or latest_time > self.last_candle_time:
            self.last_candle_time = latest_time
            
            # Update buffer
            self.candle_buffer.clear()
            for _, row in df.iterrows():
                self.candle_buffer.append(row.to_dict())
            
            return True
        
        return False
    
    def _get_processed_data(self) -> pd.DataFrame:
        """Lấy data đã xử lý từ buffer"""
        if len(self.candle_buffer) < MIN_CANDLES_FOR_INDICATORS:
            logger.warning(f"Not enough candles: {len(self.candle_buffer)} < {MIN_CANDLES_FOR_INDICATORS}")
            return None
        
        df = pd.DataFrame(list(self.candle_buffer))
        processed = pre_process_data(df, self.type_account, self.lot_size)
        return processed
    
    def _get_observation(self, df: pd.DataFrame) -> np.ndarray:
        """
        Lấy observation giống hệt environment.py
        Returns: array 11 features
        """
        if df is None or df.empty:
            return None
        
        # Get latest row
        latest_row = df.iloc[-1]
        
        # Market state (8 features)
        market_state = []
        for col in self.market_features_cols:
            if col in latest_row:
                market_state.append(float(latest_row[col]))
            else:
                market_state.append(0.0)
        market_state = np.array(market_state, dtype=np.float32)
        
        # Internal state (3 features)
        unrealized_pnl = 0.0
        time_since_entry = 0
        current_price = float(latest_row['close'])
        
        if self.position == 1:  # Long
            unrealized_pnl = (current_price - self.entry_price) * self.pnl_per_point
            time_since_entry = self.current_step - self.entry_time_step
        elif self.position == 2:  # Short
            unrealized_pnl = (self.entry_price - current_price) * self.pnl_per_point
            time_since_entry = self.current_step - self.entry_time_step
        
        # Trừ spread cost nếu có vị thế
        if self.position != 0:
            spread_cost = self.avg_spread * self.pnl_per_point
            unrealized_pnl -= spread_cost
        
        pnl_normalized = unrealized_pnl / (self.balance + 1e-9)
        time_normalized = time_since_entry / 100.0
        
        internal_state = np.array([float(self.position), pnl_normalized, time_normalized], dtype=np.float32)
        
        return np.concatenate([market_state, internal_state])
    
    def _execute_action(self, action: int, current_price: float):
        """
        Thực thi action trên MT5
        Action: 0=BUY, 1=SELL, 2=HOLD, 3=CLOSE
        """
        action_names = {0: "BUY", 1: "SELL", 2: "HOLD", 3: "CLOSE"}
        logger.info(f"🤖 Agent action: {action_names.get(action, 'UNKNOWN')}")
        
        position_was_flat = (self.position == 0)
        
        if position_was_flat:
            if action == 0:  # BUY
                self._place_order("buy", current_price)
            elif action == 1:  # SELL
                self._place_order("sell", current_price)
            # action == 2 (HOLD): Không làm gì
        else:
            if action == 3:  # CLOSE
                self._close_position("MANUAL_CLOSE")
            # action 0, 1, 2 khi đang có position: Không làm gì (giữ position)
    
    def _place_order(self, order_type: str, price: float) -> bool:
        """Đặt lệnh trên MT5"""
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            logger.error(f"❌ Symbol {self.symbol} not found")
            return False
        
        if not symbol_info.visible:
            if not mt5.symbol_select(self.symbol, True):
                logger.error(f"❌ Failed to select {self.symbol}")
                return False
        
        point = symbol_info.point
        
        # Get current price
        tick = mt5.symbol_info_tick(self.symbol)
        if tick is None:
            logger.error(f"❌ Failed to get tick for {self.symbol}")
            return False
        
        if order_type == "buy":
            order_type_mt5 = mt5.ORDER_TYPE_BUY
            exec_price = tick.ask
            sl = exec_price - self.sl_points
            tp = exec_price + self.tp_points
        else:
            order_type_mt5 = mt5.ORDER_TYPE_SELL
            exec_price = tick.bid
            sl = exec_price + self.sl_points
            tp = exec_price - self.tp_points
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot_size,
            "type": order_type_mt5,
            "price": exec_price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": 234000,
            "comment": "DDQN Agent",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logger.error(f"❌ Order failed: {result.retcode} - {result.comment}")
            return False
        
        # Update state
        self.position = 1 if order_type == "buy" else 2
        self.entry_price = exec_price
        self.entry_time = datetime.now()
        self.entry_time_step = self.current_step
        self.sl_price = sl
        self.tp_price = tp
        self.current_ticket = result.order
        
        logger.info(f"✅ Order placed: {order_type.upper()} @ {exec_price:.2f}, SL: {sl:.2f}, TP: {tp:.2f}")
        return True
    
    def _close_position(self, reason: str = "MANUAL"):
        """Đóng position hiện tại trên MT5"""
        if self.position == 0:
            return
        
        # Get positions for this symbol
        positions = mt5.positions_get(symbol=self.symbol)
        if positions is None or len(positions) == 0:
            logger.warning(f"⚠️ No position found for {self.symbol}")
            self.position = 0
            self.entry_price = 0.0
            return
        
        for pos in positions:
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                continue
            
            if pos.type == mt5.POSITION_TYPE_BUY:
                close_type = mt5.ORDER_TYPE_SELL
                close_price = tick.bid
            else:
                close_type = mt5.ORDER_TYPE_BUY
                close_price = tick.ask
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": pos.volume,
                "type": close_type,
                "position": pos.ticket,
                "price": close_price,
                "deviation": 20,
                "magic": 234000,
                "comment": f"DDQN Close: {reason}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                pnl = pos.profit
                self.balance += pnl
                self.total_trades += 1
                
                if pnl > 0:
                    self.winning_trades += 1
                    logger.info(f"✅ Position closed ({reason}): +${pnl:.2f} WIN")
                else:
                    logger.info(f"❌ Position closed ({reason}): ${pnl:.2f} LOSS")
                
                # Save trade
                self._save_trade(pos, close_price, pnl, pnl > 0, reason)
                
                # Update equity
                update_eqity_running(self.symbol, pnl, trading_type="realtime")
            else:
                logger.error(f"❌ Failed to close position: {result.retcode}")
        
        # Reset state
        self.position = 0
        self.entry_price = 0.0
        self.current_ticket = None
    
    def _check_position_status(self):
        """Kiểm tra position hiện tại (SL/TP hit?)"""
        if self.position == 0:
            return
        
        positions = mt5.positions_get(symbol=self.symbol)
        
        if positions is None or len(positions) == 0:
            # Position đã đóng (SL/TP hit)
            logger.info(f"📊 Position closed automatically (SL/TP hit)")
            
            # Get deal history to find the closed trade
            from_date = datetime.now() - timedelta(hours=1)
            deals = mt5.history_deals_get(from_date, datetime.now(), group=f"*{self.symbol}*")
            
            if deals:
                for deal in reversed(deals):
                    if deal.entry == 1:  # Exit deal
                        pnl = deal.profit
                        self.balance += pnl
                        self.total_trades += 1
                        
                        if pnl > 0:
                            self.winning_trades += 1
                            reason = "TP_HIT"
                        else:
                            reason = "SL_HIT"
                        
                        logger.info(f"💰 {reason}: ${pnl:.2f}")
                        update_eqity_running(self.symbol, pnl, trading_type="realtime")
                        break
            
            # Reset state
            self.position = 0
            self.entry_price = 0.0
            self.current_ticket = None
    
    def _save_trade(self, position, close_price: float, profit: float, win: bool, reason: str):
        """Lưu trade vào history"""
        order_type = "Buy" if position.type == mt5.POSITION_TYPE_BUY else "Sell"
        
        trade = {
            'Datetime_entry': self.entry_time.strftime('%Y-%m-%d %H:%M:%S') if self.entry_time else '',
            'Time_frame': self._tf_to_str(self.timeframe_sec),
            'Sell/Buy': order_type,
            'Entry_price': round(position.price_open, 3),
            'Stop_loss': round(position.sl, 3),
            'Take_profit': round(position.tp, 3),
            'RSI': '',
            'MACD_value': '',
            'MACD_signal': '',
            'MACD_histogram': '',
            'EMA_50': '',
            'EMA_200': '',
            'BB_upper': '',
            'BB_middle': '',
            'BB_lower': '',
            'ATR14': '',
            'Lot': position.volume,
            'Profit': round(profit, 2),
            'Win': win,
            'AI': 'DDQN_Agent'
        }
        
        self.trade_history.append(trade)
        
        try:
            save_trade_history_csv_files(self.symbol, [trade], 'DDQN_Agent', "Realtime")
            logger.info(f"✅ Saved trade: {order_type} @ {position.price_open:.2f}, PnL: ${profit:.2f}")
        except Exception as e:
            logger.error(f"Error saving trade: {e}")
    
    @staticmethod
    def _tf_to_str(tf_sec: int) -> str:
        mapping = {60: "M1", 300: "M5", 900: "M15", 1800: "M30", 3600: "H1", 14400: "H4", 86400: "D1"}
        return mapping.get(int(tf_sec), "M1")
    
    def stop(self):
        """Stop trading"""
        self.runflag = False
        logger.info(f"🛑 RealtimeAgentAI stopped for {self.symbol}")
    
    def run(self):
        """
        Main trading loop - chạy liên tục và quyết định mỗi khi có candle mới
        """
        if self.model is None:
            logger.error("❌ No model loaded")
            return
        
        logger.info(f"🎬 Starting DDQN real-time trading for {self.symbol}")
        logger.info(f"💰 Initial balance: ${self.initial_balance:.2f}")
        logger.info(f"⏱️ Checking every {self.timeframe_sec} seconds for new candle")
        
        # Initial data fetch
        if not self._update_candle_buffer():
            logger.error("❌ Failed to fetch initial candles")
            return
        
        while self.runflag:
            try:
                # Check if position was closed (SL/TP)
                self._check_position_status()
                
                # Check for new candle
                if self._update_candle_buffer():
                    self.current_step += 1
                    logger.info(f"📊 New candle detected at {self.last_candle_time}")
                    
                    # Get processed data
                    df = self._get_processed_data()
                    if df is None or df.empty:
                        logger.warning("⚠️ No processed data available")
                        continue
                    
                    # Get observation
                    obs = self._get_observation(df)
                    if obs is None:
                        continue
                    
                    # Get action from model
                    action, _ = self.model.predict(obs, deterministic=True)
                    action = int(action)
                    
                    # Get current price
                    current_price = float(df.iloc[-1]['close'])
                    
                    # Execute action
                    self._execute_action(action, current_price)
                    
                    # Log status
                    logger.info(f"📊 Step {self.current_step} | Balance: ${self.balance:.2f} | Position: {self.position}")
                
                # Sleep before next check (poll every 5 seconds)
                time.sleep(5)
                
            except Exception as e:
                logger.error(f"❌ Error in trading loop: {e}")
                time.sleep(5)
                continue
        
        # Cleanup
        logger.info("🏁 Trading loop ended")
        self._print_summary()
    
    def _print_summary(self):
        """In tổng kết trading"""
        total_pnl = self.balance - self.initial_balance
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        
        logger.info("=" * 50)
        logger.info(f"🏁 TRADING SESSION ENDED - {self.symbol}")
        logger.info("=" * 50)
        logger.info(f"📊 Total trades: {self.total_trades}")
        logger.info(f"✅ Winning trades: {self.winning_trades}")
        logger.info(f"❌ Losing trades: {self.total_trades - self.winning_trades}")
        logger.info(f"📈 Win rate: {win_rate:.1f}%")
        logger.info(f"💰 Initial balance: ${self.initial_balance:.2f}")
        logger.info(f"💰 Final balance: ${self.balance:.2f}")
        logger.info(f"📈 Total P/L: ${total_pnl:.2f} ({total_pnl/self.initial_balance*100:.2f}%)")
        logger.info("=" * 50)
        
        print("\n" + "=" * 50)
        print(f"🏁 TRADING SESSION ENDED - {self.symbol}")
        print("=" * 50)
        print(f"📊 Total trades: {self.total_trades}")
        print(f"✅ Winning trades: {self.winning_trades}")
        print(f"📈 Win rate: {win_rate:.1f}%")
        print(f"💰 P/L: ${total_pnl:.2f}")
        print("=" * 50)


# ====== EXAMPLE USAGE ======
if __name__ == "__main__":
    # Model path
    model_path = os.path.join(os.path.dirname(__file__), 
                              "DDQN_TradingAgent", "checkpoints", "final_model.zip")
    
    if os.path.exists(model_path):
        try:
            # Create trading instance
            trader = RealtimeAgentAI(
                symbol="XAUUSDm",
                balance=10000.0,
                lot_size=0.01,
                type_account="Standard",
                model_path=model_path,
                timeframe=mt5.TIMEFRAME_M1,
                timeframe_sec=60
            )
            
            # Run trading (this will block)
            trader.run()
            
        except KeyboardInterrupt:
            print("\n⚠️ Trading stopped by user")
            trader.stop()
        except Exception as e:
            print(f"❌ Error: {e}")
        finally:
            mt5.shutdown()
    else:
        print(f"❌ Model not found: {model_path}")
        print("Please train the model first or provide correct path")
