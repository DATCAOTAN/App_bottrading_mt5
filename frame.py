import sys
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QMessageBox
from matplotlib.figure import Figure
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
import os
import logging.config
import yaml
from PyQt5.QtWidgets import  QVBoxLayout
from utils_paths import current_dir_backtest
import pandas as pd
import utils_account
from utils_account import mt5
import utils_symbol_csv
from SYMBOLs import SYMBOLS, account_suffix
import utils_symbols
import utils_symbol_csv
from ui_trade import Ui_TradeDialog
from historytable import HistoryTableModel
from ui_history import Ui_HistoryDialog
from ui_running import Ui_RunningBotDialog
from utils_messagebox import show_message
list_tradeable_symbols = utils_symbols.list_tradeable_symbols()
# Lấy thông tin tài khoản và suffix symbol với error handling
if mt5.initialize():
    account_info = mt5.account_info()
    mt5.shutdown()
    if account_info:
        print(f"Account Info: {account_info}")
    else:
        print("⚠️ Không thể lấy thông tin tài khoản")
        account_info = None
else:
    print("⚠️ MT5 initialization failed")
    account_info = None
    
print(f"Symbol Suffix: {account_suffix}")

# Load logging configuration
with open("config/logging.yaml", "r") as file:
    logging_config = yaml.safe_load(file)
    logging.config.dictConfig(logging_config)

logger = logging.getLogger("live_trade")
create_symbol_csv = utils_symbol_csv.create_symbol_csv(SYMBOLS)
create_trade_history_csv_files = utils_account.create_trade_history_csv_files(SYMBOLS)
print(f"Symbols được sử dụng: {SYMBOLS}")



class Ui_MainWindow(object):
    def __init__(self):
        super().__init__()
        self.live_traders = {}  # Quản lý các bot đang chạy
        self.data_mode = "Real-time"  # Real-time | Backtest

    def setupUi(self, MainWindow):
        MainWindow.setObjectName("MainWindow")
        MainWindow.setWindowModality(QtCore.Qt.ApplicationModal)
        MainWindow.setEnabled(True)
        MainWindow.resize(1200, 800)
        MainWindow.setMaximumSize(QtCore.QSize(1200, 800))
        self.centralwidget = QtWidgets.QWidget(MainWindow)
        self.centralwidget.setObjectName("centralwidget")
        
        
        self.header_frame = QtWidgets.QFrame(self.centralwidget)
        self.header_frame.setGeometry(QtCore.QRect(0, 0, 1200, 50))
        self.header_frame.setStyleSheet("background-color: rgb(23, 31, 42);")
        self.header_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.header_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.header_frame.setObjectName("header_frame")
        
        #Trade button
        self.trade_pushButton = QtWidgets.QPushButton(self.header_frame)
        self.trade_pushButton.setGeometry(QtCore.QRect(680, 10, 150, 30))
        font = QtGui.QFont()
        font.setPointSize(16)
        font.setBold(True)
        font.setWeight(75)
        self.trade_pushButton.setFont(font)
        self.trade_pushButton.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.trade_pushButton.setStyleSheet("color: rgb(254, 254, 254);\n"
                                            "background-color: rgb(23, 249, 183);")
        self.trade_pushButton.setObjectName("trade_pushButton")

         #Running 
        self.running_bot = QtWidgets.QPushButton(self.header_frame)
        self.running_bot.setGeometry(QtCore.QRect(520, 10, 150, 30))
        font = QtGui.QFont()
        font.setPointSize(16)
        font.setBold(True)
        font.setWeight(75)
        self.running_bot.setFont(font)
        self.running_bot.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.running_bot.setStyleSheet("color: rgb(254, 254, 254);\n"
                                            "background-color: rgb(23, 249, 183);")
        self.running_bot.setObjectName("running_bot")
        #Thêm sự kiện click cho nút button running
        self.running_bot.clicked.connect(self.openRunningBotDialog)

        #Button history
        self.history_pushButton = QtWidgets.QPushButton(self.header_frame)
        self.history_pushButton.setGeometry(QtCore.QRect(840, 10, 150, 30))
        font = QtGui.QFont()
        font.setPointSize(16)
        font.setBold(True)
        font.setWeight(75)
        self.history_pushButton.setFont(font)
        self.history_pushButton.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.history_pushButton.setStyleSheet(
            "color: rgb(31, 43, 57);\n"
            "background-color: rgb(254, 254, 254);")
        self.history_pushButton.setObjectName("history_pushButton")
        
        
        self.trade_pushButton.clicked.connect(self.openTradeDialog)
        self.history_pushButton.clicked.connect(self.openHistoryDialog)
        
        
        # (replaced by time range combobox in content area)

        # Thêm hai checkbox mới: SELF-TRAIN MODEL và AI MODEL
        self.self_train_checkBox = QtWidgets.QCheckBox(self.header_frame)
        self.self_train_checkBox.setGeometry(QtCore.QRect(20, 10, 300, 31))
        self.self_train_checkBox.setFont(font)
        self.self_train_checkBox.setStyleSheet("color: rgb(254, 254, 254);")
        self.self_train_checkBox.setChecked(True)
        self.self_train_checkBox.setObjectName("self_train_checkBox")
        self.self_train_checkBox.clicked.connect(self.on_self_train_filter_clicked)

        self.ai_model_checkBox = QtWidgets.QCheckBox(self.header_frame)
        self.ai_model_checkBox.setGeometry(QtCore.QRect(320, 10, 200, 31))
        self.ai_model_checkBox.setFont(font)
        self.ai_model_checkBox.setStyleSheet("color: rgb(254, 254, 254);")
        self.ai_model_checkBox.setChecked(True)
        self.ai_model_checkBox.setObjectName("ai_model_checkBox")
        self.ai_model_checkBox.clicked.connect(self.on_ai_filter_clicked)

        # Combobox chọn chế độ dữ liệu: Real-time / Backtest
        self.mode_combo = QtWidgets.QComboBox(self.header_frame)
        self.mode_combo.setGeometry(QtCore.QRect(1030, 10, 150, 30))
        self.mode_combo.setFont(font)
        self.mode_combo.setStyleSheet("color: rgb(31, 43, 57);\nbackground-color: rgb(254, 254, 254);")
        self.mode_combo.addItems(["Real-time", "Backtest"])
        self.mode_combo.setCurrentText("Real-time")
        self.mode_combo.currentIndexChanged.connect(self.on_mode_changed)

        
        self.content_frame = QtWidgets.QFrame(self.centralwidget)
        self.content_frame.setGeometry(QtCore.QRect(0, 50, 1501, 850))
        self.content_frame.setStyleSheet("background-color: rgb(31, 43, 57);")
        self.content_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.content_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.content_frame.setObjectName("content_frame")
       
        
        # Ô tìm kiếm symbol + combobox chứa toàn bộ symbol tradeable
        self.symbol_search = QtWidgets.QLineEdit(self.content_frame)
        self.symbol_search.setGeometry(QtCore.QRect(50, 20, 240, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        self.symbol_search.setFont(font)
        self.symbol_search.setPlaceholderText("Search symbol...")
        self.symbol_search.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")

        self.symbol_combo = QtWidgets.QComboBox(self.content_frame)
        self.symbol_combo.setGeometry(QtCore.QRect(300, 20, 240, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        self.symbol_combo.setFont(font)
        self.symbol_combo.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")
        self.symbol_combo.setObjectName("symbol_combo")
        
        # Time range combobox (next to symbol combobox)
        self.time_range_combo = QtWidgets.QComboBox(self.content_frame)
        self.time_range_combo.setGeometry(QtCore.QRect(550, 20, 180, 31))
        self.time_range_combo.setFont(font)
        self.time_range_combo.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")
        self.time_range_combo.addItems(["All the time", "Day/Month/Year", "Month/Year", "Year"])
        self.time_range_combo.currentIndexChanged.connect(self.on_time_mode_changed)
        # Redraw statistics when mode changes
        self.time_range_combo.currentIndexChanged.connect(lambda: self.reload(self.get_selected_data()))
        # Metric selection combobox (y-axis: Profit or Total Trades)
        self.metric_combo = QtWidgets.QComboBox(self.content_frame)
        self.metric_combo.setGeometry(QtCore.QRect(740, 20, 150, 31))
        self.metric_combo.setFont(font)
        self.metric_combo.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")
        self.metric_combo.addItems(["Profit", "Total Trades"]) 
        self.metric_combo.currentIndexChanged.connect(lambda: self.reload(self.get_selected_data()))
        
        # Dynamic date inputs under the row
        self.time_inputs_frame = QtWidgets.QFrame(self.content_frame)
        self.time_inputs_frame.setGeometry(QtCore.QRect(50, 67, 800, 36))
        self.time_inputs_frame.setObjectName("time_inputs_frame")
        
        self.day_input = QtWidgets.QSpinBox(self.time_inputs_frame)
        self.day_input.setGeometry(QtCore.QRect(0, 0, 90, 31))
        self.day_input.setRange(1, 31)
        self.day_input.setPrefix("D:")
        self.day_input.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")
        
        self.month_input = QtWidgets.QSpinBox(self.time_inputs_frame)
        self.month_input.setGeometry(QtCore.QRect(100, 0, 90, 31))
        self.month_input.setRange(1, 12)
        self.month_input.setPrefix("M:")
        self.month_input.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")
        
        self.year_input = QtWidgets.QSpinBox(self.time_inputs_frame)
        self.year_input.setGeometry(QtCore.QRect(200, 0, 110, 31))
        self.year_input.setRange(2000, 2100)
        self.year_input.setPrefix("Y:")
        self.year_input.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")
        
        self.time_search_btn = QtWidgets.QPushButton(self.time_inputs_frame)
        self.time_search_btn.setGeometry(QtCore.QRect(320, 0, 120, 31))
        self.time_search_btn.setText("Tìm kiếm")
        self.time_search_btn.setStyleSheet("color: rgb(31, 43, 57); background-color: rgb(254, 254, 254);")
        self.time_search_btn.clicked.connect(self.on_time_search_clicked)
        
        # Initialize visibility
        self.on_time_mode_changed()
        # Nạp danh sách symbol từ MT5
        self.all_symbols = list_tradeable_symbols
        if not self.all_symbols:
            # fallback: dùng SYMBOLS động nếu không fetch được
            self.all_symbols = list(SYMBOLS.values())
        self.populate_symbol_combo("")
        self.symbol_search.textChanged.connect(self.on_symbol_search_changed)
        self.symbol_combo.currentIndexChanged.connect(self.on_symbol_changed)
        
        
        self.profit_frame = QtWidgets.QFrame(self.content_frame)
        self.profit_frame.setGeometry(QtCore.QRect(50, 110, 261, 140))
        self.profit_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.profit_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.profit_frame.setObjectName("profit_frame")
        self.profit_label = QtWidgets.QLabel(self.profit_frame)
        self.profit_label.setGeometry(QtCore.QRect(0, 0, 261, 30))
        font = QtGui.QFont()
        font.setFamily("MS Shell Dlg 2")
        font.setPointSize(16)
        font.setBold(True)
        font.setWeight(75)
        font.setKerning(True)
        self.profit_label.setFont(font)
        self.profit_label.setStyleSheet(
            "background-color: rgb(23, 249, 183);\n"
            "border-top-left-radius :15px;\n"
            "border-top-right-radius : 15px; ")
        self.profit_label.setAlignment(QtCore.Qt.AlignCenter)
        self.profit_label.setObjectName("profit_label")
        
        
        self.profitValue_label = QtWidgets.QLabel(self.profit_frame)
        self.profitValue_label.setGeometry(QtCore.QRect(0, 30, 261, 111))
        font = QtGui.QFont()
        font.setPointSize(32)
        font.setBold(True)
        font.setWeight(75)
        self.profitValue_label.setFont(font)
        self.profitValue_label.setStyleSheet(
            "background-color: rgb(254, 254, 254);\n"
            "color: rgb(23, 249, 183);\n"
            "border-bottom-left-radius :15px;\n"
            "border-bottom-right-radius : 15px; ")
        self.profitValue_label.setAlignment(QtCore.Qt.AlignCenter)
        self.profitValue_label.setObjectName("profitValue_label")
        
        
        self.winRate_frame = QtWidgets.QFrame(self.content_frame)
        self.winRate_frame.setGeometry(QtCore.QRect(380, 110, 261, 141))
        self.winRate_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.winRate_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.winRate_frame.setObjectName("winRate_frame")
        
        
        self.winRate_label = QtWidgets.QLabel(self.winRate_frame)
        self.winRate_label.setGeometry(QtCore.QRect(0, 0, 261, 31))
        font = QtGui.QFont()
        font.setFamily("MS Shell Dlg 2")
        font.setPointSize(16)
        font.setBold(True)
        font.setWeight(75)
        font.setKerning(True)
        self.winRate_label.setFont(font)
        self.winRate_label.setStyleSheet(
            "background-color: rgb(23, 249, 183);\n"
            "border-top-left-radius :15px;\n"
            "border-top-right-radius : 15px; ")
        self.winRate_label.setAlignment(QtCore.Qt.AlignCenter)
        self.winRate_label.setObjectName("winRate_label")

        
        self.winRateValue_label = QtWidgets.QLabel(self.winRate_frame)
        self.winRateValue_label.setGeometry(QtCore.QRect(0, 30, 261, 111))
        font = QtGui.QFont()
        font.setPointSize(32)
        font.setBold(True)
        font.setWeight(75)
        self.winRateValue_label.setFont(font)
        self.winRateValue_label.setStyleSheet(
            "background-color: rgb(254, 254, 254);\n"
            "color: rgb(23, 249, 183);\n"
            "border-bottom-left-radius :15px;\n"
            "border-bottom-right-radius : 15px; ")
        self.winRateValue_label.setAlignment(QtCore.Qt.AlignCenter)
        self.winRateValue_label.setObjectName("winRateValue_label")
        
        
        self.balance_label = QtWidgets.QLabel(self.content_frame)
        self.balance_label.setGeometry(QtCore.QRect(710, 80, 121, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.balance_label.setFont(font)
        self.balance_label.setStyleSheet("color: rgb(254, 254, 254);")
        self.balance_label.setObjectName("balance_label")
        
        
        self.totalTrades_label = QtWidgets.QLabel(self.content_frame)
        self.totalTrades_label.setGeometry(QtCore.QRect(710, 130, 121, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.totalTrades_label.setFont(font)
        self.totalTrades_label.setStyleSheet("color: rgb(254, 254, 254);")
        self.totalTrades_label.setObjectName("totalTrades_label")
        
        
        self.averageProfitPerTrade_label = QtWidgets.QLabel(self.content_frame)
        self.averageProfitPerTrade_label.setGeometry(QtCore.QRect(710, 180, 121, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.averageProfitPerTrade_label.setFont(font)
        self.averageProfitPerTrade_label.setStyleSheet("color: rgb(254, 254, 254);")
        self.averageProfitPerTrade_label.setObjectName("averageProfitPerTrade_label")
        
        
        self.balanceValue_label = QtWidgets.QLabel(self.content_frame)
        self.balanceValue_label.setGeometry(QtCore.QRect(840, 80, 131, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.balanceValue_label.setFont(font)
        self.balanceValue_label.setStyleSheet("color: rgb(254, 254, 254);")
        self.balanceValue_label.setObjectName("balanceValue_label")
        
        
        self.totalTradesValue_label = QtWidgets.QLabel(self.content_frame)
        self.totalTradesValue_label.setGeometry(QtCore.QRect(840, 130, 131, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.totalTradesValue_label.setFont(font)
        self.totalTradesValue_label.setStyleSheet("color: rgb(254, 254, 254);")
        self.totalTradesValue_label.setObjectName("totalTradesValue_label")
        
        
        self.averageProfitPerTradeValue_label = QtWidgets.QLabel(self.content_frame)
        self.averageProfitPerTradeValue_label.setGeometry(QtCore.QRect(840, 180, 131, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.averageProfitPerTradeValue_label.setFont(font)
        self.averageProfitPerTradeValue_label.setStyleSheet("color: rgb(254, 254, 254);")
        self.averageProfitPerTradeValue_label.setObjectName("averageProfitPerTradeValue_label")
        
        
        self.calendar_frame = QtWidgets.QFrame(self.content_frame)
        self.calendar_frame.setGeometry(QtCore.QRect(50, 260, 350, 450))
        self.calendar_frame.setStyleSheet("")
        self.calendar_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.calendar_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.calendar_frame.setObjectName("calendar_frame")
        
        
        self.calendar_label = QtWidgets.QLabel(self.calendar_frame)
        self.calendar_label.setGeometry(QtCore.QRect(0, 0, 350, 30))
        font = QtGui.QFont()
        font.setPointSize(16)
        font.setBold(True)
        font.setWeight(75)
        self.calendar_label.setFont(font)
        self.calendar_label.setStyleSheet("background-color: rgb(255, 207, 16);")
        self.calendar_label.setAlignment(QtCore.Qt.AlignCenter)
        self.calendar_label.setObjectName("calendar_label")
        
        
        self.calendarWidget = QtWidgets.QCalendarWidget(self.calendar_frame)
        self.calendarWidget.setGeometry(QtCore.QRect(0, 30, 350, 420))
        self.calendarWidget.setAutoFillBackground(False)
        self.calendarWidget.setStyleSheet(
            "color: rgb(31, 43, 57);\n"
            "background-color: rgb(254, 254, 254);")
        self.calendarWidget.setGridVisible(False)
        self.calendarWidget.setNavigationBarVisible(True)
        self.calendarWidget.setObjectName("calendarWidget")
        
        
        self.statisticsChart_frame = QtWidgets.QFrame(self.content_frame)
        self.statisticsChart_frame.setGeometry(QtCore.QRect(440, 260,700,450))
        self.statisticsChart_frame.setAutoFillBackground(False)
        self.statisticsChart_frame.setStyleSheet("background-color: rgb(254, 254, 254);")
        self.statisticsChart_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.statisticsChart_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.statisticsChart_frame.setObjectName("statisticsChart_frame")
        
        
        self.chart_frame = QtWidgets.QFrame(self.statisticsChart_frame)
        self.chart_frame.setGeometry(QtCore.QRect(0, 30, 700, 410))
        self.chart_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.chart_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.chart_frame.setObjectName("chart_frame")
        
        
        self.chart_label = QtWidgets.QLabel(self.statisticsChart_frame)
        self.chart_label.setGeometry(QtCore.QRect(0, 0, 700, 31))
        font = QtGui.QFont()
        font.setPointSize(16)
        font.setBold(True)
        font.setWeight(75)
        self.chart_label.setFont(font)
        self.chart_label.setStyleSheet("background-color: rgb(255, 207, 16);")
        self.chart_label.setAlignment(QtCore.Qt.AlignCenter)
        self.chart_label.setObjectName("chart_label")
        # Place metric selector at top-right of statistics frame
        try:
            self.metric_combo.setParent(self.statisticsChart_frame)
            self.metric_combo.setGeometry(QtCore.QRect(540, 2, 150, 26))  # 700 - 150 - 10 margin
            self.metric_combo.raise_()
        except Exception:
            pass
        
        
        MainWindow.setCentralWidget(self.centralwidget)
        self.menubar = QtWidgets.QMenuBar(MainWindow)
        self.menubar.setGeometry(QtCore.QRect(0, 0, 1500, 21))
        self.menubar.setObjectName("menubar")
        MainWindow.setMenuBar(self.menubar)
        self.statusbar = QtWidgets.QStatusBar(MainWindow)
        self.statusbar.setObjectName("statusbar")
        MainWindow.setStatusBar(self.statusbar)
        self.model=None

        self.retranslateUi(MainWindow)
        QtCore.QMetaObject.connectSlotsByName(MainWindow)

    def retranslateUi(self, MainWindow):
        balance = utils_account.get_balance()
        
        data = self.get_selected_data()

        # Tính toán tổng hợp với error handling
        try:
            # Kiểm tra xem cột 'Profit' có tồn tại không
            if 'Profit' not in data.columns:
                print("⚠️ Cột 'Profit' không tồn tại trong DataFrame, tạo cột mặc định")
                data['Profit'] = 0.0
            
            total_profit = data['Profit'].sum()
            if 'Win' in data.columns:
                win_count = data['Win'].apply(lambda x: str(x).strip().lower() == 'true').sum()
            else:
                win_count = data[data['Profit'] > 0].shape[0]
            loss_count = len(data) - win_count
        except Exception as e:
            print(f"❌ Lỗi khi tính toán profit: {e}")
            total_profit = 0.0
            win_count = 0
            loss_count = 0
        total_trades = win_count + loss_count
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
        average_profit_per_trade = total_profit / total_trades if total_trades > 0 else 0

        
        balance = self.format_large_number(balance)
        total_profit = self.format_large_number(total_profit)
        total_trades = self.format_large_number(total_trades)
        average_profit_per_trade = self.format_large_number(average_profit_per_trade)
        
        _translate = QtCore.QCoreApplication.translate
        MainWindow.setWindowTitle(_translate("MainWindow", "Bot Trading MT5"))
        self.trade_pushButton.setText(_translate("MainWindow", "Trade"))
        self.running_bot.setText("Running")
        self.history_pushButton.setText(_translate("MainWindow", "History"))
        # removed checkbox label
        self.self_train_checkBox.setText(_translate("MainWindow", "SELF-TRAIN MODEL"))
        self.ai_model_checkBox.setText(_translate("MainWindow", "AI MODEL"))
        # combobox hiển thị danh sách, không cần setText
        self.chart_label.setText(_translate("MainWindow", "Statistics Diagram"))
        self.profit_label.setText(_translate("MainWindow", "Profit"))
        self.profitValue_label.setText(_translate("MainWindow", f'${total_profit}'))
        self.winRate_label.setText(_translate("MainWindow", "Win rate"))
        self.winRateValue_label.setText(_translate("MainWindow", f'{win_rate:.1f}%'))
        self.balance_label.setText(_translate("MainWindow", "Balance:"))
        self.balanceValue_label.setText(_translate("MainWindow", f'${balance}'))
        self.totalTrades_label.setText(_translate("MainWindow", "Total Trades:"))
        self.totalTradesValue_label.setText(_translate("MainWindow", f'{total_trades}'))
        self.averageProfitPerTrade_label.setText(_translate("MainWindow", "AP/T:"))
        self.averageProfitPerTradeValue_label.setText(_translate("MainWindow", f'${average_profit_per_trade}'))
        self.calendar_label.setText(_translate("MainWindow", "Calendar"))
        self.calendarWidget.selectionChanged.connect(self.on_calendar_date_changed)
    

        self.plot_profit_chart(data)
    def on_mode_changed(self):
        try:
            self.data_mode = self.mode_combo.currentText()
        except Exception:
            self.data_mode = "Real-time"
        # Reload everything based on new mode
        self.reload(self.get_selected_data())
    def populate_symbol_combo(self, keyword):
        try:
            current = self.symbol_combo.currentText()
        except Exception:
            current = ""
        self.symbol_combo.blockSignals(True)
        self.symbol_combo.clear()
        if keyword:
            filt = [s for s in self.all_symbols if keyword.upper() in s.upper()]
        else:
            filt = list(self.all_symbols)
        # Add "All Symbol" option at top
        filt = ["All Symbol"] + filt
        self.symbol_combo.addItems(filt)
        # khôi phục lựa chọn nếu có
        if current in filt:
            idx = filt.index(current)
            self.symbol_combo.setCurrentIndex(idx)
        self.symbol_combo.blockSignals(False)

    def on_symbol_search_changed(self, text):
        self.populate_symbol_combo(text)
    

    def openTradeDialog(self):
        # Lấy danh sách symbols có thể trade
        listStatus0_symbol = utils_symbol_csv.Status0_symbol()
        print(f"Symbols có thể trade: {listStatus0_symbol}")
        
        if len(listStatus0_symbol) == 0:
            show_message("Info", "Tất cả bot đang chạy xin hãy vào running để xem.")
            return
            
        trade_dialog = QtWidgets.QDialog()
        ui = Ui_TradeDialog(self, self.data_mode)
        ui.setupUi(trade_dialog)
        trade_dialog.exec_()

    def openRunningBotDialog(self):
        running_dialog = Ui_RunningBotDialog(self,mode=self.data_mode)  # Tạo đối tượng từ class Ui_RunningBotDialog
        running_dialog.exec_()  

    def openHistoryDialog(self):
        history_dialog = QtWidgets.QDialog()
        ui = Ui_HistoryDialog()
        self.model=HistoryTableModel(self.get_selected_data())
        ui.load_trade_history(self.model,history_dialog)
        history_dialog.exec_()
        
    def format_large_number(self, number):
        if abs(number) >= 1_000_000_000:
            return f'{number / 1_000_000_000:.1f}B'  # Format as billions
        elif abs(number) >= 1_000_000:
            return f'{number / 1_000_000:.1f}M'   # Format as millions
        elif abs(number) >= 1_000:
            return f'{number / 1_000:.1f}K'       # Format as thousands
        else:
            return f'{number:.1f}'
        
    def on_calendar_date_changed(self):
        try:
            selected_qdate = self.calendarWidget.selectedDate()
            if selected_qdate is not None:
                d = selected_qdate.day()
                m = selected_qdate.month()
                y = selected_qdate.year()
                # Đồng bộ về các ô input để bộ lọc dùng đúng ngày được chọn
                self.day_input.setValue(d)
                self.month_input.setValue(m)
                self.year_input.setValue(y)
                # Đồng bộ combobox thời gian sang Day/Month/Year
                if self.time_range_combo.currentText() != "Day/Month/Year":
                    self.time_range_combo.blockSignals(True)
                    self.time_range_combo.setCurrentText("Day/Month/Year")
                    self.time_range_combo.blockSignals(False)
                    # Cập nhật hiển thị input theo mode mới
                    self.on_time_mode_changed()
        except Exception:
            pass
        self.reload(self.get_selected_data())

    def plot_profit_chart(self, data):
        fig = Figure(figsize=(9, 5.2), dpi=110)
        ax = fig.add_subplot(111)
        df = data.copy()

        # Parse datetime
        try:
            df['_dt'] = pd.to_datetime(df['Datetime_entry'], errors='coerce')
        except Exception:
            df['_dt'] = pd.NaT

        # Build bucket based on time range mode
        try:
            mode = self.time_range_combo.currentText()
        except Exception:
            mode = "All the time"

        if mode == "Day/Month/Year":
            # By hour within selected day range (data is already filtered by UI)
            df['bucket'] = df['_dt'].dt.strftime('%Y-%m-%d %H:00')
        elif mode == "Month/Year":
            # ISO week
            df['bucket'] = df['_dt'].dt.strftime('%G-W%V')
        elif mode == "Year":
            # By month
            df['bucket'] = df['_dt'].dt.strftime('%Y-%m')
        else:
            # All time → by year
            df['bucket'] = df['_dt'].dt.strftime('%Y')

        if df.empty or 'bucket' not in df.columns:
            merged = pd.DataFrame({'bucket': [], 'trades': [], 'profit': []})
        else:
            # Kiểm tra cột 'Profit' trước khi groupby
            if 'Profit' not in df.columns:
                print("⚠️ Cột 'Profit' không tồn tại trong DataFrame, tạo cột mặc định cho chart")
                df['Profit'] = 0.0
                
            g_trades = df.groupby('bucket', as_index=False).size().rename(columns={'size': 'trades'})
            g_profit = df.groupby('bucket', as_index=False)['Profit'].sum().rename(columns={'Profit': 'profit'})
            merged = g_trades.merge(g_profit, on='bucket', how='outer').sort_values('bucket')
            merged['profit'] = merged['profit'].fillna(0)
            merged['trades'] = merged['trades'].fillna(0)

        buckets = merged['bucket'].tolist()
        metric = 'Profit'
        try:
            metric = self.metric_combo.currentText()
        except Exception:
            metric = 'Profit'
        if metric == 'Total Trades':
            values = merged['trades'].tolist()
            ylabel = 'Total Trades'
            color = '#1f77b4'
        else:
            values = merged['profit'].tolist()
            ylabel = 'Profit'
            color = '#2ca02c'

        xs = list(range(len(buckets)))
        # Color negative profits red when metric is Profit
        if metric == 'Profit':
            colors = ['#d62728' if (v is not None and float(v) < 0) else '#2ca02c' for v in values]
            ax.bar(xs, values, color=colors)
            # Add legend note
            try:
                from matplotlib.patches import Patch
                handles = [
                    Patch(color='#2ca02c', label='Profit ≥ 0'),
                    Patch(color='#d62728', label='Profit < 0')
                ]
                ax.legend(handles=handles, fontsize=8, loc='upper left')
            except Exception:
                # Fallback note text
                ax.text(0.01, 0.98, 'Green: Profit ≥ 0 | Red: Profit < 0', transform=ax.transAxes, va='top', fontsize=8, color='#333')
        else:
            ax.bar(xs, values, color=color)
        ax.set_xlabel('Time')
        ax.set_ylabel(ylabel)
        ax.set_title(f'{ylabel} by Time')
        ax.set_xticks(xs)
        ax.set_xticklabels(buckets, rotation=35, ha='right', fontsize=8)
        fig.subplots_adjust(bottom=0.22, top=0.88, left=0.08, right=0.95)
        ax.tick_params(axis='y', labelsize=9)

        # Replace canvas
        layout = self.chart_frame.layout()
        if layout is not None:
            for i in reversed(range(layout.count())):
                widget_to_remove = layout.itemAt(i).widget()
                if widget_to_remove:
                    widget_to_remove.setParent(None)
        else:
            layout = QVBoxLayout(self.chart_frame)
            self.chart_frame.setLayout(layout)

        canvas = FigureCanvas(fig)
        layout.addWidget(canvas)
        canvas.draw()


        
    def on_time_mode_changed(self):
        mode = self.time_range_combo.currentText()
        # Show/hide inputs per mode
        show_day = (mode == "Day/Month/Year")
        show_month = (mode in ("Day/Month/Year", "Month/Year"))
        show_year = (mode in ("Day/Month/Year", "Month/Year", "Year"))
        self.day_input.setVisible(show_day)
        self.month_input.setVisible(show_month)
        self.year_input.setVisible(show_year)
        self.time_search_btn.setVisible(mode != "All the time")

    def on_time_search_clicked(self):
        # Update calendar selection based on inputs
        mode = self.time_range_combo.currentText()
        try:
            if mode == "Day/Month/Year":
                from PyQt5.QtCore import QDate
                d = int(self.day_input.value()); m = int(self.month_input.value()); y = int(self.year_input.value())
                self.calendarWidget.setSelectedDate(QDate(y, m, d))
            elif mode == "Month/Year":
                from PyQt5.QtCore import QDate
                m = int(self.month_input.value()); y = int(self.year_input.value())
                self.calendarWidget.setSelectedDate(QDate(y, m, 1))
            elif mode == "Year":
                from PyQt5.QtCore import QDate
                y = int(self.year_input.value())
                self.calendarWidget.setSelectedDate(QDate(y, 1, 1))
        except Exception:
            pass
        data = self.get_selected_data()
        self.reload(data)

    def on_ai_filter_clicked(self):
        """Khi nhấn SELF-TRAIN hoặc AI MODEL: lọc dữ liệu theo cột AI và reload thống kê."""
        if not self.self_train_checkBox.isChecked() and not self.ai_model_checkBox.isChecked():
            self.ai_model_checkBox.setChecked(True)
            return
        data = self.get_selected_data()
        self.reload(data)
    def on_self_train_filter_clicked(self):
        """Khi nhấn SELF-TRAIN: lọc dữ liệu theo cột AI và reload thống kê."""
        if not self.self_train_checkBox.isChecked() and not self.ai_model_checkBox.isChecked():
            self.self_train_checkBox.setChecked(True)
            return
        data = self.get_selected_data()
        self.reload(data)
            
    def get_selected_data(self):
        # 🎯 Lấy bộ lọc trước khi load dữ liệu
        try:
            selected_symbol = self.symbol_combo.currentText()
            time_mode = self.time_range_combo.currentText()
            ai_filter_self_train = self.self_train_checkBox.isChecked()
            ai_filter_ai_model = self.ai_model_checkBox.isChecked()
        except Exception:
            selected_symbol = "All Symbol"
            time_mode = "All the time"
            ai_filter_self_train = True
            ai_filter_ai_model = True

        # 🚀 Tối ưu: chỉ lấy symbols cần thiết
        symbol_items = list(SYMBOLS.items())  # [(key, value)]
        
        # Lọc symbols ngay từ đầu nếu không phải "All Symbol"
        if selected_symbol and selected_symbol != "All Symbol":
            # Tìm symbols có chứa từ khóa tìm kiếm
            filtered_items = [(key, val) for key, val in symbol_items if selected_symbol.upper() in val.upper()]
            if not filtered_items:
                print(f"⚠️ Không tìm thấy symbol nào chứa '{selected_symbol}'")
                return pd.DataFrame()
            symbol_items = filtered_items
            print(f"🎯 Chỉ load {len(symbol_items)} symbols thay vì {len(SYMBOLS)} symbols")
        
        symbols = [val for _, val in symbol_items]
        
        # Tạo danh sách đường dẫn tương ứng theo mode
        file_paths = []
        if self.data_mode == "Backtest":
            # results/backtest/trade_history_{symbol_key_lower}.csv
            for key, _ in symbol_items:
                fname = f"trade_history_{key.lower()}.csv"
                file_paths.append(os.path.join(current_dir_backtest, fname))
        else:
            # Real-time theo login
            for _, val in symbol_items:
                file_paths.append(utils_account.get_trade_history_file_path(val))
        
        # Kiểm tra xem có thể lấy được đường dẫn không
        if any(path is None for path in file_paths):
            print("⚠️ Không thể lấy đường dẫn file CSV cho một số symbols")
            return pd.DataFrame()
        
        # Cột chuẩn theo schema mới khi cần tạo file trống
        all_columns = [
            'Datetime_entry','Time_frame','Sell/Buy','Entry_price','Stop_loss','Take_profit',
            'RSI','MACD_value','MACD_signal','MACD_histogram','EMA_50','EMA_200',
            'BB_upper','BB_middle','BB_lower','ATR14','Lot','Profit','Win','AI'
        ]
        
        # Các cột cần thiết để hiển thị trong bảng
        selected_columns = [
            'Datetime_entry','Time_frame','Sell/Buy','Entry_price','Stop_loss','Take_profit',
            'Lot','Profit','Win','AI'
        ]

        data_list = []
        
        for file_path, symbol in zip(file_paths, symbols):
            # Kiểm tra đường dẫn có hợp lệ không
            if file_path is None:
                print(f"⚠️ Đường dẫn file CSV không hợp lệ cho symbol {symbol}")
                continue
                
            # 🛠 Nếu file không tồn tại, tạo file mới với các cột cần thiết
            if not os.path.exists(file_path):
                print(f"⚠️ File {file_path} không tồn tại. Đang tạo mới...")
                df_empty = pd.DataFrame(columns=all_columns)
                df_empty.to_csv(file_path, index=False)
                continue  # Bỏ qua file mới tạo để tránh lỗi đọc dữ liệu

            # 🟢 Đọc dữ liệu từ file với tối ưu hóa
            try:
                # 🚀 Tối ưu: sử dụng usecols để chỉ đọc cột cần thiết
                temp_data = pd.read_csv(file_path, usecols=lambda x: x in selected_columns or x in ['Datetime_entry'])
            except Exception as e:
                print(f"❌ Lỗi khi đọc file {file_path}: {e}")
                continue

            # 🛠 Chỉ lấy các cột cần thiết nếu tồn tại trong file
            available_columns = [col for col in selected_columns if col in temp_data.columns]
            missing_columns = [col for col in selected_columns if col not in temp_data.columns]
            
            if missing_columns:
                print(f"⚠️ Thiếu các cột {missing_columns} trong {file_path}. Sẽ sử dụng các cột có sẵn.")
            
            # Lọc các cột có sẵn và thêm cột mặc định cho các cột thiếu
            if available_columns:
                temp_data = temp_data[available_columns]
            
            # Thêm cột mặc định cho các cột thiếu
            for col in missing_columns:
                if col in ('Stop_loss','Take_profit'):
                    temp_data[col] = 0.0
                elif col in ('Lot','Profit'):
                    temp_data[col] = 0.0
                elif col == 'Win':
                    temp_data[col] = 0
                elif col == 'AI':
                    temp_data[col] = 'DEFAULT'
                elif col == 'Time_frame':
                    temp_data[col] = ''
                else:
                    temp_data[col] = ''
            
            # 🚀 Tối ưu: Lọc theo thời gian ngay khi đọc từng file
            if time_mode != "All the time" and 'Datetime_entry' in temp_data.columns and not temp_data.empty:
                try:
                    temp_data['_dt'] = pd.to_datetime(temp_data['Datetime_entry'], errors='coerce')
                    
                    if time_mode == "Day/Month/Year":
                        d = int(self.day_input.value()); m = int(self.month_input.value()); y = int(self.year_input.value())
                        temp_data = temp_data[(temp_data['_dt'].dt.day == d) & (temp_data['_dt'].dt.month == m) & (temp_data['_dt'].dt.year == y)]
                    elif time_mode == "Month/Year":
                        m = int(self.month_input.value()); y = int(self.year_input.value())
                        temp_data = temp_data[(temp_data['_dt'].dt.month == m) & (temp_data['_dt'].dt.year == y)]
                    elif time_mode == "Year":
                        y = int(self.year_input.value())
                        temp_data = temp_data[(temp_data['_dt'].dt.year == y)]
                    
                    temp_data = temp_data.drop(columns=['_dt'])
                except Exception as e:
                    print(f"⚠️ Lỗi khi lọc thời gian cho {symbol}: {e}")
            
            # � Tối ưu: Lọc theo AI mode ngay khi đọc từng file
            if 'AI' in temp_data.columns and not temp_data.empty:
                if not (ai_filter_self_train and ai_filter_ai_model):
                    if ai_filter_self_train and not ai_filter_ai_model:
                        temp_data = temp_data[temp_data['AI'].str.lower() == 'self_training']
                    elif ai_filter_ai_model and not ai_filter_self_train:
                        temp_data = temp_data[temp_data['AI'].str.lower() != 'self_training']
            
            # Thêm cột Symbol sau khi lọc
            if not temp_data.empty:
                temp_data['Symbol'] = symbol
                data_list.append(temp_data)
        
        # 🔥 Loại bỏ DataFrames rỗng trước khi concat
        data_list = [df for df in data_list if not df.empty]

        # 🛠 Gộp dữ liệu từ các file nếu có, nếu không thì tạo DataFrame rỗng
        if data_list:
            combined_data = pd.concat(data_list, ignore_index=True)
            print(f"✅ Đã gộp dữ liệu từ {len(data_list)} file CSV (tối ưu hóa)")
        else:
            combined_data = pd.DataFrame(columns=selected_columns + ['Symbol'])
            print("⚠️ Không có dữ liệu nào để hiển thị")

        # 🔹 Chuyển đổi 'Datetime_entry' thành chuỗi để tránh lỗi .str.contains()
        if not combined_data.empty:
            combined_data['Datetime_entry'] = combined_data['Datetime_entry'].astype(str)

        return combined_data


    def on_symbol_changed(self):
        self.reload(self.get_selected_data())
        
    def reload(self, data):
        data = data  # Lấy dữ liệu theo RadioButton được chọn

        # Khởi tạo các biến tính toán với error handling
        try:
            # Kiểm tra xem cột 'Profit' có tồn tại không
            if 'Profit' not in data.columns:
                print("⚠️ Cột 'Profit' không tồn tại trong DataFrame, tạo cột mặc định")
                data['Profit'] = 0.0
                
            total_profit = data['Profit'].sum()
            if 'Win' in data.columns:
                win_count = data['Win'].apply(lambda x: str(x).strip().lower() == 'true').sum()
            else:
                win_count = data[data['Profit'] > 0].shape[0]
            loss_count = len(data) - win_count
        except Exception as e:
            print(f"❌ Lỗi khi tính toán profit: {e}")
            total_profit = 0.0
            win_count = 0
            loss_count = 0
        total_trades = win_count + loss_count
        win_rate = (win_count / total_trades) * 100 if total_trades > 0 else 0
        average_profit_per_trade = total_profit / total_trades if total_trades > 0 else 0

        # Định dạng số lớn nếu cần thiết
        total_profit = self.format_large_number(total_profit)
        total_trades = self.format_large_number(total_trades)
        average_profit_per_trade = self.format_large_number(average_profit_per_trade)

        # Cập nhật giao diện với các giá trị tính toán
        self.profitValue_label.setText(f'${total_profit}')
        self.winRateValue_label.setText(f'{win_rate:.1f}%')
        self.totalTradesValue_label.setText(f'{total_trades}')
        self.averageProfitPerTradeValue_label.setText(f'${average_profit_per_trade}')

        # Cập nhật biểu đồ với dữ liệu đã chọn
        self.plot_profit_chart(data)
