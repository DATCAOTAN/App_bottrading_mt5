from PyQt5 import QtCore, QtWidgets
from PyQt5.QtCore import Qt
import pandas as pd
from utils_account import get_trade_history_file_path
from utils_paths import current_dir_results
import utils_account
from SYMBOLs import SYMBOLS
from historytable import HistoryTableModel


class Ui_HistoryDialog(object):
    def setupUi(self, HistoryDialog):
        HistoryDialog.setObjectName("HistoryDialog")
        HistoryDialog.resize(1000, 600)

        self.history_tableView = QtWidgets.QTableView(HistoryDialog)
        self.history_tableView.setGeometry(QtCore.QRect(0, 50, 930, 550))

        self.retranslateUi(HistoryDialog)
        QtCore.QMetaObject.connectSlotsByName(HistoryDialog)
        

        
    def retranslateUi(self, HistoryDialog):
        _translate = QtCore.QCoreApplication.translate
        HistoryDialog.setWindowTitle(_translate("HistoryDialog", "Trade History"))

    def load_trade_history_options(self):
        # Load options data
        options_file = 'results/trade_history/real_time/trade_history_option.csv'
        self.options_data = pd.read_csv(options_file)
        
        # Connect table to show details when clicking
        self.history_tableView.clicked.connect(self.on_option_selected)

    def load_trade_history(self,model,HistoryDialog):
        HistoryDialog.setObjectName("HistoryDialog")
   

        self.history_tableView = QtWidgets.QTableView(HistoryDialog)
        self.history_tableView.setGeometry(QtCore.QRect(0, 50, 930, 550))

        self.retranslateUi(HistoryDialog)
        QtCore.QMetaObject.connectSlotsByName(HistoryDialog)
        self.history_tableView.setModel(model)


        
    def on_option_selected(self, index):
        selected_row = index.row()
        selected_time = self.options_data.iloc[selected_row]['Datetime_entry']
        selected_symbols = self.options_data.iloc[selected_row]['Selected Symbols'].split(',')

        # Load trades within the selected period
        trades = []
        for symbol in selected_symbols:
            symbol = symbol.strip()
            # Sử dụng hàm helper để lấy đường dẫn file CSV với tên có login
            if symbol == SYMBOLS["XAUUSD"]:
                file_path = utils_account.get_trade_history_file_path("XAUUSD")
            elif symbol == SYMBOLS["BTCUSD"]:
                file_path = utils_account.get_trade_history_file_path("BTCUSD")
            elif symbol == SYMBOLS["USOIL"]:
                file_path = utils_account.get_trade_history_file_path("USOIL")
            else:
                print(f"⚠️ Symbol không được hỗ trợ: {symbol}")
                continue
            
            if file_path is None:
                print(f"⚠️ Không thể lấy đường dẫn file CSV cho symbol {symbol}")
                continue
                
            try:
                df = pd.read_csv(file_path)
                # Kiểm tra xem cột 'Datetime_entry' có tồn tại không
                if 'Datetime_entry' in df.columns:
                    filtered_trades = df[df['Datetime_entry'] >= selected_time]
                    trades.append(filtered_trades)
                    print(f"✅ Đã load {len(filtered_trades)} trades cho {symbol}")
                else:
                    print(f"⚠️ File CSV cho {symbol} không có cột 'Datetime_entry'")
                    # Sử dụng toàn bộ dữ liệu nếu không có cột thời gian
                    trades.append(df)
                    print(f"✅ Đã load {len(df)} trades cho {symbol} (không filter theo thời gian)")
            except Exception as e:
                print(f"❌ Lỗi khi đọc file CSV cho {symbol}: {e}")
                continue

        combined_trades = pd.concat(trades, ignore_index=True)
        model = HistoryTableModel(combined_trades)
        self.history_tableView.setModel(model)



