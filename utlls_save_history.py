from utils_account import get_trade_history_file_path,get_backtest_trade_history_file_path
import os
import pandas as pd
def save_trade_history_csv_files(symbol_key,data,name_ai,mode="Real time"):
    if mode=="Real time":
        file_path = get_trade_history_file_path(symbol_key)
    elif mode=="Backtest":
         file_path = get_backtest_trade_history_file_path(symbol_key)
    # Kiểm tra xem thư mục đã tồn tại chưa, nếu chưa thì tạo mới
    flag=False
    if not os.path.exists(file_path):
        flag=True
    
    # Xử lý data - có thể là list hoặc dict
    if isinstance(data, list):
        # Nếu là list, chuyển thành DataFrame trực tiếp
        df = pd.DataFrame(data)
    else:
        # Nếu là dict, thêm AI name và chuyển thành DataFrame
        data['AI'] = name_ai.strip()
        df = pd.DataFrame([data])
    
    # Ghi vào file CSV, nếu file đã tồn tại thì chỉ thêm dữ liệu, không ghi lại header
    df.to_csv(file_path, mode='a', header=flag, index=False)
