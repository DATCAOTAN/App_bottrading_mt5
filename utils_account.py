import MetaTrader5 as mt5
import pandas as pd
import os
from datetime import datetime
from utils_paths import current_dir_results
from datetime import timedelta


if not mt5.initialize():
    print("Lỗi khi khởi động MetaTrader5")
    mt5.shutdown()

def get_balance():
    # Thử kết nối lại nếu cần
    if not mt5.initialize():
        print("⚠️ Không thể khởi động MT5 để lấy balance")
        return None
        
    account_info = mt5.account_info()
    mt5.shutdown()  # Đóng connection ngay sau khi sử dụng
    
    if account_info is None:
        print("⚠️ Lỗi khi lấy thông tin tài khoản")
        return None
    return account_info.balance

def get_account_type():
    # Thử kết nối lại nếu cần
    if not mt5.initialize():
        print("⚠️ Không thể khởi động MT5 để lấy account type")
        return "m"  # default
        
    account_info = mt5.account_info()
    mt5.shutdown()  # Đóng connection ngay sau khi sử dụng
    
    if account_info is None:
        print("⚠️ Lỗi khi lấy thông tin tài khoản")
        return "m"  # default
        
    account_name = account_info.name.lower()
    if "cent" in account_name:
        print(f"Tài khoản Cent được phát hiện: {account_info.name}")
        return "c"
    else:
        print(f"Tài khoản Standard được phát hiện: {account_info.name}")
        return "m"
        return "m"

def get_symbol_suffix():
    return get_account_type()

def create_trade_history_csv_files(SYMBOLS):
    """Tạo các file CSV lịch sử giao dịch cho từng symbol với tên có login"""
    if not mt5.initialize():
        print("⚠️ Không thể khởi động MT5 để tạo file CSV")
        return
    
    account_info = mt5.account_info()
    mt5.shutdown()
    
    if account_info is None:
        print("⚠️ Không thể lấy thông tin tài khoản để tạo file CSV")
        return
    
    login = account_info.login
    print(f"🔐 Tạo file CSV lịch sử giao dịch cho login: {login}")
    
    # Định nghĩa cột theo yêu cầu mới: Trade fields + Indicators từ payload + Lot + Profit + Win + AI
    # Indicators lấy từ Build_PayLoad.get_mt5_payload():
    # RSI, MACD(value/signal/histogram), EMA_50, EMA_200, BollingerBands(upper/middle/lower), ATR14
    columns = [
        'Datetime_entry',           # Thời gian vào lệnh
        'Time_frame',               # Khung thời gian
        'Sell/Buy',                 # Loại lệnh
        'Entry_price',              # Giá vào lệnh
        'Stop_loss',                # Mức cắt lỗ
        'Take_profit',              # Mức chốt lời
        # Indicators (payload)
        'RSI',
        'MACD_value',
        'MACD_signal',
        'MACD_histogram',
        'EMA_50',
        'EMA_200',
        'BB_upper',
        'BB_middle',
        'BB_lower',
        'ATR14',
        # Kết quả
        'Lot',
        'Profit',
        'Win',
        'AI'
    ]
    
    # Tạo DataFrame mẫu với cột trống
    empty_df = pd.DataFrame(columns=columns)
    
    # Tạo file CSV cho từng symbol
    for symbol_key, symbol_value in SYMBOLS.items():
        # Tạo tên file với format: trade_history_{symbol_lower}_{login}.csv
        symbol_lower = symbol_key.lower()
        filename = f"trade_history_{symbol_lower}_{login}.csv"
        file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', filename)
        
        # Kiểm tra xem file đã tồn tại chưa
        if not os.path.exists(file_path):
            # Tạo thư mục nếu chưa tồn tại
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Lưu file CSV trống với cột đã định nghĩa
            empty_df.to_csv(file_path, index=False)
            print(f"✅ Đã tạo file {filename} với {len(columns)} cột chi tiết")
            print(f"   📊 Các cột: {', '.join(columns[:5])}... và {len(columns)-5} cột khác")
        else:
            print(f"ℹ️ File {filename} đã tồn tại")
    
    print(f"🎯 Hoàn thành tạo file CSV lịch sử giao dịch cho {len(SYMBOLS)} symbols")
    print(f"📋 Mỗi file có {len(columns)} cột với tên chi tiết và dễ hiểu")

def get_trade_history_file_path(symbol_key):
    """Lấy đường dẫn file CSV lịch sử giao dịch cho symbol với tên có login"""
    if not mt5.initialize():
        print("⚠️ Không thể khởi động MT5 để lấy file path")
        return None
    
    account_info = mt5.account_info()
    mt5.shutdown()
    
    if account_info is None:
        print("⚠️ Không thể lấy thông tin tài khoản")
        return None
    
    login = account_info.login
    symbol_lower = symbol_key.lower()
    filename = f"trade_history_{symbol_lower}_{login}.csv"
    file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', filename)
    return file_path

def get_backtest_trade_history_file_path(symbol_key):
    """
    Lấy đường dẫn file CSV lịch sử giao dịch cho backtest.
    
    Args:
        symbol_key (str): Tên symbol (vd: "XAUUSD", "EURUSD")
        
    Returns:
        str: Đường dẫn đầy đủ đến file CSV backtest
        
    Note:
        - File được lưu trong thư mục results/backtest/
        - Format tên: trade_history_{symbol_lower}.csv
        - Tự động tạo thư mục nếu chưa tồn tại
    """
    if not symbol_key or not isinstance(symbol_key, str):
        raise ValueError("symbol_key phải là string không rỗng")
    
    try:
        symbol_lower = symbol_key.lower().strip()
        filename = f"trade_history_{symbol_lower}.csv"
        file_path = os.path.join(current_dir_results, 'backtest', filename)
        
        # Tạo thư mục nếu chưa tồn tại
        backtest_dir = os.path.dirname(file_path)
        if not os.path.exists(backtest_dir):
            os.makedirs(backtest_dir, exist_ok=True)
            print(f"📁 Đã tạo thư mục backtest: {backtest_dir}")
        
        print(f"📊 Backtest file path cho {symbol_key}: {file_path}")
        return file_path
        
    except Exception as e:
        print(f"❌ Lỗi khi tạo đường dẫn backtest file cho {symbol_key}: {e}")
        raise


def get_oldest_candle(symbol: str, timeframe: int):
    """
    Trả về (thời_gian_cổ_nhất, nến_cổ_nhất_dict) cho symbol + timeframe trong MT5.
    
    PHƯƠNG PHÁP MỚI: Binary search backwards để tìm thời điểm cổ nhất CHÍNH XÁC.
    """
    print(f"🔍 Getting oldest candle for {symbol} {timeframe}")
    
    # Bước 1: Kiểm tra có dữ liệu gần đây không
    try:
        recent_rates = mt5.copy_rates_from(symbol, timeframe, datetime.now(), 1)
        if recent_rates is None or len(recent_rates) == 0:
            print(f"❌ No recent data available for {symbol}")
            return None, None
        print(f"✅ Recent data available for {symbol}")
    except Exception as e:
        print(f"❌ Error checking recent data: {e}")
        return None, None
    
    # Bước 2: Binary search để tìm oldest time chính xác
    now = datetime.now()
    
    # Định nghĩa khoảng tìm kiếm: từ 50 năm trước đến hiện tại
    left = datetime(1975, 1, 1)  # 50 năm trước
    right = now
    oldest_found = None
    
    print(f"🔍 Binary searching from {left} to {right}")
    
    # Binary search
    max_iterations = 50  # Giới hạn số lần tìm kiếm
    iteration = 0
    
    while left < right and iteration < max_iterations:
        iteration += 1
        mid = left + (right - left) / 2
        
        # Nếu khoảng cách < 1 giờ, dừng lại
        if (right - left) < timedelta(hours=1):
            print(f"  🎯 Converged to hour precision at iteration {iteration}")
            break
        
        try:
            # Thử lấy 1 candle từ mid point
            test_rates = mt5.copy_rates_from(symbol, timeframe, mid, 1)
            
            if test_rates is not None and len(test_rates) > 0:
                # Có data từ mid -> oldest có thể xa hơn
                oldest_found = datetime.fromtimestamp(test_rates[0]['time'])
                print(f"  ✅ Iter {iteration}: Found data at {mid} -> oldest: {oldest_found}")
                right = mid  # Thu hẹp về phía cũ hơn
            else:
                # Không có data từ mid -> oldest gần hơn
                print(f"  ❌ Iter {iteration}: No data at {mid}")
                left = mid + timedelta(days=1)  # Thu hẹp về phía mới hơn
                
        except Exception as e:
            print(f"  ⚠️ Iter {iteration}: Error at {mid}: {e}")
            left = mid + timedelta(days=1)
    
    if oldest_found is None:
        print(f"❌ Could not find oldest data for {symbol}")
        return None, None
    
    # Bước 3: Lấy candle cụ thể tại thời điểm oldest
    try:
        # Lấy candle đầu tiên từ oldest time
        oldest_rates = mt5.copy_rates_from(symbol, timeframe, oldest_found, 1)
        if oldest_rates is not None and len(oldest_rates) > 0:
            actual_oldest = datetime.fromtimestamp(oldest_rates[0]['time'])
            print(f"✅ Found oldest candle: {actual_oldest} (in {iteration} iterations)")
            return actual_oldest, oldest_rates[0]
        else:
            print(f"❌ Could not retrieve candle at {oldest_found}")
            return None, None
    except Exception as e:
        print(f"❌ Error retrieving oldest candle: {e}")
        return None, None