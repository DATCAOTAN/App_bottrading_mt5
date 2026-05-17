import os
import pandas as pd
from utils_paths import current_dir_results
print(f"current_dir_results: {current_dir_results}")
from SYMBOLs import SYMBOLS

def create_symbol_csv(SYMBOLS):
    """Tạo file Symbol.csv với cột Status_Realtime và Status_Backtest"""
    symbols_list = list(SYMBOLS.values())
    symbols_data = []
    for symbol in symbols_list:
        symbols_data.append({
            'Symbol': symbol,
            'Status_Realtime': 0,
            'Status_Backtest': 0
        })
    df = pd.DataFrame(symbols_data)
    file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', 'Symbol.csv')
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    df.to_csv(file_path, index=False)
    print(f"✅ Đã tạo file Symbol.csv với symbols: {symbols_list}")
    return symbols_list

def Status0_symbol(trading_type='realtime'):
    """Trả về danh sách symbols có Status = 0 (có thể trade)
    
    Args:
        trading_type: 'realtime' hoặc 'backtest'
    """
    try:
        # Sử dụng symbols động từ SYMBOLS dictionary
        symbols_list = list(SYMBOLS.values())
        
        # Xác định cột status dựa vào trading_type
        status_col = 'Status_Realtime' if trading_type == 'realtime' else 'Status_Backtest'
        
        # Kiểm tra file CSV nếu tồn tại
        path = os.path.join(current_dir_results, 'trade_history', 'real_time', 'Symbol.csv')
        if os.path.exists(path):
            df = pd.read_csv(path)
            # Kiểm tra xem cột 'Symbol' và status column có tồn tại không
            if 'Symbol' not in df.columns or status_col not in df.columns:
                print(f"File CSV không chứa cột 'Symbol' hoặc '{status_col}'. Sử dụng symbols mặc định.")
                return symbols_list
            
            # Chuyển cột Status thành kiểu số
            df[status_col] = pd.to_numeric(df[status_col], errors='coerce')
            
            # Lọc các hàng có Status = 0
            filtered_symbols = df[df[status_col] == 0]['Symbol']
            
            # Kiểm tra xem có symbols nào được filter không
            if len(filtered_symbols) > 0:
                return filtered_symbols.tolist()
            else:
                print(f"Không có symbols nào có {status_col} = 0. Sử dụng symbols mặc định.")
                return symbols_list
        else:
            print("File Symbol.csv không tồn tại. Sử dụng symbols mặc định.")
            return symbols_list

    except Exception as e:
        print(f"Lỗi khi đọc file Symbol.csv: {e}. Sử dụng symbols mặc định.")
        return list(SYMBOLS.values())



def Status1_symbol(trading_type='realtime'):
    """Trả về danh sách symbols có Status = 1 (đang chạy bot)
    
    Args:
        trading_type: 'realtime' hoặc 'backtest'
    """
    try:
        # Xác định cột status dựa vào trading_type
        status_col = 'Status_Realtime' if trading_type == 'realtime' else 'Status_Backtest'
        
        # Kiểm tra file CSV nếu tồn tại
        path = os.path.join(current_dir_results, 'trade_history', 'real_time', 'Symbol.csv')
        if os.path.exists(path):
            df = pd.read_csv(path)
            print(f"Symbol CSV data: {df}")

            # Kiểm tra xem cột 'Symbol' và status column có tồn tại không
            if 'Symbol' not in df.columns or status_col not in df.columns:
                print(f"File CSV không chứa cột 'Symbol' hoặc '{status_col}'.")
                return []

            # Chuyển cột Status thành kiểu số
            df[status_col] = pd.to_numeric(df[status_col], errors='coerce')

            # Lọc các hàng có Status = 1
            filtered_symbols = df[df[status_col] == 1]['Symbol']
            return filtered_symbols.tolist()
        else:
            print("File Symbol.csv không tồn tại.")
            return []

    except FileNotFoundError:
        print("File Symbol.csv không tồn tại.")
        return []
    except ValueError as e:
        print(f"Lỗi dữ liệu: {e}")
        return []
    except Exception as e:
        print(f"Lỗi khác: {e}")
        return []


def update_status(symbol, trading_type='realtime'):
    """Cập nhật trạng thái của symbol trong file CSV
    
    Args:
        symbol: Symbol cần cập nhật
        trading_type: 'realtime' hoặc 'backtest'
    """
    path = os.path.join(current_dir_results, 'trade_history', 'real_time', 'Symbol.csv')

    try:
        # Kiểm tra xem file có tồn tại không
        if not os.path.exists(path):
            print("File Symbol.csv không tồn tại. Tạo mới với symbols động...")
            create_symbol_csv(SYMBOLS)
        
        # Xác định cột status dựa vào trading_type
        status_col = 'Status_Realtime' if trading_type == 'realtime' else 'Status_Backtest'
        
        # Đọc file CSV
        df = pd.read_csv(path)

        # Kiểm tra nếu cột 'Symbol' và status column tồn tại
        if 'Symbol' not in df.columns or status_col not in df.columns:
            raise ValueError(f"File CSV không chứa cột 'Symbol' hoặc '{status_col}'.")

        # Chuyển cột Status thành kiểu số
        df[status_col] = pd.to_numeric(df[status_col], errors='coerce')

        # Kiểm tra nếu symbol có tồn tại
        mask = df['Symbol'] == symbol
        if mask.any():
            # Đảo giá trị Status (0 → 1, 1 → 0)
            df.loc[mask, status_col] = df.loc[mask, status_col].apply(lambda x: 1 if x == 0 else 0)
            df.to_csv(path, index=False)
            print(f"Đã cập nhật {symbol} -> {status_col} = {df.loc[mask, status_col].values[0]}")
        else:
            print(f"Không tìm thấy {symbol} trong file CSV. Có thể symbol không đúng format.")

    except Exception as e:
        print(f"Lỗi: {e}")

    except FileNotFoundError:
        print(" Lỗi: Không tìm thấy file CSV.")
    except ValueError as e:
        print(f" Lỗi dữ liệu: {e}")
    except Exception as e:
        print(f" Lỗi khác: {e}")

def check_Status0(symbol, trading_type='realtime'):
    """Kiểm tra xem symbol có Status = 0 không
    
    Args:
        symbol: Symbol cần kiểm tra
        trading_type: 'realtime' hoặc 'backtest'
    """
    path = os.path.join(current_dir_results, 'trade_history', 'real_time', 'Symbol.csv')

    try:
        # Kiểm tra xem file có tồn tại không
        if not os.path.exists(path):
            print("File Symbol.csv không tồn tại. Tạo mới với symbols động...")
            create_symbol_csv(SYMBOLS)
        
        # Xác định cột status dựa vào trading_type
        status_col = 'Status_Realtime' if trading_type == 'realtime' else 'Status_Backtest'
        
        # Đọc file CSV
        df = pd.read_csv(path)

        # Kiểm tra nếu cột 'Symbol' và status column tồn tại
        if 'Symbol' not in df.columns or status_col not in df.columns:
            raise ValueError(f"File CSV không chứa cột 'Symbol' hoặc '{status_col}'.")

        # Chuyển cột Status thành kiểu số
        df[status_col] = pd.to_numeric(df[status_col], errors='coerce')

        # Kiểm tra nếu symbol có tồn tại
        mask = df['Symbol'] == symbol
        if mask.any():
            status = df.loc[mask, status_col].values[0]
            return status == 0  # Trả về True nếu Status = 0, ngược lại False
        else:
            print(f"Không tìm thấy {symbol} trong file CSV. Có thể symbol không đúng format.")
            return False

    except Exception as e:
        print(f"Lỗi: {e}")
        return False

    except FileNotFoundError:
        print(" Lỗi: Không tìm thấy file CSV.")
        return False
    except ValueError as e:
        print(f" Lỗi dữ liệu: {e}")
        return False
    except Exception as e:
        print(f" Lỗi khác: {e}")
        return False


