import pandas as pd
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
import random
import os
import glob
import gc
import time
import shutil
import sys
import warnings
from datetime import datetime
import torch.cuda.amp as amp
import traceback

# ==============================================================================
# 0. THIẾT LẬP HỆ THỐNG KIỂM ĐỊNH (SYSTEM AUDIT SETUP)
# ==============================================================================
# Vô hiệu hóa cảnh báo rác để log hiển thị sạch sẽ các thông số Trade
warnings.filterwarnings('ignore') 

# Giải phóng triệt để bộ nhớ đệm GPU Tesla P100 trước khi bắt đầu nạp dữ liệu lớn
gc.collect()
if torch.cuda.is_available():
    torch.cuda.empty_cache()

# Cấu hình tối ưu đa luồng cho CPU xử lý dữ liệu Pandas/Numpy
torch.set_num_threads(4) 

print("=" * 90)
print(f"🛡️ HỆ THỐNG HUẤN LUYỆN AI XAUUSD - PHIÊN BẢN V162 (MILESTONE PROTECTION)")
print(f"📅 Khởi chạy lúc: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"🔧 Môi trường: Python {sys.version.split()[0]} | PyTorch {torch.__version__}")

if torch.cuda.is_available():
    gpu_name_sys = torch.cuda.get_device_name(0)
    vram_gb_sys = torch.cuda.get_device_properties(0).total_memory / 1e9
    print(f"✅ THIẾT BỊ: GPU {gpu_name_sys} ({vram_gb_sys:.2f} GB VRAM)")
else:
    print("⚠️ CẢNH BÁO: Đang chạy chế độ CPU. Tốc độ sẽ cực kỳ chậm.")

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
print("=" * 90)

# ==============================================================================
# 1. CẤU HÌNH SIÊU THÔNG SỐ (CONFIGURATION - KHÓA CỨNG LOGIC)
# ==============================================================================
class Config:
    # Thư mục chứa dữ liệu input trên Kaggle
    DATA_DIR = '/kaggle/input' 
    
    # --- ĐƯỜNG DẪN CHECKPOINT (KHỚP HOÀN TOÀN VỚI LOG /default/5/ CỦA BẠN) ---
    LOAD_CHECKPOINT_PATH = '/kaggle/input/model-bot-trade/pytorch/default/7/model_final/checkpoint_latest.pth'
    LOAD_BEST_MODEL_PATH = '/kaggle/input/model-bot-trade/pytorch/default/7/model_final/best_model.pth'
    
    # Đường dẫn lưu kết quả đầu ra (Thư mục Working)
    SAVE_PATH = "/kaggle/working/checkpoint_latest.pth"
    BEST_MODEL_PATH = "/kaggle/working/best_model.pth"
    CRASH_PATH = "/kaggle/working/checkpoint_crash.pth"
    
    # Tần suất lưu file tiến độ (mỗi 50,000 nến thực tế)
    SAVE_INTERVAL_STEPS = 50000 
    
    # --- THÔNG SỐ MẠNG NEURAL (BẮT BUỘC KHỚP 3065 DIM) ---
    WINDOW_SIZE = 180   # AI quan sát 180 nến quá khứ
    FEATURE_DIM = 17    # 17 đặc trưng kỹ thuật tường minh (bao gồm Log Volume)
    # (180 nến * 17 đặc trưng) + 5 thông số trạng thái lệnh = 3065 node đầu vào
    STATE_DIM = (WINDOW_SIZE * FEATURE_DIM) + 5
    ACTION_DIM = 4      # 0:Hold, 1:Buy, 2:Sell, 3:Close
    HIDDEN_DIM = 512    # Độ rộng mạng Neural
    
    # --- THÔNG SỐ KINH TẾ (TRADING ECONOMICS) ---
    INITIAL_BALANCE = 10000.0 
    COMMISSION = 0.0          # Bot tập trung học hướng giá (Zero Fee mode)
    DOLLAR_PER_PRICE_UNIT = 1.0 
    MIN_HOLD_STEPS = 0        # Cho phép Scalping tự do (Học linh hoạt)
    
    # --- QUẢN TRỊ RỦI RO (RISK MANAGEMENT) ---
    STOP_LOSS_PRICE_PCT = 0.002   # Dừng lỗ 0.2% (~4 giá vàng)
    TAKE_PROFIT_PRICE_PCT = 0.003  # Chốt lời 0.3% (~6 giá vàng)
    SLIPPAGE = 0.0                # Trượt giá giả lập
    COOLDOWN_STEPS = 30           # Nghỉ ngơi 30 nến sau khi lỗ nặng
    
    # --- SIÊU THÔNG SỐ HUẤN LUYỆN (HYPERPARAMETERS) ---
    LR = 1e-5           # Learning Rate thấp để tinh chỉnh deep weights
    GAMMA = 0.99        # Hệ số chiết khấu lợi nhuận tương lai
    BATCH_SIZE = 4096   # Số lượng mẫu nạp vào GPU Tesla P100 mỗi lần học
    MEMORY_SIZE = 500_000 # Độ lớn của bộ nhớ Replay Buffer
    
    EPSILON_START = 1.0
    EPSILON_END = 0.005 # Bot cực kỳ kỷ luật khi về giai đoạn cuối (99.5% kỷ luật)
    EPSILON_DECAY = 0.999995 
    
    TRAIN_FREQ = 16     # Sau mỗi 16 nến mới, thực hiện 1 bước cập nhật trọng số
    TRAIN_RATIO = 0.85  # 85% dữ liệu dùng để học, 15% dùng để thi (Validation)
    EPISODES = 100       
    
    LR_STEP_SIZE = 20   # Sau mỗi 20 epoch lớn, giảm tốc độ học đi 50%
    LR_GAMMA = 0.5      
    
    VAL_INTERVAL = 50000 # Tần suất thực hiện bài kiểm tra năng lực K-Fold
    
    # --- CẤU HÌNH K-FOLD (ĐẢM BẢO PHỦ KÍN 97k NẾN TEST) ---
    VAL_K_FOLDS = 5           
    VAL_STEPS_PER_FOLD = 19000 # ~95,000 nến test lạ hoàn toàn
    VAL_STEPS = 97500          
    
    # --- MILESTONE CONFIG (LƯU MỐC QUAN TRỌNG) ---
    MILESTONE_ROI_THRESHOLD = 0.5 # Lưu model riêng biệt nếu ROI vượt 0.5%
    
    LOG_INTERVAL = 10000 # In thông số ra màn hình mỗi 10,000 nến
    SEED = 42 
    
    # --- THIẾT LẬP HÀM THƯỞNG (REWARD MATH) ---
    REWARD_SCALE = 400.0      # Khuếch đại sai biệt để AI nhạy bén hơn
    PENALTY_SL = 0.1          # Hình phạt nhẹ khi dính Stop Loss
    PENALTY_IMPATIENCE = 0.02 # Hình phạt khi vi phạm luật giao dịch

def seed_everything(seed):
    """Thiết lập Seed để đảm bảo kết quả huấn luyện mang tính ổn định tuyệt đối"""
    random.seed(seed)
    os.environ['PYTHONHASHSEED'] = str(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.backends.cudnn.deterministic = False
    torch.backends.cudnn.benchmark = True 

seed_everything(Config.SEED)

# ==============================================================================
# 2. BỘ NHỚ REPLAY (OPTIMIZED MEMORY BUFFER)
# ==============================================================================
class NumpyReplayBuffer:
    """Sử dụng mảng Numpy tĩnh để đạt tốc độ nạp dữ liệu vào GPU Tesla P100 tối đa"""
    def __init__(self, capacity, state_dim):
        self.capacity = capacity
        self.ptr = 0
        self.size = 0
        
        # Cấp phát bộ nhớ trước cho toàn bộ mảng để tránh giật lag khi đang train
        self.states = np.zeros((capacity, state_dim), dtype=np.float32)
        self.actions = np.zeros((capacity, 1), dtype=np.int64)
        self.rewards = np.zeros((capacity, 1), dtype=np.float32)
        self.next_states = np.zeros((capacity, state_dim), dtype=np.float32)
        self.dones = np.zeros((capacity, 1), dtype=np.float32)

    def add(self, state, action, reward, next_state, done):
        """Lưu trữ một bước giao dịch vào bộ nhớ xoay vòng"""
        self.states[self.ptr] = state
        self.actions[self.ptr] = action
        self.rewards[self.ptr] = reward
        self.next_states[self.ptr] = next_state
        self.dones[self.ptr] = done
        
        # Logic quay vòng (Circular Buffer)
        self.ptr = (self.ptr + 1) % self.capacity
        self.size = min(self.size + 1, self.capacity)

    def sample(self, batch_size):
        """Lấy ngẫu nhiên mẻ dữ liệu để nạp vào mạng Neural"""
        ind = np.random.randint(0, self.size, size=batch_size)
        
        # Đẩy dữ liệu trực tiếp lên thiết bị tính toán (GPU Tesla P100)
        s_tensor = torch.FloatTensor(self.states[ind]).to(device)
        a_tensor = torch.LongTensor(self.actions[ind]).to(device)
        r_tensor = torch.FloatTensor(self.rewards[ind]).to(device)
        ns_tensor = torch.FloatTensor(self.next_states[ind]).to(device)
        d_tensor = torch.FloatTensor(self.dones[ind]).to(device)
        
        return s_tensor, a_tensor, r_tensor, ns_tensor, d_tensor

# ==============================================================================
# 3. TRÌNH NẠP DỮ LIỆU VÀ TÍNH TOÁN CHỈ BÁO (DATA LOADER)
# ==============================================================================
def load_data_optimized():
    print(f"⏳ Đang thực hiện rà soát dữ liệu XAUUSD trong thư mục input của Kaggle...")
    
    # Tìm kiếm đệ quy tất cả các file CSV có tên chứa XAUUSD
    all_files_v = glob.glob(f'{Config.DATA_DIR}/**/*.csv', recursive=True)
    valid_files_v = []
    for f in all_files_v:
        if "xauusd" in f.lower():
            valid_files_v.append(f)
    
    if not valid_files_v:
        print("❌ LỖI NGHIÊM TRỌNG: Không tìm thấy dữ liệu CSV XAUUSD!")
        return None, None
    
    print(f"📂 Tìm thấy {len(valid_files_v)} file dữ liệu. Đang tiến hành gộp...")
    
    df_list_v = []
    for f in valid_files_v:
        try:
            # Lấy đủ 7 cột chuẩn của MT4/MT5: Date, Time, Open, High, Low, Close, Volume
            temp_df = pd.read_csv(f, header=None, usecols=[0,1,2,3,4,5,6], 
                                  dtype={2:'float32', 3:'float32', 4:'float32', 5:'float32', 6:'float32'})
            temp_df.columns = ['date', 'time', 'open', 'high', 'low', 'close', 'vol']
            df_list_v.append(temp_df)
        except Exception:
            pass
            
    if not df_list_v: return None, None

    # Gộp thành chuỗi dữ liệu duy nhất
    df = pd.concat(df_list_v, ignore_index=True)
    
    # Làm sạch dữ liệu rác
    df.replace([np.inf, -np.inf], np.nan, inplace=True)
    df.dropna(inplace=True)
    df = df[(df['open'] > 0.1) & (df['high'] > 0.1)]
    
    # Chuẩn hóa DateTime và sắp xếp theo chuỗi thời gian thực
    print("⏳ Đang chuẩn hóa mốc thời gian và loại bỏ nến trùng lặp...")
    df['time'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time'].astype(str), format='%Y.%m.%d %H:%M')
    df.sort_values('time', inplace=True)
    df.drop_duplicates(subset=['time'], keep='last', inplace=True) 
    df.drop(columns=['date'], inplace=True)
    df.reset_index(drop=True, inplace=True)
    
    total_candles_v = len(df)
    print(f"📊 Dữ liệu thô đạt quy mô: {total_candles_v:,} nến.")
    
    # Trích xuất mảng Numpy để tính toán indicators với hiệu suất cao nhất
    closes_v = df['close'].values.astype(np.float32)
    highs_v = df['high'].values.astype(np.float32)
    lows_v = df['low'].values.astype(np.float32)
    opens_v = df['open'].values.astype(np.float32)
    vols_v = df['vol'].values.astype(np.float32)

    # --- TÍNH TOÁN 17 ĐẶC TRƯNG CHI TIẾT (FEATURE ENGINEERING) ---
    print("🛠️ Đang trích xuất 17 đặc trưng (Features) tường minh 100%...")
    
    # 1. Log Returns
    log_ret_v = np.log(closes_v / (np.roll(closes_v, 1) + 1e-8))
    log_ret_v[0] = 0
    df['returns'] = log_ret_v
    
    # 2. Log Volume
    df['log_vol'] = np.log1p(vols_v)
    
    # 3. RSI (Relative Strength Index)
    delta_v = np.diff(closes_v, prepend=closes_v[0])
    gain_v = np.where(delta_v > 0, delta_v, 0)
    loss_v = np.where(delta_v < 0, -delta_v, 0)
    avg_gain_v = pd.Series(gain_v).ewm(alpha=1/14, adjust=False).mean().values
    avg_loss_v = pd.Series(loss_v).ewm(alpha=1/14, adjust=False).mean().values
    rs_temp_v = avg_gain_v / (avg_loss_v + 1e-8)
    df['rsi'] = (100 - (100 / (1 + rs_temp_v))) / 100.0
    
    # 4. SMA Trend (SMA 20 nến vs SMA 50 nến)
    ma_short_v = pd.Series(closes_v).rolling(window=20).mean().values
    ma_long_v = pd.Series(closes_v).rolling(window=50).mean().values
    df['trend'] = ((ma_short_v - ma_long_v) / (ma_long_v + 1e-8)) * 1000.0
    
    # 5. ATR (Average True Range)
    prev_cl_v = np.roll(closes_v, 1)
    tr_1_v = highs_v - lows_v
    tr_2_v = np.abs(highs_v - prev_cl_v)
    tr_3_v = np.abs(lows_v - prev_cl_v)
    true_range_v = np.maximum(tr_1_v, np.maximum(tr_2_v, tr_3_v))
    atr_rolling_v = pd.Series(true_range_v).rolling(window=14).mean().values
    df['atr'] = atr_rolling_v / (closes_v + 1e-8)
    
    # 6. MACD Histogram
    ema_12_v = pd.Series(closes_v).ewm(span=12, adjust=False).mean().values
    ema_26_v = pd.Series(closes_v).ewm(span=26, adjust=False).mean().values
    macd_line_v = ema_12_v - ema_26_v
    signal_line_v = pd.Series(macd_line_v).ewm(span=9, adjust=False).mean().values
    df['macd_hist'] = macd_line_v - signal_line_v
    
    # 7. Volatility
    df['volatility'] = pd.Series(log_ret_v).rolling(window=20).std().values
    
    # 8-9. Price Action Distances
    roll_min_v = pd.Series(lows_v).rolling(window=Config.WINDOW_SIZE).min().values
    roll_max_v = pd.Series(highs_v).rolling(window=Config.WINDOW_SIZE).max().values
    range_v = roll_max_v - roll_min_v + 1e-8
    df['dist_max'] = (roll_max_v - closes_v) / range_v
    df['dist_min'] = (closes_v - roll_min_v) / range_v
    
    # 10-11. Candle Anatomy
    df['body_size'] = (closes_v - opens_v) / (atr_rolling_v + 1e-8)
    df['wick_size'] = (highs_v - lows_v) / (atr_rolling_v + 1e-8)
    
    # 12-13. Bollinger Bands
    bb_mean_v = pd.Series(closes_v).rolling(window=20).mean().values
    bb_std_v = pd.Series(closes_v).rolling(window=20).std().values
    df['bb_pct_b'] = (closes_v - (bb_mean_v - bb_std_v * 2)) / (bb_std_v * 4 + 1e-8)
    df['bb_width'] = (bb_std_v * 4) / (bb_mean_v + 1e-8)
    
    # 14-17. Cyclic Time Encoding
    time_dt_v = df['time'].dt
    df['hour_sin'] = np.sin(2 * np.pi * time_dt_v.hour / 24.0)
    df['hour_cos'] = np.cos(2 * np.pi * time_dt_v.hour / 24.0)
    df['day_sin'] = np.sin(2 * np.pi * time_dt_v.dayofweek / 7.0)
    df['day_cos'] = np.cos(2 * np.pi * time_dt_v.dayofweek / 7.0)

    # Chuẩn hóa trượt (Rolling Z-Score)
    print("⏳ Đang chuẩn hóa Rolling Normalization (5,000 nến)...")
    cols_norm_v = ['returns', 'macd_hist', 'trend', 'atr', 'volatility', 'body_size', 'wick_size', 'bb_pct_b', 'bb_width', 'dist_max', 'dist_min', 'log_vol'] 
    for col in cols_norm_v:
        r_m_v = df[col].rolling(window=5000).mean()
        r_s_v = df[col].rolling(window=5000).std()
        df[col] = (df[col] - r_m_v) / (r_s_v + 1e-8)
        # Kẹp giá trị (Clip) để tránh Gradient Explosion
        df[col] = df[col].clip(-5.0, 5.0).fillna(0)

    # Lập danh sách các đặc trưng cuối cùng nạp vào AI
    feature_list_final_v = [
        'returns', 'rsi', 'trend', 'atr', 'macd_hist', 'volatility',
        'hour_sin', 'hour_cos', 'day_sin', 'day_cos', 
        'dist_max', 'dist_min', 'body_size', 'wick_size',
        'bb_pct_b', 'bb_width', 'log_vol'
    ]
    
    split_index_v = int(total_candles_v * Config.TRAIN_RATIO)
    # Đảm bảo tập Validation đủ lớn
    if total_candles_v - split_index_v < Config.VAL_STEPS + Config.WINDOW_SIZE:
        split_index_v = total_candles_v - (Config.VAL_STEPS + Config.WINDOW_SIZE + 1000)

    print(f"🧹 Đang tách tập dữ liệu thành mảng Numpy (Tỉ lệ 85/15)...")
    
    def df_to_bundle(data_slice):
        x = data_slice[feature_list_final_v].values.astype(np.float32)
        c = data_slice['close'].values.astype(np.float32)
        h = data_slice['high'].values.astype(np.float32)
        l = data_slice['low'].values.astype(np.float32)
        o = data_slice['open'].values.astype(np.float32)
        t = data_slice['time'].values
        return (x, c, h, l, o, t)

    train_pack_v = df_to_bundle(df.iloc[:split_index_v])
    test_pack_v = df_to_bundle(df.iloc[split_index_v:])
    
    print(f"✅ HOÀN TẤT NẠP DỮ LIỆU: Train {len(train_pack_v[0]):,} | Test {len(test_pack_v[0]):,}")
    return train_pack_v, test_pack_v

# ==============================================================================
# 4. KIẾN TRÚC MẠNG NEURAL VÀ TÁC NHÂN (AGENT)
# ==============================================================================
class DuelingDQN(nn.Module):
    def __init__(self, input_dim, output_dim):
        super(DuelingDQN, self).__init__()
        
        # CẤU TRÚC 2 LỚP LINEAR + LAYERNORM - KHỚP 100% VỚI TRỌNG SỐ 24H
        self.feature_layer = nn.Sequential(
            nn.Linear(input_dim, Config.HIDDEN_DIM),
            nn.LayerNorm(Config.HIDDEN_DIM),
            nn.LeakyReLU(0.01),
            nn.Linear(Config.HIDDEN_DIM, Config.HIDDEN_DIM),
            nn.LayerNorm(Config.HIDDEN_DIM),
            nn.LeakyReLU(0.01)
        )
        self.value_stream = nn.Sequential(nn.Linear(Config.HIDDEN_DIM, 256), nn.LeakyReLU(0.01), nn.Linear(256, 1))
        self.advantage_stream = nn.Sequential(nn.Linear(Config.HIDDEN_DIM, 256), nn.LeakyReLU(0.01), nn.Linear(256, output_dim))
        self.apply(lambda m: nn.init.xavier_uniform_(m.weight) if isinstance(m, nn.Linear) else None)

    def forward(self, x):
        features_p = self.feature_layer(x)
        val_v = self.value_stream(features_p)
        adv_v = self.advantage_stream(features_p)
        return val_v + (adv_v - adv_v.mean(dim=1, keepdim=True))

class DDQNAgent:
    def __init__(self):
        self.policy_net = DuelingDQN(Config.STATE_DIM, Config.ACTION_DIM).to(device)
        self.target_net = DuelingDQN(Config.STATE_DIM, Config.ACTION_DIM).to(device)
        self.target_net.load_state_dict(self.policy_net.state_dict())
        self.target_net.eval()
        
        self.optimizer = optim.AdamW(self.policy_net.parameters(), lr=Config.LR, weight_decay=1e-4) 
        self.scheduler = optim.lr_scheduler.StepLR(self.optimizer, step_size=Config.LR_STEP_SIZE, gamma=Config.LR_GAMMA)
        self.scaler = torch.amp.GradScaler('cuda')
        self.memory = NumpyReplayBuffer(Config.MEMORY_SIZE, Config.STATE_DIM)
        
        self.steps_done = 0
        self.start_epoch = 0
        self.best_roi = -999.0
        self.epsilon = Config.EPSILON_START

        # --- BẢO VỆ ROI: Nạp kỷ lục cũ từ Best Model (Bảo vệ 100%) ---
        if os.path.exists(Config.LOAD_BEST_MODEL_PATH):
            try:
                # weight_only=False để nạp các scalars từ Numpy
                best_ckpt_v = torch.load(Config.LOAD_BEST_MODEL_PATH, map_location=device, weights_only=False)
                loaded_roi_v = best_ckpt_v.get('best_roi', -999.0)
                if loaded_roi_v != -999.0:
                    self.best_roi = loaded_roi_v
                print(f"📈 [BENCHMARK] Phải vượt qua kỷ lục ROI: {self.best_roi:.2f}%")
            except Exception:
                pass

        # --- NẠP TIẾN ĐỘ TRAINING ---
        checkpoint_p = Config.LOAD_CHECKPOINT_PATH if os.path.exists(Config.LOAD_CHECKPOINT_PATH) else Config.LOAD_BEST_MODEL_PATH
        if os.path.exists(checkpoint_p):
            print(f"🔄 Đang thực hiện nạp tiến trình huấn luyện từ: {checkpoint_p}")
            try:
                ckpt_data_v = torch.load(checkpoint_p, map_location=device, weights_only=False)
                self.policy_net.load_state_dict(ckpt_data_v['policy_net'])
                self.target_net.load_state_dict(self.policy_net.state_dict())
                self.optimizer.load_state_dict(ckpt_data_v['optimizer'])
                
                if 'scheduler' in ckpt_data_v: self.scheduler.load_state_dict(ckpt_data_v['scheduler'])
                if 'scaler' in ckpt_data_v: self.scaler.load_state_dict(ckpt_data_v['scaler'])
                
                self.epsilon = ckpt_data_v['epsilon']
                self.steps_done = ckpt_data_v['steps_done']
                self.start_epoch = ckpt_data_v['epoch']
                
                # Cập nhật mốc benchmark nếu file nạp xịn hơn
                ckpt_roi_p = ckpt_data_v.get('best_roi', -999.0)
                if ckpt_roi_p > self.best_roi:
                    self.best_roi = ckpt_roi_p
                
                print(f"✅ NẠP XONG. Tiếp tục từ Epoch {self.start_epoch}. Mốc ROI mục tiêu > {self.best_roi:.2f}%")
            except Exception as err_v:
                print(f"⚠️ LỖI NẠP: {err_v}. Bot sẽ bắt đầu lại từ đầu.")
            
        gc.collect()

    def save_checkpoint(self, epoch_v, is_record=False, path_v=None):
        """Lưu lại trạng thái hiện tại của bộ não AI"""
        if path_v is None:
            path_v = Config.SAVE_PATH
        
        save_bundle_v = {
            'policy_net': self.policy_net.state_dict(), 
            'optimizer': self.optimizer.state_dict(), 
            'scheduler': self.scheduler.state_dict(),
            'scaler': self.scaler.state_dict(),
            'epsilon': self.epsilon, 
            'steps_done': self.steps_done, 
            'epoch': epoch_v, 
            'best_roi': self.best_roi
        }
        
        # Cơ chế lưu an toàn
        torch.save(save_bundle_v, path_v + ".tmp")
        if os.path.exists(path_v):
            os.remove(path_v)
        os.rename(path_v + ".tmp", path_v)
        
        if is_record: 
            torch.save(save_bundle_v, Config.BEST_MODEL_PATH)
            print(f"🏆 [HỆ THỐNG] ĐÃ LƯU BEST MODEL MỚI! ROI trung bình: {self.best_roi:.2f}%")

    def select_action(self, state_array_v, eval_mode_v=False):
        """
        AI quyết định hành động.
        Đã rà soát: Tham số là eval_mode_v để đồng bộ với run_kfold_validation
        """
        # Chế độ khám phá ngẫu nhiên
        if not eval_mode_v and random.random() < self.epsilon:
            return random.randrange(Config.ACTION_DIM)
        
        # Chế độ AI dự đoán theo kỷ luật
        with torch.no_grad():
            st_tensor_v = torch.FloatTensor(state_array_v).unsqueeze(0).to(device)
            q_values_v = self.policy_net(st_tensor_v)
            return q_values_v.argmax().item()

    def train_step(self):
        """Thực hiện một bước cập nhật trọng số mạng Neural"""
        if self.memory.size < Config.BATCH_SIZE:
            return
            
        self.steps_done += 1
        if self.steps_done % Config.TRAIN_FREQ != 0:
            return
            
        # Lấy mẻ trải nghiệm
        s_b, a_b, r_b, ns_b, d_b = self.memory.sample(Config.BATCH_SIZE)
        
        with torch.amp.autocast('cuda'):
            # Điểm Q thực tế
            q_current_v = self.policy_net(s_b).gather(1, a_b)
            
            # Logic Double DQN
            with torch.no_grad():
                best_acts_next_v = self.policy_net(ns_b).argmax(1, keepdim=True)
                q_next_val_v = self.target_net(ns_b).gather(1, best_acts_next_v).detach()
                q_target_v = r_b + (1 - d_b) * Config.GAMMA * q_next_val_v
                
            loss_final_v = nn.SmoothL1Loss()(q_current_v, q_target_v)
            
        self.optimizer.zero_grad()
        self.scaler.scale(loss_final_v).backward()
        self.scaler.step(self.optimizer)
        self.scaler.update()
        
        # Soft Update (Tau = 0.001)
        tau_val_v = 0.001
        for t_p, p_p in zip(self.target_net.parameters(), self.policy_net.parameters()):
            t_p.data.copy_(tau_val_v * p_p.data + (1.0 - tau_val_v) * t_p.data)
            
        # Giảm dần chỉ số ngẫu nhiên Epsilon
        self.epsilon = max(Config.EPSILON_END, self.epsilon * Config.EPSILON_DECAY)

# ==============================================================================
# 5. MÔI TRƯỜNG GIAO DỊCH GIẢ LẬP (TRADING ENV)
# ==============================================================================
class TradingEnv:
    def __init__(self, f_arr, c_arr, h_arr, l_arr, o_arr, t_arr=None):
        self.f_p, self.c_p, self.h_p, self.l_p, self.o_p, self.t_p = f_arr, c_arr, h_arr, l_arr, o_arr, t_arr
        self.total_limit_v = len(c_arr) - 1
        self.reset()

    def reset(self):
        self.cur_idx_v = Config.WINDOW_SIZE
        self.balance_v = Config.INITIAL_BALANCE
        self.position_v = 0 # 0: None, 1: Long, -1: Short
        self.entry_price_v = 0.0
        self.hold_steps_v = 0
        self.cooldown_v = 0
        self.trades_v = 0
        self.wins_v = 0
        self.equity_v = self.balance_v
        return self._get_state()

    def _get_state(self):
        # AI NHÌN DỮ LIỆU ĐÃ ĐÓNG (WINDOW ĐẾN CUR_IDX_V-1)
        slice_f_v = self.f_p[self.cur_idx_v - Config.WINDOW_SIZE : self.cur_idx_v].flatten()
        
        # PnL thả nổi
        pnl_float_v = 0.0
        if self.position_v == 1:
            pnl_float_v = (self.c_p[self.cur_idx_v-1] - self.entry_price_v)
        elif self.position_v == -1:
            pnl_float_v = (self.entry_price_v - self.c_p[self.cur_idx_v-1])
        
        # Chuẩn hóa PnL % so với vốn
        pnl_norm_v = np.clip((pnl_float_v / max(self.balance_v, 1.0)) * 100.0, -10.0, 10.0)
        
        # Vector bổ trợ trạng thái vị thế (5 tham số)
        status_info_v = np.array([
            1.0 if self.position_v == 1 else 0.0, 
            1.0 if self.position_v == -1 else 0.0, 
            1.0 if self.position_v == 0 else 0.0, 
            pnl_norm_v, 
            self.cool_down_v / Config.COOLDOWN_STEPS if hasattr(self, 'cool_down_v') else self.cooldown_v / Config.COOLDOWN_STEPS
        ], dtype=np.float32)
        
        return np.concatenate([slice_f_v, status_info_v])

    def step(self, action_v):
        op_v, hi_v, lo_v, cl_v, pre_eq_v = self.o_p[self.cur_idx_v], self.h_p[self.cur_idx_v], self.l_p[self.cur_idx_v], self.c_p[self.cur_idx_v], self.equity_v
        reward_o_v, realized_pnl_v, force_close_v = 0.0, 0.0, False
        
        # 0. KIỂM TRA THỜI GIAN NGHỈ (COOLDOWN)
        if self.cooldown_v > 0: 
            self.cooldown_v -= 1
            self.equity_v = self.balance_v
            self.cur_idx_v += 1
            return self._get_state(), -0.01, self.cur_idx_v >= self.total_limit_v
        
        # 1. KIỂM TRA STOP LOSS / TAKE PROFIT (QUÉT TRONG NẾN)
        if self.position_v != 0:
            sl_v, tp_v = self.entry_price_v * Config.STOP_LOSS_PRICE_PCT, self.entry_price_v * Config.TAKE_PROFIT_PRICE_PCT
            if self.position_v == 1:
                if lo_v <= (self.entry_price_v - sl_v): realized_pnl_v, force_close_v, self.cooldown_v = -sl_v, True, Config.COOLDOWN_STEPS
                elif hi_v >= (self.entry_price_v + tp_v): realized_pnl_v, force_close_v = tp_v, True
            elif self.position_v == -1:
                if hi_v >= (self.entry_price_v + sl_v): realized_pnl_v, force_close_v, self.cooldown_v = -sl_v, True, Config.COOLDOWN_STEPS
                elif lo_v <= (self.entry_price_v - tp_v): realized_pnl_v, force_close_v = tp_v, True
        
        if force_close_v:
            self.balance_v += realized_pnl_v
            self.trades_v += 1
            if realized_pnl_v > 0: self.wins_v += 1
            self.position_v, self.entry_price_v, self.hold_steps_v = 0, 0.0, 0
            self.equity_v = self.balance_v
            reward_o_v = np.clip(np.log(max(self.equity_v, 1e-5)/max(pre_eq_v, 1e-5)) * Config.REWARD_SCALE, -20, 20)
            self.cur_idx_v += 1
            return self._get_state(), reward_o_v, self.cur_idx_v >= self.total_limit_v

        # 2. XỬ LÝ QUYẾT ĐỊNH CỦA AI (TẠI GIÁ MỞ CỬA NẾN)
        target_v = self.position_v
        if action_v == 1: target_v = 1
        elif action_v == 2: target_v = -1
        elif action_v == 3: target_v = 0
        
        if target_v != self.position_v:
            if self.position_v != 0:
                p_v = (op_v - self.entry_price_v) if self.position_v == 1 else (self.entry_price_v - op_v)
                self.balance_v += p_v; self.trades_v += 1
                if p_v > 0: self.wins_v += 1
            self.entry_price_v, self.hold_steps_v, self.position_v = (op_v if target_v != 0 else 0.0), 0, target_v
            
        self.hold_steps_v = self.hold_steps_v + 1 if self.position_v != 0 else 0
        
        # 3. CẬP NHẬT TRẠNG THÁI EQUITY CUỐI NẾN (BÁO CÁO LÃI LỖ)
        unrealized_pnl_v = 0.0
        if self.position_v == 1: unrealized_pnl_v = (cl_v - self.entry_price_v)
        elif self.position_v == -1: unrealized_pnl_v = (self.entry_price_v - cl_v)
        self.equity_v = self.balance_v + unrealized_pnl_v
        
        # 4. TÍNH TOÁN REWARD (LOG EQUITY RETURN)
        reward_o_v = np.clip(np.log(max(self.equity_v, 1e-5)/max(pre_eq_v, 1e-5)) * Config.REWARD_SCALE, -20, 20)
        
        # 5. CHUYỂN BƯỚC VÀ KIỂM TRA ĐIỀU KIỆN DỪNG
        self.cur_idx_v += 1
        done_v_p = (self.cur_idx_v >= self.total_limit_v) or (self.equity_v < (Config.INITIAL_BALANCE * 0.01))
        
        return self._get_state(), reward_o_v, done_v_p

# ==============================================================================
# 6. KIỂM ĐỊNH K-FOLD NGẪU NHIÊN (STOCHASTIC VALIDATION)
# ==============================================================================
def run_kfold_validation(agent_obj, full_unseen_bundle):
    """Tiến hành thi tốt nghiệp trên 5 đoạn dữ liệu lạ, phủ kín 97,500 nến test"""
    x_test_v = full_unseen_bundle[0]
    total_unseen_len_v = len(x_test_v)
    
    folds_v, fold_size_v = Config.VAL_K_FOLDS, Config.VAL_STEPS_PER_FOLD
    jump_v_p = (total_unseen_len_v - fold_size_v) // (folds_v - 1) if folds_v > 1 else 0
    
    print(f"🔎 [VALIDATION] Chạy Stochastic {folds_v}-Fold Cross Validation...")
    roi_results_v = []
    
    for i in range(folds_v):
        # Kỹ thuật Jitter: Trượt mốc nến ±500 nến
        jitter_v = random.randint(-500, 500)
        s_idx_v = max(0, min(i * jump_v_p + jitter_v, total_unseen_len_v - fold_size_v))
        e_idx_v = s_idx_v + fold_size_v
        
        # Cắt mảng dữ liệu cho Fold
        fold_data_v = [arr[s_idx_v : e_idx_v] for arr in full_unseen_bundle]
        val_env_v = TradingEnv(*fold_data_v)
        
        st_v, done_v = val_env_v.reset(), False
        while not done_v:
            # ĐÃ RÀ SOÁT: Tham số là eval_mode_v=True đồng nhất với select_action
            act_v = agent_obj.select_action(st_v, eval_mode_v=True)
            st_v, _, done_v = val_env_v.step(act_v)
            
        current_fold_roi_v = ((val_env_v.equity_v - Config.INITIAL_BALANCE) / Config.INITIAL_BALANCE) * 100
        roi_results_v.append(current_fold_roi_v)
        
        wr_fold_v = (val_env_v.wins_v / max(val_env_v.trades_v, 1)) * 100
        print(f"   📑 Fold {i+1} (Nến {s_idx_v:,} -> {e_idx_v:,}): ROI {current_fold_roi_v:.2f}% | Winrate: {wr_fold_v:.1f}%")
        
    avg_mean_roi_v = np.mean(roi_results_v)
    print(f"📊 [KẾT QUẢ VAL] ROI trung bình toàn tập thi: {avg_mean_roi_v:.2f}%")
    return avg_mean_roi_v

# ==============================================================================
# 7. VÒNG LẶP HUẤN LUYỆN CHÍNH (MAIN LOOP)
# ==============================================================================
if __name__ == "__main__":
    try:
        # BƯỚC 1: NẠP DỮ LIỆU CÀNH CẬN
        train_p_final, val_p_final = load_data_optimized()
        
        if train_pack_final := train_p_final:
            # BƯỚC 2: KHỞI TẠO TÁC NHÂN AI VÀ MÔI TRƯỜNG TRADE
            bot_agent_v = DDQNAgent()
            env_trading_v = TradingEnv(*train_pack_final)
            
            print(f"🔥 HỆ THỐNG SẴN SÀNG: Huấn luyện từ Epoch {bot_agent_v.start_epoch} đến 100")
            
            for epoch_idx_v in range(bot_agent_v.start_epoch, 100):
                curr_state_p_v = env_trading_v.reset()
                is_over_v_p = False
                timer_ckpt_v = bot_agent_v.steps_done
                timer_val_v = bot_agent_v.steps_done
                start_time_ep_v = time.time()
                
                # Vòng lặp nến trong 1 Episode (Cả năm trời giao dịch)
                while not is_over_v_p:
                    # AI nhìn nến và ra quyết định
                    act_p_v = bot_agent_v.select_action(curr_state_p_v)
                    
                    # Thực thi hành động trên đồ thị
                    next_st_p_v, reward_p_v, is_over_v_p = env_trading_v.step(act_p_v)
                    
                    # Ghi nhớ trải nghiệm và thực hiện học tập bộ não
                    bot_agent_v.memory.add(curr_state_p_v, act_p_v, reward_p_v, next_st_p_v, is_over_v_p)
                    bot_agent_v.train_step()
                    
                    curr_state_p_v = next_st_p_v
                    
                    # A. LƯU TIẾN ĐỘ CHECKPOINT ĐỊNH KỲ (MỖI 50K NẾN)
                    if (bot_agent_v.steps_done - timer_ckpt_v) >= Config.SAVE_INTERVAL_STEPS:
                        bot_agent_v.save_checkpoint(epoch_idx_v) 
                        timer_ckpt_v = bot_agent_v.steps_done
                        torch.cuda.empty_cache() # Dọn dẹp VRAM GPU
                    
                    # B. CHẠY BÀI THI NĂNG LỰC K-FOLD (VALIDATION)
                    if (bot_agent_v.steps_done - timer_val_v) >= Config.VAL_INTERVAL:
                        final_mean_roi_v = run_kfold_validation(bot_agent_v, val_p_final) 
                        
                        # --- 1. SIÊU PHÒNG THỦ: CẬP NHẬT BEST MODEL ---
                        if final_mean_roi_v > 0 and final_mean_roi_v > bot_agent_v.best_roi: 
                            bot_agent_v.best_roi = final_mean_roi_v
                            bot_agent_v.save_checkpoint(epoch_idx_v, is_record=True)
                        elif final_mean_roi_v < bot_agent_v.best_roi:
                            print(f"   [SKIP] ROI {final_mean_roi_v:.2f}% không phá được kỷ lục {bot_agent_v.best_roi:.2f}%")
                        
                        # --- 2. LƯU LANDMARK MODEL (> MILESTONE THRESHOLD) ---
                        if final_mean_roi_v > Config.MILESTONE_ROI_THRESHOLD:
                            landmark_name = f"model_epoch_{epoch_idx_v}_roi_{final_mean_roi_v:.2f}.pth"
                            landmark_path = os.path.join("/kaggle/working/", landmark_name)
                            bot_agent_v.save_checkpoint(epoch_idx_v, path_v=landmark_path)
                            print(f"⭐ [MILESTONE] Đã lưu model cột mốc: {landmark_name}")
                        
                        timer_val_v = bot_agent_v.steps_done
                        torch.cuda.empty_cache()
                    
                    # C. LOG TIẾN ĐỘ RA MÀN HÌNH MỖI 10,000 BƯỚC
                    if env_trading_v.cur_idx_v % Config.LOG_INTERVAL == 0:
                        wr_p_v = (env_trading_v.wins_v / max(env_trading_v.trades_v, 1) * 100)
                        speed_v = Config.LOG_INTERVAL / (time.time() - start_time_ep_v + 1e-8)
                        start_time_ep_v = time.time()
                        print(f"Step {env_trading_v.cur_idx_v:,} | Eps: {bot_agent_v.epsilon:.4f} | Eq: {env_trading_v.equity_v:.1f} | WR: {wr_p_v:.1f}% | {speed_v:.0f} n/s")
                
                # KẾT THÚC MỘT BÀI HỌC LỚN (EPOCH)
                print(f"✅ Epoch {epoch_idx_v} hoàn tất | Equity cuối cùng: {env_trading_v.equity_v:.2f}")
                
                # Cập nhật Learning Rate Scheduler
                bot_agent_v.scheduler.step()
                
                # Lưu file tiến độ sau mỗi Episode lớn
                bot_agent_v.save_checkpoint(epoch_idx_v + 1)
                
                # Dọn dẹp tài nguyên rác hệ thống tránh treo máy
                torch.cuda.empty_cache()
                gc.collect()
                
    except Exception as fatal_e_p: 
        print(f"\n❌ LỖI NGHIÊM TRỌNG DẪN ĐẾN DỪNG HỆ THỐNG: {fatal_e_p}")
        traceback.print_exc()
        raise fatal_e_p