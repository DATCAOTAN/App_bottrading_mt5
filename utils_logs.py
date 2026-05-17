import os
import pandas as pd
from datetime import datetime
from utils_paths import current_dir_results

def log_bot_run(symbol, balance, lot_size, equity, trading_type='realtime'):
    """Ghi log khi bot chạy
    
    Args:
        symbol: Symbol đang trade
        balance: Balance hiện tại
        lot_size: Lot size
        equity: Equity
        trading_type: 'realtime' hoặc 'backtest'
    """
    # Định dạng thời gian hiện tại theo format: 12/3/2024 19:34
    time_now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Đường dẫn file
    file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', "Bot_running_details.csv")

    # Chuyển đổi dữ liệu sang kiểu số trước khi lưu
    balance = float(balance)
    lot_size = float(lot_size)
    equity = float(equity)

    # Xác định cột equity và time_stop dựa vào trading_type
    equity_col = 'Eqity_Realtime' if trading_type == 'realtime' else 'Eqity_Backtest'
    time_stop_col = 'Time_stop_bot_Realtime' if trading_type == 'realtime' else 'Time_stop_bot_Backtest'

    # Tạo DataFrame mới với dữ liệu cần ghi
    new_data = pd.DataFrame([{
        "Symbol": symbol,
        "Time_run_bot": time_now,
        "Balance": balance,
        "Lot_size": lot_size,
        "Eqity_Realtime": equity if trading_type == 'realtime' else 0,
        "Eqity_Backtest": equity if trading_type == 'backtest' else 0,
        "Time_stop_bot_Realtime": "Running" if trading_type == 'realtime' else "",
        "Time_stop_bot_Backtest": "Running" if trading_type == 'backtest' else ""
    }])

    # Nếu file đã tồn tại, kiểm tra xem symbol đã có chưa
    if os.path.exists(file_path):
        df = pd.read_csv(file_path)

        # Đảm bảo các cột tồn tại
        for col in ['Eqity_Realtime', 'Eqity_Backtest', 'Time_stop_bot_Realtime', 'Time_stop_bot_Backtest']:
            if col not in df.columns:
                df[col] = 0 if 'Eqity' in col else ""

        # Chuyển đổi kiểu dữ liệu
        df['Balance'] = pd.to_numeric(df['Balance'], errors='coerce')
        df['Lot_size'] = pd.to_numeric(df['Lot_size'], errors='coerce')
        df['Eqity_Realtime'] = pd.to_numeric(df['Eqity_Realtime'], errors='coerce').fillna(0)
        df['Eqity_Backtest'] = pd.to_numeric(df['Eqity_Backtest'], errors='coerce').fillna(0)

        # Kiểm tra xem symbol đã tồn tại hay chưa với trading_type tương ứng
        mask = (df["Symbol"] == symbol) & (df[time_stop_col] == "Running")
        
        if mask.any():
            # Cập nhật dòng có symbol đó (cập nhật dữ liệu mới)
            df.loc[mask, ["Time_run_bot", "Balance", "Lot_size", equity_col]] = \
                [time_now, balance, lot_size, equity]
        else:
            # Thêm dòng mới nếu symbol chưa tồn tại hoặc không đang Running
            df = pd.concat([df, new_data], ignore_index=True)
    else:
        # Nếu file chưa tồn tại, tạo mới
        df = new_data

    # Sắp xếp lại thứ tự cột
    column_order = ['Symbol', 'Time_run_bot', 'Balance', 'Lot_size', 
                    'Eqity_Realtime', 'Eqity_Backtest', 
                    'Time_stop_bot_Realtime', 'Time_stop_bot_Backtest']
    df = df[column_order]

    # Lưu lại file CSV
    df.to_csv(file_path, index=False)
    print(f"✅ Đã cập nhật log cho {symbol} ({trading_type}) vào {file_path}")

def update_stop_time(symbol, trading_type='realtime'):
    """Cập nhật thời gian dừng bot
    
    Args:
        symbol: Symbol cần cập nhật
        trading_type: 'realtime' hoặc 'backtest'
    """
    file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', "Bot_running_details.csv")
    file_path_close = os.path.join(current_dir_results, 'trade_history', 'real_time', "Bot_close_details.csv")

    if not os.path.exists(file_path):
        print("❌ Không tìm thấy file log.")
        return

    # Đọc dữ liệu từ file
    df = pd.read_csv(file_path)

    # Định dạng thời gian hiện tại
    time_now = datetime.now().strftime("%d/%m/%Y %H:%M")

    # Xác định cột time_stop dựa vào trading_type
    time_stop_col = 'Time_stop_bot_Realtime' if trading_type == 'realtime' else 'Time_stop_bot_Backtest'

    # Tìm dòng có symbol đang chạy với trading_type tương ứng
    mask = (df["Symbol"] == symbol) & (df[time_stop_col] == "Running")

    if mask.any():
        latest_index = df[mask].index[-1]
        
        # Cập nhật thời gian dừng bot
        df.at[latest_index, time_stop_col] = time_now  # Dùng `.at[]` để tránh SettingWithCopyWarning
        
        # Lấy dữ liệu của bot đã dừng
        closed_data = df.loc[[latest_index]].copy()
        
        # Xác định cột equity dựa vào trading_type
        equity_col = 'Eqity_Realtime' if trading_type == 'realtime' else 'Eqity_Backtest'
        
        # Tạo cột Eqity cho file close (lấy từ equity column tương ứng)
        closed_data['Eqity'] = closed_data[equity_col]
        
        # Thêm cột Time_stop_bot cho file close
        closed_data['Time_stop_bot'] = time_now
        
        # Xóa các cột riêng biệt của 2 mode
        closed_data = closed_data.drop(columns=[
            'Eqity_Realtime', 'Eqity_Backtest',
            'Time_stop_bot_Realtime', 'Time_stop_bot_Backtest'
        ], errors='ignore')
        
        # Sắp xếp lại cột cho file close
        close_column_order = ['Symbol', 'Time_run_bot', 'Balance', 'Lot_size', 'Eqity', 'Time_stop_bot']
        closed_data = closed_data[[col for col in close_column_order if col in closed_data.columns]]

        # Xử lý nếu file đóng lệnh đã tồn tại
        if os.path.exists(file_path_close):
            df_close = pd.read_csv(file_path_close)
            
            # Kiểm tra nếu `df_close` trống
            if df_close.empty:
                df_close = closed_data
            else:
                df_close = pd.concat([df_close, closed_data], ignore_index=True)  # Thêm dòng mới
        else:
            df_close = closed_data  # Tạo mới nếu file chưa tồn tại

        # Ghi lại cả hai file
        df.to_csv(file_path, index=False)  # Cập nhật danh sách bot đang chạy
        df_close.to_csv(file_path_close, index=False)  # Cập nhật danh sách bot đã đóng

        print(f"✅ Đã cập nhật `{time_stop_col}` cho {symbol} và lưu vào file đóng lệnh.")
    else:
        print(f"⚠️ Không tìm thấy {symbol} ({trading_type}) đang Running trong file log.")

def update_eqity_running(symbol, profit, trading_type='realtime'):
    """Cập nhật Equity cho bot đang chạy
    
    Args:
        symbol: Symbol cần cập nhật
        profit: Profit cần cộng vào
        trading_type: 'realtime' hoặc 'backtest'
    """
    file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', "Bot_running_details.csv")

    if not os.path.exists(file_path):
        print("Không tìm thấy file log.")
        return

    # Đọc dữ liệu từ file CSV
    df = pd.read_csv(file_path)

    # Xác định cột equity và time_stop dựa vào trading_type
    equity_col = 'Eqity_Realtime' if trading_type == 'realtime' else 'Eqity_Backtest'
    time_stop_col = 'Time_stop_bot_Realtime' if trading_type == 'realtime' else 'Time_stop_bot_Backtest'

    # Tìm dòng mới nhất của symbol có Time_stop_bot = "Running" cho trading_type tương ứng
    mask = (df["Symbol"] == symbol) & (df[time_stop_col] == "Running")
    
    if mask.any():
        latest_index = df[mask].index[-1]  # Lấy dòng cuối cùng phù hợp
        df.at[latest_index, equity_col] += profit  # Cộng profit vào Eqity tương ứng
        df.to_csv(file_path, index=False)
        print(f"Đã cập nhật {equity_col} cho {symbol} ({trading_type}): {profit}")
    else:
        print(f"Không tìm thấy dòng `Running` của {symbol} ({trading_type}) trong file log.")


def total_balance_running(trading_type='realtime'):
    """Tính tổng Balance của các bot đang chạy
    
    Args:
        trading_type: 'realtime' hoặc 'backtest'
    """
    file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', "Bot_running_details.csv")

    if not os.path.exists(file_path):
        print("Không tìm thấy file log.")
        return 0  # Trả về 0 nếu file không tồn tại

    # Đọc dữ liệu từ file CSV
    df = pd.read_csv(file_path)

    # Xác định cột time_stop dựa vào trading_type
    time_stop_col = 'Time_stop_bot_Realtime' if trading_type == 'realtime' else 'Time_stop_bot_Backtest'

    # Kiểm tra nếu cột cần thiết tồn tại
    if time_stop_col not in df.columns or 'Balance' not in df.columns:
        print(f"File CSV không chứa cột '{time_stop_col}' hoặc 'Balance'.")
        return 0

    # Lọc các dòng có Time_stop_bot == "Running" cho trading_type tương ứng
    running_bots = df[df[time_stop_col] == "Running"]

    # Chuyển cột Balance về dạng số để tính tổng
    running_bots.loc[:, "Balance"] = pd.to_numeric(running_bots["Balance"], errors='coerce').fillna(0)

    # Tính tổng Balance
    total_balance = running_bots["Balance"].sum()

    print(f"Tổng Balance của các bot ({trading_type}) đang chạy: {total_balance}")
    return total_balance



