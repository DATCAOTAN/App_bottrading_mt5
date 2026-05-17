"""
Backtest_tradeAgentAI.py - Backtest sử dụng PyTorch DDQN Agent đã train

Chạy backtest với model PyTorch DuelingDQN (best_model.pth) trên dữ liệu lịch sử,
đúng với môi trường training trong kaggle_training.py
"""

import numpy as np
import pandas as pd
import os
import logging
import logging.config
import yaml
import torch
import torch.nn as nn
from datetime import datetime
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
    DOLLAR_PER_PRICE_UNIT = 1.0  # $1 per point
    MIN_HOLD_STEPS = 0      # Cho phép thoát nhanh (Scalping)
    
    # --- RISK MANAGEMENT (KHỚP kaggle) ---
    STOP_LOSS_PRICE_PCT = 0.002   # SL 0.2% (KHỚP kaggle)
    TAKE_PROFIT_PRICE_PCT = 0.003 # TP 0.3% (KHỚP kaggle)
    SLIPPAGE = 0.0          # Trượt giá giả lập
    COOLDOWN_STEPS = 30     # Nghỉ 30 nến sau SL (KHỚP kaggle)

# ====== FEATURE COLUMNS (KHỚP HOÀN TOÀN kaggle_training.py - 17 features) ======
FEATURE_COLS = [
    'returns', 'rsi', 'trend', 'atr', 'macd_hist', 'volatility',
    'hour_sin', 'hour_cos', 'day_sin', 'day_cos', 
    'dist_max', 'dist_min', 'body_size', 'wick_size',
    'bb_pct_b', 'bb_width', 'log_vol'  # THÊM log_vol (feature thứ 17)
]

# Setup logging
try:
    config_path = os.path.join(os.path.dirname(__file__), "config", "backtest_agent_ai_logging.yaml")
    if os.path.exists(config_path):
        with open(config_path, "r") as file:
            logging_config = yaml.safe_load(file)
            logging.config.dictConfig(logging_config)
        logger = logging.getLogger("backtest_agent_ai")
    else:
        logging.basicConfig(level=logging.INFO)
        logger = logging.getLogger("backtest_agent_ai")
    logger.info("BacktestAgentAI logging initialized successfully")
except Exception as e:
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger("backtest_agent_ai")
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


def preprocess_data_for_backtest(df):
    """
    Tiền xử lý data giống hệt kaggle_training.py
    
    Returns:
        features: np.array shape (n, 16)
        closes, highs, lows, opens: np.arrays
        times: array of datetime
    """
    df = df.copy()
    
    # Validate input columns
    required = ['open', 'high', 'low', 'close']
    for col in required:
        if col not in df.columns:
            raise ValueError(f"Missing required column: {col}")
    
    # Convert to float32
    closes = df['close'].values.astype(np.float32)
    highs = df['high'].values.astype(np.float32)
    lows = df['low'].values.astype(np.float32)
    opens = df['open'].values.astype(np.float32)
    
    # --- FEATURES (giống kaggle_training.py) ---
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
    # Handle different time column formats
    if 'time' in df.columns:
        time_col = pd.to_datetime(df['time'], errors='coerce')
    elif 'datetime' in df.columns:
        time_col = pd.to_datetime(df['datetime'], errors='coerce')
    elif 'date' in df.columns:
        time_col = pd.to_datetime(df['date'], errors='coerce')
    else:
        # Fallback: create dummy time series
        time_col = pd.date_range(start='2025-01-01', periods=len(df), freq='1min')
    
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
    
    # --- ROLLING NORMALIZATION (giống kaggle_training.py) ---
    cols_to_norm = [
        'returns', 'macd_hist', 'trend', 'atr', 'volatility', 
        'body_size', 'wick_size', 'bb_pct_b', 'bb_width',
        'dist_max', 'dist_min', 'log_vol'  # THÊM log_vol vào normalization
    ]
    for col in cols_to_norm:
        roll_mean = df[col].rolling(window=5000, min_periods=1).mean()
        roll_std = df[col].rolling(window=5000, min_periods=1).std()
        df[col] = (df[col] - roll_mean) / (roll_std + 1e-8)
        df[col] = df[col].clip(-5.0, 5.0).fillna(0)
    
    # Clean data
    df.replace([np.inf, -np.inf], 0, inplace=True)
    df.fillna(0, inplace=True)
    
    # Extract arrays
    features = df[FEATURE_COLS].values.astype(np.float32)
    times = time_col.values
    
    return features, closes, highs, lows, opens, times


class BacktestAgentAI:
    """
    Backtest trading sử dụng PyTorch DDQN Agent đã train.
    
    Môi trường giống hệt kaggle_training.py:
    - Action space: 0=HOLD, 1=BUY, 2=SELL, 3=CLOSE
    - State: 180 candles x 17 features + 5 position features = 3065 dim
    - SL/TP theo % price (0.2% / 0.3%)
    """
    
    def __init__(self, symbol: str, balance: float, lot_size: float = 0.01,
                 type_account: str = "Standard", data: pd.DataFrame = None,
                 model_path: str = None, timeframe_sec: int = 60):
        
        self.symbol = symbol
        self.initial_balance = float(balance)
        self.balance_real = float(balance)  # Thêm biến balance_real để theo dõi số dư thực
        self.balance = 10000.0  # Sử dụng balance ảo cho backtest
        self.lot_size = float(lot_size)
        self.type_account = type_account
        self.timeframe_sec = timeframe_sec
        self.runflag = True
        
        # Device
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"🔧 Using device: {self.device}")
        
        # Trading state
        self.position = 0       # 0=flat, 1=long, -1=short
        self.entry_price = 0.0
        self.entry_step = 0
        self.entry_time = None
        self.hold_duration = 0
        self.cooldown_counter = 0
        
        # Data arrays (will be set by _load_data)
        self.features = None
        self.closes = None
        self.highs = None
        self.lows = None
        self.opens = None
        self.times = None
        self.current_step = Config.WINDOW_SIZE
        
        # Load and process data
        if data is not None:
            self._load_data(data)
        
        # Load PyTorch model
        self.model = None
        if model_path is not None:
            self._load_model(model_path)
        
        # Trade history
        self.trade_history = []
        self.total_trades = 0
        self.winning_trades = 0
        
        logger.info(f"🚀 BacktestAgentAI initialized: {symbol}")
        logger.info(f"   Balance: ${balance:.2f}, Lot: {lot_size}, Account: {type_account}")
        logger.info(f"   SL: {Config.STOP_LOSS_PRICE_PCT*100:.1f}%, TP: {Config.TAKE_PROFIT_PRICE_PCT*100:.1f}%")
    
    def _load_data(self, data: pd.DataFrame):
        """Load và tiền xử lý data giống kaggle_training.py"""
        logger.info(f"📊 Loading data with shape: {data.shape}")
        
        self.features, self.closes, self.highs, self.lows, self.opens, self.times = \
            preprocess_data_for_backtest(data)
        
        logger.info(f"✅ Preprocessed data: {len(self.closes):,} candles, {self.features.shape[1]} features")
    
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
            # Assume direct state dict
            self.model.load_state_dict(checkpoint)
        
        self.model.eval()
        logger.info("✅ PyTorch model loaded successfully")
    
    def _get_state(self) -> np.ndarray:
        """
        Tạo state giống hệt kaggle_training.py
        Returns: array shape (STATE_DIM,) = 1925
        """
        # Window of features (120 x 16 = 1920)
        window = self.features[self.current_step - Config.WINDOW_SIZE : self.current_step]
        flat_window = window.flatten()
        
        # PnL context
        pnl_context = 0.0
        mult = Config.DOLLAR_PER_PRICE_UNIT
        
        if self.position == 1:  # Long
            pnl_context = (self.closes[self.current_step - 1] - self.entry_price) * mult
        elif self.position == -1:  # Short
            pnl_context = (self.entry_price - self.closes[self.current_step - 1]) * mult
        
        if self.position != 0:
            pnl_context -= Config.COMMISSION
        
        pnl_norm = np.clip((pnl_context / max(self.balance, 1.0)) * 100.0, -10.0, 10.0)
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
        """Get action from model (deterministic for backtest)"""
        with torch.no_grad():
            state_t = torch.FloatTensor(state).unsqueeze(0).to(self.device)
            q_values = self.model(state_t)
            action = q_values.argmax().item()
        return action
    
    def _execute_step(self, action: int):
        """
        Thực thi action giống hệt kaggle_training.py step()
        Action: 0=HOLD, 1=BUY, 2=SELL, 3=CLOSE
        
        Returns:
            done: bool
        """
        curr_open = self.opens[self.current_step]
        curr_high = self.highs[self.current_step]
        curr_low = self.lows[self.current_step]
        curr_close = self.closes[self.current_step]
        
        mult = Config.DOLLAR_PER_PRICE_UNIT
        
        # 0. COOLDOWN CHECK
        if self.cooldown_counter > 0:
            self.cooldown_counter -= 1
            self.current_step += 1
            done = self.current_step >= len(self.closes) - 1
            return done
        
        # 1. GAP CHECK (SL/TP at open)
        is_emergency = False
        is_take_profit = False
        
        if self.position != 0:
            ref_price = self.entry_price
            sl_dist = ref_price * Config.STOP_LOSS_PRICE_PCT
            tp_dist = ref_price * Config.TAKE_PROFIT_PRICE_PCT
            
            if self.position == 1:  # Long
                if curr_open <= (self.entry_price - sl_dist):
                    is_emergency = True
                elif curr_open >= (self.entry_price + tp_dist):
                    is_take_profit = True
            elif self.position == -1:  # Short
                if curr_open >= (self.entry_price + sl_dist):
                    is_emergency = True
                elif curr_open <= (self.entry_price - tp_dist):
                    is_take_profit = True
        
        # 2. GAP EXECUTION
        if is_emergency or is_take_profit:
            pnl = 0.0
            if self.position == 1:
                pnl = (curr_open - self.entry_price) * mult
            elif self.position == -1:
                pnl = (self.entry_price - curr_open) * mult
            
            reason = "SL_GAP" if is_emergency else "TP_GAP"
            self._close_position(curr_open, pnl, reason)
            
            if is_emergency:
                self.cooldown_counter = Config.COOLDOWN_STEPS
            
            self.current_step += 1
            done = self.current_step >= len(self.closes) - 1
            return done
        
        # 3. ACTION LOGIC
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
                target_pos = self.position  # Force hold
        
        # 4. EXECUTION AT OPEN
        trade_executed = False
        if target_pos != self.position:
            trade_executed = True
            
            # Close old position
            if self.position != 0:
                pnl = 0.0
                if self.position == 1:
                    pnl = (curr_open - self.entry_price) * mult
                elif self.position == -1:
                    pnl = (self.entry_price - curr_open) * mult
                self._close_position(curr_open, pnl, "MANUAL_CLOSE")
            
            # Open new position
            if target_pos != 0:
                self.entry_price = curr_open
                self.balance -= Config.COMMISSION
                self.hold_duration = 0
                self.entry_step = self.current_step
                self.entry_time = self._get_time_at_step(self.current_step)
                
                order_type = "BUY" if target_pos == 1 else "SELL"
                logger.info(f"Step {self.current_step}: 📈 {order_type} @ {curr_open:.2f}")
            else:
                self.entry_price = 0.0
                self.hold_duration = 0
            
            self.position = target_pos
        
        if self.position != 0 and not trade_executed:
            self.hold_duration += 1
        elif trade_executed:
            self.hold_duration = 0
        
        # 5. INTRA-CANDLE SL/TP CHECK
        is_sl = False
        is_tp = False
        
        if self.position != 0:
            sl_dist = self.entry_price * Config.STOP_LOSS_PRICE_PCT
            tp_dist = self.entry_price * Config.TAKE_PROFIT_PRICE_PCT
            
            if self.position == 1:  # Long
                if curr_low <= (self.entry_price - sl_dist):
                    is_sl = True
                elif curr_high >= (self.entry_price + tp_dist):
                    is_tp = True
            elif self.position == -1:  # Short
                if curr_high >= (self.entry_price + sl_dist):
                    is_sl = True
                elif curr_low <= (self.entry_price - tp_dist):
                    is_tp = True
        
        # 6. HANDLE INTRA HIT
        if is_sl or is_tp:
            pnl = 0.0
            if is_sl:
                sl_price = self.entry_price - sl_dist if self.position == 1 else self.entry_price + sl_dist
                slippage = Config.SLIPPAGE * mult
                pnl = -(sl_dist * mult) - slippage
                self._close_position(sl_price, pnl, "SL_HIT")
                self.cooldown_counter = Config.COOLDOWN_STEPS
                logger.info(f"🛑 Stop Loss hit!")
            elif is_tp:
                tp_price = self.entry_price + tp_dist if self.position == 1 else self.entry_price - tp_dist
                pnl = tp_dist * mult
                self._close_position(tp_price, pnl, "TP_HIT")
                logger.info(f"🎯 Take Profit hit!")
        
        self.current_step += 1
        done = self.current_step >= len(self.closes) - 1
        
        # Bankrupt check
        if self.balance < 50.0:
            done = True
            logger.warning("⚠️ Balance too low, stopping backtest")
        
        return done
    
    def _close_position(self, close_price: float, pnl: float, reason: str):
        """Đóng vị thế và ghi nhận P/L"""
        self.balance += pnl
        self.total_trades += 1
        
        win = pnl > 0
        if win:
            self.winning_trades += 1
        
        order_type = "Buy" if self.position == 1 else "Sell"
        
        logger.info(f"Step {self.current_step}: {reason} - PnL: ${pnl:.2f} ({'WIN' if win else 'LOSS'})")
        
        # Save trade history
        self._save_trade(order_type, close_price, pnl, win, reason)
        
        # Update equity running
        update_eqity_running(self.symbol, pnl, trading_type="backtest")
        
        # Reset position
        self.position = 0
        self.entry_price = 0.0
        self.hold_duration = 0
    
    def _get_time_at_step(self, step: int) -> datetime:
        """Lấy datetime tại step"""
        try:
            time_val = self.times[step]
            if isinstance(time_val, np.datetime64):
                return pd.Timestamp(time_val).to_pydatetime()
            elif isinstance(time_val, pd.Timestamp):
                return time_val.to_pydatetime()
            else:
                return datetime.now()
        except:
            return datetime.now()
    
    def _save_trade(self, order_type: str, close_price: float, profit: float, win: bool, reason: str):
        """Lưu trade vào history"""
        # Format datetime entry
        if isinstance(self.entry_time, datetime):
            datetime_entry = self.entry_time.strftime('%Y-%m-%d %H:%M:%S')
        else:
            datetime_entry = str(self.entry_time)
        
        # Calculate SL/TP prices
        sl_dist = self.entry_price * Config.STOP_LOSS_PRICE_PCT if self.entry_price > 0 else 0
        tp_dist = self.entry_price * Config.TAKE_PROFIT_PRICE_PCT if self.entry_price > 0 else 0
        
        if order_type == "Buy":
            sl_price = self.entry_price - sl_dist
            tp_price = self.entry_price + tp_dist
        else:
            sl_price = self.entry_price + sl_dist
            tp_price = self.entry_price - tp_dist
        
        trade = {
            'Datetime_entry': datetime_entry,
            'Time_frame': self._tf_to_str(self.timeframe_sec),
            'Sell/Buy': order_type,
            'Entry_price': round(self.entry_price, 3),
            'Stop_loss': round(sl_price, 3),
            'Take_profit': round(tp_price, 3),
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
            'Lot': self.lot_size,
            'Profit': round(profit, 2),
            'Win': win,
            'AI': 'PyTorch_DuelingDQN'
        }
        
        self.trade_history.append(trade)
        self.balance_real += profit  # Cập nhật số dư thực
        
        # Save to CSV
        try:
            save_trade_history_csv_files(self.symbol, [trade], 'PyTorch_DuelingDQN', "Backtest")
            logger.info(f"✅ Saved trade: {order_type} @ {self.entry_price:.2f} → {close_price:.2f}, PnL: ${profit:.2f}")
        except Exception as e:
            logger.error(f"Error saving trade: {e}")
    
    @staticmethod
    def _tf_to_str(tf_sec: int) -> str:
        mapping = {60: "M1", 300: "M5", 900: "M15", 1800: "M30", 3600: "H1", 14400: "H4", 86400: "D1"}
        return mapping.get(int(tf_sec), "M1")
    
    def stop(self):
        """Stop backtest"""
        self.runflag = False
        logger.info(f"🛑 BacktestAgentAI stopped for {self.symbol}")
    
    def run(self):
        """
        Main backtest loop sử dụng PyTorch model
        """
        if self.features is None or len(self.closes) == 0:
            logger.error("❌ No data available for backtest")
            return
        
        if self.model is None:
            logger.error("❌ No model loaded for backtest")
            return
        
        logger.info(f"🎬 Starting PyTorch DDQN backtest for {self.symbol}")
        logger.info(f"📊 Processing {len(self.closes):,} candles")
        logger.info(f"💰 Initial balance: ${self.initial_balance:.2f}")
        
        # Start from WINDOW_SIZE (need 120 candles for state)
        self.current_step = Config.WINDOW_SIZE
        
        while self.runflag and self.current_step < len(self.closes) - 1:
            try:
                # Get state
                state = self._get_state()
                
                # Get action from model
                action = self._select_action(state)
                print(f"Step {self.current_step}: Action selected: {action}")
                
                # Execute action
                done = self._execute_step(action)
                
                if done:
                    break
                
                # Log progress every 10000 steps
                if self.current_step % 10000 == 0:
                    equity = self.balance
                    if self.position != 0:
                        unrealized = 0.0
                        if self.position == 1:
                            unrealized = (self.closes[self.current_step - 1] - self.entry_price)
                        elif self.position == -1:
                            unrealized = (self.entry_price - self.closes[self.current_step - 1])
                        equity += unrealized * Config.DOLLAR_PER_PRICE_UNIT
                    
                    wr = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
                    logger.info(f"📊 Step {self.current_step:,}/{len(self.closes):,} | "
                               f"Equity: ${equity:.2f} | Trades: {self.total_trades} | WR: {wr:.1f}%")
                
            except Exception as e:
                logger.error(f"❌ Error at step {self.current_step}: {e}")
                self.current_step += 1
                continue
        
        # Close any open position at the end
        if self.position != 0:
            final_price = self.closes[self.current_step - 1]
            pnl = 0.0
            if self.position == 1:
                pnl = (final_price - self.entry_price) * Config.DOLLAR_PER_PRICE_UNIT
            elif self.position == -1:
                pnl = (self.entry_price - final_price) * Config.DOLLAR_PER_PRICE_UNIT
            self._close_position(final_price, pnl, "END_OF_DATA")
        
        # Print summary
        self._print_summary()
    
    def _print_summary(self):
        """In tổng kết backtest"""
        total_pnl = self.balance_real - self.initial_balance
        win_rate = (self.winning_trades / self.total_trades * 100) if self.total_trades > 0 else 0
        roi = (total_pnl / self.initial_balance) * 100
        
        summary = f"""
{'='*60}
🏁 BACKTEST COMPLETED - {self.symbol}
{'='*60}
📊 Total trades: {self.total_trades}
✅ Winning trades: {self.winning_trades}
❌ Losing trades: {self.total_trades - self.winning_trades}
📈 Win rate: {win_rate:.1f}%
💰 Initial balance: ${self.initial_balance:.2f}
💰 Final balance: ${self.balance_real:.2f}
📈 Total P/L: ${total_pnl:.2f} (ROI: {roi:.2f}%)
{'='*60}
"""
        logger.info(summary)
        print(summary)


# # ====== EXAMPLE USAGE ======
# if __name__ == "__main__":
#     import MetaTrader5 as mt5
    
#     # Initialize MT5 for symbol info (optional)
#     try:
#         if not mt5.initialize():
#             print("⚠️ MT5 not available, continuing without MT5")
#     except:
#         print("⚠️ MT5 module not available")
    
#     # Load data từ CSV
#     data_path = os.path.join(os.path.dirname(__file__), "data", "XAUUSDm_last_month.csv")
    
#     # Model path - PyTorch checkpoint
#     model_path = os.path.join(os.path.dirname(__file__), 
#                               "DDQN_TradingAgent", "gemini3_vibe_code_AgentMT5", "best_model.pth")
    
#     if os.path.exists(data_path):
#         # Load data with header (format from data folder)
#         df = pd.read_csv(data_path)
        
#         # Ensure required columns exist
#         required_cols = ['open', 'high', 'low', 'close']
#         for col in required_cols:
#             if col not in df.columns:
#                 print(f"❌ Missing required column: {col}")
#                 exit(1)
        
#         # Rename datetime column if needed
#         if 'datetime' in df.columns:
#             df['time'] = df['datetime']
        
#         print(f"✅ Loaded data shape: {df.shape}")
#         print(f"   Columns: {list(df.columns)}")
#         print(f"   Date range: {df['time'].iloc[0] if 'time' in df.columns else 'N/A'} → {df['time'].iloc[-1] if 'time' in df.columns else 'N/A'}")
        
#         if os.path.exists(model_path):
#             # Create backtest instance
#             backtest = BacktestAgentAI(
#                 symbol="XAUUSDm",
#                 balance=500.0,  # Giống kaggle_training.py
#                 lot_size=0.01,
#                 type_account="Standard",
#                 data=df,
#                 model_path=model_path,
#                 timeframe_sec=60  # M1
#             )
            
#             # Run backtest
#             backtest.run()
#         else:
#             print(f"❌ Model not found: {model_path}")
#             print("   Please ensure best_model.pth is in the correct location")
#             print(f"   Expected path: {model_path}")
#     else:
#         print(f"❌ Data file not found: {data_path}")
#         print("   Please provide historical data CSV with columns: datetime, open, high, low, close")
    
#     # Cleanup
#     try:
#         mt5.shutdown()
#     except:
#         pass
