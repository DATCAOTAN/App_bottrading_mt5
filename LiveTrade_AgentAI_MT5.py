"""
LiveTrade_AgentAI_MT5.py - Live Trading với PyTorch DDQN Agent trên MT5

Realtime trading với model PyTorch DuelingDQN (best_model.pth),
đúng với môi trường training trong kaggle_training.py

Features:
- Kiểm tra candle mới (đợi 0.1s sau khi nến mới bắt đầu)
- Tính toán 16 technical features giống training
- Order lệnh thực qua MT5 API
- SL/TP management theo % price
- Lưu lịch sử giao dịch và update equity
"""

import numpy as np
import pandas as pd
import os
import logging
import logging.config
import yaml
import torch
import torch.nn as nn
from datetime import datetime, timedelta, timezone
import time
import threading
import MetaTrader5 as mt5
from utils_logs import update_eqity_running
from utlls_save_history import save_trade_history_csv_files

# ====== CONFIGURATION (KHỚP HOÀN TOÀN VỚI kaggle_training.py) ======
class Config:
    # --- MODEL (KHỚP 3065 DIM) ---
    WINDOW_SIZE = 180       # 180 candles lookback (KHỚP kaggle)
    FEATURE_DIM = 17        # 17 technical features (KHỚP kaggle, có log_vol)
    STATE_DIM = (WINDOW_SIZE * FEATURE_DIM) + 5  # 3065 features
    ACTION_DIM = 4          # 0=HOLD, 1=BUY, 2=SELL, 3=CLOSE
    HIDDEN_DIM = 512
    
    # --- ECONOMICS (KHỚP kaggle) ---
    INITIAL_BALANCE = 10000.0 
    COMMISSION = 0.0        # Zero Fee mode (như kaggle)
    DOLLAR_PER_PRICE_UNIT = 1.0  # $1 per point (sẽ cập nhật theo symbol)
    MIN_HOLD_STEPS = 0      # Cho phép thoát nhanh (Scalping)
    
    # --- RISK MANAGEMENT (KHỚP kaggle) ---
    STOP_LOSS_PRICE_PCT = 0.002   # SL 0.2% (KHỚP kaggle)
    TAKE_PROFIT_PRICE_PCT = 0.003 # TP 0.3% (KHỚP kaggle)
    SLIPPAGE = 20           # Points slippage for MT5 orders
    COOLDOWN_STEPS = 30     # Nghỉ 30 nến sau SL (KHỚP kaggle)
    
    # --- LIVE TRADING ---
    CANDLE_WAIT_SECONDS = 0.0  # Wait 0.0s after new candle starts
    POLL_INTERVAL = 0.1  # Check for new candle every 0.1 second
    MAX_HISTORY_CANDLES = 500  # Number of candles to fetch from MT5

# ====== FEATURE COLUMNS (KHỚP HOÀN TOÀN kaggle_training.py - 17 features) ======
FEATURE_COLS = [
    'returns', 'rsi', 'trend', 'atr', 'macd_hist', 'volatility',
    'hour_sin', 'hour_cos', 'day_sin', 'day_cos', 
    'dist_max', 'dist_min', 'body_size', 'wick_size',
    'bb_pct_b', 'bb_width', 'log_vol'  # THÊM log_vol (feature thứ 17)
]

# Setup logging
try:
    config_path = os.path.join(os.path.dirname(__file__), "config", "live_agent_ai_logging.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as file:
            logging_config = yaml.safe_load(file)
            logging.config.dictConfig(logging_config)
        logger = logging.getLogger("live_agent_ai")
    else:
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        logger = logging.getLogger("live_agent_ai")
    logger.info("LiveTrade_AgentAI logging initialized successfully")
except Exception as e:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("live_agent_ai")
    logger.warning(f"Failed to load logging config: {e}, using basic logging")


# ====== PYTORCH MODEL (giống kaggle_training.py) ======
class DuelingDQN(nn.Module):
    """Dueling DQN architecture từ kaggle_training.py"""
    def __init__(self, input_dim, output_dim, hidden_dim=512):
        super(DuelingDQN, self).__init__()
        self.feature_layer = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.LeakyReLU(0.01),
            nn.Linear(hidden_dim, hidden_dim),
            nn.LayerNorm(hidden_dim),
            nn.LeakyReLU(0.01)
        )
        self.value_stream = nn.Sequential(
            nn.Linear(hidden_dim, 256),
            nn.LeakyReLU(0.01),
            nn.Linear(256, 1)
        )
        self.advantage_stream = nn.Sequential(
            nn.Linear(hidden_dim, 256),
            nn.LeakyReLU(0.01),
            nn.Linear(256, output_dim)
        )

    def forward(self, x):
        features = self.feature_layer(x)
        values = self.value_stream(features)
        advantages = self.advantage_stream(features)
        return values + (advantages - advantages.mean(dim=1, keepdim=True))


class LiveTradeAgentAI:
    """
    Live Trading Agent sử dụng PyTorch DDQN model.
    
    Môi trường giống hệt kaggle_training.py:
    - Action space: 0=HOLD, 1=BUY, 2=SELL, 3=CLOSE
    - State: 120 candles x 16 features + 5 position features = 1925 dim
    - SL/TP theo % price (0.3% / 0.5%)
    - Kiểm tra candle mới trước khi ra quyết định
    """
    
    def __init__(self, symbol: str, balance: float, lot_size: float = 0.01,
                 type_account: str = "Standard", model_path: str = None,
                 timeframe: int = mt5.TIMEFRAME_M1):
        
        self.symbol = symbol
        # User inputs (KHÔNG ĐỘNG VÀO - giữ nguyên đầu vào người dùng)
        self.balance_real = float(balance)  # Balance thật của người dùng
        self.user_lot_size = float(lot_size)  # Lot size thật người dùng nhập
        
        # Training consistency (KHỚP TRAINING - dùng cho tính PnL trong state)
        self.initial_balance =  float(balance)# Giống training
        self.balance = 10000.0  # Balance cho training consistency
        
        self.type_account = type_account
        self.timeframe = timeframe
        self.timeframe_sec = self._get_timeframe_seconds(timeframe)
        self.runflag = True
        
        # Device
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🔧 Using device: {self.device}")
        
        # Trading state (giống TradingEnv)
        self.position = 0       # 0=flat, 1=long, -1=short
        self.entry_price = 0.0
        self.entry_time = None
        self.hold_duration = 0  # Count in candles
        self.cooldown_counter = 0
        
        # MT5 position tracking
        self.mt5_ticket = None
        self.mt5_position_type = None
        
        # Candle tracking
        self.last_candle_time = None
        self.candle_count = 0
        
        # Feature buffer for rolling normalization
        self.feature_buffer = None
        
        # Load PyTorch model
        self.model = None
        if model_path is not None:
            self._load_model(model_path)
        
        # Trade history
        self.total_trades = 0
        self.winning_trades = 0
        
        # Symbol info
        self._init_symbol_info()
        
        logger.info(f"🚀 LiveTradeAgentAI initialized: {symbol}")
        logger.info(f"   💰 User Balance: ${balance:.2f}, Lot: {lot_size}")
        logger.info(f"   🎯 Training Balance: ${self.balance:.2f} (for PnL calculation)")
        logger.info(f"   📊 TF: {self._tf_to_str(timeframe)}, SL: {Config.STOP_LOSS_PRICE_PCT*100:.1f}%, TP: {Config.TAKE_PROFIT_PRICE_PCT*100:.1f}%")
    
    def _get_timeframe_seconds(self, tf) -> int:
        """Convert MT5 timeframe to seconds"""
        tf_map = {
            mt5.TIMEFRAME_M1: 60,
            mt5.TIMEFRAME_M5: 300,
            mt5.TIMEFRAME_M15: 900,
            mt5.TIMEFRAME_M30: 1800,
            mt5.TIMEFRAME_H1: 3600,
            mt5.TIMEFRAME_H4: 14400,
            mt5.TIMEFRAME_D1: 86400,
        }
        return tf_map.get(tf, 60)
    
    def _tf_to_str(self, tf) -> str:
        """Convert MT5 timeframe to string"""
        tf_map = {
            mt5.TIMEFRAME_M1: "M1",
            mt5.TIMEFRAME_M5: "M5",
            mt5.TIMEFRAME_M15: "M15",
            mt5.TIMEFRAME_M30: "M30",
            mt5.TIMEFRAME_H1: "H1",
            mt5.TIMEFRAME_H4: "H4",
            mt5.TIMEFRAME_D1: "D1",
        }
        return tf_map.get(tf, "M1")
    
    def _init_symbol_info(self):
        """Initialize symbol info from MT5"""
        try:
            symbol_info = mt5.symbol_info(self.symbol)
            if symbol_info is not None:
                self.point = symbol_info.point
                self.digits = symbol_info.digits
                self.tick_value = symbol_info.trade_tick_value
                self.tick_size = symbol_info.trade_tick_size
                self.contract_size = symbol_info.trade_contract_size
                logger.info(f"📊 Symbol info: {self.symbol}, point={self.point}, digits={self.digits}")
            else:
                logger.warning(f"⚠️ Could not get symbol info for {self.symbol}")
                self.point = 0.01
                self.digits = 2
                self.tick_value = 1.0
                self.tick_size = 0.01
                self.contract_size = 100
        except Exception as e:
            logger.error(f"❌ Error getting symbol info: {e}")
            self.point = 0.01
            self.digits = 2
    
    def _load_model(self, model_path: str):
        """Load PyTorch DuelingDQN model"""
        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")
        
        logger.info(f"📥 Loading PyTorch model from: {model_path}")
        
        # Create model architecture
        self.model = DuelingDQN(
            input_dim=Config.STATE_DIM, 
            output_dim=Config.ACTION_DIM,
            hidden_dim=Config.HIDDEN_DIM
        ).to(self.device)
        
        # Load weights
        checkpoint = torch.load(model_path, map_location=self.device, weights_only=False)
        
        # Handle different checkpoint formats
        if 'policy_net' in checkpoint:
            self.model.load_state_dict(checkpoint['policy_net'])
        elif 'model_state_dict' in checkpoint:
            self.model.load_state_dict(checkpoint['model_state_dict'])
        else:
            self.model.load_state_dict(checkpoint)
        
        self.model.eval()
        logger.info("✅ PyTorch model loaded successfully")
    
    def _fetch_candles(self, count: int = None) -> pd.DataFrame:
        """
        Fetch historical candles from MT5
        
        CRITICAL FIX: Lấy từ pos=1 (nến đã đóng) thay vì pos=0 (nến đang chạy)
        - pos=0: Nến hiện tại ĐANG CHẠY (Close thay đổi liên tục) → SAI!
        - pos=1: Nến ĐÃ ĐÓNG hoàn toàn → ĐÚNG với training data
        
        Việc này đảm bảo features (RSI, MACD...) được tính từ nến đã đóng,
        khớp với logic training trong kaggle_training.py
        """
        if count is None:
            count = Config.MAX_HISTORY_CANDLES
        
        # CRITICAL: Lấy từ pos=1 để đảm bảo tất cả nến đều đã ĐÓNG
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 1, count)
        
        if rates is None or len(rates) == 0:
            logger.error(f"❌ Failed to fetch candles for {self.symbol}")
            return None
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.rename(columns={'tick_volume': 'volume'}, inplace=True)
        
        return df
    
    def _compute_features(self, df: pd.DataFrame) -> np.ndarray:
        """
        Tính toán 16 features giống hệt kaggle_training.py
        Returns: np.array shape (n, 16)
        """
        df = df.copy()
        
        closes = df['close'].values.astype(np.float32)
        highs = df['high'].values.astype(np.float32)
        lows = df['low'].values.astype(np.float32)
        opens = df['open'].values.astype(np.float32)
        
        # 1. Returns
        returns = np.zeros_like(closes)
        returns[1:] = np.log(closes[1:] / (closes[:-1] + 1e-8))
        df['returns'] = returns
        
        # 2. RSI
        delta = np.diff(closes, prepend=closes[0])
        gain = np.where(delta > 0, delta, 0)
        loss = np.where(delta < 0, -delta, 0)
        avg_gain = pd.Series(gain).ewm(alpha=1/14, adjust=False).mean().values
        avg_loss = pd.Series(loss).ewm(alpha=1/14, adjust=False).mean().values
        rs = avg_gain / (avg_loss + 1e-8)
        df['rsi'] = (100 - (100 / (1 + rs))) / 100.0
        
        # 3. Trend (SMA 20 - SMA 50)
        sma_20 = pd.Series(closes).rolling(20).mean().values
        sma_50 = pd.Series(closes).rolling(50).mean().values
        df['trend'] = ((sma_20 - sma_50) / (sma_50 + 1e-8)) * 1000.0
        
        # 4. ATR
        prev_closes = np.roll(closes, 1)
        prev_closes[0] = closes[0]
        tr = np.maximum(highs - lows, np.maximum(np.abs(highs - prev_closes), np.abs(lows - prev_closes)))
        atr = pd.Series(tr).rolling(14).mean().values
        df['atr'] = atr / (closes + 1e-8)
        
        # 5. MACD Histogram
        exp12 = pd.Series(closes).ewm(span=12, adjust=False).mean().values
        exp26 = pd.Series(closes).ewm(span=26, adjust=False).mean().values
        macd = exp12 - exp26
        signal = pd.Series(macd).ewm(span=9, adjust=False).mean().values
        df['macd_hist'] = macd - signal
        
        # 6. Volatility
        df['volatility'] = pd.Series(returns).rolling(20).std().values
        
        # 7-8. Distance from rolling high/low
        roll_low = pd.Series(lows).rolling(Config.WINDOW_SIZE).min().values
        roll_high = pd.Series(highs).rolling(Config.WINDOW_SIZE).max().values
        df['dist_max'] = (roll_high - closes) / (roll_high - roll_low + 1e-8)
        df['dist_min'] = (closes - roll_low) / (roll_high - roll_low + 1e-8)
        
        # 9-10. Candle features
        safe_atr = np.where(atr == 0, 1.0, atr)
        df['body_size'] = (closes - opens) / (safe_atr + 1e-8)
        df['wick_size'] = (highs - lows) / (safe_atr + 1e-8)
        
        # 11-12. Bollinger Bands
        bb_mean = pd.Series(closes).rolling(20).mean().values
        bb_std = pd.Series(closes).rolling(20).std().values
        bb_upper = bb_mean + (bb_std * 2)
        bb_lower = bb_mean - (bb_std * 2)
        df['bb_pct_b'] = (closes - bb_lower) / (bb_upper - bb_lower + 1e-8)
        df['bb_width'] = (bb_upper - bb_lower) / (bb_mean + 1e-8)
        
        # 13-16. Time features
        time_col = df['time']
        df['hour_sin'] = np.sin(2 * np.pi * time_col.dt.hour / 24.0).astype(np.float32)
        df['hour_cos'] = np.cos(2 * np.pi * time_col.dt.hour / 24.0).astype(np.float32)
        df['day_sin'] = np.sin(2 * np.pi * time_col.dt.dayofweek / 7.0).astype(np.float32)
        df['day_cos'] = np.cos(2 * np.pi * time_col.dt.dayofweek / 7.0).astype(np.float32)
        
        # 17. Log Volume (THÊM MỚI - KHỚP kaggle_training.py)
        if 'volume' in df.columns:
            vols = df['volume'].values.astype(np.float32)
        elif 'tick_volume' in df.columns:
            vols = df['tick_volume'].values.astype(np.float32)
        else:
            vols = np.ones(len(df), dtype=np.float32)
        df['log_vol'] = np.log1p(vols)
        
        # Rolling Normalization (giống kaggle_training.py)
        cols_to_norm = [
            'returns', 'macd_hist', 'trend', 'atr', 'volatility', 
            'body_size', 'wick_size', 'bb_pct_b', 'bb_width',
            'dist_max', 'dist_min', 'log_vol'  # THÊM log_vol vào normalization
        ]
        for col in cols_to_norm:
            roll_mean = df[col].rolling(window=min(5000, len(df)), min_periods=1).mean()
            roll_std = df[col].rolling(window=min(5000, len(df)), min_periods=1).std()
            df[col] = (df[col] - roll_mean) / (roll_std + 1e-8)
            df[col] = df[col].clip(-5.0, 5.0).fillna(0)
        
        # Clean data
        df.replace([np.inf, -np.inf], 0, inplace=True)
        df.fillna(0, inplace=True)
        
        return df[FEATURE_COLS].values.astype(np.float32)
    
    def _get_state(self, features: np.ndarray, current_price: float) -> np.ndarray:
        """
        Tạo state giống hệt kaggle_training.py
        Returns: array shape (STATE_DIM,) = 3065 (180*17 + 5)
        """
        # Window of features (180 x 17 = 3060)
        if len(features) < Config.WINDOW_SIZE:
            # Pad with zeros if not enough data
            padding = np.zeros((Config.WINDOW_SIZE - len(features), Config.FEATURE_DIM), dtype=np.float32)
            window = np.vstack([padding, features])
        else:
            window = features[-Config.WINDOW_SIZE:]
        
        flat_window = window.flatten()
        
        # PnL context (TÍNH THEO CONFIG ĐỂ KHỚP TRAINING)
        # Balance = 10000 (training), DOLLAR_PER_PRICE_UNIT = 1.0
        pnl_context = 0.0
        mult = Config.DOLLAR_PER_PRICE_UNIT  # 1.0
        
        if self.position == 1:  # Long
            pnl_context = (current_price - self.entry_price) * mult
        elif self.position == -1:  # Short
            pnl_context = (self.entry_price - current_price) * mult
        
        if self.position != 0:
            pnl_context -= Config.COMMISSION  # 0.0 (zero fee mode)
        
        # Normalize theo balance training (10000) - GIỐNG TRAINING
        pnl_norm = np.clip((pnl_context / 10000.0) * 100.0, -10.0, 10.0)
        cooldown_norm = self.cooldown_counter / Config.COOLDOWN_STEPS
        
        # Position encoding (5 features)
        pos_arr = np.array([
            1.0 if self.position == 1 else 0.0,   # is_long
            1.0 if self.position == -1 else 0.0,  # is_short
            1.0 if self.position == 0 else 0.0,   # is_flat
            pnl_norm,                              # pnl_normalized
            cooldown_norm                          # cooldown_normalized
        ], dtype=np.float32)
        
        return np.concatenate([flat_window, pos_arr])
    
    def _select_action(self, state: np.ndarray) -> int:
        """Get action from model (deterministic)"""
        with torch.no_grad():
            state_t = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.model(state_t)
            action = q_values.argmax().item()
        return action
    
    def _check_new_candle(self) -> bool:
        """
        Kiểm tra có candle mới không.
        Trả về True nếu có candle mới và đã qua CANDLE_WAIT_SECONDS.
        """
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, 1)
        if rates is None or len(rates) == 0:
            return False
        
        current_candle_time = datetime.fromtimestamp(rates[0]['time'])
        
        if self.last_candle_time is None:
            self.last_candle_time = current_candle_time
            return False
        
        if current_candle_time > self.last_candle_time:
            # New candle detected!
            # Calculate seconds since candle started
            now = datetime.now()
            candle_age = (now - current_candle_time).total_seconds()
            
            if candle_age >= Config.CANDLE_WAIT_SECONDS:
                self.last_candle_time = current_candle_time
                self.candle_count += 1
                logger.info(f"🕯️ New candle detected: {current_candle_time} (age: {candle_age:.2f}s)")
                return True
        
        return False
    
    def _sync_mt5_position(self):
        """Đồng bộ position với MT5"""
        positions = mt5.positions_get(symbol=self.symbol)
        
        if positions is None or len(positions) == 0:
            # No position on MT5
            if self.position != 0:
                logger.info(f"📊 MT5 position closed externally, syncing...")
                self.position = 0
                self.entry_price = 0.0
                self.mt5_ticket = None
            return
        
        # Has position on MT5
        pos = positions[0]
        self.mt5_ticket = pos.ticket
        
        if pos.type == mt5.ORDER_TYPE_BUY:
            if self.position != 1:
                logger.info(f"📊 Syncing with MT5 BUY position @ {pos.price_open}")
                self.position = 1
                self.entry_price = pos.price_open
        elif pos.type == mt5.ORDER_TYPE_SELL:
            if self.position != -1:
                logger.info(f"📊 Syncing with MT5 SELL position @ {pos.price_open}")
                self.position = -1
                self.entry_price = pos.price_open
    
    def _execute_order(self, action: int, current_price: float) -> bool:
        """
        Thực thi lệnh MT5 dựa trên action.
        Action: 0=HOLD, 1=BUY, 2=SELL, 3=CLOSE
        """
        # 0. COOLDOWN CHECK
        if self.cooldown_counter > 0:
            self.cooldown_counter -= 1
            return False
        
        # Determine target position
        target_pos = 0
        if action == 0:    # HOLD
            target_pos = self.position
        elif action == 1:  # BUY
            target_pos = 1
        elif action == 2:  # SELL
            target_pos = -1
        elif action == 3:  # CLOSE
            target_pos = 0
        
        # MIN_HOLD_STEPS rule
        if self.position != 0 and self.hold_duration < Config.MIN_HOLD_STEPS:
            if target_pos != self.position:
                logger.debug(f"⏳ Min hold not reached ({self.hold_duration}/{Config.MIN_HOLD_STEPS})")
                target_pos = self.position  # Force hold
        
        # No change needed
        if target_pos == self.position:
            if self.position != 0:
                self.hold_duration += 1
            return False
        
        # EXECUTION
        trade_success = False
        
        # Close existing position first
        if self.position != 0:
            close_success, close_pnl = self._close_mt5_position(current_price)
            if close_success:
                trade_success = True
        
        # Open new position
        if target_pos != 0:
            open_success = self._open_mt5_position(target_pos, current_price)
            if open_success:
                trade_success = True
                self.hold_duration = 0
        else:
            self.hold_duration = 0
        
        return trade_success
    
    def _open_mt5_position(self, direction: int, price: float) -> bool:
        """Mở lệnh mới trên MT5"""
        try:
            # Check MT5 connection using symbol_info (more reliable than terminal_info)
            # terminal_info() can return None even when connected during busy periods
            
            # Retry logic for symbol_info (3 attempts)
            symbol_info = None
            for attempt in range(3):
                # Refresh symbol info from server
                symbol_info = mt5.symbol_info(self.symbol)
                if symbol_info is not None:
                    break
                
                # Only reconnect on last attempt if all retries failed
                if attempt == 2:
                    logger.warning("⚠️ MT5 may be disconnected, attempting reconnect...")
                    if mt5.initialize():
                        time.sleep(0.1)
                        symbol_info = mt5.symbol_info(self.symbol)
                        if symbol_info is not None:
                            break
                
                logger.warning(f"⚠️ Attempt {attempt+1}/3: Symbol {self.symbol} not found, retrying...")
                if not mt5.symbol_select(self.symbol, True):
                    logger.warning(f"⚠️ Failed to add {self.symbol} to Market Watch")
                time.sleep(0.1)
            
            if symbol_info is None:
                logger.error(f"❌ Symbol {self.symbol} not found after 3 attempts")
                return False
            
            # Ensure symbol is visible
            if not symbol_info.visible:
                if not mt5.symbol_select(self.symbol, True):
                    logger.error(f"❌ Could not enable {self.symbol} in Market Watch")
                    return False
                time.sleep(0.1)
            
            # Get tick data with null check
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                logger.error(f"❌ Cannot get tick data for {self.symbol}")
                return False
            
            # Calculate SL/TP
            sl_dist = price * Config.STOP_LOSS_PRICE_PCT
            tp_dist = price * Config.TAKE_PROFIT_PRICE_PCT
            
            if direction == 1:  # BUY
                order_type = mt5.ORDER_TYPE_BUY
                sl = price - sl_dist
                tp = price + tp_dist
                action_price = tick.ask
            else:  # SELL
                order_type = mt5.ORDER_TYPE_SELL
                sl = price + sl_dist
                tp = price - tp_dist
                action_price = tick.bid
            
            # Round to symbol digits
            sl = round(sl, self.digits)
            tp = round(tp, self.digits)
            
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": self.user_lot_size,  # Dùng lot size thật người dùng nhập
                "type": order_type,
                "price": action_price,
                "sl": sl,
                "tp": tp,
                "deviation": Config.SLIPPAGE,
                "magic": 123456,
                "comment": "PyTorch_DuelingDQN",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.position = direction
                self.entry_price = result.price
                self.entry_time = datetime.now()
                self.mt5_ticket = result.order
                self.balance -= Config.COMMISSION
                
                order_str = "BUY" if direction == 1 else "SELL"
                logger.info(f"✅ {order_str} order executed @ {result.price:.{self.digits}f}, SL={sl}, TP={tp} time={datetime.now()}")
                return True
            else:
                logger.error(f"❌ Order failed: {result.retcode} - {result.comment}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Error opening position: {e}")
            return False
    
    def _close_mt5_position(self, current_price: float) -> tuple:
        """Đóng lệnh hiện tại trên MT5"""
        try:
            positions = mt5.positions_get(symbol=self.symbol)
            
           
            pos = positions[0]
            
            # Get tick data with null check
            tick = mt5.symbol_info_tick(self.symbol)
            if tick is None:
                logger.error(f"❌ Cannot get tick data for closing position")
                return False, 0.0
            
            # Determine close order type
            if pos.type == mt5.ORDER_TYPE_BUY:
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
                "deviation": Config.SLIPPAGE,
                "magic": 123456,
                "comment": "AI_CLOSE",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            
            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                # Calculate PnL
                pnl = pos.profit
                
                self._record_trade(result.price, pnl, "MANUAL_CLOSE")
                
                self.position = 0
                self.entry_price = 0.0
                self.mt5_ticket = None
                
                logger.info(f"✅ Position closed @ {result.price:.{self.digits}f}, PnL: ${pnl:.2f}")
                
                # Brief wait for MT5 to sync (retry logic in _open_mt5_position handles the rest)
                if not mt5.initialize():
                    logger.warning("⚠️ MT5 may be disconnected after close, attempting reconnect...")
                    mt5.initialize()
                
                return True, pnl
            else:
                logger.error(f"❌ Close failed: {result.retcode} - {result.comment}")
                return False, 0.0
                
        except Exception as e:
            logger.error(f"❌ Error closing position: {e}")
            return False, 0.0
    
    def _check_sl_tp_hit(self, current_price: float):
        """Kiểm tra SL/TP có bị hit không (backup cho MT5 SL/TP)"""
        if self.position == 0 or self.entry_price == 0:
            return
        
        sl_dist = self.entry_price * Config.STOP_LOSS_PRICE_PCT
        tp_dist = self.entry_price * Config.TAKE_PROFIT_PRICE_PCT
        
        is_sl = False
        is_tp = False
        
        if self.position == 1:  # Long
            if current_price <= (self.entry_price - sl_dist):
                is_sl = True
            elif current_price >= (self.entry_price + tp_dist):
                is_tp = True
        elif self.position == -1:  # Short
            if current_price >= (self.entry_price + sl_dist):
                is_sl = True
            elif current_price <= (self.entry_price - tp_dist):
                is_tp = True
        
         # 6. HANDLE INTRA HIT
        mult = Config.DOLLAR_PER_PRICE_UNIT  # 1.0
        if is_sl or is_tp:
            pnl = 0.0
            if is_sl:
                pnl = -(sl_dist * mult)
                self._record_trade(current_price, pnl, "SL hit")
                self.position = 0
                self.entry_price = 0.0
                self.mt5_ticket = None
                self.cooldown_counter = Config.COOLDOWN_STEPS
                logger.info(f"🛑 Stop Loss hit!")
            elif is_tp:
                pnl = tp_dist * mult
                self._record_trade(current_price, pnl, "TP hit")
                self.position = 0
                self.entry_price = 0.0
                self.mt5_ticket = None
                logger.info(f"🎯 Take Profit hit!")
            if not mt5.initialize():
                logger.warning("⚠️ MT5 may be disconnected after close, attempting reconnect...")
                mt5.initialize()
    
    def _record_trade(self, close_price: float, pnl: float, reason: str):
        """Ghi nhận trade và lưu lịch sử"""
        # Update balance training (chỉ để tracking, không ảnh hưởng trading thật)
        self.balance += pnl
        self.total_trades += 1
        
        win = pnl > 0
        if win:
            self.winning_trades += 1
        
        order_type = "Buy" if self.position == 1 else "Sell"
        
        logger.info(f"📝 Trade {reason}: {order_type} @ {self.entry_price:.{self.digits}f} → {close_price:.{self.digits}f}, PnL: ${pnl:.2f} ({'WIN' if win else 'LOSS'})")
        
        # Save trade history
        while self._save_trade(order_type, close_price, win, reason) != True:
            logger.warning("⚠️ Retry saving trade...")
            time.sleep(0.1)

        # Update equity running
        update_eqity_running(self.symbol, pnl, trading_type="realtime")
    
    def _save_trade(self, order_type: str, close_price: float, win: bool, reason: str):
        """
        Lưu trade vào history và CSV.
        Lấy thông tin từ MT5 history deals gần nhất của symbol này.
        """
        try:
            # Lấy lịch sử giao dịch từ MT5 (deals gần đây)
            now = datetime.now()
            since = now - timedelta(seconds=65)  # Lấy 65 giây gần nhất
            
            deals = mt5.history_deals_get(since, now) or []
            logger.debug(f"Found {len(deals)} deals in last 65 seconds")
            
            # Lọc deals đóng (OUT) của symbol này
            closed_deals = [d for d in deals 
                          if getattr(d, 'symbol', None) == self.symbol 
                          and getattr(d, 'entry', None) == mt5.DEAL_ENTRY_OUT]
            
            if not closed_deals:
                logger.warning(f"No closed deals found for {self.symbol}, using internal data")
                # Fallback: dùng dữ liệu nội bộ
                datetime_entry = self.entry_time.strftime('%Y-%m-%d %H:%M:%S') if self.entry_time else str(datetime.now())
                entry_price = self.entry_price
                lot = self.user_lot_size  # Lot size thật người dùng
                profit = 0.0  # Không có deal từ MT5
            else:
                # Lấy deal gần nhất
                def _deal_time(deal):
                    t = getattr(deal, 'time', None)
                    if t is None:
                        t = getattr(deal, 'time_msc', None)
                    return int(t) if t is not None else 0
                
                deal = max(closed_deals, key=_deal_time)
                logger.info(f"Found closed deal: ticket={getattr(deal, 'ticket', 'N/A')}, profit={getattr(deal, 'profit', 'N/A')}")
                
                # Lấy thông tin từ deal
                position_id = getattr(deal, 'position_id', None)
                lot = float(getattr(deal, 'volume', self.user_lot_size))  # Lot size thật
                profit = float(getattr(deal, 'profit', 0.0))  # Dùng profit từ MT5
                
                # Tìm deal mở (IN) để lấy entry price và time
                entry_price = self.entry_price
                datetime_entry = self.entry_time.strftime('%Y-%m-%d %H:%M:%S') if self.entry_time else str(datetime.now())
                
                if position_id is not None:
                    try:
                        # Tìm deals mở trong 7 ngày gần đây
                        deals_open = mt5.history_deals_get(now - timedelta(days=7), now) or []
                        opens = [x for x in deals_open 
                               if getattr(x, 'position_id', None) == position_id 
                               and getattr(x, 'entry', None) == mt5.DEAL_ENTRY_IN]
                        
                        if opens:
                            open_leg = sorted(opens, key=_deal_time)[0]
                            entry_price = float(getattr(open_leg, 'price', entry_price))
                            
                            # Lấy thời gian entry từ deal mở
                            ot = getattr(open_leg, 'time', None)
                            if ot is None:
                                ot = getattr(open_leg, 'time_msc', None)
                            if ot:
                                # Chuyển từ UTC sang UTC+7
                                entry_dt = datetime.fromtimestamp(int(ot), tz=timezone.utc) + timedelta(hours=7)
                                datetime_entry = entry_dt.strftime('%Y-%m-%d %H:%M:%S')
                            
                            # Xác định order type từ deal mở
                            deal_type = int(getattr(open_leg, 'type', -1))
                            order_type = 'Buy' if deal_type == mt5.DEAL_TYPE_BUY else 'Sell'
                            
                            logger.info(f"Found open leg: price={entry_price}, time={datetime_entry}, type={order_type}")
                    except Exception as e:
                        logger.error(f"Error finding open leg: {e}")
                        return False
            
            # Calculate SL/TP prices dựa trên entry_price thực tế từ MT5
            sl_dist = entry_price * Config.STOP_LOSS_PRICE_PCT if entry_price > 0 else 0
            tp_dist = entry_price * Config.TAKE_PROFIT_PRICE_PCT if entry_price > 0 else 0
            
            if order_type == "Buy":
                sl_price = entry_price - sl_dist
                tp_price = entry_price + tp_dist
            else:
                sl_price = entry_price + sl_dist
                tp_price = entry_price - tp_dist
            
            # Tạo trade record với thông tin từ MT5
            trade = {
                'Datetime_entry': datetime_entry,
                'Time_frame': self._tf_to_str(self.timeframe),
                'Sell/Buy': order_type,
                'Entry_price': round(entry_price, self.digits),
                'Stop_loss': round(sl_price, self.digits),
                'Take_profit': round(tp_price, self.digits),
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
                'Lot': lot,
                'Profit': round(profit, 2),
                'Win': win,
                'AI': 'PyTorch_DuelingDQN'
            }
            
            logger.info(f"Saving trade to CSV: Entry={entry_price}, Lot={lot}, Profit={profit}")
            self.balance_real += profit
            
            # Lưu vào CSV với structure giống live_trade_ai.py
            save_trade_history_csv_files(self.symbol, [trade], 'PyTorch_DuelingDQN')
            logger.info(f"✅ Trade saved successfully to CSV")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error saving trade: {e}", exc_info=True)
            return False
    
    def stop(self):
        """Stop live trading"""
        self.runflag = False
        logger.info(f"🛑 LiveTradeAgentAI stopped for {self.symbol}")
    
    def run(self):
        """
        Main live trading loop.
        - Kiểm tra candle mới mỗi POLL_INTERVAL
        - Đợi CANDLE_WAIT_SECONDS sau khi candle mới bắt đầu
        - Lấy action từ model và thực thi
        """
        if self.model is None:
            logger.error("❌ No model loaded for live trading")
            return
        
        # Initialize MT5
        if not mt5.initialize():
            logger.error("❌ MT5 initialization failed")
            return
        
        logger.info(f"🎬 Starting live trading for {self.symbol}")
        logger.info(f"📊 Timeframe: {self._tf_to_str(self.timeframe)}, Poll: {Config.POLL_INTERVAL}s")
        logger.info(f"💰 Initial balance: ${self.initial_balance:.2f}")
        
        while self.runflag and self.balance_real > 0:
            try:
                # Sync with MT5 position
                if not mt5.initialize():
                    print("MT5 initialize failed, retrying in 10s...")
                    logger.error("MT5 initialize failed, retrying in 10s...")
                    time.sleep(1)
                    continue
                
                # Check for new candle
                if self._check_new_candle():
                    # Fetch historical data
                    df = self._fetch_candles()
                    if df is None or len(df) < Config.WINDOW_SIZE:
                        logger.warning("⚠️ Not enough candle data")
                        time.sleep(0.1)
                        continue
                    
                    # Compute features
                    features = self._compute_features(df)
                    
                    # Get current price từ open của nến hiện tại (KHỚP TRAINING)
                    current_candle = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, 1)
                    if current_candle is None or len(current_candle) == 0:
                        logger.warning("⚠️ Could not get current candle")
                        time.sleep(0.1)
                        continue
                    
                    current_price = float(current_candle[0]['open'])  # Giá open của nến hiện tại
                    
                    # Get state
                    state = self._get_state(features, current_price)
                    
                    # Get action from model
                    action = self._select_action(state)
                    action_names = ['HOLD', 'BUY', 'SELL', 'CLOSE']
                    logger.info(f"🤖 AI Action: {action_names[action]} (position={self.position}, hold={self.hold_duration})")
                    
                    # Execute action
                    self._execute_order(action, current_price)
                    
                    # Log progress
                    equity = self.balance
                    if self.position != 0 and self.entry_price > 0:
                        if self.position == 1:
                            # Tính PnL thật theo lot size người dùng
                            unrealized = (current_price - self.entry_price) 
                        else:
                            unrealized = (self.entry_price - current_price) 
                        equity += unrealized * Config.DOLLAR_PER_PRICE_UNIT 
                    wr = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
                    logger.info(f"📊 Candle #{self.candle_count} | Equity: ${equity:.2f} | Trades: {self.total_trades} | WR: {wr:.1f}% | Real Balance: ${self.balance_real:.2f}")
                
                else:
                    # Check SL/TP in between candles
                    if self.position != 0:
                        current_candle = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, 1)
                        if current_candle is not None and len(current_candle) > 0:
                            current_price = float(current_candle[0]['open'])  # Giá open của nến hiện tại
                            self._check_sl_tp_hit(current_price)
                
                time.sleep(0.1)
                print("waiting...", end='\r')
                
            except Exception as e:
                logger.error(f"❌ Error in main loop: {e}")
                time.sleep(0.1)
                continue
        
        # Cleanup
        logger.info("🏁 Live trading stopped")
        self._print_summary()
    
    def _print_summary(self):
        """In tổng kết trading"""
        total_pnl = self.balance_real - self.initial_balance
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        roi = (total_pnl / self.initial_balance) * 100
        
        summary = f"""
{'='*60}
🏁 LIVE TRADING SUMMARY - {self.symbol}
{'='*60}
📊 Total trades: {self.total_trades}
✅ Winning trades: {self.winning_trades}
❌ Losing trades: {self.total_trades - self.winning_trades}
📈 Win rate: {win_rate:.1f}%
💰 Initial balance: ${self.initial_balance:.2f}
💰 Final balance: ${self.balance_real:.2f}
📈 Total P/L: ${total_pnl:.2f} (ROI: {roi:.2f}%)
🕯️ Candles processed: {self.candle_count}
{'='*60}
"""
        logger.info(summary)
        print(summary)


# ====== EXAMPLE USAGE ======
# if __name__ == "__main__":
#     # Initialize MT5
#     if not mt5.initialize():
#         print("❌ MT5 initialization failed")
#         exit(1)
    
#     print("✅ MT5 initialized successfully")
    
#     # Model path
#     model_path = os.path.join(os.path.dirname(__file__), 
#                               "DDQN_TradingAgent", "gemini3_vibe_code_AgentMT5", "best_model.pth")
    
#     if os.path.exists(model_path):
#         # Create live trader
#         trader = LiveTradeAgentAI(
#             symbol="XAUUSDm",
#             balance=500.0,
#             lot_size=0.01,
#             type_account="Standard",
#             model_path=model_path,
#             timeframe=mt5.TIMEFRAME_M1
#         )
        
#         # Run in separate thread or main thread
#         try:
#             trader.run()
#         except KeyboardInterrupt:
#             print("\n⏹️ Stopping trader...")
#             trader.stop()
#     else:
#         print(f"❌ Model not found: {model_path}")
    
#     # Cleanup
#     mt5.shutdown()
