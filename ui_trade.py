
import utils_symbol_csv
from  utils_account import mt5
from live_trade_ai import LiveTradeAI
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QAbstractItemView, QFileDialog, QPushButton, QHBoxLayout, QVBoxLayout, QMessageBox
from concurrent.futures import ThreadPoolExecutor
from SYMBOLs import SYMBOLS
from utils_symbol_csv import Status0_symbol
import utils_account
from utils_account import get_oldest_candle
from get_full_history_chunked import get_full_history_chunked
from utils_messagebox import show_message
import utils_logs
from utils_logs import  update_stop_time
from datetime import datetime as _dt, time, timedelta
from PyQt5.QtCore import QDate, QTime
from datetime import date as dt_date
from datetime import time as dt_time
import os
import pandas as pd
from historytable import HistoryTableModel
from Backtest_trade_ai import BacktestTradeAI
from Backtest_tradeAgentAI import BacktestAgentAI
from LiveTrade_AgentAI_MT5 import LiveTradeAgentAI

class Ui_TradeDialog(object):
    def __init__(self, main_window, data_mode="Real-time"):
        self.main_window = main_window  # Lưu tham chiếu tới MainWindow
        self.live_traders = main_window.live_traders  # Sử dụng live_traders chung
        self.data_mode = data_mode
        # Cache MT5 oldest candle theo (symbol, timeframe) để tránh gọi lặp
        self._mt5_oldest_cache = {}  # { (symbol, tf_const): (oldest_dt, saved_at_dt) }
        # Debounce timer cho việc cập nhật range khi người dùng đổi symbol/timeframe
        self._update_range_timer = QtCore.QTimer()
        self._update_range_timer.setSingleShot(True)
        self._update_range_timer.setInterval(300)  # 300ms debounce
        self._update_range_timer.timeout.connect(self._update_mt5_range_debounced)
        
        # Lưu trữ phạm vi MT5 hiện tại để validation
        self._current_mt5_range = None  # (oldest_dt, newest_dt)
        
        # Lưu trữ warning đang chờ hiển thị
        self._pending_warning = None
        
        # Flag để ngăn chặn validation khi đang reconnect
        self._is_reconnecting = False
        
        # Cache MT5 account info để tránh gọi liên tục
        self._cached_account_info = None
        self._account_cache_time = None
        self._account_cache_ttl = 30  # Cache trong 30 giây
        
        # Flag để tránh update preview và suppress warnings
        self._suppress_preview_update = False
        self._suppress_date_warning = False
        
        # Flag để ngăn gọi update_data_preview lặp lại
        self._is_updating_preview = False
        
        # Debounce timer cho update_data_preview
        self._update_preview_timer = QtCore.QTimer()
        self._update_preview_timer.setSingleShot(True)
        self._update_preview_timer.setInterval(500)  # 500ms debounce
        self._update_preview_timer.timeout.connect(self._update_data_preview_debounced)
        
        # Cache cho full history data để tránh lấy lặp lại
        self._full_history_cache = {}  # { (symbol, timeframe): DataFrame }
        
        # Cache data theo symbol cho Backtest mode
        self._symbol_data_cache = {}  # { symbol: DataFrame }
        
        # Lưu trữ giá trị trước đó để reset lại
        self._previous_from_date = None
        self._previous_to_date = None
        
        # Storage cho AI Keys theo từng row
        self.ai_keys_by_row = {}
        self._row_ai_keys = {}  # { row_index: ai_key_string }
        
        # Thêm các timer và flag cần thiết
        self._update_preview_timer = QtCore.QTimer()
        self._update_preview_timer.setSingleShot(True)
        self._update_preview_timer.setInterval(500)  # 500ms debounce
        self._update_preview_timer.timeout.connect(self._update_data_preview_debounced)
        
        self._is_updating_preview = False
        
    def get_cached_account_info(self):
        """Get account info với cache để tránh gọi MT5 liên tục"""
        import time
        current_time = time.time()
        
        # Kiểm tra cache còn hiệu lực không
        if (self._cached_account_info is not None and 
            self._account_cache_time is not None and 
            current_time - self._account_cache_time < self._account_cache_ttl):
            return self._cached_account_info
        
        # Cache hết hạn, lấy thông tin mới
        if mt5.initialize():
            account_info = mt5.account_info()
            if account_info:
                self._cached_account_info = account_info
                self._account_cache_time = current_time
                print(f"🔄 Cached account info updated: leverage={account_info.leverage}")
            else:
                print("⚠️ Không thể lấy thông tin tài khoản")
            mt5.shutdown()
            return account_info
        else:
            print("⚠️ MT5 connection failed")
            return None
        

    def setupUi(self, TradeDialog):
        # Lấy danh sách symbols có thể trade
        
        TradeDialog.setObjectName("TradeDialog")
        # Kích thước mặc định
        TradeDialog.resize(950, 700)
        self.trade_buttonBox = QtWidgets.QDialogButtonBox(TradeDialog)
        self.trade_buttonBox.setGeometry(QtCore.QRect(20, 620, 200, 32))
        self.trade_buttonBox.setOrientation(QtCore.Qt.Horizontal)
        self.trade_buttonBox.setStandardButtons(QtWidgets.QDialogButtonBox.Cancel|QtWidgets.QDialogButtonBox.Ok)
        self.trade_buttonBox.setObjectName("trade_buttonBox")
        self.balance_currentLabel=QtWidgets.QLabel(TradeDialog)
        self.balance_currentLabel.setObjectName("balance_current")
        self.balance_currentLabel.setGeometry(QtCore.QRect(30, 0, 420, 41))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.balance_currentLabel.setFont(font)
        self.tradeContent_frame = QtWidgets.QFrame(TradeDialog)
        self.tradeContent_frame.setGeometry(QtCore.QRect(30, 50, 950,550))
        self.tradeContent_frame.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.tradeContent_frame.setFrameShadow(QtWidgets.QFrame.Raised)
        self.tradeContent_frame.setObjectName("tradeContent_frame")
        self.tradeBalance_label = QtWidgets.QLabel(self.tradeContent_frame)
        self.tradeBalance_label.setGeometry(QtCore.QRect(0,230,121,41))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        if self.data_mode == "Backtest":
            # Cho phép nhập số tiền tuỳ ý trong backtest
            self.balance = 10**12  # large cap so validation passes
        else:
            # Handle trường hợp get_balance() trả về None
            account_balance = utils_account.get_balance()
            total_running = utils_logs.total_balance_running()
            
            if account_balance is None:
                print("⚠️ Không thể lấy balance từ MT5, sử dụng giá trị mặc định")
                self.balance = 10000.0  # Giá trị mặc định
            else:
                self.balance = account_balance - total_running
        self.leverage=0
        self.tradeBalance_label.setFont(font)
        self.tradeBalance_label.setObjectName("tradeBalance_label")
        self.tradeBalanc_textEdit = QtWidgets.QLineEdit(TradeDialog)
        self.tradeBalanc_textEdit.setGeometry(QtCore.QRect(140, 280, 181, 41))
        font = QtGui.QFont()
        font.setPointSize(12)
        self.tradeBalanc_textEdit.setFont(font) 
        self.tradeBalanc_textEdit.setObjectName("tradeBalanc_textEdit")
        
        # Thêm validator cho phép nhập số với 2 chữ số thập phân
        validator = QtGui.QDoubleValidator(0.0, 99999999.99, 2)
        validator.setNotation(QtGui.QDoubleValidator.StandardNotation)
        self.tradeBalanc_textEdit.setValidator(validator)
        # self.tradeBalanc_textEdit.focusOutEvent = self.on_focus_out

        # Nhóm 1: Chế độ lot
        self.lotGroup = QtWidgets.QGroupBox(self.tradeContent_frame)
        self.lotGroup.setGeometry(QtCore.QRect(310, 290, 200, 40))
        self.lotGroup.setObjectName("lotGroup")

        self.tradeAutoLot_radioButton = QtWidgets.QRadioButton(self.lotGroup)
        self.tradeAutoLot_radioButton.setGeometry(QtCore.QRect(10,20,82,17))
        self.tradeAutoLot_radioButton.setObjectName("tradeAutoLot_radioButton")
        self.tradeAutoLot_radioButton.setChecked(True)
        self.tradeManualLot_radioButton = QtWidgets.QRadioButton(self.lotGroup)
        self.tradeManualLot_radioButton.setGeometry(QtCore.QRect(100,20,82,17))
        self.tradeManualLot_radioButton.setObjectName("tradeManualLot_radioButton")
        self.tradeAutoLot_radioButton.toggled.connect(self.on_auto_toggled)

        # Đảm bảo độc quyền cho nhóm lot
        self.lotModeGroup = QtWidgets.QButtonGroup(self.lotGroup)
        self.lotModeGroup.setExclusive(True)
        self.lotModeGroup.addButton(self.tradeAutoLot_radioButton)
        self.lotModeGroup.addButton(self.tradeManualLot_radioButton)

        # Radio chọn nguồn AI: SELF-TRAIN vs AI MODEL (hàng đầu tiên)
        # Nhóm 2: Nguồn mô hình AI
        self.aiGroup = QtWidgets.QGroupBox(self.tradeContent_frame)
        # Vị trí sẽ điều chỉnh lại nếu ở Backtest
        self.aiGroup.setGeometry(QtCore.QRect(30, 10, 400, 140))
        self.aiGroup.setObjectName("aiGroup")

        self.radioSelfTrain = QtWidgets.QRadioButton(self.aiGroup)
        self.radioSelfTrain.setGeometry(QtCore.QRect(10,20,110,17))
        self.radioSelfTrain.setObjectName("radioSelfTrain")
        self.radioSelfTrain.setChecked(False)

        self.radioAIModel = QtWidgets.QRadioButton(self.aiGroup)
        self.radioAIModel.setGeometry(QtCore.QRect(130,20,100,17))
        self.radioAIModel.setObjectName("radioAIModel")
        self.radioAIModel.setChecked(True)
        # Đảm bảo độc quyền cho nhóm AI
        self.aiModeGroup = QtWidgets.QButtonGroup(self.aiGroup)
        self.aiModeGroup.setExclusive(True)
        self.aiModeGroup.addButton(self.radioSelfTrain)
        self.aiModeGroup.addButton(self.radioAIModel)

        # Trường nhập AI Name và AI Key (chỉ hiện khi chọn AI MODEL)
        self.aiName_label = QtWidgets.QLabel(self.aiGroup)
        self.aiName_label.setGeometry(QtCore.QRect(10, 45, 80, 20))
        self.aiName_label.setObjectName("aiName_label")
        self.aiName_edit = QtWidgets.QLineEdit(self.aiGroup)
        self.aiName_edit.setGeometry(QtCore.QRect(95, 45, 190, 20))
        self.aiName_edit.setObjectName("aiName_edit")

        self.aiKey_label = QtWidgets.QLabel(self.aiGroup)
        self.aiKey_label.setGeometry(QtCore.QRect(10, 70, 80, 20))
        self.aiKey_label.setObjectName("aiKey_label")
        self.aiKey_edit = QtWidgets.QLineEdit(self.aiGroup)
        self.aiKey_edit.setGeometry(QtCore.QRect(95, 70, 190, 20))
        self.aiKey_edit.setObjectName("aiKey_edit")
        self.aiKey_edit.setEchoMode(QtWidgets.QLineEdit.Password)

        # Ẩn các trường AI Name/Key (không bắt buộc nhập)
        self.aiName_label.hide(); self.aiName_edit.hide()
        self.aiKey_label.hide(); self.aiKey_edit.hide()
        # Thêm trường cấu hình rủi ro khi chọn AI MODEL
        self.rr_label = QtWidgets.QLabel(self.aiGroup)
        self.rr_label.setGeometry(QtCore.QRect(10, 95, 120, 20))
        self.rr_label.setObjectName("rr_label")
        self.rr_edit = QtWidgets.QDoubleSpinBox(self.aiGroup)
        self.rr_edit.setGeometry(QtCore.QRect(135, 95, 70, 20))
        self.rr_edit.setDecimals(2)
        self.rr_edit.setMinimum(0.1)
        self.rr_edit.setMaximum(10.0)
        self.rr_edit.setSingleStep(0.1)
        self.rr_edit.setValue(1.5)
        self.rr_edit.setObjectName("rr_edit")

        self.maxloss_label = QtWidgets.QLabel(self.aiGroup)
        self.maxloss_label.setGeometry(QtCore.QRect(210, 95, 80, 20))
        self.maxloss_label.setObjectName("maxloss_label")
        self.maxloss_edit = QtWidgets.QDoubleSpinBox(self.aiGroup)
        self.maxloss_edit.setGeometry(QtCore.QRect(290, 95, 60, 20))
        self.maxloss_edit.setSuffix(" %")
        self.maxloss_edit.setDecimals(1)
        self.maxloss_edit.setMinimum(0.1)
        self.maxloss_edit.setMaximum(100.0)
        self.maxloss_edit.setSingleStep(0.1)
        self.maxloss_edit.setValue(1.0)
        self.maxloss_edit.setObjectName("maxloss_edit")

        # Mặc định hiển thị RR và Max loss vì AI MODEL đang được chọn
        for w in [self.rr_label, self.rr_edit, self.maxloss_label, self.maxloss_edit]:
            w.show()
        self.radioAIModel.toggled.connect(self.on_ai_mode_changed)
        self.radioSelfTrain.toggled.connect(self.on_ai_mode_changed)
        
        # ========== THÊM RADIO BUTTONS CHO BACKTEST MODE: Predictive AI vs Agent AI ==========
        # Nhóm chọn loại AI (chỉ hiện trong Backtest mode)
        self.backtestAITypeGroup = QtWidgets.QGroupBox(self.tradeContent_frame)
        self.backtestAITypeGroup.setGeometry(QtCore.QRect(450, 10, 280, 50))
        self.backtestAITypeGroup.setTitle("AI Type")
        self.backtestAITypeGroup.setObjectName("backtestAITypeGroup")
        
        self.radioPredictiveAI = QtWidgets.QRadioButton(self.backtestAITypeGroup)
        self.radioPredictiveAI.setGeometry(QtCore.QRect(15, 20, 120, 20))
        self.radioPredictiveAI.setText("Predictive AI")
        self.radioPredictiveAI.setObjectName("radioPredictiveAI")
        self.radioPredictiveAI.setChecked(True)
        
        self.radioAgentAI = QtWidgets.QRadioButton(self.backtestAITypeGroup)
        self.radioAgentAI.setGeometry(QtCore.QRect(145, 20, 120, 20))
        self.radioAgentAI.setText("Agent AI")
        self.radioAgentAI.setObjectName("radioAgentAI")
        
        # Đảm bảo độc quyền cho nhóm AI Type
        self.backtestAITypeModeGroup = QtWidgets.QButtonGroup(self.backtestAITypeGroup)
        self.backtestAITypeModeGroup.setExclusive(True)
        self.backtestAITypeModeGroup.addButton(self.radioPredictiveAI)
        self.backtestAITypeModeGroup.addButton(self.radioAgentAI)
        
        # Kết nối sự kiện
        self.radioPredictiveAI.toggled.connect(self.on_ai_type_changed)
        self.radioAgentAI.toggled.connect(self.on_ai_type_changed)
        
        # Hiển thị cho cả Real-time và Backtest mode (không ẩn nữa)
        # Đổi title tùy theo mode
        if self.data_mode == "Backtest":
            self.backtestAITypeGroup.setTitle("AI Type (Backtest)")
        else:
            self.backtestAITypeGroup.setTitle("AI Type (Real-time)")
        # self.tradeManualLot_textEdit = QtWidgets.QTextEdit(self.tradeContent_frame)
        # self.tradeManualLot_textEdit.setGeometry(QtCore.QRect(220, 80, 101, 41))
        # font = QtGui.QFont()
        # font.setPointSize(12)
        # self.tradeManualLot_textEdit.setFont(font)
        # self.tradeManualLot_textEdit.setObjectName("tradeManualLot_textEdit")
        # Ô tìm kiếm symbol khi setup Trade
        self.tradeSymbol_search = QtWidgets.QLineEdit(self.tradeContent_frame)
        self.tradeSymbol_search.setGeometry(QtCore.QRect(140, 180, 131, 31))
        font = QtGui.QFont()
        font.setPointSize(12)
        self.tradeSymbol_search.setFont(font)
        self.tradeSymbol_search.setPlaceholderText("Search symbol...")
        self.tradeSymbol_search.setObjectName("tradeSymbol_search")

        self.tradeSymbol_comboBox = QtWidgets.QComboBox(self.tradeContent_frame)
        self.tradeSymbol_comboBox.setGeometry(QtCore.QRect(290, 180, 161, 31))
        self.tradeSymbol_comboBox.setFont(font)
        self.tradeSymbol_comboBox.setObjectName("tradeSymbol_comboBox")
        
        # Nguồn symbol: mặc định AI MODEL → tất cả symbol có thể trade theo mode
        trading_type = 'backtest' if self.data_mode == 'Backtest' else 'realtime'
        self.trade_all_symbols = Status0_symbol(trading_type) or list(SYMBOLS.values())
        self.populate_trade_symbol_combo("")
        self.tradeSymbol_search.textChanged.connect(self.on_trade_symbol_search_changed)
        self.tradeSymbol_label = QtWidgets.QLabel(self.tradeContent_frame)
        self.tradeSymbol_label.setGeometry(QtCore.QRect(0,170,121,51))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.tradeSymbol_label.setFont(font)
        self.tradeSymbol_label.setObjectName("tradeSymbol_label")
        # Timeframe
        self.timeframe_label = QtWidgets.QLabel(self.tradeContent_frame)
        self.timeframe_label.setGeometry(QtCore.QRect(470, 170, 130, 51))
        self.timeframe_label.setFont(font)
        self.timeframe_label.setObjectName("timeframe_label")
        self.timeframe_comboBox = QtWidgets.QComboBox(self.tradeContent_frame)
        self.timeframe_comboBox.setGeometry(QtCore.QRect(610, 180, 70, 31))
        self.timeframe_comboBox.setFont(font)
        self.timeframe_comboBox.setObjectName("timeframe_comboBox")
        # Map timeframe label -> MT5 const
        self.timeframe_map = {
            "M1": mt5.TIMEFRAME_M1,
            "M5": mt5.TIMEFRAME_M5,
            "M15": mt5.TIMEFRAME_M15,
            "M30": mt5.TIMEFRAME_M30,
            "H1": mt5.TIMEFRAME_H1,
            "H4": mt5.TIMEFRAME_H4,
            "D1": mt5.TIMEFRAME_D1
        }
        self.timeframe_comboBox.addItems(list(self.timeframe_map.keys()))
        self.timeframe_comboBox.setCurrentText("M5")
        
        # Thêm nhóm chọn nguồn dữ liệu backtest (chỉ hiện khi ở chế độ Backtest)
        if self.data_mode == "Backtest":
            self.dsGroup = QtWidgets.QGroupBox(self.tradeContent_frame)
            self.dsGroup.setGeometry(QtCore.QRect(0, 220, 450, 200))  # Giảm width để nhường chỗ cho bảng
            self.dsGroup.setTitle("Data source")
            
            # Radio buttons cho chọn nguồn dữ liệu
            self.dsImportRadio = QtWidgets.QRadioButton(self.dsGroup)
            self.dsImportRadio.setText("Import CSV folders")
            self.dsImportRadio.setGeometry(QtCore.QRect(15, 25, 160, 25))
            self.dsApiRadio = QtWidgets.QRadioButton(self.dsGroup)
            self.dsApiRadio.setText("Fetch MT5 history")
            self.dsApiRadio.setGeometry(QtCore.QRect(200, 25, 160, 25))
            self.dsImportRadio.setChecked(True)
            
            # Kết nối event handlers cho radio buttons
            self.dsImportRadio.clicked.connect(self.on_ds_import_clicked)
            self.dsApiRadio.clicked.connect(self.on_ds_api_clicked)

            # Nút chọn nhiều file CSV/Excel
            self.chooseFilesBtn = QtWidgets.QPushButton(self.dsGroup)
            self.chooseFilesBtn.setGeometry(QtCore.QRect(15, 55, 120, 30))
            self.chooseFilesBtn.setText("Choose files...")
            self.chooseFilesBtn.clicked.connect(self.on_choose_import_files)

            # Label hiển thị các file đã chọn
            self.chosenFilesLabel = QtWidgets.QLabel(self.dsGroup)
            self.chosenFilesLabel.setGeometry(QtCore.QRect(145, 55, 300, 30))
            self.chosenFilesLabel.setText("Select one or more CSV/Excel files")
            self.chosenFilesLabel.setStyleSheet("color: rgb(100, 100, 100); font-size: 11px;")
            self.import_file_paths = []

            # Hàng 2: Date selection (From/To dates)
            self.fromDateLabel = QtWidgets.QLabel(self.dsGroup)
            self.fromDateLabel.setText("From Date:")
            self.fromDateLabel.setGeometry(QtCore.QRect(15, 120, 70, 20))
            self.fromDateLabel.setStyleSheet("font-weight: bold;")
            
            self.fromDateEdit = QtWidgets.QDateEdit(self.dsGroup)
            self.fromDateEdit.setGeometry(QtCore.QRect(90, 120, 120, 30))
            self.fromDateEdit.setDisplayFormat("dd/MM/yyyy")
            self.fromDateEdit.setDate(QtCore.QDate(2000, 1, 1))
            self.fromDateEdit.setCalendarPopup(True)
            
            self.toDateLabel = QtWidgets.QLabel(self.dsGroup)
            self.toDateLabel.setText("To Date:")
            self.toDateLabel.setGeometry(QtCore.QRect(220, 120, 60, 20))
            self.toDateLabel.setStyleSheet("font-weight: bold;")
            
            self.toDateEdit = QtWidgets.QDateEdit(self.dsGroup)
            self.toDateEdit.setGeometry(QtCore.QRect(285, 120, 120, 30))
            self.toDateEdit.setDisplayFormat("dd/MM/yyyy")
            self.toDateEdit.setDate(QtCore.QDate(2000, 1, 1))
            self.toDateEdit.setCalendarPopup(True)

            # Hàng 3: Time selection (From/To time) ngay dưới hàng Date
            self.fromTimeLabel = QtWidgets.QLabel(self.dsGroup)
            self.fromTimeLabel.setText("From Time:")
            self.fromTimeLabel.setGeometry(QtCore.QRect(15, 155, 80, 20))
            self.fromTimeLabel.setStyleSheet("font-weight: bold;")
            self.fromTimeEdit = QtWidgets.QTimeEdit(self.dsGroup)
            self.fromTimeEdit.setGeometry(QtCore.QRect(90, 152, 120, 30))
            self.fromTimeEdit.setDisplayFormat("HH:mm")
            self.fromTimeEdit.setTime(QtCore.QTime(0, 0, 0))

            self.toTimeLabel = QtWidgets.QLabel(self.dsGroup)
            self.toTimeLabel.setText("To Time:")
            self.toTimeLabel.setGeometry(QtCore.QRect(220, 155, 60, 20))
            self.toTimeLabel.setStyleSheet("font-weight: bold;")
            self.toTimeEdit = QtWidgets.QTimeEdit(self.dsGroup)
            self.toTimeEdit.setGeometry(QtCore.QRect(285, 152, 120, 30))
            self.toTimeEdit.setDisplayFormat("HH:mm")
            self.toTimeEdit.setTime(QtCore.QTime(23, 59, 0))
            
            # Label hiển thị thông tin range
            self.dateLabel = QtWidgets.QLabel(self.dsGroup)
            self.dateLabel.setGeometry(QtCore.QRect(0, 82, 430, 30))
            self.dateLabel.setText("")
            self.dateLabel.setStyleSheet("color: rgb(50, 150, 50); font-size: 11px; font-weight: bold;")

            # Nút "Xem dữ liệu--->" ở giữa bên phải
            self.viewDataBtn = QtWidgets.QPushButton(self.dsGroup)
            self.viewDataBtn.setGeometry(QtCore.QRect(290, 70, 150, 35))
            self.viewDataBtn.setText("Lấy và xem dữ liệu--->")
            self.viewDataBtn.setStyleSheet("""
                QPushButton {
                    background-color: #4CAF50;
                    color: white;
                    border: none;
                    border-radius: 5px;
                    font-weight: bold;
                    font-size: 12px;
                }
                QPushButton:hover {
                    background-color: #45a049;
                }
                QPushButton:pressed {
                    background-color: #3d8b40;
                }
            """)
            self.viewDataBtn.clicked.connect(self.on_view_data_clicked)

            def _on_ds_toggle():
                use_import = self.dsImportRadio.isChecked()
                self.chooseFilesBtn.setVisible(use_import)
                self.chosenFilesLabel.setVisible(use_import)
                if use_import:
                    # Disconnect validation khi chuyển sang Import mode
                    self._disconnect_date_validation()
                    self._current_mt5_range = None
                    # Tắt auto update - chỉ hiển thị khi user click "Xem dữ liệu"
                    # self.update_import_year_range()
                else:
                    # Tắt auto update MT5 range - chỉ cập nhật khi user click "Xem dữ liệu"
                    # self.update_mt5_available_range()
                    pass
            self.dsImportRadio.toggled.connect(_on_ds_toggle)
            self.dsApiRadio.toggled.connect(_on_ds_toggle)
            _on_ds_toggle()

            # Khi chọn nguồn dữ liệu → hiện/ẩn và cập nhật range
            def _sync_date_inputs_visibility():
                show_dates = True  # hiển thị cho cả hai chế độ theo yêu cầu
                self.fromDateEdit.setVisible(show_dates)
                self.toDateEdit.setVisible(show_dates)
                self.fromDateLabel.setVisible(show_dates)
                self.toDateLabel.setVisible(show_dates)
                # Hiển thị/ẩn phần Time cùng lúc với Date
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.setVisible(show_dates)
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.setVisible(show_dates)
                if hasattr(self, 'fromTimeLabel'):
                    self.fromTimeLabel.setVisible(show_dates)
                if hasattr(self, 'toTimeLabel'):
                    self.toTimeLabel.setVisible(show_dates)
                self.dateLabel.setVisible(True)
                
                # Tắt auto clear table - để user tự quyết định khi nào xem data mới
                # if hasattr(self, 'dataPreview_table'):
                #     self._clear_preview_table()
                    
                # Clear import file paths khi chuyển từ import sang MT5
                if self.dsApiRadio.isChecked() and hasattr(self, 'import_file_paths'):
                    self.import_file_paths = []
                    if hasattr(self, 'chosenFilesLabel'):
                        self.chosenFilesLabel.setText("Select one or more CSV/Excel files")
                    print("Cleared import file paths when switching to MT5 mode")
                
                if self.dsApiRadio.isChecked():
                    self.update_mt5_available_range()
                # Tắt auto range update để tránh load MT5 data tự động
                if show_dates and not self._suppress_preview_update:
                    # self.update_import_year_range()
                    pass
                else:
                    # self.update_import_year_range()
                    pass
                    
                # Chỉ update preview nếu data source thực sự thay đổi
                # và không suppress update
                current_source = "api" if self.dsApiRadio.isChecked() else "import"
                
                # Kiểm tra nếu data source thay đổi
                if not hasattr(self, '_last_data_source'):
                    self._last_data_source = current_source
                    should_update = True
                elif self._last_data_source != current_source:
                    self._last_data_source = current_source
                    should_update = True
                    print(f"📊 Data source changed to: {current_source}")
                else:
                    should_update = False
                    print(f"📊 Data source unchanged: {current_source}")
                
                # Chỉ update preview khi thực sự cần thiết
                if should_update and not self._suppress_preview_update:
                    print("🔄 Data source changed - no auto preview loading")
                    # Tắt auto preview - chỉ hiển thị khi user click "Xem dữ liệu"  
                    # self.update_data_preview()
                else:
                    print("🔒 Skipping preview update (no change or suppressed)")
                
            self.dsApiRadio.toggled.connect(_sync_date_inputs_visibility)
            self.dsImportRadio.toggled.connect(_sync_date_inputs_visibility)
            _sync_date_inputs_visibility()

            # Giữ lại sự kiện symbol/timeframe nhưng không load data hiển thị
            self.timeframe_comboBox.currentIndexChanged.connect(self.on_symbol_or_tf_changed)
            self.tradeSymbol_comboBox.currentIndexChanged.connect(self.on_symbol_or_tf_changed)
            
            # Giữ lại sự kiện date/time nhưng không load data hiển thị
            self.fromDateEdit.dateChanged.connect(self.on_date_time_changed)
            self.toDateEdit.dateChanged.connect(self.on_date_time_changed)
            if hasattr(self, 'fromTimeEdit'):
                self.fromTimeEdit.timeChanged.connect(self.on_date_time_changed)
            if hasattr(self, 'toTimeEdit'):
                self.toTimeEdit.timeChanged.connect(self.on_date_time_changed)
            
            # Thêm bảng dữ liệu bên phải dsGroup
            self.dataPreviewGroup = QtWidgets.QGroupBox(self.tradeContent_frame)
            self.dataPreviewGroup.setGeometry(QtCore.QRect(460, 220, 640, 200))  # Bên phải dsGroup
            self.dataPreviewGroup.setTitle("Data Preview")
            # self.dataPreviewGroup.setVisible(False)  # Comment out - hiển thị ngay từ đầu
            
            # Bảng hiển thị dữ liệu
            self.dataPreview_table = QtWidgets.QTableWidget(self.dataPreviewGroup)
            self.dataPreview_table.setGeometry(QtCore.QRect(10, 25, 620, 140))
            self.dataPreview_table.setColumnCount(6)  # Symbol, Timeframe, Type_Data, Size_Data, From_Date, To_Date
            self.dataPreview_table.setHorizontalHeaderLabels(['Symbol', 'Timeframe', 'Type_Data', 'Size_Data', 'From_Date', 'To_Date'])
            self.dataPreview_table.setAlternatingRowColors(True)
            self.dataPreview_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
            self.dataPreview_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
            
            # Cải thiện hiển thị cho nhiều rows
            self.dataPreview_table.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self.dataPreview_table.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
            self.dataPreview_table.setSortingEnabled(False)  # Tắt sorting để giữ thứ tự thời gian
            self.dataPreview_table.verticalHeader().setVisible(True)  # Hiển thị số thứ tự rows
            
            # Thiết lập width cho các cột
            self.dataPreview_table.setColumnWidth(0, 80)   # Symbol
            self.dataPreview_table.setColumnWidth(1, 80)   # Timeframe
            self.dataPreview_table.setColumnWidth(2, 90)   # Type_Data
            self.dataPreview_table.setColumnWidth(3, 80)   # Size_Data
            self.dataPreview_table.setColumnWidth(4, 140)  # From_Date
            self.dataPreview_table.setColumnWidth(5, 140)  # To_Date
            
            # Nút "View Details" để mở HistoryDialog
            self.viewDetailsBtn = QtWidgets.QPushButton(self.dataPreviewGroup)
            self.viewDetailsBtn.setGeometry(QtCore.QRect(10, 170, 100, 25))
            self.viewDetailsBtn.setText("View Details")
            self.viewDetailsBtn.clicked.connect(self.on_view_details_clicked)
            
            # Label hiển thị thông tin dữ liệu
            self.dataInfoLabel = QtWidgets.QLabel(self.dataPreviewGroup)
            self.dataInfoLabel.setGeometry(QtCore.QRect(120, 170, 510, 25))
            self.dataInfoLabel.setText("Configure data source and click 'Lấy và xem dữ liệu' to view summary")
            self.dataInfoLabel.setStyleSheet("color: rgb(100, 100, 100); font-size: 10px;")
            
            # Khởi tạo dữ liệu preview trống
            self._current_preview_data = None
            
            # Cập nhật preview data ban đầu
            QtCore.QTimer.singleShot(2000, self._initialize_default_dates_and_preview)  # Delay 2 giây để UI load xong

        self.tradeLot_label = QtWidgets.QLabel(self.tradeContent_frame)
        self.tradeLot_label.setGeometry(QtCore.QRect(0, 300, 121, 41))
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.tradeLot_label.setFont(font)
        self.tradeLot_label.setObjectName("tradeLot_label")
        
        #Nút Add
        self.tradeAddSymbol_pushButton = QtWidgets.QPushButton(self.tradeContent_frame)
        self.tradeAddSymbol_pushButton.setGeometry(QtCore.QRect(20, 360, 100, 35))
        self.tradeAddSymbol_pushButton.setObjectName("tradeAddSymbol_pushButton")
        #Nút Delete
        self.tradeDeleteSymbol_pushButton = QtWidgets.QPushButton(self.tradeContent_frame)
        self.tradeDeleteSymbol_pushButton.setGeometry(QtCore.QRect(140, 360, 100, 35))
        self.tradeDeleteSymbol_pushButton.setObjectName("tradeDeleteSymbol_pushButton")
        #Nút Edit
        self.tradeEditSymbol_pushButton = QtWidgets.QPushButton(self.tradeContent_frame)
        self.tradeEditSymbol_pushButton.setGeometry(QtCore.QRect(260, 360, 100, 35))
        self.tradeEditSymbol_pushButton.setObjectName("tradeEditSymbol_pushButton")
        ##Sự kiện clicked Add,Delete,Edit
        self.tradeAddSymbol_pushButton.clicked.connect(self.add_new_row)
        self.tradeEditSymbol_pushButton.clicked.connect(self.edit_selected_row)
        self.tradeDeleteSymbol_pushButton.clicked.connect(self.delete_selected_row)
        
        #Table
        self.tradeSymbolPicked_tableWidget = QtWidgets.QTableWidget(self.tradeContent_frame)
        self.tradeSymbolPicked_tableWidget.setGeometry(QtCore.QRect(0, 410, 900, 400))
        # Cột: Symbol, Timeframe, Balance, Lot size, AI, R:R, Max loss, Max Loss/Trade (+ Size_data ở Backtest)
        if self.data_mode == "Backtest":
            self.tradeSymbolPicked_tableWidget.setColumnCount(10)
            self.tradeSymbolPicked_tableWidget.setHorizontalHeaderLabels(['Symbol', 'Timeframe', 'Balance', 'Lot size', 'AI', 'R:R', 'Max loss', 'Max Loss/Trade', 'Size_data', 'Type_Data'])
        else:
            self.tradeSymbolPicked_tableWidget.setColumnCount(8)
            self.tradeSymbolPicked_tableWidget.setHorizontalHeaderLabels(['Symbol', 'Timeframe', 'Balance', 'Lot size', 'AI', 'R:R', 'Max loss', 'Max Loss/Trade'])
        # Chỉ cho phép chọn cả hàng, không được chọn từng ô
        self.tradeSymbolPicked_tableWidget.setSelectionBehavior(QAbstractItemView.SelectRows)

        # Ngăn chặn chỉnh sửa các ô trong bảng
        self.tradeSymbolPicked_tableWidget.setEditTriggers(QAbstractItemView.NoEditTriggers)

        

        # self.tradeSymbolPicked_listWidget = QtWidgets.QListWidget(self.tradeContent_frame)
        # self.tradeSymbolPicked_listWidget.setGeometry(QtCore.QRect(0, 271, 181, 71))
        # font = QtGui.QFont()
        # font.setPointSize(8)
        # self.tradeSymbolPicked_listWidget.setFont(font)
        # self.tradeSymbolPicked_listWidget.setObjectName("tradeSymbolPicked_listWidget")

        self.retranslateUi(TradeDialog)
        # Remove the default accept connection to avoid conflicts
        # self.trade_buttonBox.accepted.connect(TradeDialog.accept) # type: ignore
        self.trade_buttonBox.rejected.connect(TradeDialog.reject) # type: ignore
        QtCore.QMetaObject.connectSlotsByName(TradeDialog)
        
        # Store dialog reference for closing later
        self._dialog = TradeDialog
        
        # Connect OK button directly to our handler
        print("🔗 Connecting OK button to handler...")
        self.trade_buttonBox.accepted.connect(self.on_ok_button_clicked)
        print("✅ OK button connected successfully")

        # Thêm QSpinBox cho lot size
        self.tradeLot_spinBox = QtWidgets.QDoubleSpinBox(TradeDialog)
        self.tradeLot_spinBox.setGeometry(QtCore.QRect(140, 340, 181, 41))
        font = QtGui.QFont()
        font.setPointSize(12)
        self.tradeLot_spinBox.setFont(font)
        self.tradeLot_spinBox.setDecimals(2)
        self.tradeLot_spinBox.setSingleStep(0.01)
        self.tradeLot_spinBox.setMaximum(20)
        self.tradeLot_spinBox.setMinimum(0.01)
        self.tradeLot_spinBox.setValue(0.01)
        self.tradeLot_spinBox.setObjectName("tradeLot_spinBox")
         # Mặc định QSpinBox bị vô hiệu hóa khi Auto được chọn
        self.tradeLot_spinBox.setEnabled(False)
        
        # Thêm nhãn và input cho max loss per trade (chỉ hiện khi Auto mode)
        # Đặt bên phải lot size, cùng hàng với lot size spinbox
        self.maxLossPerTrade_label = QtWidgets.QLabel(TradeDialog)
        self.maxLossPerTrade_label.setGeometry(QtCore.QRect(560, 340, 180, 41))
        font = QtGui.QFont()
        font.setPointSize(10)
        self.maxLossPerTrade_label.setFont(font)
        self.maxLossPerTrade_label.setObjectName("maxLossPerTrade_label")
        self.maxLossPerTrade_label.setText("Max Loss/Trade (USD):")
        
        self.maxLossPerTrade_spinBox = QtWidgets.QDoubleSpinBox(TradeDialog)
        self.maxLossPerTrade_spinBox.setGeometry(QtCore.QRect(750, 340, 120, 41))
        font = QtGui.QFont()
        font.setPointSize(12)
        self.maxLossPerTrade_spinBox.setFont(font)
        self.maxLossPerTrade_spinBox.setDecimals(2)
        self.maxLossPerTrade_spinBox.setSingleStep(1.0)
        self.maxLossPerTrade_spinBox.setMaximum(10000)
        self.maxLossPerTrade_spinBox.setMinimum(1.0)
        self.maxLossPerTrade_spinBox.setValue(10.0)
        self.maxLossPerTrade_spinBox.setObjectName("maxLossPerTrade_spinBox")
        # Hiển thị khi Auto mode (mặc định)
        self.maxLossPerTrade_label.setVisible(True)
        self.maxLossPerTrade_spinBox.setVisible(True)

        # Cấu hình UI dành cho Backtest
        if self.data_mode == "Backtest":
            # Ẩn ví hiện có, người dùng sẽ nhập Balance vào ô Balance
            self.balance_currentLabel.hide()

        self.tradeSymbol_comboBox.currentIndexChanged.connect(self.on_combobox_changed)
        # Đồng bộ giao diện theo mode ban đầu
        self.on_ai_mode_changed()

        # Điều chỉnh layout khi ở Backtest để tránh chồng lấn giao diện
        if self.data_mode == "Backtest":
            # Mở rộng dialog và vùng content để chứa data source group
            TradeDialog.resize(1200, 950)
            self.tradeContent_frame.setGeometry(QtCore.QRect(30, 30, 1130, 800))
            # Đẩy nhóm AI xuống dưới để không đè lên Data source
            self.aiGroup.setGeometry(QtCore.QRect(0, 0, 430, 140))
            # Dời cụm Symbol/Timeframe xuống một chút
            self.tradeSymbol_search.setGeometry(QtCore.QRect(140, 170, 131, 31))
            self.tradeSymbol_comboBox.setGeometry(QtCore.QRect(290, 170, 161, 31))
            self.tradeSymbol_label.setGeometry(QtCore.QRect(0, 160, 121, 51))
            self.timeframe_label.setGeometry(QtCore.QRect(470, 160, 130, 51))
            self.timeframe_comboBox.setGeometry(QtCore.QRect(610, 170, 70, 31))
            # Dời khu vực Balance/Lot xuống theo (sau data source group)
            self.tradeBalance_label.setGeometry(QtCore.QRect(0, 450, 121, 41))
            self.tradeBalanc_textEdit.setGeometry(QtCore.QRect(140, 470, 181, 41))
            self.lotGroup.setGeometry(QtCore.QRect(310, 490, 200, 40))
            self.tradeLot_label.setGeometry(QtCore.QRect(0, 500, 121, 41))
            self.tradeLot_spinBox.setGeometry(QtCore.QRect(140, 520, 181, 41))
            # Adjust max loss per trade field position for Backtest mode
            self.maxLossPerTrade_label.setGeometry(QtCore.QRect(560, 520, 180, 41))
            self.maxLossPerTrade_spinBox.setGeometry(QtCore.QRect(750, 520, 120, 41))
            # Dời các nút Add/Delete/Edit xuống
            self.tradeAddSymbol_pushButton.setGeometry(QtCore.QRect(20, 550, 100, 35))
            self.tradeDeleteSymbol_pushButton.setGeometry(QtCore.QRect(140, 550, 100, 35))
            self.tradeEditSymbol_pushButton.setGeometry(QtCore.QRect(260, 550, 100, 35))
            # Dời bảng xuống dưới
            self.tradeSymbolPicked_tableWidget.setGeometry(QtCore.QRect(0, 600, 1100, 200))
            self.trade_buttonBox.setGeometry(QtCore.QRect(20, 850, 200, 32))

            
    ################################################################################

    def _is_btc_symbol(self, symbol_text: str) -> bool:
        try:
            return "BTCUSD" in str(symbol_text)
        except Exception:
            return False

    # ===== Backtest helpers =====
    def on_choose_import_files(self):
        try:
            files, _ = QFileDialog.getOpenFileNames(
                None,
                "Select one or more CSV/Excel files",
                "",
                "CSV/Excel Files (*.csv *.xlsx *.xls);;All Files (*)"
            )
            if files:
                self.import_file_paths = files
                self.chosenFilesLabel.setText("; ".join([os.path.basename(f) for f in files]))
                print(f"Selected {len(files)} import files")
                # Tắt auto preview - chỉ hiển thị khi user click "Xem dữ liệu"
                # self.update_data_preview()
            else:
                self.import_file_paths = []
                self.chosenFilesLabel.setText("Select one or more CSV/Excel files")
                print("No files selected - cleared import paths")
                # Tắt auto clear preview - để user tự quyết định
                # if hasattr(self, 'dataPreview_table'):
                #     self._clear_preview_table()
        except Exception as e:
            print(f"Choose files error: {e}")

    def update_import_year_range(self):
        """Cập nhật phạm vi năm có thể import từ thư mục đã chọn"""
        try:
            if not hasattr(self, 'import_root_dir') or not self.import_root_dir:
                self.dateLabel.setText("Select one or more CSV/Excel files")
                return
            
            
            years = []
            for item in os.listdir(self.import_root_dir):
                if os.path.isdir(os.path.join(self.import_root_dir, item)):
                    try:
                        year = int(item)
                        if 2000 <= year <= 2100:
                            years.append(year)
                    except ValueError:
                        continue
            
            if years:
                years.sort()
                min_year, max_year = min(years), max(years)
                self.yearFrom.setValue(min_year)
                self.yearTo.setValue(max_year)
                self.fromDateEdit.setDate(QtCore.QDate(min_year, 1, 1))
                self.toDateEdit.setDate(QtCore.QDate(max_year, 12, 31))
                self.dateLabel.setText(f"Import range: 01/01/{min_year} → 31/12/{max_year}")
            else:
                self.dateLabel.setText("No valid year folders found")
        except Exception as e:
            print(f"Update import year range error: {e}")
            self.dateLabel.setText("Error scanning folder")

    def on_symbol_or_tf_changed(self):
        """Cập nhật khi đổi symbol hoặc timeframe (không load data hiển thị)."""
        try:
            if self.data_mode == "Backtest":
                if hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked():
                    # Debounce để tránh gọi MT5 liên tục khi người dùng rê chọn
                    self._update_range_timer.start()
                elif hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked():
                    # Chỉ update range info, không load data hiển thị
                    self.update_import_year_range()
                
                # Tắt auto preview - chỉ hiển thị khi user click "Xem dữ liệu"
                # self.update_data_preview()
                print(f"📝 Symbol/Timeframe changed - no auto data loading")
        except Exception as e:
            print(f"Symbol/TF change error: {e}")

    def on_date_time_changed(self):
        """Xử lý khi thay đổi date/time (không load data hiển thị)."""
        try:
            if self.data_mode == "Backtest":
                # Tắt auto preview - chỉ hiển thị khi user click "Xem dữ liệu"
                # if not hasattr(self, '_preview_update_timer'):
                #     self._preview_update_timer = QtCore.QTimer()
                #     self._preview_update_timer.setSingleShot(True)
                #     self._preview_update_timer.setInterval(500)  # 500ms debounce
                #     self._preview_update_timer.timeout.connect(self.update_data_preview)
                
                # self._preview_update_timer.start()
                print(f"📅 Date/Time changed - no auto data loading")
        except Exception as e:
            print(f"Date/time change error: {e}")

    def _update_mt5_range_debounced(self):
        try:
            # Đảm bảo chạy trong main thread
            QtCore.QTimer.singleShot(0, self.update_mt5_available_range)
        except Exception as e:
            print(f"Debounced update error: {e}")

    def populate_trade_symbol_combo(self, keyword):
        try:
            current = self.tradeSymbol_comboBox.currentText()
        except Exception:
            current = ""
        self.tradeSymbol_comboBox.blockSignals(True)
        self.tradeSymbol_comboBox.clear()
        if keyword:
            filt = [s for s in self.trade_all_symbols if keyword.upper() in s.upper()]
        else:
            filt = list(self.trade_all_symbols)
        
        self.tradeSymbol_comboBox.addItems(filt)
        
        # Logic cải thiện để chọn symbol phù hợp
        if current in filt:
            # Giữ lại selection hiện tại nếu vẫn trong filtered list
            idx = filt.index(current)
            self.tradeSymbol_comboBox.setCurrentIndex(idx)
            print(f"📊 Kept current symbol: {current}")
        elif keyword and len(filt) > 0:
            # Nếu có keyword và có kết quả, chọn symbol đầu tiên phù hợp nhất
            # Ưu tiên symbol có keyword ở đầu
            exact_matches = [s for s in filt if s.upper().startswith(keyword.upper())]
            if exact_matches:
                self.tradeSymbol_comboBox.setCurrentIndex(filt.index(exact_matches[0]))
                print(f"📊 Auto-selected exact match: {exact_matches[0]}")
            else:
                self.tradeSymbol_comboBox.setCurrentIndex(0)
                print(f"📊 Auto-selected first match: {filt[0]}")
        elif len(filt) > 0:
            # Fallback: chọn symbol đầu tiên
            self.tradeSymbol_comboBox.setCurrentIndex(0)
            print(f"📊 Selected first symbol: {filt[0]}")
            
        self.tradeSymbol_comboBox.blockSignals(False)

    def on_trade_symbol_search_changed(self, text):
        self.populate_trade_symbol_combo(text)

    def on_ai_mode_changed(self):
        """Chuyển nguồn symbol và hiển thị trường theo mode AI."""
        use_ai = self.radioAIModel.isChecked()
        # Hiển thị RR và % thua khi AI MODEL; ẩn khi SELF-TRAIN
        for w in [self.rr_label, self.rr_edit, self.maxloss_label, self.maxloss_edit]:
            w.setVisible(use_ai)
        # Nguồn danh sách symbol
        # Hiển thị tất cả symbol có thể trade cho mọi chế độ
        try:
            trading_type = 'backtest' if self.data_mode == 'Backtest' else 'realtime'
            self.trade_all_symbols = Status0_symbol(trading_type) or list(SYMBOLS.values())
        except Exception:
            self.trade_all_symbols = list(SYMBOLS.values())
        # Cập nhật combobox theo danh sách mới
        self.populate_trade_symbol_combo(self.tradeSymbol_search.text())

    def update_mt5_available_range(self):
        """Cập nhật phạm vi thời gian từ MT5 bằng hàm get_oldest_candle: From = cổ nhất, To = hiện tại."""
        try:
            symbol = self.tradeSymbol_comboBox.currentText()
            tf_label = self.timeframe_comboBox.currentText()
            tf_const = self.timeframe_map.get(tf_label, mt5.TIMEFRAME_M5)
            
            if not symbol or not tf_const:
                self.dateLabel.setText("Please select symbol and timeframe")
                return
                
            print(f"Updating MT5 range for {symbol} {tf_label}...")
            
            # Kiểm tra symbol có tồn tại trong MT5 không
            if not mt5.initialize():
                print("MT5 not initialized")
                self.dateLabel.setText("MT5 connection failed")
                return
                
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                print(f"Symbol {symbol} not found in MT5")
                self.dateLabel.setText(f"Symbol {symbol} not available in MT5")
                return
            
            # Dùng cache với TTL ngắn để tránh gọi lặp lại
            cache_key = (symbol, tf_const)
            ttl_sec = 300  # 5 phút
            oldest_dt = None
            saved_at = None
            
            if cache_key in self._mt5_oldest_cache:
                oldest_dt, saved_at = self._mt5_oldest_cache[cache_key]
                if (_dt.now() - saved_at).total_seconds() > ttl_sec:
                    oldest_dt = None  # hết hạn, buộc làm mới
                    
            if oldest_dt is None:
                print(f"Cache miss, calling get_oldest_candle for {symbol} {tf_label}")
                try:
                    # Đảm bảo symbol được enable
                    if not symbol_info.visible:
                        print(f"Enabling symbol {symbol}...")
                        if not mt5.symbol_select(symbol, True):
                            print(f"Failed to enable symbol {symbol}")
                            self.dateLabel.setText(f"Cannot enable symbol {symbol}")
                            return
                    
                    oldest_dt, _ = get_oldest_candle(symbol, tf_const)
                    if oldest_dt is not None:
                        self._mt5_oldest_cache[cache_key] = (oldest_dt, _dt.now())
                        print(f"Cached oldest: {oldest_dt}")
                    else:
                        print(f"No data found for {symbol} {tf_label}")
                except Exception as mt5_error:
                    print(f"MT5 call error: {mt5_error}")
                    oldest_dt = None
                    
            now_dt = _dt.now()
            if oldest_dt is None:
                # Thử lấy dữ liệu gần đây nhất để kiểm tra
                try:
                    latest_rates = mt5.copy_rates_from_pos(symbol, tf_const, 0, 1)
                    if latest_rates is not None and len(latest_rates) > 0:
                        latest_time = pd.to_datetime(latest_rates[0]['time'], unit='s')
                        self.dateLabel.setText(f"Limited data available. Latest: {latest_time:%d/%m/%Y %H:%M}")
                    else:
                        self.dateLabel.setText(f"No MT5 data available for {symbol} {tf_label}")
                except Exception:
                    self.dateLabel.setText(f"No MT5 data available for {symbol} {tf_label}")
                return
                
            # Set Date & Time (suppress warnings for both)
            self._suppress_date_warning = True
            # Ngắt kết nối signal trước khi set để tránh bị ghi đè lại
            try:
                self.fromDateEdit.dateChanged.disconnect()
            except Exception:
                pass
            print(f"[DEBUG] Set fromDateEdit: oldest_dt={oldest_dt}")
            self.fromDateEdit.setDate(QDate(oldest_dt.year, oldest_dt.month, oldest_dt.day))
            print(f"[DEBUG] After set, fromDateEdit={self.fromDateEdit.date().toString('dd/MM/yyyy')}")
            # Reconnect validation (sẽ không load data)
            self.fromDateEdit.dateChanged.connect(self._validate_from_date)
            self.toDateEdit.setDate(QDate(now_dt.year, now_dt.month, now_dt.day))
            if hasattr(self, 'fromTimeEdit') and hasattr(self, 'toTimeEdit'):
                self.fromTimeEdit.setTime(QTime(oldest_dt.hour, oldest_dt.minute, oldest_dt.second))
                self.toTimeEdit.setTime(QTime(now_dt.hour, now_dt.minute, now_dt.second))
            self._suppress_date_warning = False
                
            self.dateLabel.setText(f"Available MT5: {oldest_dt:%d/%m/%Y %H:%M:%S} → {now_dt:%d/%m/%Y %H:%M:%S}")
            
            # Lưu phạm vi hiện tại để validation
            self._current_mt5_range = (oldest_dt, now_dt)
            
            # Kết nối validation cho date/time widgets nếu đang ở chế độ Fetch MT5
            self._connect_date_validation()
            
            # Tắt auto preview - chỉ hiển thị khi user click "Xem dữ liệu"
            # self.update_data_preview()
            
            print(f"MT5 range updated successfully - no auto data loading")
            
        except Exception as e:
            import traceback
            error_msg = f"Cannot detect MT5 range: {e}"
            print(f"MT5 range error: {error_msg}")
            print(f"Traceback: {traceback.format_exc()}")
            self.dateLabel.setText(error_msg)
            # Clear range khi có lỗi
            self._current_mt5_range = None

    def _connect_date_validation(self):
        """Kết nối validation cho date/time widgets khi ở chế độ Fetch MT5."""
        try:
            # Chỉ kết nối khi đang ở chế độ Fetch MT5 và không suppress
            if not self.dsApiRadio.isChecked() or self._suppress_date_warning:
                return
            # Disconnect existing connections để tránh duplicate
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass  # Chưa có connection nào
            # Kết nối validation (nhưng validation sẽ không load data)
            self.fromDateEdit.dateChanged.connect(self._validate_from_date)
            self.toDateEdit.dateChanged.connect(self._validate_to_date)
            if hasattr(self, 'fromTimeEdit'):
                self.fromTimeEdit.timeChanged.connect(self._validate_from_time)
            if hasattr(self, 'toTimeEdit'):
                self.toTimeEdit.timeChanged.connect(self._validate_to_time)
        except Exception as e:
            print(f"Error connecting date validation: {e}")

    def _disconnect_date_validation(self):
        """Ngắt kết nối validation cho date/time widgets."""
        try:
            # Disconnect existing connections
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass  # Chưa có connection nào
        except Exception as e:
            print(f"Error disconnecting date validation: {e}")

    def _validate_from_date(self, date):
        """Validate From Date không vượt quá phạm vi MT5 và kiểm tra với To Date."""
        if not self._current_mt5_range or not self.dsApiRadio.isChecked() or self._suppress_date_warning or self._is_reconnecting:
            return
            
        oldest_dt, newest_dt = self._current_mt5_range
        
        # Lấy From DateTime (date + time)
        from_date_py = dt_date(date.year(), date.month(), date.day())
        if hasattr(self, 'fromTimeEdit'):
            from_time_qt = self.fromTimeEdit.time()
            from_time_py = dt_time(from_time_qt.hour(), from_time_qt.minute(), from_time_qt.second())
        else:
            from_time_py = time.min
        from_datetime = _dt.combine(from_date_py, from_time_py)
        
        # Lấy To DateTime để kiểm tra
        to_date = self.toDateEdit.date()
        to_date_py = dt_date(to_date.year(), to_date.month(), to_date.day())
        if hasattr(self, 'toTimeEdit'):
            to_time_qt = self.toTimeEdit.time()
            to_time_py = dt_time(to_time_qt.hour(), to_time_qt.minute(), to_time_qt.second())
        else:
            to_time_py = time.max
        to_datetime = _dt.combine(to_date_py, to_time_py)
        
        current_date = self.fromDateEdit.date()
        valid_oldest = QDate(oldest_dt.year, oldest_dt.month, oldest_dt.day)
        valid_newest = QDate(newest_dt.year, newest_dt.month, newest_dt.day)
        
        # Kiểm tra 1: From DateTime không được sớm hơn oldest
        if from_datetime < oldest_dt and current_date != valid_oldest:
            # Lưu giá trị trước đó
            self._previous_from_date = current_date
            
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            # Disconnect tất cả date/time signals để tránh cascade
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass
            
            # Set giá trị hợp lệ
            self.fromDateEdit.setDate(valid_oldest)
            
            # Lưu thông tin để hiển thị warning sau
            self._pending_warning = ("From Date", f"cannot be earlier than {oldest_dt:%d/%m/%Y %H:%M}")
            
            # Sử dụng QTimer để delay reconnect và hiển thị warning
            QtCore.QTimer.singleShot(200, self._reconnect_date_signals_and_show_warning)
            QtCore.QTimer.singleShot(250, self._show_pending_warning)
            return
            
        # Kiểm tra 2: From DateTime không được muộn hơn newest
        if from_datetime > newest_dt and current_date != valid_newest:
            # Lưu giá trị trước đó
            self._previous_from_date = current_date
            
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            # Disconnect tất cả date/time signals để tránh cascade
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass
            
            # Set giá trị hợp lệ
            self.fromDateEdit.setDate(valid_newest)
            
            # Lưu thông tin để hiển thị warning sau
            self._pending_warning = ("From Date", f"cannot be later than {newest_dt:%d/%m/%Y %H:%M}")
            
            # Sử dụng QTimer để delay reconnect và hiển thị warning
            QtCore.QTimer.singleShot(200, self._reconnect_date_signals_and_show_warning)
            QtCore.QTimer.singleShot(250, self._show_pending_warning)
            return
        
        # Kiểm tra 3: From DateTime phải nhỏ hơn To DateTime
        if from_datetime >= to_datetime:
            # Lưu giá trị trước đó
            self._previous_from_date = current_date
            
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            # Disconnect tất cả date/time signals để tránh cascade
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass
            
            # Set From Date = To Date - 1 ngày (hoặc giữ nguyên nếu có thể)
            if to_date_py > oldest_dt.date():
                # Có thể lùi 1 ngày
                new_from_date = to_date_py - timedelta(days=1)
                self.fromDateEdit.setDate(QDate(new_from_date.year, new_from_date.month, new_from_date.day))
            else:
                # Không thể lùi, giữ nguyên date nhưng cảnh báo
                pass
            
            # Lưu thông tin để hiển thị warning sau
            self._pending_warning = ("From Date", f"phải nhỏ hơn To Date")
            
            # Sử dụng QTimer để delay reconnect và hiển thị warning
            QtCore.QTimer.singleShot(200, self._reconnect_date_signals_and_show_warning)
            QtCore.QTimer.singleShot(250, self._show_pending_warning)


    def _validate_to_date(self, date):
        """Validate To Date không vượt quá phạm vi MT5 và kiểm tra với From Date."""
        if not self._current_mt5_range or not self.dsApiRadio.isChecked() or self._suppress_date_warning or self._is_reconnecting:
            return
            
        oldest_dt, newest_dt = self._current_mt5_range
        
        # Lấy To DateTime (date + time)
        to_date_py = dt_date(date.year(), date.month(), date.day())
        if hasattr(self, 'toTimeEdit'):
            to_time_qt = self.toTimeEdit.time()
            to_time_py = dt_time(to_time_qt.hour(), to_time_qt.minute(), to_time_qt.second())
        else:
            to_time_py = time.max
        to_datetime = _dt.combine(to_date_py, to_time_py)
        
        # Lấy From DateTime để kiểm tra
        from_date = self.fromDateEdit.date()
        from_date_py = dt_date(from_date.year(), from_date.month(), from_date.day())
        if hasattr(self, 'fromTimeEdit'):
            from_time_qt = self.fromTimeEdit.time()
            from_time_py = dt_time(from_time_qt.hour(), from_time_qt.minute(), from_time_qt.second())
        else:
            from_time_py = time.min
        from_datetime = _dt.combine(from_date_py, from_time_py)
        
        current_date = self.toDateEdit.date()
        valid_oldest = QDate(oldest_dt.year, oldest_dt.month, oldest_dt.day)
        valid_newest = QDate(newest_dt.year, newest_dt.month, newest_dt.day)
        
        # Kiểm tra 1: To DateTime không được muộn hơn newest
        if to_datetime > newest_dt and current_date != valid_newest:
            # Lưu giá trị trước đó
            self._previous_to_date = current_date
            
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            # Disconnect tất cả date/time signals để tránh cascade
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass
            
            # Set giá trị hợp lệ
            self.toDateEdit.setDate(valid_newest)
            
            # Lưu thông tin để hiển thị warning sau
            self._pending_warning = ("To Date", f"cannot be later than {newest_dt:%d/%m/%Y %H:%M}")
            
            # Sử dụng QTimer để delay reconnect và hiển thị warning
            QtCore.QTimer.singleShot(200, self._reconnect_date_signals_and_show_warning)
            QtCore.QTimer.singleShot(250, self._show_pending_warning)
            return
            
        # Kiểm tra 2: To DateTime không được sớm hơn oldest
        if to_datetime < oldest_dt and current_date != valid_oldest:
            # Lưu giá trị trước đó
            self._previous_to_date = current_date
            
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            # Disconnect tất cả date/time signals để tránh cascade
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass
            
            # Set giá trị hợp lệ
            self.toDateEdit.setDate(valid_oldest)
            
            # Lưu thông tin để hiển thị warning sau
            self._pending_warning = ("To Date", f"cannot be earlier than {oldest_dt:%d/%m/%Y %H:%M}")
            
            # Sử dụng QTimer để delay reconnect và hiển thị warning
            QtCore.QTimer.singleShot(200, self._reconnect_date_signals_and_show_warning)
            QtCore.QTimer.singleShot(250, self._show_pending_warning)
            return
        
        # Kiểm tra 3: To DateTime phải lớn hơn From DateTime
        if to_datetime <= from_datetime:
            # Lưu giá trị trước đó
            self._previous_to_date = current_date
            
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            # Disconnect tất cả date/time signals để tránh cascade
            try:
                self.fromDateEdit.dateChanged.disconnect()
                self.toDateEdit.dateChanged.disconnect()
                if hasattr(self, 'fromTimeEdit'):
                    self.fromTimeEdit.timeChanged.disconnect()
                if hasattr(self, 'toTimeEdit'):
                    self.toTimeEdit.timeChanged.disconnect()
            except Exception:
                pass
            
            # Set To Date = From Date + 1 ngày (hoặc giữ nguyên nếu cần)
            if from_date_py < newest_dt.date():
                # Có thể tiến 1 ngày
                new_to_date = from_date_py + timedelta(days=1)
                self.toDateEdit.setDate(QDate(new_to_date.year, new_to_date.month, new_to_date.day))
            else:
                # Không thể tiến, giữ nguyên date nhưng cảnh báo
                pass
            
            # Lưu thông tin để hiển thị warning sau
            self._pending_warning = ("To Date", f"phải lớn hơn From Date")
            
            # Sử dụng QTimer để delay reconnect và hiển thị warning
            QtCore.QTimer.singleShot(200, self._reconnect_date_signals_and_show_warning)
            QtCore.QTimer.singleShot(250, self._show_pending_warning)


    def _validate_from_time(self, time):
        """Validate From Time khi kết hợp với From Date."""
        if not self._current_mt5_range or not self.dsApiRadio.isChecked() or self._suppress_date_warning:
            return
        
        oldest_dt, newest_dt = self._current_mt5_range
        
        # Get From DateTime
        from_date = self.fromDateEdit.date()
        from_date_py = dt_date(from_date.year(), from_date.month(), from_date.day())
        qt_time = time
        from_time_py = dt_time(qt_time.hour(), qt_time.minute(), qt_time.second())
        from_dt = _dt.combine(from_date_py, from_time_py)
        
        # Get To DateTime để kiểm tra cùng ngày
        to_date = self.toDateEdit.date()
        to_date_py = dt_date(to_date.year(), to_date.month(), to_date.day())
        to_time_qt = self.toTimeEdit.time()
        to_time_py = dt_time(to_time_qt.hour(), to_time_qt.minute(), to_time_qt.second())
        to_dt = _dt.combine(to_date_py, to_time_py)
        
        # Kiểm tra 1: From Time không được sớm hơn MT5 oldest
        if from_dt < oldest_dt:
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            self.fromTimeEdit.setTime(QTime(oldest_dt.hour, oldest_dt.minute, oldest_dt.second))
            self._suppress_date_warning = False
            
            # Hiển thị warning chỉ 1 lần
            self._show_date_warning("From Time", f"cannot be earlier than {oldest_dt:%d/%m/%Y %H:%M}")
            return
        
        # Kiểm tra 2: Nếu cùng ngày, From Time phải nhỏ hơn To Time
        if from_date_py == to_date_py:
            if from_time_py >= to_time_py:
                # From Time >= To Time trên cùng ngày → không hợp lệ
                self._suppress_date_warning = True
                # Set From Time = To Time - 1 giờ (hoặc 00:00 nếu To Time quá nhỏ)
                to_hour = to_time_qt.hour()
                to_minute = to_time_qt.minute()
                
                if to_hour > 0:
                    self.fromTimeEdit.setTime(QTime(to_hour - 1, to_minute, 0))
                else:
                    self.fromTimeEdit.setTime(QTime(0, 0, 0))
                
                self._suppress_date_warning = False
                
                # Hiển thị warning
                self._show_date_warning("From Time", f"must be earlier than To Time ({to_time_qt.toString('HH:mm:ss')}) on the same day")

    def _validate_to_time(self, time):
        """Validate To Time khi kết hợp với To Date."""
        if not self._current_mt5_range or not self.dsApiRadio.isChecked() or self._suppress_date_warning:
            return
        
        oldest_dt, newest_dt = self._current_mt5_range
        
        # Get To DateTime
        to_date = self.toDateEdit.date()
        to_date_py = dt_date(to_date.year(), to_date.month(), to_date.day())
        qt_time = time
        to_time_py = dt_time(qt_time.hour(), qt_time.minute(), qt_time.second())
        to_dt = _dt.combine(to_date_py, to_time_py)
        
        # Get From DateTime để kiểm tra cùng ngày
        from_date = self.fromDateEdit.date()
        from_date_py = dt_date(from_date.year(), from_date.month(), from_date.day())
        from_time_qt = self.fromTimeEdit.time()
        from_time_py = dt_time(from_time_qt.hour(), from_time_qt.minute(), from_time_qt.second())
        from_dt = _dt.combine(from_date_py, from_time_py)
        
        # Kiểm tra 1: To Time không được muộn hơn MT5 newest
        if to_dt > newest_dt:
            # Suppress warning để tránh hiển thị 2 lần
            self._suppress_date_warning = True
            self.toTimeEdit.setTime(QTime(newest_dt.hour, newest_dt.minute, newest_dt.second))
            self._suppress_date_warning = False
            
            # Hiển thị warning chỉ 1 lần
            self._show_date_warning("To Time", f"cannot be later than {newest_dt:%d/%m/%Y %H:%M}")
            return
        
        # Kiểm tra 2: Nếu cùng ngày, To Time phải lớn hơn From Time
        if from_date_py == to_date_py:
            if to_time_py <= from_time_py:
                # To Time <= From Time trên cùng ngày → không hợp lệ
                self._suppress_date_warning = True
                # Set To Time = From Time + 1 giờ (hoặc 23:59 nếu From Time quá lớn)
                from_hour = from_time_qt.hour()
                from_minute = from_time_qt.minute()
                
                if from_hour < 23:
                    self.toTimeEdit.setTime(QTime(from_hour + 1, from_minute, 0))
                else:
                    self.toTimeEdit.setTime(QTime(23, 59, 0))
                
                self._suppress_date_warning = False
                
                # Hiển thị warning
                self._show_date_warning("To Time", f"must be later than From Time ({from_time_qt.toString('HH:mm:ss')}) on the same day")


    def _reconnect_date_signals_and_show_warning(self):
        """Reconnect tất cả date/time signals và reset suppress flag."""
        try:
            # Set flag để ngăn chặn validation khi reconnect
            self._is_reconnecting = True
            
            # Reconnect signals (validation sẽ không load data)
            self.fromDateEdit.dateChanged.connect(self._validate_from_date)
            self.toDateEdit.dateChanged.connect(self._validate_to_date)
            if hasattr(self, 'fromTimeEdit'):
                self.fromTimeEdit.timeChanged.connect(self._validate_from_time)
            if hasattr(self, 'toTimeEdit'):
                self.toTimeEdit.timeChanged.connect(self._validate_to_time)
            
            # Reset suppress flag
            self._suppress_date_warning = False
            
            # Reset reconnect flag
            self._is_reconnecting = False
        except Exception as e:
            print(f"Error reconnecting date signals: {e}")
            self._is_reconnecting = False

    def _show_pending_warning(self):
        """Hiển thị warning đã được lưu trước đó và luôn reset UI về giá trị hợp lệ."""
        try:
            if hasattr(self, '_pending_warning') and self._pending_warning:
                field_name, message = self._pending_warning
                from PyQt5.QtWidgets import QMessageBox
                msg = QMessageBox()
                msg.setIcon(QMessageBox.Warning)
                msg.setWindowTitle("Date Range Warning")
                msg.setText(f"{field_name} {message}")
                msg.setInformativeText("The date/time has been reset to the nearest valid value.")
                msg.setStandardButtons(QMessageBox.Ok)
                msg.setDefaultButton(QMessageBox.Ok)
                msg.exec_()

                # Đảm bảo trường ngày/giờ trên UI luôn về giá trị hợp lệ
                if field_name == "From Date" and self._current_mt5_range:
                    oldest_dt, newest_dt = self._current_mt5_range
                    valid_oldest = QDate(oldest_dt.year, oldest_dt.month, oldest_dt.day)
                    self._suppress_date_warning = True
                    self.fromDateEdit.setDate(valid_oldest)
                    self._suppress_date_warning = False
                elif field_name == "To Date" and self._current_mt5_range:
                    oldest_dt, newest_dt = self._current_mt5_range
                    valid_newest = QDate(newest_dt.year, newest_dt.month, newest_dt.day)
                    self._suppress_date_warning = True
                    self.toDateEdit.setDate(valid_newest)
                    self._suppress_date_warning = False

                self._previous_from_date = None
                self._previous_to_date = None
                self._pending_warning = None
        except Exception as e:
            print(f"Warning display error: {e}")
            # Fallback: in ra console
            if hasattr(self, '_pending_warning') and self._pending_warning:
                field_name, message = self._pending_warning
                print(f"WARNING: {field_name} {message}")

    def _show_delayed_warning(self, field_name, message):
        """Hiển thị warning sau khi đã reset suppress flag."""
        try:
            from PyQt5.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Date Range Warning")
            msg.setText(f"{field_name} {message}")
            msg.setInformativeText("The date/time has been reset to the nearest valid value.")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
        except Exception as e:
            print(f"Warning display error: {e}")
            # Fallback: in ra console
            print(f"WARNING: {field_name} {message}")

    def _show_date_warning(self, field_name, message):
        """Hiển thị cảnh báo khi người dùng chọn ngày/giờ ngoài phạm vi."""
        try:
            # Kiểm tra xem có đang trong quá trình suppress không
            if self._suppress_date_warning:
                return
                
            from PyQt5.QtWidgets import QMessageBox
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Warning)
            msg.setWindowTitle("Date Range Warning")
            msg.setText(f"{field_name} {message}")
            msg.setInformativeText("The date/time has been reset to the nearest valid value.")
            msg.setStandardButtons(QMessageBox.Ok)
            msg.exec_()
        except Exception as e:
            print(f"Warning display error: {e}")
            # Fallback: in ra console
            print(f"WARNING: {field_name} {message}")

    def update_import_year_range(self):
        """Cập nhật label/range khi người dùng chọn Import folders: kiểm tra thư mục theo năm và báo phạm vi."""
        try:
            root = getattr(self, 'import_root_dir', '') or ''
            
            if not root:
                self.dateLabel.setText("Select one or more CSV/Excel files")
                return
            import os as _os
            years = []
            for name in _os.listdir(root):
                try:
                    yr = int(name)
                    years.append(yr)
                except Exception:
                    continue
            if not years:
                self.dateLabel.setText("No year folders found in selected directory")
                return
            y_min, y_max = min(years), max(years)
            from PyQt5.QtCore import QDate
            symbol = self.tradeSymbol_comboBox.currentText()
            timeframe = self.timeframe_comboBox.currentText()
            self.fromDateEdit.setDate(QDate(y_min, 1, 1))
            self.toDateEdit.setDate(QDate(y_max, 12, 31))
            self.dateLabel.setText(f"Symbol: {symbol} timeframe: {timeframe} import range: 01/01/{y_min} → 31/12/{y_max}")
            
            # Tắt auto preview - chỉ hiển thị khi user click "Xem dữ liệu"
            # self.update_data_preview()
        except Exception as e:
            self.dateLabel.setText(f"Import range error: {e}")

    def update_data_preview(self):
        """Cập nhật bảng preview dữ liệu với debounce để tránh gọi lặp lại."""
        try:
            # Kiểm tra flag suppress
            if self._suppress_preview_update:
                print(f"🔒 update_data_preview suppressed")
                return
                
            print(f"🔄 update_data_preview triggered - starting debounce timer...")
            
            # Stop timer hiện tại và restart với delay mới
            self._update_preview_timer.stop()
            self._update_preview_timer.start()
            
        except Exception as e:
            print(f"Update data preview trigger error: {e}")
    
    def _update_data_preview_debounced(self):
        """Thực hiện update data preview sau debounce."""
        try:
            # Ngăn chặn gọi lặp lại
            if self._is_updating_preview:
                print("❌ update_data_preview already in progress, skipping...")
                return
                
            self._is_updating_preview = True
            print(f"✅ Executing debounced update_data_preview...")
            
            if not hasattr(self, 'dataPreview_table'):
                print("dataPreview_table not found")
                return
                
            symbol = self.tradeSymbol_comboBox.currentText()
            timeframe = self.timeframe_comboBox.currentText()
            
            print(f"_update_data_preview_debounced called - Symbol: {symbol}, Timeframe: {timeframe}")
            
            if not symbol:
                print("No symbol selected")
                self._clear_preview_table()
                return
            
            # Kiểm tra data source
            ds_api_checked = hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked()
            ds_import_checked = hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked()
            
            print(f"Data source - API: {ds_api_checked}, Import: {ds_import_checked}")
            
            # Lấy dữ liệu dựa trên nguồn được chọn
            if ds_api_checked:
                # Fetch từ MT5
                print("Fetching from MT5...")
                self._fetch_mt5_preview_data(symbol, timeframe)
            elif ds_import_checked:
                # Kiểm tra xem có file được chọn không
                if not hasattr(self, 'import_file_paths') or not self.import_file_paths:
                    print("No import files selected")
                    self._clear_preview_table()
                    if hasattr(self, 'dataInfoLabel'):
                        self.dataInfoLabel.setText("Please select import files to preview data")
                    return
                    
                # Load từ file import
                print("Loading from import files...")
                self._load_import_preview_data(symbol, timeframe)
            else:
                print("No data source selected")
                self._clear_preview_table()
                
        except Exception as e:
            print(f"Update data preview debounced error: {e}")
            import traceback
            traceback.print_exc()
            self._clear_preview_table()
        finally:
            # Reset flag sau khi hoàn thành
            self._is_updating_preview = False

    def _fetch_mt5_preview_data(self, symbol, timeframe):
        """Lấy dữ liệu preview từ MT5 sử dụng chunked method."""
        try:
            print(f"_fetch_mt5_preview_data called with {symbol}, {timeframe}")
            
            # Đảm bảo MT5 được khởi tạo
            if not mt5.initialize():
                print("MT5 initialization failed")
                self.dataInfoLabel.setText("MT5 connection failed")
                return
            
            # Kiểm tra symbol có tồn tại không
            symbol_info = mt5.symbol_info(symbol)
            if symbol_info is None:
                print(f"Symbol {symbol} not found in MT5")
                self.dataInfoLabel.setText(f"Symbol {symbol} not available in MT5")
                self._clear_preview_table()
                return
            
            # Kiểm tra symbol có được enable không
            if not symbol_info.visible:
                print(f"Symbol {symbol} is not visible, trying to enable...")
                if not mt5.symbol_select(symbol, True):
                    print(f"Failed to enable symbol {symbol}")
                    self.dataInfoLabel.setText(f"Cannot enable symbol {symbol}")
                    self._clear_preview_table()
                    return
                else:
                    print(f"Successfully enabled symbol {symbol}")
            
            tf_const = self.timeframe_map.get(timeframe, mt5.TIMEFRAME_M5)
            print(f"Using timeframe constant: {tf_const}")
            
            # Kiểm tra cache trước khi lấy data mới
            cache_key = (symbol, timeframe)
            if cache_key in self._full_history_cache:
                print(f"📦 Using cached data for {symbol} {timeframe}")
                full_df = self._full_history_cache[cache_key]
                
                # Hiển thị data từ cache
                if full_df is not None and len(full_df) > 0:
                    required_columns = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
                    if all(col in full_df.columns for col in required_columns):
                        print(f"🔄 Displaying cached {len(full_df):,} records in table...")
                        self._populate_preview_table(full_df)
                        self._current_preview_data = full_df
                        
                        total_records = len(full_df)
                        first_time = full_df['time'].iloc[0].strftime('%Y-%m-%d %H:%M')
                        last_time = full_df['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')
                        
                        self.dataInfoLabel.setText(
                            f"MT5 Full History (Cached): {total_records:,} total records "
                            f"({first_time} to {last_time}) - All data displayed"
                        )
                        print(f"✅ Successfully displayed cached {total_records:,} records")
                        return
            
            # Lấy oldest timestamp
            print(f"🔍 Getting oldest candle for {symbol}...")
            oldest_result = get_oldest_candle(symbol, tf_const)
            
            if oldest_result is None or oldest_result[0] is None:
                print(f"Cannot find oldest candle for {symbol}")
                self.dataInfoLabel.setText(f"Cannot find data range for {symbol}")
                self._clear_preview_table()
                return
            
            # Sử dụng get_full_history_chunked để lấy toàn bộ data
            print(f"🚀 Using chunked method to get full history for {symbol}...")
            self.dataInfoLabel.setText("🔄 Loading full historical data...")
            
            # Lấy toàn bộ data từ oldest đến hiện tại
            from_date = oldest_result[0]  # oldest_result[0] là datetime object
            to_date = _dt.now().replace(hour=23, minute=59, second=59)
            
            full_df = get_full_history_chunked(
                symbol=symbol, 
                timeframe=tf_const,
                from_date=from_date,
                to_date=to_date,
                chunk_days=30,  # 30 ngày mỗi chunk
                save_to_csv=False  # Không save file trong preview
            )
            
            if full_df is not None and len(full_df) > 0:
                print(f"✅ Successfully loaded {len(full_df)} records")
                
                # Đảm bảo có đủ cột cần thiết
                required_columns = ['time', 'open', 'high', 'low', 'close', 'tick_volume']
                if all(col in full_df.columns for col in required_columns):
                    print("All required columns found, populating table...")
                    
                    # Hiển thị TẤT CẢ dữ liệu ra bảng
                    print(f"🔄 Displaying ALL {len(full_df):,} records in table...")
                    print(f"📊 DEBUG: full_df shape before populate: {full_df.shape}")
                    print(f"📊 DEBUG: full_df type: {type(full_df)}")
                    print(f"📊 DEBUG: full_df columns: {list(full_df.columns)}")
                    
                    self._populate_preview_table(full_df)
                    self._current_preview_data = full_df  # Lưu toàn bộ data
                    
                    # Thông tin hiển thị
                    total_records = len(full_df)
                    first_time = full_df['time'].iloc[0].strftime('%Y-%m-%d %H:%M')
                    last_time = full_df['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')
                    
                    self.dataInfoLabel.setText(
                        f"MT5 Full History: {total_records:,} total records "
                        f"({first_time} to {last_time}) - All data displayed"
                    )
                    
                    print(f"✅ Successfully displayed ALL {total_records:,} records in table")
                    print(f"Date range: {first_time} to {last_time}")
                    
                    # Lưu vào cache để sử dụng lần sau
                    cache_key = (symbol, timeframe)
                    self._full_history_cache[cache_key] = full_df
                    print(f"💾 Cached data for {symbol} {timeframe}")
                    
                else:
                    missing_cols = [col for col in required_columns if col not in full_df.columns]
                    print(f"Missing required columns: {missing_cols}")
                    self._clear_preview_table()
                    self.dataInfoLabel.setText(f"Missing columns: {missing_cols}")
                    
            else:
                print(f"No data returned from chunked method for {symbol}")
                self._clear_preview_table()
                self.dataInfoLabel.setText(f"No historical data available for {symbol}")
                
        except Exception as e:
            print(f"Fetch MT5 preview data error: {e}")
            import traceback
            traceback.print_exc()
            self._clear_preview_table()
            self.dataInfoLabel.setText(f"MT5 Error: {str(e)}")
        finally:
            mt5.shutdown()

    def _load_import_preview_data(self, symbol, timeframe):
        """Load dữ liệu preview từ file import."""
        try:
            print(f"_load_import_preview_data called with {symbol}, {timeframe}")
            
            if not hasattr(self, 'import_file_paths') or not self.import_file_paths:
                print("No import files selected")
                self._clear_preview_table()
                self.dataInfoLabel.setText("No import files selected")
                return
            
            print(f"Available import files: {self.import_file_paths}")
            
            # Tìm file phù hợp với symbol (loại bỏ chữ 'm' ở cuối để match)
            matching_files = []
            symbol_base = symbol.upper().rstrip('M')  # Loại bỏ 'M' ở cuối
            
            for file_path in self.import_file_paths:
                filename = os.path.basename(file_path).upper()
                print(f"Checking file: {filename} for symbol: {symbol.upper()} (base: {symbol_base})")
                
                # Kiểm tra match với symbol gốc hoặc symbol base (không có 'm')
                if symbol.upper() in filename or symbol_base in filename:
                    matching_files.append(file_path)
                    print(f"File matched: {filename}")
            
            if not matching_files:
                print(f"No matching files found for {symbol} (base: {symbol_base})")
                self._clear_preview_table()
                self.dataInfoLabel.setText(f"No matching files found for {symbol}")
                return
            
            # Load file đầu tiên phù hợp
            file_path = matching_files[0]
            print(f"Loading import data from: {file_path}")
            
            # Đọc CSV với các options để xử lý format khác nhau
            try:
                df = pd.read_csv(file_path)
                print(f"Successfully read CSV with separator ','")
            except Exception as e:
                print(f"Error reading CSV with ',': {e}")
                try:
                    df = pd.read_csv(file_path, sep=';')
                    print(f"Successfully read CSV with separator ';'")
                except Exception as e2:
                    print(f"Error reading CSV with ';': {e2}")
                    self._clear_preview_table()
                    self.dataInfoLabel.setText(f"Cannot read file: {os.path.basename(file_path)}")
                    return
            
            print(f"CSV columns: {list(df.columns)}")
            print(f"CSV shape: {df.shape}")
            print(f"First few rows:\n{df.head()}")
            
            # Chuẩn hóa tên cột (xử lý nhiều format khác nhau)
            column_mapping = {}
            
            # Kiểm tra cấu trúc file dựa trên tên cột
            print(f"Analyzing column structure...")
            print(f"First column: '{df.columns[0]}' (type: {type(df.columns[0])})")
            print(f"Second column: '{df.columns[1]}' (type: {type(df.columns[1])})")
            
            # Kiểm tra xem cột đầu có phải là date không
            first_col_is_date = False
            try:
                # Thử parse cột đầu tiên như date
                pd.to_datetime(df.columns[0], format='%Y.%m.%d')
                first_col_is_date = True
                print("First column appears to be a date")
            except:
                print("First column is not a date")
            
            # Nếu cột đầu là date, cột thứ 2 là time
            if first_col_is_date and len(df.columns) >= 6:
                print("Detected date/time structure: Date column + Time column")
                column_mapping['date_col'] = df.columns[0]  # Date column
                column_mapping['time_col'] = df.columns[1]  # Time column
                column_mapping['open'] = df.columns[2]      # Open
                column_mapping['high'] = df.columns[3]      # High  
                column_mapping['low'] = df.columns[4]       # Low
                column_mapping['close'] = df.columns[5]     # Close
                column_mapping['volume'] = df.columns[6]    # Volume
                print(f"Date/Time structure mapping: {column_mapping}")
            else:
                # Fallback: tìm cột theo tên
                print("Using name-based column mapping")
                
                # Tìm cột time (có thể là Date, Time, hoặc kết hợp)
                for col in df.columns:
                    col_lower = str(col).lower().strip()
                    if 'time' in col_lower or 'date' in col_lower:
                        column_mapping['time'] = col
                        print(f"Found time column: {col}")
                        break
                
                # Tìm cột OHLCV
                for col in df.columns:
                    col_lower = str(col).lower().strip()
                    if 'open' in col_lower and col not in column_mapping.values():
                        column_mapping['open'] = col
                        print(f"Found open column: {col}")
                    elif 'high' in col_lower and col not in column_mapping.values():
                        column_mapping['high'] = col
                        print(f"Found high column: {col}")
                    elif 'low' in col_lower and col not in column_mapping.values():
                        column_mapping['low'] = col
                        print(f"Found low column: {col}")
                    elif 'close' in col_lower and col not in column_mapping.values():
                        column_mapping['close'] = col
                        print(f"Found close column: {col}")
                    elif 'volume' in col_lower and col not in column_mapping.values():
                        column_mapping['volume'] = col
                        print(f"Found volume column: {col}")
                
                # Nếu không tìm thấy theo tên, thử theo vị trí (như trong hình Excel)
                if len(df.columns) >= 6:
                    print("Using positional mapping for columns")
                    if 'time' not in column_mapping:
                        column_mapping['time'] = df.columns[1] if len(df.columns) > 1 else df.columns[0]
                    if 'open' not in column_mapping:
                        column_mapping['open'] = df.columns[2] if len(df.columns) > 2 else None
                    if 'high' not in column_mapping:
                        column_mapping['high'] = df.columns[3] if len(df.columns) > 3 else None
                    if 'low' not in column_mapping:
                        column_mapping['low'] = df.columns[4] if len(df.columns) > 4 else None
                    if 'close' not in column_mapping:
                        column_mapping['close'] = df.columns[5] if len(df.columns) > 5 else None
                    if 'volume' not in column_mapping:
                        column_mapping['volume'] = df.columns[6] if len(df.columns) > 6 else df.columns[5]
            
            print(f"Final column mapping: {column_mapping}")
            
            # Tạo DataFrame mới với cột đã chuẩn hóa
            new_df = pd.DataFrame()
            
            # Xử lý cấu trúc date/time riêng biệt
            if 'date_col' in column_mapping and 'time_col' in column_mapping:
                print("Creating combined datetime from separate date and time columns")
                # Combine date và time columns
                date_col = column_mapping['date_col']
                time_col = column_mapping['time_col']
                new_df['time'] = df[date_col].astype(str) + ' ' + df[time_col].astype(str)
                print(f"Combined time column created from {date_col} + {time_col}")
            elif 'time' in column_mapping and column_mapping['time']:
                new_df['time'] = df[column_mapping['time']]
                print(f"Using single time column: {column_mapping['time']}")
            
            # Thêm các cột OHLCV
            if 'open' in column_mapping and column_mapping['open']:
                new_df['open'] = pd.to_numeric(df[column_mapping['open']], errors='coerce')
                print(f"Added open column: {column_mapping['open']}")
            if 'high' in column_mapping and column_mapping['high']:
                new_df['high'] = pd.to_numeric(df[column_mapping['high']], errors='coerce')
                print(f"Added high column: {column_mapping['high']}")
            if 'low' in column_mapping and column_mapping['low']:
                new_df['low'] = pd.to_numeric(df[column_mapping['low']], errors='coerce')
                print(f"Added low column: {column_mapping['low']}")
            if 'close' in column_mapping and column_mapping['close']:
                new_df['close'] = pd.to_numeric(df[column_mapping['close']], errors='coerce')
                print(f"Added close column: {column_mapping['close']}")
            if 'volume' in column_mapping and column_mapping['volume']:
                new_df['volume'] = pd.to_numeric(df[column_mapping['volume']], errors='coerce')
                print(f"Added volume column: {column_mapping['volume']}")
            
            print(f"New DataFrame columns: {list(new_df.columns)}")
            print(f"New DataFrame shape: {new_df.shape}")
            
            # Xử lý cột time với format cụ thể
            if 'time' in new_df.columns:
                print("Processing time column...")
                
                # Thử các format phổ biến (ưu tiên format của CSV hiện tại)
                time_formats = [
                    '%Y.%m.%d %H:%M',      # 2016.01.04 1:00 (format chính của CSV)
                    '%Y.%m.%d %H:%M:%S',   # 2016.01.04 01:00:00
                    '%Y-%m-%d %H:%M:%S',   # 2016-01-04 01:00:00
                    '%Y-%m-%d %H:%M',      # 2016-01-04 01:00
                    '%d/%m/%Y %H:%M',      # 04/01/2016 01:00
                    '%m/%d/%Y %H:%M',      # 01/04/2016 01:00
                    '%Y.%m.%d',            # 2016.01.04
                    '%Y-%m-%d',            # 2016-01-04
                ]
                
                time_parsed = False
                for fmt in time_formats:
                    try:
                        new_df['time'] = pd.to_datetime(new_df['time'], format=fmt, errors='coerce')
                        # Kiểm tra xem có parse thành công không (không có NaT)
                        if not new_df['time'].isna().all():
                            print(f"Successfully parsed time column with format: {fmt}")
                            time_parsed = True
                            break
                    except:
                        continue
                
                # Nếu không parse được với format cụ thể, thử với dateutil
                if not time_parsed:
                    try:
                        new_df['time'] = pd.to_datetime(new_df['time'], errors='coerce')
                        print("Successfully parsed time column with dateutil")
                        time_parsed = True
                    except:
                        print("Failed to parse time column with dateutil")
                
                # Nếu vẫn không được, thử combine Date và Time riêng biệt
                if not time_parsed and len(df.columns) >= 2:
                    try:
                        date_col = df.columns[0]  # Cột đầu tiên thường là date
                        time_col = df.columns[1]  # Cột thứ hai thường là time
                        
                        # Thử parse date và time riêng biệt
                        date_series = pd.to_datetime(df[date_col], errors='coerce')
                        time_series = pd.to_datetime(df[time_col], format='%H:%M', errors='coerce')
                        
                        # Combine date và time
                        new_df['time'] = date_series.dt.date.astype(str) + ' ' + time_series.dt.time.astype(str)
                        new_df['time'] = pd.to_datetime(new_df['time'], errors='coerce')
                        
                        if not new_df['time'].isna().all():
                            print("Successfully combined date and time columns")
                            time_parsed = True
                    except Exception as e:
                        print(f"Failed to combine date and time: {e}")
                
                if not time_parsed:
                    print("Warning: Could not parse time column, keeping as string")
            
            # Loại bỏ rows có NaN
            new_df = new_df.dropna()
            print(f"After removing NaN, shape: {new_df.shape}")
            
            if len(new_df) > 0:
                # Hiển thị tất cả dữ liệu (không giới hạn 100 rows)
                print(f"Final data shape: {new_df.shape}")
                self._populate_preview_table(new_df)
                self._current_preview_data = new_df
                self.dataInfoLabel.setText(f"Import Data: {len(new_df)} records from {os.path.basename(file_path)}")
                print(f"Successfully loaded {len(new_df)} records from import file")
            else:
                print("No valid data after processing")
                self._clear_preview_table()
                self.dataInfoLabel.setText("No valid data found in import file")
            
        except Exception as e:
            print(f"Load import preview data error: {e}")
            import traceback
            traceback.print_exc()
            self._clear_preview_table()
            self.dataInfoLabel.setText(f"Import Error: {str(e)}")

    def _initialize_default_dates_and_preview(self):
        """Khởi tạo date range mặc định và cập nhật preview."""
        try:
            if not hasattr(self, 'dataPreview_table'):
                return
                
            # Set default date range (30 ngày gần đây)
            now = _dt.now()
            thirty_days_ago = now - timedelta(days=30)
            
            self.fromDateEdit.setDate(QDate(thirty_days_ago.year, thirty_days_ago.month, thirty_days_ago.day))
            self.toDateEdit.setDate(QDate(now.year, now.month, now.day))
            
            print(f"Set default date range: {thirty_days_ago.date()} to {now.date()}")
            
            # Tắt auto preview - chỉ hiển thị khi user click "Xem dữ liệu"
            # self.update_data_preview()
            
        except Exception as e:
            print(f"Initialize default dates error: {e}")
            # Tắt fallback auto preview
            # self.update_data_preview()

    def _populate_preview_table(self, df, symbol=None, timeframe=None):
        """Điền thông tin tổng hợp dữ liệu vào bảng preview với các cột: Symbol, Timeframe, Type_Data, Size_Data, From_Date, To_Date."""
        try:
            print(f"🎯 _populate_preview_table called with DataFrame shape: {df.shape}")
            print(f"📊 DataFrame columns: {list(df.columns)}")
            print(f"🔧 dataPreview_table exists: {hasattr(self, 'dataPreview_table')}")
            
            if not hasattr(self, 'dataPreview_table'):
                print("❌ dataPreview_table not found!")
                return
            
            # Chỉ hiển thị 1 hàng thông tin tổng hợp
            print("📝 Setting table row count to 1...")
            self.dataPreview_table.setRowCount(1)
            print(f"✅ Set table row count to: {self.dataPreview_table.rowCount()}")
            print(f"📊 Table column count: {self.dataPreview_table.columnCount()}")
            
            # Lấy symbol và timeframe - ưu tiên từ parameter, sau đó từ combobox
            if symbol is None:
                symbol = self.tradeSymbol_comboBox.currentText()
                print(f"📊 Symbol taken from combobox: {symbol}")
            else:
                print(f"📊 Symbol from parameter: {symbol}")
                
            if timeframe is None:
                timeframe = self.timeframe_comboBox.currentText()
                print(f"📊 Timeframe taken from combobox: {timeframe}")
            else:
                print(f"📊 Timeframe from parameter: {timeframe}")
            
            # Xác định type_data dựa trên data source được chọn
            type_data = ""
            try:
                if hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked():
                    type_data = "MT5"
                elif hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked():
                    type_data = "Import"
                else:
                    type_data = "Unknown"
                print(f"📊 Data source type: {type_data}")
            except Exception as e:
                type_data = "Unknown"
                print(f"⚠️ Error determining data source: {e}")
            
            # Size_data - số lượng records
            size_data = str(len(df)) if df is not None and len(df) > 0 else "0"
            
            # From_Date và To_Date - lấy từ dữ liệu đầu tiên và cuối cùng
            from_date = ""
            to_date = ""
            
            if df is not None and len(df) > 0 and 'time' in df.columns:
                try:
                    # Sắp xếp theo thời gian để đảm bảo thứ tự đúng
                    df_sorted = df.sort_values('time')
                    
                    # Lấy thời gian đầu tiên và cuối cùng
                    first_time = df_sorted['time'].iloc[0]
                    last_time = df_sorted['time'].iloc[-1]
                    
                    # Format thành YYYY-MM-DD HH:MM
                    if pd.notna(first_time):
                        if isinstance(first_time, str):
                            first_dt = pd.to_datetime(first_time)
                        else:
                            first_dt = first_time
                        from_date = first_dt.strftime('%Y-%m-%d %H:%M')
                    
                    if pd.notna(last_time):
                        if isinstance(last_time, str):
                            last_dt = pd.to_datetime(last_time)
                        else:
                            last_dt = last_time
                        to_date = last_dt.strftime('%Y-%m-%d %H:%M')
                        
                    print(f"Extracted date range: {from_date} to {to_date}")
                        
                except Exception as e:
                    print(f"Error extracting date range: {e}")
                    from_date = "N/A"
                    to_date = "N/A"
            else:
                from_date = "N/A"
                to_date = "N/A"
            
            # Điền dữ liệu vào hàng duy nhất
            self.dataPreview_table.setItem(0, 0, QtWidgets.QTableWidgetItem(symbol))          # Symbol
            self.dataPreview_table.setItem(0, 1, QtWidgets.QTableWidgetItem(timeframe))      # Timeframe
            self.dataPreview_table.setItem(0, 2, QtWidgets.QTableWidgetItem(type_data))      # Type_Data
            self.dataPreview_table.setItem(0, 3, QtWidgets.QTableWidgetItem(size_data))      # Size_Data
            self.dataPreview_table.setItem(0, 4, QtWidgets.QTableWidgetItem(from_date))      # From_Date
            self.dataPreview_table.setItem(0, 5, QtWidgets.QTableWidgetItem(to_date))        # To_Date
            
            print(f"Successfully populated summary table:")
            print(f"  Symbol: {symbol}, Timeframe: {timeframe}")
            print(f"  Type: {type_data}, Size: {size_data}")
            print(f"  Range: {from_date} to {to_date}")
            
        except Exception as e:
            print(f"Populate preview table error: {e}")
            import traceback
            traceback.print_exc()

    def _clear_preview_table(self):
        """Xóa dữ liệu trong bảng preview."""
        try:
            self.dataPreview_table.setRowCount(0)
            self._current_preview_data = None
            if hasattr(self, 'dataInfoLabel'):
                self.dataInfoLabel.setText("Configure data source and click 'Lấy và xem dữ liệu' to view summary")
        except Exception as e:
            print(f"Clear preview table error: {e}")
    
    def clear_full_history_cache(self):
        """Xóa cache full history data."""
        try:
            self._full_history_cache.clear()
            print("📦 Cleared full history cache")
        except Exception as e:
            print(f"Clear cache error: {e}")
    
    def suppress_preview_updates(self, suppress=True):
        """Temporarily suppress preview updates."""
        self._suppress_preview_update = suppress
        if suppress:
            print("🔒 Preview updates suppressed")
        else:
            print("🔓 Preview updates enabled")
            
    def on_view_data_clicked(self):
        """Xử lý khi nhấn nút 'Xem dữ liệu--->'."""
        try:
            print("🔍 View data button clicked")
            
            # Debug thông tin chi tiết về UI components
            print(f"🔧 Debug UI components:")
            print(f"   dsApiRadio exists: {hasattr(self, 'dsApiRadio')}")
            print(f"   dsImportRadio exists: {hasattr(self, 'dsImportRadio')}")
            if hasattr(self, 'dsApiRadio'):
                print(f"   dsApiRadio checked: {self.dsApiRadio.isChecked()}")
            if hasattr(self, 'dsImportRadio'):
                print(f"   dsImportRadio checked: {self.dsImportRadio.isChecked()}")
            print(f"   import_file_paths exists: {hasattr(self, 'import_file_paths')}")
            if hasattr(self, 'import_file_paths'):
                print(f"   import_file_paths: {self.import_file_paths}")
                print(f"   import_file_paths length: {len(self.import_file_paths) if self.import_file_paths else 0}")
            
            # Validate input trước khi lấy dữ liệu
            validation_result = self.validate_input_data()
            print(f"📋 Validation result: {validation_result}")
            if not validation_result["valid"]:
                show_message("Validation Error", validation_result["message"])
                return
            
            # Hiển thị table
            self.dataPreviewGroup.setVisible(True)
            
            # Lấy dữ liệu theo nguồn được chọn
            symbol = self.tradeSymbol_comboBox.currentText()
            timeframe = self.timeframe_comboBox.currentText()
            
            # Debug thông tin
            print(f"📊 Selected data:")
            print(f"   Symbol: {symbol}")
            print(f"   Timeframe: {timeframe}")
            
            ds_api_checked = hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked()
            ds_import_checked = hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked()
            
            print(f"   Data source: {'MT5' if ds_api_checked else 'Import' if ds_import_checked else 'None'}")
            
            if ds_api_checked:
                print("🚀 Calling MT5 data fetch...")
                self._fetch_mt5_data_with_range(symbol, timeframe)
            elif ds_import_checked:
                print("📁 Calling import data load...")
                self._load_import_data_with_range(symbol, timeframe)
            else:
                print("❌ No data source selected")
                show_message("Error", "Please select a data source (MT5 or Import)")
                
        except Exception as e:
            print(f"❌ View data error: {e}")
            import traceback
            print(f"📄 Traceback: {traceback.format_exc()}")
            show_message("Error", f"Error loading data: {str(e)}")
    
    def validate_input_data(self):
        """Validate dữ liệu đầu vào trước khi lấy data."""
        try:
            # Kiểm tra symbol
            symbol = self.tradeSymbol_comboBox.currentText()
            if not symbol:
                return {"valid": False, "message": "Vui lòng chọn Symbol"}
            
            # Kiểm tra timeframe
            timeframe = self.timeframe_comboBox.currentText()
            if not timeframe:
                return {"valid": False, "message": "Vui lòng chọn Timeframe"}
            
            # Kiểm tra data source
            ds_api_checked = hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked()
            ds_import_checked = hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked()
            
            if not ds_api_checked and not ds_import_checked:
                return {"valid": False, "message": "Vui lòng chọn nguồn dữ liệu (Import hoặc MT5)"}
            
            # Validate import files nếu chọn import
            if ds_import_checked:
                if not hasattr(self, 'import_file_paths') or not self.import_file_paths:
                    return {"valid": False, "message": "Vui lòng chọn file CSV/Excel để import"}
            
            # Validate date range
            from_date_qt = self.fromDateEdit.date()
            to_date_qt = self.toDateEdit.date()
            
            # Convert QDate to Python date
            from_date = dt_date(from_date_qt.year(), from_date_qt.month(), from_date_qt.day())
            to_date = dt_date(to_date_qt.year(), to_date_qt.month(), to_date_qt.day())
            
            # Get time if available
            if hasattr(self, 'fromTimeEdit'):
                from_time_qt = self.fromTimeEdit.time()
                from_time = dt_time(from_time_qt.hour(), from_time_qt.minute(), from_time_qt.second())
            else:
                from_time = dt_time(0, 0, 0)
            
            if hasattr(self, 'toTimeEdit'):
                to_time_qt = self.toTimeEdit.time()
                to_time = dt_time(to_time_qt.hour(), to_time_qt.minute(), to_time_qt.second())
            else:
                to_time = dt_time(23, 59, 0)
            
            # Combine date + time to create full datetime
            from_datetime = _dt.combine(from_date, from_time)
            to_datetime = _dt.combine(to_date, to_time)
            
            # Validate: From DateTime must be less than To DateTime
            if from_datetime >= to_datetime:
                return {"valid": False, "message": "From Date phải nhỏ hơn To Date"}
            
            # Không cần validate time riêng nữa vì đã check datetime ở trên

            
            return {"valid": True, "message": "Validation passed"}
            
        except Exception as e:
            return {"valid": False, "message": f"Validation error: {str(e)}"}
    
    def _fetch_mt5_data_with_range(self, symbol, timeframe):
        """Lấy dữ liệu MT5 theo range người dùng nhập."""
        try:
            print(f"🚀 Fetching MT5 data with user range...")
            print(f"📊 Requested symbol: {symbol}, timeframe: {timeframe}")
            
            # Lấy date/time từ UI
            from_date_qt = self.fromDateEdit.date()
            to_date_qt = self.toDateEdit.date()
            
            # Convert QDate to Python date
            from_date = dt_date(from_date_qt.year(), from_date_qt.month(), from_date_qt.day())
            to_date = dt_date(to_date_qt.year(), to_date_qt.month(), to_date_qt.day())
            
            # Convert QTime to Python time if exists
            if hasattr(self, 'fromTimeEdit'):
                from_time_qt = self.fromTimeEdit.time()
                from_time = dt_time(from_time_qt.hour(), from_time_qt.minute(), from_time_qt.second())
            else:
                from_time = dt_time(0, 0, 0)
                
            if hasattr(self, 'toTimeEdit'):
                to_time_qt = self.toTimeEdit.time()
                to_time = dt_time(to_time_qt.hour(), to_time_qt.minute(), to_time_qt.second())
            else:
                to_time = dt_time(23, 59, 0)
            
            # Combine date + time
            from_datetime = _dt.combine(from_date, from_time)
            to_datetime = _dt.combine(to_date, to_time)
            
            print(f"📅 User range: {from_datetime} to {to_datetime}")
            
            # Kiểm tra MT5
            if not mt5.initialize():
                show_message("Error", "MT5 connection failed")
                return
            
            tf_const = self.timeframe_map.get(timeframe, mt5.TIMEFRAME_M5)
            
            # Sử dụng get_full_history_chunked với range
            self.dataInfoLabel.setText("🔄 Loading data from MT5...")
            
            full_df = get_full_history_chunked(
                symbol=symbol,
                timeframe=tf_const,
                from_date=from_datetime,
                to_date=to_datetime,
                chunk_days=30,
                save_to_csv=False
            )
            
            if full_df is not None and len(full_df) > 0:
                print(f"✅ Loaded {len(full_df)} records from MT5 for {symbol}")
                self._populate_preview_table(full_df, symbol, timeframe)
                self._current_preview_data = full_df
                
                # Thông tin cho dataInfoLabel - hiển thị với format mới
                first_time = full_df['time'].iloc[0].strftime('%Y-%m-%d %H:%M')
                last_time = full_df['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')
                
                self.dataInfoLabel.setText(
                    f"✅ Data Summary: {symbol} {timeframe} | {len(full_df):,} records | {first_time} → {last_time}"
                )
            else:
                self._clear_preview_table()
                self.dataInfoLabel.setText("❌ No data found in specified range")
                
        except Exception as e:
            print(f"Fetch MT5 with range error: {e}")
            self._clear_preview_table()
            self.dataInfoLabel.setText(f"❌ Error: {str(e)}")
        finally:
            mt5.shutdown()
    
    def _resample_to_timeframe(self, df, target_timeframe):
        """Resample dữ liệu M1 thành timeframe khác."""
        try:
            if target_timeframe == "M1":
                return df  # Không cần resample
            
            print(f"🔄 Resampling from M1 to {target_timeframe}")
            
            # Mapping timeframe to pandas resample rule
            timeframe_rules = {
                "M5": "5min",     # 5 minutes
                "M15": "15min",   # 15 minutes  
                "M30": "30min",   # 30 minutes
                "H1": "1h",       # 1 hour
                "H4": "4h",       # 4 hours
                "D1": "1D"        # 1 day
            }
            
            if target_timeframe not in timeframe_rules:
                print(f"⚠️ Unknown timeframe: {target_timeframe}, returning original data")
                return df
            
            rule = timeframe_rules[target_timeframe]
            
            # Set time as index for resampling
            df_copy = df.copy()
            df_copy.set_index('time', inplace=True)
            
            # Resample với OHLCV logic
            resampled = df_copy.resample(rule).agg({
                'open': 'first',      # Open của candle đầu tiên
                'high': 'max',        # High cao nhất
                'low': 'min',         # Low thấp nhất  
                'close': 'last',      # Close của candle cuối cùng
                'volume': 'sum'       # Tổng volume
            }).dropna()
            
            # Reset index để có lại cột time
            resampled.reset_index(inplace=True)
            
            print(f"✅ Resampled from {len(df)} M1 candles to {len(resampled)} {target_timeframe} candles")
            return resampled
            
        except Exception as e:
            print(f"❌ Resample error: {e}")
            return df  # Return original data if error
    
    def _load_import_data_with_range(self, symbol, timeframe):
        """Load dữ liệu import theo range người dùng nhập."""
        try:
            print(f"📁 Loading import data with user range...")
            print(f"📊 Requested symbol: {symbol}, timeframe: {timeframe}")
            
            # Lấy date/time từ UI
            from_date_qt = self.fromDateEdit.date()
            to_date_qt = self.toDateEdit.date()
            
            # Convert QDate to Python date
            from_date = dt_date(from_date_qt.year(), from_date_qt.month(), from_date_qt.day())
            to_date = dt_date(to_date_qt.year(), to_date_qt.month(), to_date_qt.day())
            
            # Convert QTime to Python time if exists
            if hasattr(self, 'fromTimeEdit'):
                from_time_qt = self.fromTimeEdit.time()
                from_time = dt_time(from_time_qt.hour(), from_time_qt.minute(), from_time_qt.second())
            else:
                from_time = dt_time(0, 0, 0)
                
            if hasattr(self, 'toTimeEdit'):
                to_time_qt = self.toTimeEdit.time()
                to_time = dt_time(to_time_qt.hour(), to_time_qt.minute(), to_time_qt.second())
            else:
                to_time = dt_time(23, 59, 0)
            
            # Combine date + time
            from_datetime = _dt.combine(from_date, from_time)
            to_datetime = _dt.combine(to_date, to_time)
            
            print(f"📅 User range: {from_datetime} to {to_datetime}")
            
            # Load data từ files (sử dụng logic từ _load_import_preview_data)
            if not hasattr(self, 'import_file_paths') or not self.import_file_paths:
                print("❌ No import_file_paths found")
                show_message("Error", "No import files selected")
                return
            
            print(f"📂 Found {len(self.import_file_paths)} import files:")
            for i, path in enumerate(self.import_file_paths):
                print(f"   {i+1}. {path}")
            
            # Load và filter theo range
            all_dataframes = []
            
            for file_path in self.import_file_paths:
                try:
                    print(f"📂 Loading file: {os.path.basename(file_path)}")
                    
                    if file_path.endswith('.csv'):
                        # Đọc CSV với header để detect format
                        df_check = pd.read_csv(file_path, nrows=1)
                        columns = df_check.columns.tolist()
                        print(f"   📊 Detected columns: {columns}")
                        
                        # Check if ANY column contains datetime or time info
                        has_datetime_col = any('datetime' in col.lower() for col in columns)
                        has_time_col = any('time' in col.lower() for col in columns)
                        
                        if has_datetime_col or has_time_col:
                            # Format mới: có cột datetime hoặc time
                            df = pd.read_csv(file_path)
                            
                            # Tìm cột datetime hoặc time
                            datetime_col = None
                            for col in df.columns:
                                if 'datetime' in col.lower():
                                    datetime_col = col
                                    break
                                elif 'time' in col.lower():
                                    datetime_col = col
                                    break
                            
                            if datetime_col is None:
                                print(f"   ❌ No datetime/time column found despite detection")
                                continue
                                
                            print(f"   📊 Using datetime column: {datetime_col}")
                            df['time'] = pd.to_datetime(df[datetime_col], errors='coerce')
                            
                            # Đảm bảo có các cột OHLCV cần thiết
                            required_cols = ['open', 'high', 'low', 'close']
                            missing_cols = [col for col in required_cols if col not in df.columns]
                            
                            if missing_cols:
                                print(f"   ❌ Missing required columns: {missing_cols}")
                                continue
                                
                            # Chỉ giữ các cột cần thiết
                            keep_cols = ['time', 'open', 'high', 'low', 'close']
                            if 'volume' in df.columns:
                                keep_cols.append('volume')
                            else:
                                # Tạo volume giả nếu không có
                                df['volume'] = 100
                                keep_cols.append('volume')
                                
                            df = df[keep_cols]
                            
                        else:
                            # Format cũ: Date, Time, Open, High, Low, Close, Volume (không có header)
                            df = pd.read_csv(file_path, header=None)
                            
                            # Kiểm tra số cột và gán tên cột phù hợp
                            if len(df.columns) >= 6:
                                # Format: Date, Time, Open, High, Low, Close, Volume
                                df.columns = ['date', 'time_str', 'open', 'high', 'low', 'close', 'volume'][:len(df.columns)]
                                
                                # Combine date và time thành datetime
                                df['time'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time_str'].astype(str), 
                                                           errors='coerce', format='%Y.%m.%d %H:%M')
                                
                                # Drop original date và time_str columns
                                df = df.drop(['date', 'time_str'], axis=1)
                                
                            else:
                                print(f"   ⚠️ Unexpected CSV format, columns: {len(df.columns)}")
                                continue
                            
                    elif file_path.endswith(('.xlsx', '.xls')):
                        # Đọc Excel với header để detect format
                        df_check = pd.read_excel(file_path, nrows=1)
                        columns = df_check.columns.tolist()
                        print(f"   📊 Detected Excel columns: {columns}")
                        
                        # Check if ANY column contains datetime or time info
                        has_datetime_col = any('datetime' in str(col).lower() for col in columns)
                        has_time_col = any('time' in str(col).lower() for col in columns)
                        
                        if has_datetime_col or has_time_col:
                            # Format mới: có cột datetime hoặc time
                            df = pd.read_excel(file_path)
                            
                            # Tìm cột datetime hoặc time
                            datetime_col = None
                            for col in df.columns:
                                if 'datetime' in str(col).lower():
                                    datetime_col = col
                                    break
                                elif 'time' in str(col).lower():
                                    datetime_col = col
                                    break
                            
                            if datetime_col is None:
                                print(f"   ❌ No datetime/time column found despite detection")
                                continue
                                
                            print(f"   📊 Using datetime column: {datetime_col}")
                            df['time'] = pd.to_datetime(df[datetime_col], errors='coerce')
                            
                            # Đảm bảo có các cột OHLCV cần thiết
                            required_cols = ['open', 'high', 'low', 'close']
                            missing_cols = [col for col in required_cols if col not in df.columns]
                            
                            if missing_cols:
                                print(f"   ❌ Missing required Excel columns: {missing_cols}")
                                continue
                                
                            # Chỉ giữ các cột cần thiết
                            keep_cols = ['time', 'open', 'high', 'low', 'close']
                            if 'volume' in df.columns:
                                keep_cols.append('volume')
                            else:
                                # Tạo volume giả nếu không có
                                df['volume'] = 100
                                keep_cols.append('volume')
                                
                            df = df[keep_cols]
                            
                        else:
                            # Format cũ: Date, Time, Open, High, Low, Close, Volume (không có header)
                            df = pd.read_excel(file_path, header=None)
                            
                            # Tương tự như CSV
                            if len(df.columns) >= 6:
                                df.columns = ['date', 'time_str', 'open', 'high', 'low', 'close', 'volume'][:len(df.columns)]
                                df['time'] = pd.to_datetime(df['date'].astype(str) + ' ' + df['time_str'].astype(str), 
                                                           errors='coerce', format='%Y.%m.%d %H:%M')
                                df = df.drop(['date', 'time_str'], axis=1)
                            else:
                                print(f"   ⚠️ Unexpected Excel format, columns: {len(df.columns)}")
                                continue
                    else:
                        continue
                    
                    # Đảm bảo có cột time và dữ liệu hợp lệ
                    if 'time' not in df.columns:
                        print(f"   ❌ No valid time column found")
                        continue
                    
                    # Filter theo range
                    df = df.dropna(subset=['time'])
                    
                    if len(df) == 0:
                        print(f"   ⚠️ No valid time data after parsing")
                        continue
                        
                    df = df[(df['time'] >= from_datetime) & (df['time'] <= to_datetime)]
                    
                    if len(df) > 0:
                        all_dataframes.append(df)
                        print(f"   ✅ Found {len(df)} records in range")
                    else:
                        print(f"   ⚠️ No records in range")
                        
                except Exception as e:
                    print(f"   ❌ Error loading {file_path}: {e}")
                    import traceback
                    print(f"   📄 Details: {traceback.format_exc()}")
            
            if all_dataframes:
                print(f"📊 Processing {len(all_dataframes)} dataframes...")
                
                # Combine all data
                combined_df = pd.concat(all_dataframes, ignore_index=True)
                combined_df = combined_df.drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
                
                print(f"✅ Combined {len(combined_df)} total M1 records for {symbol}")
                print(f"📊 Combined data columns: {list(combined_df.columns)}")
                print(f"📊 Combined data sample:\n{combined_df.head(3)}")
                
                # Resample dữ liệu theo timeframe đã chọn
                final_df = self._resample_to_timeframe(combined_df, timeframe)
                
                print(f"📊 Final data: {len(final_df)} {timeframe} records")
                print(f"📊 Final data columns: {list(final_df.columns)}")
                print(f"📊 Final data sample:\n{final_df.head(3)}")
                
                print("🎯 Calling _populate_preview_table...")
                self._populate_preview_table(final_df, symbol, timeframe)
                self._current_preview_data = final_df
                
                # Thông tin cho dataInfoLabel - hiển thị với format mới  
                first_time = final_df['time'].iloc[0].strftime('%Y-%m-%d %H:%M')
                last_time = final_df['time'].iloc[-1].strftime('%Y-%m-%d %H:%M')
                
                info_text = f"✅ Data Summary: {symbol} {timeframe} | {len(final_df):,} records | {first_time} → {last_time}"
                print(f"📝 Setting dataInfoLabel: {info_text}")
                self.dataInfoLabel.setText(info_text)
                
                print("✅ _load_import_data_with_range completed successfully")
            else:
                print("❌ No dataframes found - clearing preview table")
                self._clear_preview_table()
                
                # Thông báo chi tiết hơn về lý do không có dữ liệu
                error_msg = "❌ No data found in specified range"
                
                # Nếu có file nhưng không có data sau filtering, hiển thị thông tin chi tiết
                if hasattr(self, 'import_file_paths') and self.import_file_paths:
                    try:
                        # Thử load một file để xem có dữ liệu gì không
                        sample_file = self.import_file_paths[0]
                        if sample_file.endswith('.csv'):
                            df_sample = pd.read_csv(sample_file, nrows=100)
                            if len(df_sample) > 0:
                                # Tìm cột time
                                time_col = None
                                for col in df_sample.columns:
                                    if 'datetime' in col.lower() or 'time' in col.lower():
                                        time_col = col
                                        break
                                
                                if time_col:
                                    df_sample['time_parsed'] = pd.to_datetime(df_sample[time_col], errors='coerce')
                                    valid_times = df_sample['time_parsed'].dropna()
                                    if len(valid_times) > 0:
                                        data_start = valid_times.min().strftime('%Y-%m-%d')
                                        data_end = valid_times.max().strftime('%Y-%m-%d')
                                        error_msg += f"\n📅 Data available: {data_start} to {data_end}"
                                        
                                        # So sánh với user range
                                        from_date_qt = self.fromDateEdit.date()
                                        to_date_qt = self.toDateEdit.date()
                                        user_start = f"{from_date_qt.year()}-{from_date_qt.month():02d}-{from_date_qt.day():02d}"
                                        user_end = f"{to_date_qt.year()}-{to_date_qt.month():02d}-{to_date_qt.day():02d}"
                                        error_msg += f"\n📅 Requested: {user_start} to {user_end}"
                    except Exception as e:
                        print(f"Error checking data range: {e}")
                
                self.dataInfoLabel.setText(error_msg)
                
        except Exception as e:
            print(f"Load import with range error: {e}")
            self._clear_preview_table()
            self.dataInfoLabel.setText(f"❌ Error: {str(e)}")

    def on_view_details_clicked(self):
        """Xử lý khi nhấn nút View Details."""
        try:
            if self._current_preview_data is None or len(self._current_preview_data) == 0:
                show_message("Warning", "No data available to view details")
                return
            
            # Tạo HistoryDialog với custom layout
            history_dialog = QtWidgets.QDialog()
            history_dialog.setWindowTitle("Trade History")
            history_dialog.setModal(True)
            history_dialog.resize(1000, 600)
            
            # Tạo layout chính
            main_layout = QVBoxLayout(history_dialog)
            
            # Thêm Save button nếu ở chế độ Backtest
            if self.data_mode == "Backtest":
                # Tạo layout cho buttons
                button_layout = QHBoxLayout()
                
                # Tạo Save button
                save_button = QPushButton("💾 Save Data")
                save_button.setStyleSheet("""
                    QPushButton {
                        background-color: #4CAF50;
                        color: white;
                        border: none;
                        padding: 8px 16px;
                        font-size: 14px;
                        font-weight: bold;
                        border-radius: 4px;
                    }
                    QPushButton:hover {
                        background-color: #45a049;
                    }
                    QPushButton:pressed {
                        background-color: #3d8b40;
                    }
                """)
                save_button.clicked.connect(lambda: self.save_trade_history_data(self._current_preview_data))
                
                # Thêm button và spacer
                button_layout.addWidget(save_button)
                button_layout.addStretch()  # Push button to left
                
                # Thêm button layout vào main layout
                main_layout.addLayout(button_layout)
            
            # Tạo table view
            table_view = QtWidgets.QTableView()
            
            # Tạo model từ dữ liệu hiện tại
            model = HistoryTableModel(self._current_preview_data)
            table_view.setModel(model)
            
            # Thêm table vào layout
            main_layout.addWidget(table_view)
            
            # Hiển thị dialog
            history_dialog.exec_()
            
        except Exception as e:
            print(f"View details error: {e}")
            show_message("Error", f"Failed to open details: {str(e)}")

    def save_trade_history_data(self, data):
        """Lưu dữ liệu trade history vào file do user chọn."""
        try:
            if data is None or len(data) == 0:
                QMessageBox.warning(None, "Warning", "No data to save!")
                return
            
            # Mở file dialog để chọn nơi lưu
            file_dialog = QFileDialog()
            file_path, _ = file_dialog.getSaveFileName(
                None,
                "Save Trade History", 
                "trade_history.csv",  # Default filename
                "CSV files (*.csv);;Excel files (*.xlsx);;All files (*.*)"
            )
            
            if file_path:  # User đã chọn file
                try:
                    import pandas as pd
                    
                    # Convert data to DataFrame nếu chưa phải
                    if isinstance(data, list):
                        df = pd.DataFrame(data)
                    else:
                        df = data
                    
                    # Xác định format file dựa trên extension
                    if file_path.lower().endswith('.xlsx'):
                        # Lưu as Excel
                        df.to_excel(file_path, index=False)
                        file_type = "Excel"
                    else:
                        # Lưu as CSV (default)
                        if not file_path.lower().endswith('.csv'):
                            file_path += '.csv'  # Thêm .csv extension nếu chưa có
                        df.to_csv(file_path, index=False, encoding='utf-8')
                        file_type = "CSV"
                    
                    # Hiển thị thông báo thành công
                    QMessageBox.information(
                        None, 
                        "Save Complete", 
                        f"✅ Trade history saved successfully!\n\n"
                        f"File: {file_path}\n"
                        f"Format: {file_type}\n"
                        f"Records: {len(df)} rows"
                    )
                    
                    print(f"✅ Trade history saved: {file_path} ({len(df)} records)")
                    
                except Exception as save_error:
                    QMessageBox.critical(
                        None,
                        "Save Error", 
                        f"❌ Could not save file!\n\nError: {str(save_error)}"
                    )
                    print(f"❌ Save error: {save_error}")
        
        except Exception as e:
            QMessageBox.critical(
                None,
                "Error", 
                f"❌ An error occurred while saving!\n\nError: {str(e)}"
            )
            print(f"❌ Save dialog error: {e}")

    def on_ds_import_clicked(self):
        """Xử lý khi chọn Import CSV folders."""
        try:
            print("Data source changed to: Import CSV folders")
            
            # Đã được xử lý trong _sync_date_inputs_visibility(), không cần làm gì thêm
            # Chỉ log để theo dõi
            print("Import mode activated - preview cleared by sync function")
                
        except Exception as e:
            print(f"Import radio button error: {e}")

    def on_ds_api_clicked(self):
        """Xử lý khi chọn Fetch MT5 history."""
        try:
            print("Data source changed to: Fetch MT5 history")
            
            # Đã được xử lý trong _sync_date_inputs_visibility(), không cần làm gì thêm  
            # Chỉ log để theo dõi
            print("MT5 fetch mode activated - preview cleared by sync function")
                
        except Exception as e:
            print(f"API radio button error: {e}")


    def retranslateUi(self, TradeDialog):
        _translate = QtCore.QCoreApplication.translate
        TradeDialog.setWindowTitle(_translate("TradeDialog", "Trade"))
        self.tradeBalance_label.setText(_translate("TradeDialog", "Balance:"))
        self.tradeAutoLot_radioButton.setText(_translate("TradeDialog", "Auto"))
        self.tradeManualLot_radioButton.setText(_translate("TradeDialog", "Manual"))
        self.radioSelfTrain.setText(_translate("TradeDialog", "SELF-TRAIN"))
        self.radioAIModel.setText(_translate("TradeDialog", "AI MODEL"))
        self.aiName_label.setText(_translate("TradeDialog", "AI Name:"))
        self.aiKey_label.setText(_translate("TradeDialog", "AI Key:"))
        self.rr_label.setText(_translate("TradeDialog", "R:R"))
        self.maxloss_label.setText(_translate("TradeDialog", "Max loss:"))
        self.tradeSymbol_label.setText(_translate("TradeDialog", "Symbol:"))
        self.timeframe_label.setText(_translate("TradeDialog", "Timeframe:"))
        self.tradeLot_label.setText(_translate("TradeDialog", "Lot Size:"))
        self.tradeAddSymbol_pushButton.setText(_translate("TradeDialog", "Add"))
        self.tradeDeleteSymbol_pushButton.setText("Delete")
        self.tradeEditSymbol_pushButton.setText(_translate("TradeDialog", "Edit"))
        if self.data_mode == "Backtest":
            self.balance_currentLabel.setText(_translate("balance_current","Backtest mode: nhập Balance tuỳ ý"))
        else:
            self.balance_currentLabel.setText(_translate("balance_current",f"Ví hiện có:  {self.balance} USD"))
        

    def add_new_row(self):
        # Thêm dữ liệu vào QTableWidget
        row_count = self.tradeSymbolPicked_tableWidget.rowCount()
        selected_value = self.tradeSymbol_comboBox.currentText()
        for row in range(row_count):
            item = self.tradeSymbolPicked_tableWidget.item(row, 0)
            existing_symbol = item.text() if item else ""
            if existing_symbol == selected_value:
                show_message("Warning", f"Symbol '{selected_value}' đã tồn tại trong bảng.")
                return
          # Thêm một hàng mới

    # Logic để thêm một hàng mới
        is_valid = self.validate_balance_input()
        
        if is_valid != 3:
            if is_valid == 0:
                show_message("Error", "Balance input is empty.")
            elif is_valid == 1:
                show_message("Error", "Invalid number format.")
            elif is_valid == 2:
                show_message("Error", "Số tiền phải nhỏ hơn hoặc bằng số tiền trong tài khoản.")
            self.tradeBalanc_textEdit.setFocus()
            return
        else:
            valid_balance = self.tradeBalanc_textEdit.text()
            
            # Kiểm tra có phải Agent AI mode không - bypass is_run() vì Agent AI có SL/TP cố định
            use_agent_ai = self.data_mode == "Backtest" and hasattr(self, 'radioAgentAI') and self.radioAgentAI.isChecked()
            
            if use_agent_ai:
                # Agent AI mode: Chỉ kiểm tra balance hợp lệ, không cần kiểm tra margin
                show_message("Success", f"Số tiền hợp lệ: {valid_balance}. Agent AI Backtest được chấp nhận.")
            else:
                # Predictive AI / Real-time mode: Kiểm tra margin như bình thường
                flag = self.is_run()
                
                if flag == 0:
                    show_message("Warning", "Không đủ số tiền để giao dịch. Vui lòng thay đổi số lot hoặc đòn bẩy.")
                    self.tradeBalanc_textEdit.setFocus()
                    return
                elif flag == 0.5:
                    show_message("Warning", "Rủi ro cao.")
                else:
                    show_message("Success", f"Số tiền hợp lệ: {valid_balance}. Giao dịch được chấp nhận.")
            
            # Gọi phương thức gốc để xử lý các sự kiện khá
        text = self.tradeBalanc_textEdit.text()
        value=float(text)
        self.balance-=value
        lot_size = self.tradeLot_spinBox.value()  # Giả định bạn có một spinbox để nhập Lot size
        self.balance_currentLabel.setText(f"Ví hiện có: {self.balance} USD")

       
        # Điền dữ liệu vào hàng mới
        self.tradeSymbolPicked_tableWidget.insertRow(row_count)
        current_tf = self.timeframe_comboBox.currentText()
        lot_size = self.tradeLot_spinBox.value()
        
        # Kiểm tra có phải Agent AI mode không (cho cả Backtest và Real-time)
        use_agent_ai = hasattr(self, 'radioAgentAI') and self.radioAgentAI.isChecked()
        
        if use_agent_ai:
            # Agent AI mode
            # Symbol
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 0, QtWidgets.QTableWidgetItem(selected_value))
            # Timeframe
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 1, QtWidgets.QTableWidgetItem(current_tf))
            # Balance
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 2, QtWidgets.QTableWidgetItem(f"{value:.2f}"))
            # Lot size - Agent AI sử dụng lot size cố định từ spinbox
            lot_display = f"{lot_size}"
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 3, QtWidgets.QTableWidgetItem(lot_display))
            # AI Type - hiển thị "Agent AI"
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 4, QtWidgets.QTableWidgetItem("Agent AI"))
            
            # Chỉ có Backtest mode mới có cột Size_data và Type_Data
            if self.data_mode == "Backtest":
                # Size_data
                size_text = str(len(self._current_preview_data)) if getattr(self, '_current_preview_data', None) is not None else ""
                self.tradeSymbolPicked_tableWidget.setItem(row_count, 5, QtWidgets.QTableWidgetItem(size_text))
                # Type_Data: 'MT5' nếu chọn Fetch MT5, ngược lại 'Import'
                type_text = ""
                try:
                    if hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked():
                        type_text = "MT5"
                    elif hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked():
                        type_text = "Import"
                except Exception:
                    type_text = ""
                self.tradeSymbolPicked_tableWidget.setItem(row_count, 6, QtWidgets.QTableWidgetItem(type_text))
            # Real-time mode chỉ có 5 cột (Symbol, Timeframe, Balance, Lot size, AI Type) - không cần thêm gì
        else:
            # Predictive AI mode (giữ nguyên logic cũ)
            # Symbol
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 0, QtWidgets.QTableWidgetItem(selected_value))
            # Timeframe
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 1, QtWidgets.QTableWidgetItem(current_tf))
            # Balance, Lot size
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 2, QtWidgets.QTableWidgetItem(f"{value:.2f}"))
            # Hiển thị "auto" nếu chọn Auto mode, ngược lại hiển thị lot size
            lot_display = "auto" if self.tradeAutoLot_radioButton.isChecked() else f"{lot_size}"
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 3, QtWidgets.QTableWidgetItem(lot_display))
            # Hiển thị ở cột AI: nếu chọn AI MODEL thì hiển thị AI Name; ngược lại ghi 'self_training'
            if self.radioAIModel.isChecked():
                ai_text = self.aiName_edit.text().strip() or 'ai_model'
            else:
                ai_text = 'self_training'
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 4, QtWidgets.QTableWidgetItem(ai_text))
            # Cột R:R và Max loss (chỉ hiển thị khi AI MODEL; SELF-TRAIN thì để rỗng)
            rr_display = f"{self.rr_edit.value():.2f}" if self.radioAIModel.isChecked() else ""
            maxloss_display = f"{self.maxloss_edit.value():.1f} %" if self.radioAIModel.isChecked() else ""
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 5, QtWidgets.QTableWidgetItem(rr_display))
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 6, QtWidgets.QTableWidgetItem(maxloss_display))
            # Cột Max Loss/Trade (chỉ hiển thị khi Auto mode)
            max_loss_per_trade_display = f"{self.maxLossPerTrade_spinBox.value():.2f}" if self.tradeAutoLot_radioButton.isChecked() else ""
            self.tradeSymbolPicked_tableWidget.setItem(row_count, 7, QtWidgets.QTableWidgetItem(max_loss_per_trade_display))
            # Cột Size_data ở cuối nếu Backtest
            if self.data_mode == "Backtest":
                size_text = str(len(self._current_preview_data)) if getattr(self, '_current_preview_data', None) is not None else ""
                self.tradeSymbolPicked_tableWidget.setItem(row_count, 8, QtWidgets.QTableWidgetItem(size_text))
                # Type_Data: 'MT5' nếu chọn Fetch MT5, ngược lại 'Import'
                type_text = ""
                try:
                    if hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked():
                        type_text = "MT5"
                    elif hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked():
                        type_text = "Import"
                except Exception:
                    type_text = ""
                self.tradeSymbolPicked_tableWidget.setItem(row_count, 9, QtWidgets.QTableWidgetItem(type_text))
        
        # Lưu AI Key cho row này nếu đang ở AI Model mode
        if self.radioAIModel.isChecked():
            ai_key = self.aiKey_edit.text().strip()
            if ai_key:
                self._row_ai_keys[row_count] = ai_key
                print(f"Saved AI Key for row {row_count}")
        
        # Lưu data vào cache với key (symbol, timeframe) khi Add thành công
        if hasattr(self, '_current_preview_data') and self._current_preview_data is not None:
            cache_key = (selected_value, current_tf)
            self._full_history_cache[cache_key] = self._current_preview_data.copy()
            
            # Cache riêng theo symbol cho Backtest mode
            if self.data_mode == "Backtest":
                self._symbol_data_cache[selected_value] = self._current_preview_data.copy()
                print(f"💾 Cached symbol data for Backtest: {selected_value} - {len(self._current_preview_data)} rows")
            
            print(f"💾 Cached data for {selected_value} {current_tf} - {len(self._current_preview_data)} rows")
        else:
            print(f"⚠️ No preview data to cache for {selected_value} {current_tf}")
        
        #Xóa hết data khi nhấn nút Add thành công
        self.back_tradeDialog_Add()

    def edit_selected_row(self):
        """Chỉnh sửa hàng được chọn trong bảng."""
        # Lấy chỉ số hàng đang được chọn
        selected_row = self.tradeSymbolPicked_tableWidget.currentRow()

        if selected_row == -1:  # Nếu không có hàng nào được chọn
            show_message("Warning", "Vui lòng chọn một hàng để chỉnh sửa.")
            return

        # Ẩn combobox Symbol và hiển thị tên Symbol
        symbol_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 0)
        timeframe_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 1)
        balance_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 2)
        lot_size_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 3)
        ai_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 4)
        rr_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 5)
        maxloss_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 6)

        if not (symbol_item and timeframe_item and balance_item and lot_size_item):
            show_message("Error", "Không thể chỉnh sửa dữ liệu. Hàng có giá trị trống.")
            return

        symbol = symbol_item.text()
        timeframe = timeframe_item.text()
        balance_symbol = balance_item.text()
        lot_size = lot_size_item.text()
        ai_mode = ai_item.text() if ai_item else "self_training"
        rr_value = rr_item.text() if rr_item else ""
        maxloss_value = maxloss_item.text() if maxloss_item else ""
        
        self.balance+=float(balance_symbol)
        self.balance_currentLabel.setText(f"Ví hiện có: {self.balance} USD")

        # Set symbol vào combobox trước khi ẩn nó
        symbol_index = self.tradeSymbol_comboBox.findText(symbol)
        if symbol_index >= 0:
            self.tradeSymbol_comboBox.setCurrentIndex(symbol_index)
            print(f"Set combobox symbol to: {symbol}")
        else:
            print(f"⚠️ Symbol {symbol} not found in combobox")

        # Hiển thị tên Symbol trong QLabel thay vì combobox
        self.symbol_label = QtWidgets.QLabel(self.tradeContent_frame)
        self.symbol_label.setText(symbol)
        self.symbol_label.setGeometry(self.tradeSymbol_comboBox.geometry())
        self.symbol_label.show()
        font = QtGui.QFont()
        font.setPointSize(12)
        font.setBold(True)
        font.setWeight(75)
        self.symbol_label.setFont(font)
        #Hiển thị nút Back
        self.button_back = QtWidgets.QPushButton(self.tradeContent_frame)
        self.button_back.setText("Back")
        self.button_back.setGeometry(self.tradeAddSymbol_pushButton.geometry())
        self.button_back.show()
        ##Sự kiện clicked nút Back
        self.button_back.clicked.connect(self.back_tradeDialog_EditSave)
        ##Hiển thị nút save edit
        self.saveEdit_button = QtWidgets.QPushButton(self.tradeContent_frame)
        self.saveEdit_button.setText("Save Edit")
        self.saveEdit_button.setGeometry(self.tradeEditSymbol_pushButton.geometry())
        self.saveEdit_button.show()
        ##Sự kiện clicked nút saveEdit
        self.saveEdit_button.clicked.connect(self.save_edited_row)


        # Ẩn các biến không liên quan 
        self.tradeSymbol_comboBox.hide()
        self.tradeAddSymbol_pushButton.hide()
        self.tradeDeleteSymbol_pushButton.hide()
        self.tradeSymbolPicked_tableWidget.hide()
        self.trade_buttonBox.hide()
        self.tradeEditSymbol_pushButton.hide()

        # Set giá trị Balance và Lot size vào các ô text
        self.balance_edit=float(balance_symbol)
        self.tradeBalanc_textEdit.setText(balance_symbol)
        
        # Set lot size - GIỮ NGUYÊN giá trị từ hàng được chọn
        original_lot_size = float(lot_size)
        print(f"🎯 EDIT MODE: Setting lot size to original value: {original_lot_size}")
        
        # SET LOT SIZE TRƯỚC KHI SET SYMBOL/TIMEFRAME để tránh bị override
        self.tradeLot_spinBox.setValue(original_lot_size)
        print(f"✅ Lot spinbox value set to: {self.tradeLot_spinBox.value()}")
        
        # Determine lot mode - nếu lot size là symbol minimum thì có thể là Auto, ngược lại là Manual
        is_auto_mode = False
        if not self._is_btc_symbol(symbol):
            try:
                if mt5.initialize():
                    symbol_info = mt5.symbol_info(symbol)
                    if symbol_info is not None:
                        # Nếu lot size bằng volume_min thì có thể là Auto mode
                        if abs(original_lot_size - symbol_info.volume_min) < 0.001:
                            is_auto_mode = True
                            print(f"Detected Auto mode for {symbol} (lot = {original_lot_size}, min = {symbol_info.volume_min})")
                    mt5.shutdown()
            except Exception as e:
                print(f"Error checking symbol info for lot mode: {e}")
        
        # Set lot mode dựa trên phân tích  
        if is_auto_mode:
            self.tradeAutoLot_radioButton.setChecked(True)
            self.tradeManualLot_radioButton.setChecked(False)
            self.tradeLot_spinBox.setEnabled(False)
            print("Set lot mode to: Auto")
        else:
            self.tradeManualLot_radioButton.setChecked(True)
            self.tradeAutoLot_radioButton.setChecked(False)
            self.tradeLot_spinBox.setEnabled(True)
            print("Set lot mode to: Manual")
            
        # KIỂM TRA LOT SIZE SAU KHI SET MODE
        current_lot_after_mode = self.tradeLot_spinBox.value()
        print(f"📊 Lot size after setting mode: {current_lot_after_mode}")
        if abs(current_lot_after_mode - original_lot_size) > 0.001:
            print(f"⚠️ WARNING: Lot size changed from {original_lot_size} to {current_lot_after_mode}")
            # Restore lại lot size
            self.tradeLot_spinBox.setValue(original_lot_size)
            print(f"🔧 Restored lot size to: {original_lot_size}")

        # Set Timeframe
        print(f"🔄 Setting timeframe to: {timeframe}")
        timeframe_index = self.timeframe_comboBox.findText(timeframe)
        if timeframe_index >= 0:
            current_lot_before_tf = self.tradeLot_spinBox.value()
            print(f"📊 Lot size before setting timeframe: {current_lot_before_tf}")
            
            self.timeframe_comboBox.setCurrentIndex(timeframe_index)
            print(f"Set timeframe to: {timeframe}")
            
            current_lot_after_tf = self.tradeLot_spinBox.value()
            print(f"📊 Lot size after setting timeframe: {current_lot_after_tf}")
            if abs(current_lot_after_tf - original_lot_size) > 0.001:
                print(f"⚠️ WARNING: Timeframe change modified lot size from {original_lot_size} to {current_lot_after_tf}")
                # Restore lại lot size
                self.tradeLot_spinBox.setValue(original_lot_size)
                print(f"🔧 Restored lot size after timeframe change to: {original_lot_size}")
        
        # Set AI Mode và các giá trị liên quan
        if ai_mode.lower() in ['self_training', 'default']:
            self.radioSelfTrain.setChecked(True)
            self.radioAIModel.setChecked(False)
            print("Set AI mode to: SELF-TRAIN")
        else:
            # AI Model mode - ai_mode là tên AI
            self.radioAIModel.setChecked(True)
            self.radioSelfTrain.setChecked(False)
            self.aiName_edit.setText(ai_mode)
            print(f"Set AI mode to: AI MODEL with name: {ai_mode}")
            
            # Set R:R value
            if rr_value:
                try:
                    rr_float = float(rr_value)
                    self.rr_edit.setValue(rr_float)
                    print(f"Set R:R to: {rr_float}")
                except ValueError:
                    print(f"Invalid R:R value: {rr_value}")
            
            # Set Max Loss value
            if maxloss_value:
                try:
                    # Remove % sign if present
                    maxloss_clean = maxloss_value.replace('%', '').strip()
                    if maxloss_clean:
                        maxloss_float = float(maxloss_clean)
                        self.maxloss_edit.setValue(maxloss_float)
                        print(f"Set Max Loss to: {maxloss_float}%")
                except ValueError:
                    print(f"Invalid Max Loss value: {maxloss_value}")
        
        # Trigger AI mode change để show/hide các controls
        self.on_ai_mode_changed()
        
        # Restore AI Key nếu có
        if selected_row in self._row_ai_keys:
            saved_ai_key = self._row_ai_keys[selected_row]
            self.aiKey_edit.setText(saved_ai_key)
            print(f"Restored AI Key for row {selected_row}")
        else:
            self.aiKey_edit.clear()
            print(f"No saved AI Key for row {selected_row}")

        # Thêm trạng thái chỉnh sửa
        self.current_editing_row = selected_row
        
        # CẬP NHẬT DATA PREVIEW TABLE VÀ DSGROUP COMPONENTS
        # 1. Cập nhật symbol search box
        if hasattr(self, 'symbolSearch_lineEdit'):
            self.symbolSearch_lineEdit.setText(symbol)
            print(f"Set symbol search to: {symbol}")
        
        # 2. Populate symbol combo theo search keyword
        print(f"🔄 Populating symbol combo - temporarily disconnecting change event")
        # Temporarily disconnect combo change event để tránh trigger khi populate
        try:
            self.tradeSymbol_comboBox.currentTextChanged.disconnect()
            print("📤 Disconnected symbol combo change event")
        except:
            print("📤 No combo change event to disconnect")
        
        try:
            self.populate_trade_symbol_combo(symbol.lower())
            print(f"Populated symbol combo with keyword: {symbol.lower()}")
        except Exception as e:
            print(f"Error populating symbol combo: {e}")
        
        # 3. Set lại symbol trong combo (sau khi populate)  
        print(f"🔄 Setting symbol combo...")
        current_lot_before_symbol = self.tradeLot_spinBox.value()
        print(f"📊 Lot size before setting symbol combo: {current_lot_before_symbol}")
        
        symbol_index = self.tradeSymbol_comboBox.findText(symbol)
        if symbol_index >= 0:
            self.tradeSymbol_comboBox.setCurrentIndex(symbol_index)
            print(f"Re-set symbol combo to: {symbol}")
        
        # Reconnect combo change event
        try:
            self.tradeSymbol_comboBox.currentTextChanged.connect(self.on_combobox_changed)
            print("📥 Reconnected symbol combo change event")
        except:
            print("📥 Error reconnecting combo change event")
            
        # Kiểm tra lot size sau khi set symbol combo
        current_lot_after_symbol = self.tradeLot_spinBox.value()
        print(f"📊 Lot size after setting symbol combo: {current_lot_after_symbol}")
        if abs(current_lot_after_symbol - original_lot_size) > 0.001:
            print(f"⚠️ WARNING: Symbol combo change modified lot size from {original_lot_size} to {current_lot_after_symbol}")
            # Restore lại lot size
            self.tradeLot_spinBox.setValue(original_lot_size)
            print(f"🔧 Restored lot size after symbol combo change to: {original_lot_size}")
            
            # Cũng cần restore lot mode
            if is_auto_mode:
                self.tradeAutoLot_radioButton.setChecked(True)
                self.tradeManualLot_radioButton.setChecked(False)
                self.tradeLot_spinBox.setEnabled(False)
                print("🔧 Restored lot mode to: Auto")
            else:
                self.tradeManualLot_radioButton.setChecked(True)
                self.tradeAutoLot_radioButton.setChecked(False)
                self.tradeLot_spinBox.setEnabled(True)
                print("🔧 Restored lot mode to: Manual")
        
        # 4. Trigger load lại dữ liệu cho symbol/timeframe được chọn
        if self.data_mode == "Backtest":
            print(f"Loading data for selected row (Backtest) - Symbol: {symbol}, Timeframe: {timeframe}")
            
            # 5. Lấy thông tin Type_Data và Size_Data từ table (nếu có)
            type_data = ""
            size_data = ""
            if self.tradeSymbolPicked_tableWidget.columnCount() > 8:
                type_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 8)  # Type_Data
                if type_item:
                    type_data = type_item.text()
                    
            if self.tradeSymbolPicked_tableWidget.columnCount() > 7:
                size_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 7)  # Size_Data
                if size_item:
                    size_data = size_item.text()
                    
            print(f"Row data - Type: {type_data}, Size: {size_data}")
            
            # 6. Set data source radio button dựa trên Type_Data
            if type_data == "MT5":
                if hasattr(self, 'dsApiRadio'):
                    self.dsApiRadio.setChecked(True)
                    print("Set data source to: MT5 API")
            elif type_data == "Import":
                if hasattr(self, 'dsImportRadio'):
                    self.dsImportRadio.setChecked(True)
                    print("Set data source to: Import")
            
            # 7. Load dữ liệu từ cache cho symbol/timeframe nếu có
            cache_key = (symbol, timeframe)
            if cache_key in self._full_history_cache:
                cached_df = self._full_history_cache[cache_key].copy()
                self._current_preview_data = cached_df
                print(f"📦 Loaded cached data for editing: {symbol} {timeframe} - {len(cached_df)} rows")
                
                # Update preview table với data từ cache
                try:
                    self._populate_preview_table(cached_df, symbol, timeframe)
                    print("✅ Updated preview table with cached data")
                except Exception as e:
                    print(f"❌ Error updating preview table: {e}")
                
                # 8. Set From/To date time từ data đầu và cuối của cached data
                if len(cached_df) > 0 and 'time' in cached_df.columns:
                    try:
                        # DISCONNECT date validation để tránh warning khi set date từ cached data
                        print("🔇 Temporarily disconnecting date validation for edit mode")
                        self._disconnect_date_validation()
                        
                        # Lấy time đầu tiên và cuối cùng từ cached data
                        first_time = cached_df['time'].iloc[0]
                        last_time = cached_df['time'].iloc[-1]
                        
                        print(f"Setting date range from cached data: {first_time} to {last_time}")
                        
                        # Convert to QDate và QTime
                        if hasattr(self, 'fromDateEdit'):
                            from_qdate = QDate(first_time.year, first_time.month, first_time.day)
                            self.fromDateEdit.setDate(from_qdate)
                            print(f"Set From Date to: {first_time.date()}")
                        
                        if hasattr(self, 'toDateEdit'):
                            to_qdate = QDate(last_time.year, last_time.month, last_time.day)
                            self.toDateEdit.setDate(to_qdate)
                            print(f"Set To Date to: {last_time.date()}")
                        
                        # Set time nếu có time controls
                        if hasattr(self, 'fromTimeEdit'):
                            from_qtime = QTime(first_time.hour, first_time.minute, first_time.second)
                            self.fromTimeEdit.setTime(from_qtime)
                            print(f"Set From Time to: {first_time.time()}")
                        
                        if hasattr(self, 'toTimeEdit'):
                            to_qtime = QTime(last_time.hour, last_time.minute, last_time.second)
                            self.toTimeEdit.setTime(to_qtime)
                            print(f"Set To Time to: {last_time.time()}")
                        
                        # RECONNECT date validation sau khi set xong
                        print("🔊 Reconnecting date validation after setting cached data")
                        self._connect_date_validation()
                            
                        # Update data info label
                        if hasattr(self, 'dataInfoLabel'):
                            first_time_str = first_time.strftime('%Y-%m-%d %H:%M')
                            last_time_str = last_time.strftime('%Y-%m-%d %H:%M')
                            self.dataInfoLabel.setText(
                                f"✅ Data Summary: {symbol} {timeframe} | {len(cached_df):,} records | {first_time_str} → {last_time_str}"
                            )
                            
                    except Exception as e:
                        print(f"❌ Error setting date/time from cached data: {e}")
                        # Đảm bảo reconnect validation ngay cả khi có lỗi
                        try:
                            self._connect_date_validation()
                            print("🔊 Reconnected date validation after error")
                        except Exception as reconnect_error:
                            print(f"❌ Error reconnecting date validation: {reconnect_error}")
                
            else:
                print(f"⚠️ No cached data found for {symbol} {timeframe}")
                # Clear preview table và hiển thị message
                self._clear_preview_table()
                if hasattr(self, 'dataInfoLabel'):
                    self.dataInfoLabel.setText(f"⚠️ No cached data available for {symbol} {timeframe}. Please use 'Xem dữ liệu' to load data first.")
                    
        elif self.data_mode == "Live Trade":
            print(f"Selected row for edit (Live Trade) - Symbol: {symbol}, Timeframe: {timeframe}")
            # Trong Live Trade mode, không cần load historical data cho preview table
            # Chỉ cần update symbol combo
            print("Live Trade mode - symbol combo updated only")
        
        # FINAL CHECK: Đảm bảo lot size được preserve
        final_lot_size = self.tradeLot_spinBox.value()
        print(f"🔍 FINAL CHECK: Current lot size: {final_lot_size}, Original: {original_lot_size}")
        if abs(final_lot_size - original_lot_size) > 0.001:
            print(f"🚨 CRITICAL: Lot size was modified during edit setup! Restoring...")
            self.tradeLot_spinBox.setValue(original_lot_size)
            
            # Restore lot mode cũng
            if is_auto_mode:
                self.tradeAutoLot_radioButton.setChecked(True)
                self.tradeManualLot_radioButton.setChecked(False)
                self.tradeLot_spinBox.setEnabled(False)
                print("🔧 FINAL: Restored lot mode to Auto")
            else:
                self.tradeManualLot_radioButton.setChecked(True)
                self.tradeAutoLot_radioButton.setChecked(False)
                self.tradeLot_spinBox.setEnabled(True)
                print("🔧 FINAL: Restored lot mode to Manual")
                
            print(f"✅ FINAL: Lot size restored to: {self.tradeLot_spinBox.value()}")
        else:
            print(f"✅ FINAL: Lot size preserved correctly: {final_lot_size}")
        
        show_message("Info", f"Đang chỉnh sửa hàng {selected_row + 1}.")


    def delete_selected_row(self):
        """Xóa hàng được chọn trong bảng."""
        # Lấy chỉ số hàng đang được chọn
        selected_row = self.tradeSymbolPicked_tableWidget.currentRow()
        
        if selected_row == -1:  # Nếu không có hàng nào được chọn
            show_message("Warning", "Vui lòng chọn một hàng để xóa.")  # Hiển thị thông báo
            return
            
        # Lấy thông tin symbol trước khi xóa
        symbol_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 0)
        balance_item = self.tradeSymbolPicked_tableWidget.item(selected_row, 2)
        symbol_to_delete = symbol_item.text() if symbol_item else ""
        balance_symbol = balance_item.text() if balance_item else "0"
        # Xác nhận xóa hàng
        reply = QtWidgets.QMessageBox.question(
            self.tradeContent_frame,  # Đặt cha là frame chính
            "Xác nhận xóa",
            f"Bạn có chắc chắn muốn xóa hàng {selected_row + 1} không?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )

        if reply == QtWidgets.QMessageBox.Yes:
            # Xóa AI Key cho row này nếu có
            if selected_row in self._row_ai_keys:
                del self._row_ai_keys[selected_row]
                print(f"Removed AI Key for deleted row {selected_row}")
            
            # Shift các AI Key index sau selected_row xuống 1
            updated_keys = {}
            for row_idx, ai_key in self._row_ai_keys.items():
                if row_idx > selected_row:
                    updated_keys[row_idx - 1] = ai_key  # Shift down by 1
                elif row_idx < selected_row:
                    updated_keys[row_idx] = ai_key  # Keep same index
            self._row_ai_keys = updated_keys
            
            # Xóa cache symbol cho Backtest mode
            if self.data_mode == "Backtest" and symbol_to_delete:
                # Kiểm tra xem còn symbol nào khác giống vậy không trong bảng
                has_duplicate = False
                for row in range(self.tradeSymbolPicked_tableWidget.rowCount()):
                    if row != selected_row:  # Bỏ qua row sắp bị xóa
                        item = self.tradeSymbolPicked_tableWidget.item(row, 0)
                        if item and item.text() == symbol_to_delete:
                            has_duplicate = True
                            break
                
                # Chỉ xóa cache nếu không còn symbol nào khác
                if not has_duplicate and symbol_to_delete in self._symbol_data_cache:
                    del self._symbol_data_cache[symbol_to_delete]
                    print(f"🗑️ Removed symbol cache for: {symbol_to_delete}")
            
            # Xóa hàng được chọn
            self.tradeSymbolPicked_tableWidget.removeRow(selected_row)
            
            self.balance+=float(balance_symbol)
            self.balance_currentLabel.setText(f"Ví hiện có: {self.balance} USD")
            show_message("Success", f"Hàng {selected_row + 1} đã được xóa thành công.")  # Thông báo thành công
        else:
            show_message("Info", "Bạn đã hủy xóa hàng.")  # Thông báo khi người dùng hủy


    def on_ok_button_clicked(self):
        print("🎯 OK button clicked - method called successfully!")  # Debug print
        print(f"💾 Data mode: {self.data_mode}")  # Debug data mode
        
        # Debug: Check data mode and UI state
        print(f"🔘 Current data_mode: {self.data_mode}")
        print(f"🔘 AI Mode - Self Train: {self.radioSelfTrain.isChecked()}")
        print(f"🔘 AI Mode - AI Model: {self.radioAIModel.isChecked()}")
        
        # Debug: Check button box status
        buttons = self.trade_buttonBox.buttons()
        print(f"🔲 ButtonBox has {len(buttons)} buttons")
        for i, btn in enumerate(buttons):
            print(f"   Button {i}: {btn.text()} - Enabled: {btn.isEnabled()}")
        
        data = []
        row_count = self.tradeSymbolPicked_tableWidget.rowCount()
        print(f"📊 Table has {row_count} rows")

        if(row_count>0):
            for row in range(row_count):
                row_data = []
                for col in range(self.tradeSymbolPicked_tableWidget.columnCount()):
                    item = self.tradeSymbolPicked_tableWidget.item(row, col)
                    if item is not None:
                        row_data.append(item.text())
                    else:
                        row_data.append("")  # Nếu ô trống, thêm chuỗi rỗng
                data.append(row_data)
            
            # Khởi tạo arrays cho cả 2 chế độ
            selected_symbols=[]
            selected_timeframes=[]
            selected_balances=[]
            selected_lot_sizes=[]
            selected_ai_modes=[]
            selected_rrs=[]
            selected_maxlosses=[]
            selected_max_loss_per_trades=[]  # Thêm array cho max loss per trade
            
            print(f"🔄 Chế độ hiện tại: {self.data_mode}")
            
            # Xác định trading_type
            trading_type = 'backtest' if self.data_mode == 'Backtest' else 'realtime'
            
            # Kiểm tra có phải Agent AI mode không (cho cả Backtest và Real-time)
            use_agent_ai = hasattr(self, 'radioAgentAI') and self.radioAgentAI.isChecked()
            
            if use_agent_ai:
                # Agent AI mode: Bảng có cấu trúc khác nhau tùy mode
                # Backtest: 7 cột (Symbol, Timeframe, Balance, Lot size, AI Type, Size_data, Type_Data)
                # Real-time: 5 cột (Symbol, Timeframe, Balance, Lot size, AI Type)
                print(f"🤖 Xử lý data theo chế độ Agent AI ({self.data_mode})")
                for row in data:
                    selected_symbols.append(row[0])
                    utils_symbol_csv.update_status(row[0], trading_type)
                    selected_timeframes.append(row[1] if len(row) > 1 else "")
                    
                    balance = float(row[2]) if len(row) > 2 and row[2] else 0.0
                    selected_balances.append(balance)
                    
                    # Lot size - Agent AI sử dụng lot size cố định từ spinbox
                    lot_text = row[3] if len(row) > 3 else ""
                    lot = float(lot_text) if lot_text else 0.01
                    selected_lot_sizes.append(lot)
                    
                    # AI mode = "Agent AI"
                    selected_ai_modes.append(row[4] if len(row) > 4 else "Agent AI")
                    
                    # Agent AI không có RR, Max loss, Max loss per trade
                    selected_rrs.append(None)
                    selected_maxlosses.append(None)
                    selected_max_loss_per_trades.append(None)
                    
                    # Ghi log Backtest: symbol, balance, lot, equity (equity = balance)
                    print(f"📝 Logging Agent AI Backtest: {row[0]}, balance={balance}, lot={lot}, equity={balance}")
                    utils_logs.log_bot_run(row[0], balance, lot, balance, trading_type)
            elif self.data_mode == "Backtest":
                # Chế độ Backtest: Cấu trúc bảng có cột Size_data và Type_Data
                # 0:Symbol, 1:Timeframe, 2:Balance, 3:Lot, 4:AI, 5:RR, 6:Max_loss, 7:Max_Loss/Trade, 8:Size_data, 9:Type_Data
                print("📊 Xử lý data theo chế độ Backtest")
                for row in data:
                    selected_symbols.append(row[0])
                    utils_symbol_csv.update_status(row[0], trading_type)
                    selected_timeframes.append(row[1] if len(row) > 1 else "")
                    
                    balance = float(row[2]) if len(row) > 2 and row[2] else 0.0
                    selected_balances.append(balance)
                    
                    # Xử lý lot size - nếu là "auto" thì dùng giá trị nhỏ nhất
                    lot_text = row[3] if len(row) > 3 else ""
                    if lot_text.lower() == "auto":
                        lot = 0.01  # Placeholder, sẽ được tính lại trong BacktestTradeAI
                    else:
                        lot = float(lot_text) if lot_text else 0.0
                    selected_lot_sizes.append(lot)
                    
                    selected_ai_modes.append(row[4] if len(row) > 4 and row[4] else 'default')
                    
                    # RR và Max loss
                    try:
                        rr_val = float(row[5]) if len(row) > 5 and row[5] else None
                    except Exception:
                        rr_val = None
                    try:
                        ml_text = row[6] if len(row) > 6 else ""
                        max_loss_val = float(ml_text.replace('%','').strip()) if ml_text else None
                    except Exception:
                        max_loss_val = None
                    selected_rrs.append(rr_val)
                    selected_maxlosses.append(max_loss_val)
                    
                    # Max loss per trade (USD)
                    try:
                        mlpt_val = float(row[7]) if len(row) > 7 and row[7] else None
                    except Exception:
                        mlpt_val = None
                    selected_max_loss_per_trades.append(mlpt_val)
                    
                    # Ghi log Backtest: symbol, balance, lot, equity (equity = balance)
                    print(f"📝 Logging Backtest: {row[0]}, balance={balance}, lot={lot}, equity={balance}")
                    utils_logs.log_bot_run(row[0], balance, lot, balance, trading_type)  # equity = balance
            else:
                # Chế độ Real-time: Cấu trúc bảng đơn giản hơn
                # 0:Symbol, 1:Timeframe, 2:Balance, 3:Lot, 4:AI, 5:RR, 6:Max_loss, 7:Max_Loss/Trade
                print("🔴 Xử lý data theo chế độ Real-time")
                for row in data:
                    selected_symbols.append(row[0])
                    utils_symbol_csv.update_status(row[0], trading_type)
                    selected_timeframes.append(row[1] if len(row) > 1 else "")
                    
                    balance = float(row[2]) if len(row) > 2 and row[2] else 0.0
                    selected_balances.append(balance)
                    
                    # Xử lý lot size - nếu là "auto" thì dùng giá trị nhỏ nhất
                    lot_text = row[3] if len(row) > 3 else ""
                    if lot_text.lower() == "auto":
                        lot = 0.01  # Placeholder, sẽ được tính lại trong LiveTradeAI
                    else:
                        lot = float(lot_text) if lot_text else 0.0
                    selected_lot_sizes.append(lot)
                    
                    selected_ai_modes.append(row[4] if len(row) > 4 and row[4] else 'default')
                    
                    # RR và Max loss
                    try:
                        rr_val = float(row[5]) if len(row) > 5 and row[5] else None
                    except Exception:
                        rr_val = None
                    try:
                        ml_text = row[6] if len(row) > 6 else ""
                        max_loss_val = float(ml_text.replace('%','').strip()) if ml_text else None
                    except Exception:
                        max_loss_val = None
                    selected_rrs.append(rr_val)
                    selected_maxlosses.append(max_loss_val)
                    
                    # Max loss per trade (USD)
                    try:
                        mlpt_val = float(row[7]) if len(row) > 7 and row[7] else None
                    except Exception:
                        mlpt_val = None
                    selected_max_loss_per_trades.append(mlpt_val)
                    
                    # Ghi log Real-time: symbol, balance, lot, equity (equity = balance)
                    print(f"📝 Logging Real-time: {row[0]}, balance={balance}, lot={lot}, equity={balance}")
                    utils_logs.log_bot_run(row[0], balance, lot, balance, trading_type)  # equity = balance
            
            
            # Thu thập AI Keys riêng cho từng row
            selected_ai_keys = []
            for row_idx in range(row_count):
                if row_idx in self._row_ai_keys:
                    ai_key = self._row_ai_keys[row_idx]
                    selected_ai_keys.append(ai_key)
                    print(f"🔑 Row {row_idx} has AI Key: {ai_key}")
                else:
                    # Fallback: lấy từ input field nếu không có key riêng
                    fallback_key = self.aiKey_edit.text().strip() if hasattr(self, 'aiKey_edit') else ""
                    selected_ai_keys.append(fallback_key)
                    print(f"🔑 Row {row_idx} using fallback AI Key: {fallback_key}")

            # Chuẩn bị cached data cho Backtest mode
            symbol_cached_data = None
            if self.data_mode == "Backtest":
                symbol_cached_data = self._symbol_data_cache
                print(f"🎯 Passing cached data for {len(symbol_cached_data)} symbols to start_live_traders")
            
            self.start_live_traders(
                selected_symbols,
                selected_balances,
                selected_lot_sizes,
                selected_ai_modes,  # Truyền AI modes từ cột AI trong bảng
                selected_rrs,
                selected_maxlosses,
                selected_timeframes,
                selected_ai_keys,  # Truyền AI Keys riêng cho từng row
                symbol_cached_data,  # Truyền cached data theo symbol
                selected_max_loss_per_trades  # Truyền max loss per trade
            )
            
            
        # Đóng dialog sau khi xử lý xong
        print("🔓 Closing trade dialog...")
        print(f"🔍 Has _dialog attribute: {hasattr(self, '_dialog')}")
        if hasattr(self, '_dialog'):
            print(f"🔍 _dialog exists: {self._dialog is not None}")
        
        if hasattr(self, '_dialog') and self._dialog:
            print("✅ Using _dialog.accept()")
            self._dialog.accept()  # Đóng dialog với accepted state
        else:
            print("✅ Using self.accept() as fallback")
            self.accept()  # Fallback: đóng dialog hiện tại

    def start_live_traders(self, selected_symbols, selected_balances, selected_lot_sizes, selected_ai_modes=None, selected_rrs=None, selected_maxlosses=None, selected_timeframes=None, selected_ai_keys=None, symbol_cached_data=None, selected_max_loss_per_trades=None):
        # Sử dụng cached account info
        account_info = self.get_cached_account_info()
        leverage = 500  # fallback default
        if account_info:
            leverage = account_info.leverage
        model_path=[]
       
        # for symbol in selected_symbols:
        #     if(symbol!=SYMBOLS["BTCUSD"]):
        #         leverage=account_info.leverage
        #         if(symbol==SYMBOLS["XAUUSD"]):
        #             model_path.append("ppo_trading_xauusd.zip") 
        #         else:
        #             model_path.append("ppo_trading_usoilusd.zip")
        #     else:
        #        model_path.append("ppo_trading_btcusd.zip")

        # Khởi tạo BotMonitor (QDialog)
        # monitor = BotMonitor()
        # monitor.show()

        # Sử dụng hàm helper để lấy đường dẫn file CSV với tên có login
        # trade_history_paths = {
        #     SYMBOLS["XAUUSD"]: utils_account.get_trade_history_file_path("XAUUSD"),
        #     SYMBOLS["BTCUSD"]: utils_account.get_trade_history_file_path("BTCUSD"),
        #     SYMBOLS["USOIL"]: utils_account.get_trade_history_file_path("USOIL")
        # }
        
        # print(f"📁 Trade history paths: {trade_history_paths}")
        self.executor = ThreadPoolExecutor(max_workers=len(selected_symbols))

        # Sử dụng AI modes từ cột AI của bảng (đã được xử lý ở trên)
        # selected_ai_modes đã chứa tên AI từ từng row trong bảng
        print(f"🤖 AI modes from table: {selected_ai_modes}")
        timeframe_secs_map = {
            'M1': 60,
            'M5': 300,
            'M15': 900,
            'M30': 1800,
            'H1': 3600,
            'H4': 14400,
            'D1': 86400
        }

        for i in range(0,len(selected_symbols)):
            if self._is_btc_symbol(selected_symbols[i]):
                leverage=400
            else: 
                # Sử dụng cached leverage thay vì gọi account_info lặp lại
                leverage = account_info.leverage if account_info else 500
            # Lấy AI mode từ bảng cho từng symbol
            per_ai = selected_ai_modes[i] if i < len(selected_ai_modes) else 'default'
            print(f"🎯 Symbol {selected_symbols[i]} using AI mode: {per_ai}")
            
            # Kiểm tra có phải Agent AI mode không
            if isinstance(per_ai, str) and per_ai.strip().lower() == 'agent ai':
                # Agent AI mode - sử dụng BacktestAgentAI hoặc RealtimeAgentAI tùy theo mode
                timeframes = timeframe_secs_map.get(selected_timeframes[i])
                print(f"🤖 Khởi động Agent AI bot cho {selected_symbols[i]}")
                print(f"Balance: {selected_balances[i]}, Lot size: {selected_lot_sizes[i]}, Timeframe: {timeframes} sec")
                print(f"📊 Mode: {self.data_mode}")
                print("-----------------------------------------------------")
                
                # Lấy type_account từ MT5 account_info
                # trade_mode: 0 = DEMO, 1 = CONTEST, 2 = REAL
                type_account = "Standard"
                if account_info:
                    trade_mode = getattr(account_info, 'trade_mode', 0)
                    # Kiểm tra tên server hoặc company để xác định loại tài khoản
                    server = getattr(account_info, 'server', '')
                    company = getattr(account_info, 'company', '')
                    
                    # Nếu server/company chứa "Raw" thì là Raw Spread account
                    if 'raw' in server.lower() or 'raw' in company.lower():
                        type_account = "Raw Spread"
                    else:
                        type_account = "Standard"
                    print(f"📊 Account type detected: {type_account} (server: {server})")
                
                if self.data_mode == "Backtest":
                    # Backtest mode - sử dụng BacktestAgentAI với cached data (PyTorch DDQN)
                    current_symbol_data = None
                    if symbol_cached_data and selected_symbols[i] in symbol_cached_data:
                        current_symbol_data = symbol_cached_data[selected_symbols[i]]
                        print(f"🎯 Using cached data for {selected_symbols[i]} - {len(current_symbol_data)} rows")
                    else:
                        print(f"⚠️ No cached data found for {selected_symbols[i]}")
                    
                    # Timeframe in seconds
                    tf_sec = timeframes if timeframes else 60
                    
                    live_trader = BacktestAgentAI(
                        symbol=selected_symbols[i],
                        balance=selected_balances[i],
                        lot_size=selected_lot_sizes[i],
                        type_account=type_account,
                        data=current_symbol_data,
                        model_path="DDQN_TradingAgent/gemini3_vibe_code_AgentMT5/best_model.pth",
                        timeframe_sec=tf_sec
                    )
                else:
                    # Real-time mode - sử dụng RealtimeAgentAI với MT5 API
                    # Convert timeframe string to MT5 timeframe constant
                    tf_str = selected_timeframes[i] if i < len(selected_timeframes) else 'M1'
                    mt5_tf_map = {
                        'M1': mt5.TIMEFRAME_M1,
                        'M5': mt5.TIMEFRAME_M5,
                        'M15': mt5.TIMEFRAME_M15,
                        'M30': mt5.TIMEFRAME_M30,
                        'H1': mt5.TIMEFRAME_H1,
                        'H4': mt5.TIMEFRAME_H4,
                        'D1': mt5.TIMEFRAME_D1
                    }
                    mt5_timeframe = mt5_tf_map.get(tf_str, mt5.TIMEFRAME_M1)
                    
                    print(f"🚀 Starting LiveTradeAgentAI for {selected_symbols[i]} with MT5 timeframe: {tf_str}")
                    print(f"   Balance: ${selected_balances[i]:.2f}, Lot: {selected_lot_sizes[i]}, Account: {type_account}")
                    

                    live_trader = LiveTradeAgentAI(
                            symbol=selected_symbols[i],
                            balance=selected_balances[i],
                            lot_size=selected_lot_sizes[i],
                            type_account=type_account,
                            model_path="DDQN_TradingAgent/gemini3_vibe_code_AgentMT5/best_model.pth",
                            timeframe=mt5_timeframe
                        )
            # Nếu per_ai là tên AI (AI MODEL) → chạy LiveTradeAI/BacktestTradeAI
            elif isinstance(per_ai, str) and per_ai.strip().lower() not in ['self_training', 'default']:
                ai_name = per_ai.strip()
                rr_val = selected_rrs[i] if selected_rrs and i < len(selected_rrs) else None
                max_loss_val = selected_maxlosses[i] if selected_maxlosses and i < len(selected_maxlosses) else None
                max_loss_per_trade = selected_max_loss_per_trades[i] if selected_max_loss_per_trades and i < len(selected_max_loss_per_trades) else None
                # Lấy AI Key riêng cho symbol hiện tại
                current_ai_key = selected_ai_keys[i] if selected_ai_keys and i < len(selected_ai_keys) else ''
                timeframes=timeframe_secs_map.get(selected_timeframes[i])
                # Endpoint mặc định là OpenAI Responses API nếu không cấu hình khác
                print(f"Khởi động bot AI cho {selected_symbols[i]} với AI Name: {ai_name}, R:R: {rr_val}, Max loss: {max_loss_val}, Max loss/trade: {max_loss_per_trade}")
                print(f"Key: {current_ai_key}")
                print(f"Balance: {selected_balances[i]}, Lot size: {selected_lot_sizes[i]}, Leverage: {leverage}, Timeframe: {timeframes} sec")
                print("-----------------------------------------------------")
                ai_endpoint = 'https://api.openai.com/v1/responses'
                
                print(f"Timeframe selected: {selected_timeframes[i]}, seconds: {timeframes}")
                if self.data_mode == "Backtest":
                    # Lấy cached data cho symbol hiện tại
                    current_symbol_data = None
                    if symbol_cached_data and selected_symbols[i] in symbol_cached_data:
                        current_symbol_data = symbol_cached_data[selected_symbols[i]]
                        print(f"🎯 Using cached data for {selected_symbols[i]} - {len(current_symbol_data)} rows")
                    else:
                        print(f"⚠️ No cached data found for {selected_symbols[i]}")
                    
                    live_trader = BacktestTradeAI(
                        symbol=selected_symbols[i],
                        balance=selected_balances[i],
                        lot_size=selected_lot_sizes[i],
                        leverage=leverage,
                        ai_name_model=ai_name,
                        ai_endpoint=ai_endpoint,
                        ai_key=current_ai_key,
                        data=current_symbol_data,  # Truyền cached data theo symbol
                        rr=rr_val,
                        max_loss_pct=max_loss_val,
                        timeframe_sec=timeframes if timeframes else 60,
                        max_loss_per_trade=max_loss_per_trade
                    )
                else:
                    # Fallback to Python implementation
                        live_trader = LiveTradeAI(
                            symbol=selected_symbols[i],
                            balance=selected_balances[i],
                            lot_size=selected_lot_sizes[i],
                            leverage=leverage,
                            ai_name_model=ai_name,
                            ai_endpoint=ai_endpoint,
                            ai_key=current_ai_key,
                            rr=rr_val,
                            max_loss_pct=max_loss_val,
                            poll_interval_sec=5,
                            timeframe_sec=timeframes if timeframes else 60,
                            max_loss_per_trade=max_loss_per_trade
                        )
                    
                        
            else:
                live_trader = LiveTradeAI(
                    symbol=selected_symbols[i],
                    balance=selected_balances[i],
                    lot_size=selected_lot_sizes[i],
                    leverage=leverage,
                    ai_name_model=ai_name,
                    ai_endpoint=ai_endpoint,
                    ai_key=current_ai_key,
                    rr=rr_val,
                    max_loss_pct=max_loss_val,
                    poll_interval_sec=5,
                    timeframe_sec=timeframes if timeframes else 60,
                    max_loss_per_trade=max_loss_per_trade
                )
            # trade_history_path = trade_history_paths.get(selected_symbols[i])
            #monitor.add_symbol_monitor(symbol, live_trader, trade_history_path)
            
            # Gửi công việc vào ThreadPoolExecutor
            future = self.executor.submit(self.run_live_trader, live_trader)
            
            # Lưu trạng thái vào live_traders với key theo format symbol_mode
            trading_type = 'backtest' if self.data_mode == 'Backtest' else 'realtime'
            trader_key = f"{selected_symbols[i]}_{trading_type}"
            self.live_traders[trader_key] = {
                "trader": live_trader,
                "future": future
            }
        

        # Dùng QTimer để cập nhật giao diện của BotMonitor
        # self.timer = QTimer()
        # self.timer.timeout.connect(monitor.update_monitor)
        # self.timer.start(1000)  # Cập nhật mỗi giây
    
    def run_live_trader(self, trader):
        try:
            trader.run()
            print(f"Trader for {trader.symbol} completed successfully.")
        except Exception as e:
            print(f"Error in Trader for {trader.symbol}: {str(e)}")
        finally:
            # Kiểm tra trạng thái của luồng sau khi bot đã chạy xong
            symbol = trader.symbol
            trading_type = 'backtest' if self.data_mode == 'Backtest' else 'realtime'
            
            if utils_symbol_csv.check_Status0(symbol, trading_type)==False:
                print(f"Trader for {symbol} ({trading_type}) finished with status 0, performing cleanup.")
                utils_symbol_csv.update_status(symbol, trading_type)  # Cập nhật trạng thái trong Symbol.csv
                update_stop_time(symbol, trading_type)  # Cập nhật thời gian dừng trong Bot_running_details

            # Lấy future trước khi xóa khỏi live_traders
            trader_key = f"{symbol}_{trading_type}"
            if trader_key in self.live_traders:
                future = self.live_traders[trader_key]["future"]

                # Xóa bot khỏi danh sách live_traders
                del self.live_traders[trader_key]

                # Kiểm tra trạng thái của future
                if not future.done():  # Kiểm tra xem luồng đã hoàn thành hay chưa
                    future.cancel()
                    print(f"Luồng cho {symbol} ({trading_type}) đã được đóng.")
                else:
                    print(f"Luồng cho {symbol} ({trading_type}) đã hoàn thành tự nhiên.")
                print(f"Luồng cho {symbol} đã hoàn thành.")


    def save_edited_row(self):
        is_valid = self.validate_balance_input()
        if is_valid != 3:
            if is_valid == 0:
                show_message("Error", "Balance input is empty.")
            elif is_valid == 1:
                show_message("Error", "Invalid number format.")
            elif is_valid == 2:
                show_message("Error", "Số tiền phải nhỏ hơn hoặc bằng số tiền trong tài khoản.")
            self.tradeBalanc_textEdit.setFocus()
            return
        else:
            valid_balance = self.tradeBalanc_textEdit.text()
            flag = self.is_run()
            
            if flag == 0:
                show_message("Warning", "Không đủ số tiền để giao dịch. Vui lòng thay đổi số lot hoặc đòn bẩy.")
                self.tradeBalanc_textEdit.setFocus()
                return
            elif flag == 0.5:
                show_message("Warning", "Rủi ro cao.")
            else:
                show_message("Success", f"Số tiền hợp lệ: {valid_balance}. Giao dịch được chấp nhận.")
        
        print(f"💾 Saving changes for row {self.current_editing_row}")
        
        # Lấy giá trị mới từ UI
        new_balance = float(self.tradeBalanc_textEdit.text())
        new_lot_size = self.tradeLot_spinBox.value()
        new_symbol = self.tradeSymbol_comboBox.currentText()
        new_timeframe = self.timeframe_comboBox.currentText()
        
        # Cập nhật balance
        self.balance = self.balance + self.balance_edit - new_balance
        
        # CẬP NHẬT TẤT CẢ CÁC CỘT TRONG BẢNG
        # Cột 0: Symbol
        self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 0, QtWidgets.QTableWidgetItem(new_symbol))
        print(f"Updated Symbol: {new_symbol}")
        
        # Cột 1: Timeframe
        self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 1, QtWidgets.QTableWidgetItem(new_timeframe))
        print(f"Updated Timeframe: {new_timeframe}")
        
        # Cột 2: Balance
        self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 2, QtWidgets.QTableWidgetItem(str(new_balance)))
        print(f"Updated Balance: {new_balance}")
        
        # Cột 3: Lot Size
        self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 3, QtWidgets.QTableWidgetItem(str(new_lot_size)))
        print(f"Updated Lot Size: {new_lot_size}")
        
        # Cột 4: AI Mode
        if self.radioAIModel.isChecked():
            ai_text = self.aiName_edit.text().strip() or 'ai_model'
        else:
            ai_text = 'self_training'
        self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 4, QtWidgets.QTableWidgetItem(ai_text))
        print(f"Updated AI Mode: {ai_text}")
        
        # Cột 5: R:R
        rr_display = f"{self.rr_edit.value():.2f}" if self.radioAIModel.isChecked() else ""
        self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 5, QtWidgets.QTableWidgetItem(rr_display))
        print(f"Updated R:R: {rr_display}")
        
        # Cột 6: Max Loss
        maxloss_display = f"{self.maxloss_edit.value():.1f} %" if self.radioAIModel.isChecked() else ""
        self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 6, QtWidgets.QTableWidgetItem(maxloss_display))
        print(f"Updated Max Loss: {maxloss_display}")
        
        # Cộtn 7 & 8: Size_Data và Type_Data (chỉ trong Backtest mode)
        if self.data_mode == "Backtest":
            # Cột 7: Size_Data - lấy từ current preview data
            if hasattr(self, '_current_preview_data') and self._current_preview_data is not None:
                size_text = str(len(self._current_preview_data))
            else:
                size_text = "0"
            self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 7, QtWidgets.QTableWidgetItem(size_text))
            print(f"Updated Size_Data: {size_text}")
            
            # Cột 8: Type_Data
            type_text = ""
            try:
                if hasattr(self, 'dsApiRadio') and self.dsApiRadio.isChecked():
                    type_text = "MT5"
                elif hasattr(self, 'dsImportRadio') and self.dsImportRadio.isChecked():
                    type_text = "Import"
            except Exception:
                type_text = ""
            self.tradeSymbolPicked_tableWidget.setItem(self.current_editing_row, 8, QtWidgets.QTableWidgetItem(type_text))
            print(f"Updated Type_Data: {type_text}")
        
        # Cập nhật AI Key nếu đang ở AI Model mode
        if self.radioAIModel.isChecked():
            ai_key = self.aiKey_edit.text().strip()
            if ai_key:
                self._row_ai_keys[self.current_editing_row] = ai_key
                print(f"Updated AI Key for row {self.current_editing_row}")
            elif self.current_editing_row in self._row_ai_keys:
                # Remove AI Key nếu bị xóa
                del self._row_ai_keys[self.current_editing_row]
                print(f"Removed AI Key for row {self.current_editing_row}")
        elif self.current_editing_row in self._row_ai_keys:
            # Remove AI Key nếu chuyển về Self Training mode
            del self._row_ai_keys[self.current_editing_row]
            print(f"Removed AI Key for row {self.current_editing_row} (switched to Self Training)")
        
        # Cập nhật cache nếu symbol/timeframe đã thay đổi và có data hiện tại
        if hasattr(self, '_current_preview_data') and self._current_preview_data is not None:
            cache_key = (new_symbol, new_timeframe)
            self._full_history_cache[cache_key] = self._current_preview_data.copy()
            
            # Cache riêng theo symbol cho Backtest mode khi edit
            if self.data_mode == "Backtest":
                self._symbol_data_cache[new_symbol] = self._current_preview_data.copy()
                print(f"💾 Updated symbol cache for Backtest: {new_symbol} - {len(self._current_preview_data)} rows")
            
            print(f"💾 Updated cache for {new_symbol} {new_timeframe}")
        
        # Khôi phục trạng thái ban đầu
        self.back_tradeDialog_EditSave()
        self.balance_currentLabel.setText(f"Ví hiện có: {self.balance} USD")
        self.current_editing_row = -1
        print("✅ Row updated successfully")
        show_message("Success", "Chỉnh sửa thành công.")

    #Back Trade Dialog khi nhấn nút save edit hoặc back
    def back_tradeDialog_EditSave(self):
        print("🔄 Resetting all UI components after Edit/Save...")
        
        # 1. Clear balance input
        self.tradeBalanc_textEdit.clear()
        
        # 2. Reset symbol combobox về trạng thái ban đầu (chọn item đầu tiên)
        if self.tradeSymbol_comboBox.count() > 0:
            self.tradeSymbol_comboBox.setCurrentIndex(0)
            selected_text = self.tradeSymbol_comboBox.currentText()
            print(f"Reset symbol combo to first item: {selected_text}")
        else:
            print("Symbol combo is empty")
            selected_text = ""
        
        # 3. Reset timeframe về mặc định (chỉ trong Backtest mode)
        # Trong Real-time mode, giữ nguyên timeframe hiện tại để người dùng tiếp tục sử dụng
        if self.data_mode == "Backtest":
            default_timeframe_index = self.timeframe_comboBox.findText("M5")
            if default_timeframe_index >= 0:
                self.timeframe_comboBox.setCurrentIndex(default_timeframe_index)
                print("Reset timeframe to: M5 (Backtest mode)")
            elif self.timeframe_comboBox.count() > 0:
                self.timeframe_comboBox.setCurrentIndex(0)
                print(f"Reset timeframe to first item: {self.timeframe_comboBox.currentText()} (Backtest mode)")
        else:
            print(f"Keeping current timeframe: {self.timeframe_comboBox.currentText()} (Real-time mode)")
        
        # 4. Reset lot size và lot mode
        if selected_text and not self._is_btc_symbol(selected_text):
            # Kiểm tra MT5 connection trước khi lấy symbol info
            if mt5.initialize():
                symbol_info = mt5.symbol_info(selected_text)
                if symbol_info is not None:
                    self.tradeLot_spinBox.setValue(symbol_info.volume_min)
                    self.tradeAutoLot_radioButton.setChecked(True)
                    self.tradeLot_spinBox.setEnabled(False)
                    print(f"Set lot size to minimum: {symbol_info.volume_min}")
                else:
                    print(f"⚠️ Không thể lấy thông tin symbol: {selected_text}")
                    # Fallback: set manual mode với 0.01
                    self.tradeLot_spinBox.setValue(0.01)
                    self.tradeManualLot_radioButton.setChecked(True)
                    self.tradeLot_spinBox.setEnabled(True)
                mt5.shutdown()
            else:
                print(f"⚠️ MT5 connection failed when setting symbol info: {selected_text}")
                # Fallback: set manual mode với 0.01
                self.tradeLot_spinBox.setValue(0.01)
                self.tradeManualLot_radioButton.setChecked(True)
                self.tradeLot_spinBox.setEnabled(True)
        else:
            print("BTCUSD selected or no symbol, using default lot size")
            self.tradeLot_spinBox.setValue(0.01)
            self.tradeManualLot_radioButton.setChecked(True)
            self.tradeLot_spinBox.setEnabled(True)
        
        # 5. Reset AI mode về SELF-TRAIN (default)
        self.radioSelfTrain.setChecked(True)
        self.radioAIModel.setChecked(False)
        print("Reset AI mode to: SELF-TRAIN")
        
        # 6. Clear AI related inputs
        if hasattr(self, 'aiName_edit'):
            self.aiName_edit.clear()
            print("Cleared AI Name")
        if hasattr(self, 'aiKey_edit'):
            self.aiKey_edit.clear()
            print("Cleared AI Key")
        if hasattr(self, 'rr_edit'):
            self.rr_edit.setValue(1.0)  # Reset về giá trị mặc định
            print("Reset R:R to: 1.0")
        if hasattr(self, 'maxloss_edit'):
            self.maxloss_edit.setValue(5.0)  # Reset về giá trị mặc định
            print("Reset Max Loss to: 5.0%")
            
        # 7. Trigger AI mode change để hide/show controls đúng
        self.on_ai_mode_changed()
        
        # 8. Reset symbol search box (nếu có)
        if hasattr(self, 'symbolSearch_lineEdit'):
            self.symbolSearch_lineEdit.clear()
            print("Cleared symbol search")
        
        # 9. Clear data preview trong dsGroup (nếu có)
        if hasattr(self, 'dataPreview_table'):
            self._clear_preview_table()
            print("Cleared data preview table")
        
        # 10. Reset data source radio buttons (nếu có)
        if hasattr(self, 'dsApiRadio') and hasattr(self, 'dsImportRadio'):
            # Mặc định chọn MT5 API
            self.dsApiRadio.setChecked(True)
            self.dsImportRadio.setChecked(False)
            print("Reset data source to: MT5 API")
        
        # 11. Reset date/time inputs về default range (nếu có)
        try:
            self._initialize_default_dates_and_preview()
            print("Reset date/time inputs to default range")
        except Exception as e:
            print(f"Error resetting date inputs: {e}")
            
        # 12. Clear current preview data
        self._current_preview_data = None
        print("Cleared current preview data")
            
        # 13. Hiển thị lại các controls
        self.tradeSymbol_comboBox.show()
        self.tradeAddSymbol_pushButton.show()
        self.tradeDeleteSymbol_pushButton.show()
        self.tradeSymbolPicked_tableWidget.show()
        self.trade_buttonBox.show()
        self.tradeEditSymbol_pushButton.show()
        
        # 14. Ẩn các controls edit mode
        self.button_back.hide()
        self.symbol_label.hide()
        self.saveEdit_button.hide()
        
        print("✅ All UI components reset successfully after Edit/Save")

    #Back lại Ui_Trade khi nhấn nút Add
    def back_tradeDialog_Add(self):
        print("🔄 Resetting all UI components after Add...")
        
        # 1. Clear balance input
        self.tradeBalanc_textEdit.clear()
        
        # 2. Reset symbol combobox về trạng thái ban đầu (chọn item đầu tiên hoặc clear)
        if self.tradeSymbol_comboBox.count() > 0:
            self.tradeSymbol_comboBox.setCurrentIndex(0)
            selected_text = self.tradeSymbol_comboBox.currentText()
            print(f"Reset symbol combo to first item: {selected_text}")
        else:
            print("Symbol combo is empty")
            selected_text = ""
        
        # 3. Reset timeframe về mặc định (chỉ trong Backtest mode)
        # Trong Real-time mode, giữ nguyên timeframe hiện tại để người dùng tiếp tục sử dụng
        if self.data_mode == "Backtest":
            default_timeframe_index = self.timeframe_comboBox.findText("M5")
            if default_timeframe_index >= 0:
                self.timeframe_comboBox.setCurrentIndex(default_timeframe_index)
                print("Reset timeframe to: M5 (Backtest mode)")
            elif self.timeframe_comboBox.count() > 0:
                self.timeframe_comboBox.setCurrentIndex(0)
                print(f"Reset timeframe to first item: {self.timeframe_comboBox.currentText()} (Backtest mode)")
        else:
            print(f"Keeping current timeframe: {self.timeframe_comboBox.currentText()} (Real-time mode)")
        
        # 4. Reset lot size và lot mode
        if selected_text and not self._is_btc_symbol(selected_text):
            # Kiểm tra MT5 connection trước khi lấy symbol info
            if mt5.initialize():
                symbol_info = mt5.symbol_info(selected_text)
                if symbol_info is not None:
                    self.tradeLot_spinBox.setValue(symbol_info.volume_min)
                    self.tradeAutoLot_radioButton.setChecked(True)
                    self.tradeLot_spinBox.setEnabled(False)
                    print(f"Set lot size to minimum: {symbol_info.volume_min}")
                else:
                    print(f"⚠️ Không thể lấy thông tin symbol: {selected_text}")
                    # Fallback: set manual mode với 0.01
                    self.tradeLot_spinBox.setValue(0.01)
                    self.tradeManualLot_radioButton.setChecked(True)
                    self.tradeLot_spinBox.setEnabled(True)
                mt5.shutdown()
            else:
                print(f"⚠️ MT5 connection failed when setting symbol info: {selected_text}")
                # Fallback: set manual mode với 0.01
                self.tradeLot_spinBox.setValue(0.01)
                self.tradeManualLot_radioButton.setChecked(True)
                self.tradeLot_spinBox.setEnabled(True)
        else:
            print("BTCUSD selected or no symbol, using default lot size")
            self.tradeLot_spinBox.setValue(0.01)
            self.tradeManualLot_radioButton.setChecked(True)
            self.tradeLot_spinBox.setEnabled(True)
        
        # 5. Reset AI mode về SELF-TRAIN (default)
        self.radioSelfTrain.setChecked(True)
        self.radioAIModel.setChecked(False)
        print("Reset AI mode to: SELF-TRAIN")
        
        # 6. Clear AI related inputs
        if hasattr(self, 'aiName_edit'):
            self.aiName_edit.clear()
            print("Cleared AI Name")
        if hasattr(self, 'aiKey_edit'):
            self.aiKey_edit.clear()
            print("Cleared AI Key")
        if hasattr(self, 'rr_edit'):
            self.rr_edit.setValue(1.0)  # Reset về giá trị mặc định
            print("Reset R:R to: 1.0")
        if hasattr(self, 'maxloss_edit'):
            self.maxloss_edit.setValue(5.0)  # Reset về giá trị mặc định
            print("Reset Max Loss to: 5.0%")
            
        # 7. Trigger AI mode change để hide/show controls đúng
        self.on_ai_mode_changed()
        
        # 8. Reset symbol search box (nếu có)
        if hasattr(self, 'symbolSearch_lineEdit'):
            self.symbolSearch_lineEdit.clear()
            print("Cleared symbol search")
        
        # 9. Clear data preview trong dsGroup (nếu có)
        if hasattr(self, 'dataPreview_table'):
            self._clear_preview_table()
            print("Cleared data preview table")
        
        # 10. Reset data source radio buttons (nếu có)
        if hasattr(self, 'dsApiRadio') and hasattr(self, 'dsImportRadio'):
            # Mặc định chọn MT5 API
            self.dsApiRadio.setChecked(True)
            self.dsImportRadio.setChecked(False)
            print("Reset data source to: MT5 API")
        
        # 11. Reset date/time inputs về default range (nếu có)
        try:
            self._initialize_default_dates_and_preview()
            print("Reset date/time inputs to default range")
        except Exception as e:
            print(f"Error resetting date inputs: {e}")
            
        # 12. Clear current preview data
        self._current_preview_data = None
        print("Cleared current preview data")
        
        print("✅ All UI components reset successfully after Add")

    #Kiểm tra đàu vào của balance
    def validate_balance_input(self):
        """Hàm kiểm tra điều kiện đầu vào bổ sung."""
        text = self.tradeBalanc_textEdit.text()
        if not text:
            return 0
        # Chuyển text thành số để kiểm tra thêm điều kiện
        try:
            value = float(text)
        except ValueError:
            return 1
        # Thêm các điều kiện khác tại đây
        if value >= self.balance: 
            return 2
        return 3

    def on_combobox_changed(self):
        """Hàm xử lý khi combobox thay đổi."""
        selected_text = self.tradeSymbol_comboBox.currentText()
        print(f"Combobox changed to symbol: {selected_text}")
        
        # KIỂM TRA XEM CÓ ĐANG TRONG EDIT MODE KHÔNG
        in_edit_mode = hasattr(self, 'current_editing_row') and self.current_editing_row >= 0
        if in_edit_mode:
            print(f"🔒 In edit mode - preserving user's lot settings for row {self.current_editing_row}")
            # Trong edit mode, chỉ update leverage và symbol constraints, KHÔNG thay đổi lot size
            
            # Xác định leverage dựa trên symbol
            if self._is_btc_symbol(selected_text):
                self.leverage = 400
                print(f"BTCUSD detected, setting leverage to 400")
            else:
                # Sử dụng cached account info
                account_info = self.get_cached_account_info()
                if account_info:
                    self.leverage = account_info.leverage
                    print(f"Other symbol detected, using cached account leverage: {self.leverage}")
                else:
                    self.leverage = 500  # fallback default
                    print("⚠️ Using fallback leverage: 500")
                
            # Chỉ update min/max/step cho spinbox, KHÔNG thay đổi value
            if mt5.initialize():
                symbol_info = mt5.symbol_info(selected_text)
                if symbol_info is not None:
                    lot_min = symbol_info.volume_min
                    lot_max = symbol_info.volume_max
                    lot_step = symbol_info.volume_step
                    
                    # Preserve current lot size
                    current_lot_value = self.tradeLot_spinBox.value()
                    
                    # Update constraints
                    self.tradeLot_spinBox.setMinimum(lot_min)
                    self.tradeLot_spinBox.setMaximum(lot_max)
                    self.tradeLot_spinBox.setSingleStep(lot_step)
                    
                    # Restore user's lot size (don't override with minimum)
                    self.tradeLot_spinBox.setValue(current_lot_value)
                    print(f"🔒 Edit mode: Updated constraints but preserved lot size: {current_lot_value}")
                    
                mt5.shutdown()
            return
        
        # NORMAL MODE - không trong edit mode
        # Xác định leverage dựa trên symbol sử dụng cached account info
        if self._is_btc_symbol(selected_text):
            self.leverage = 400
            print(f"BTCUSD detected, setting leverage to 400")
        else:
            account_info = self.get_cached_account_info()
            if account_info:
                self.leverage = account_info.leverage
                print(f"Other symbol detected, using cached account leverage: {self.leverage}")
            else:
                self.leverage = 500  # fallback
                print("⚠️ Using fallback leverage: 500")
        
        # Lấy thông tin symbol từ MT5
        if not mt5.initialize():
            print("⚠️ MT5 initialize() failed")
            return
        symbol_info = mt5.symbol_info(selected_text)
        print(f"Symbol info: {symbol_info}")
        if symbol_info is None:
            print(f"⚠️ Không thể lấy thông tin symbol: {selected_text}")
            mt5.shutdown()
            return
            
        lot_min = symbol_info.volume_min
        lot_max = symbol_info.volume_max
        lot_step = symbol_info.volume_step

        print(f"Symbol: {selected_text}")
        print("Lot size tối thiểu:", lot_min)
        print("Lot size tối đa:", lot_max)
        print("Bước nhảy của lot:", lot_step)
        
        # Thiết lập các giá trị này cho QDoubleSpinBox
        self.tradeLot_spinBox.setMinimum(lot_min)
        self.tradeLot_spinBox.setMaximum(lot_max)
        self.tradeLot_spinBox.setSingleStep(lot_step)
        # CHỈ set về minimum khi KHÔNG trong edit mode
        self.tradeLot_spinBox.setValue(lot_min)
        print(f"Normal mode: Set lot size to minimum: {lot_min}")
        
        mt5.shutdown()
      

    def on_auto_toggled(self):
        """Hàm được gọi khi Auto RadioButton được chọn hoặc bỏ chọn."""
        # Nếu combobox chưa được khởi tạo (tín hiệu bật sớm trong setup), bỏ qua
        if not hasattr(self, 'tradeSymbol_comboBox') or self.tradeSymbol_comboBox is None:
            return
        selected_text = self.tradeSymbol_comboBox.currentText()
        print(f"Auto toggle changed for symbol: {selected_text}")
        
        # KIỂM TRA XEM CÓ ĐANG TRONG EDIT MODE KHÔNG
        in_edit_mode = hasattr(self, 'current_editing_row') and self.current_editing_row >= 0
        if in_edit_mode:
            print(f"🔒 In edit mode - allowing user's lot mode change for row {self.current_editing_row}")
            # Trong edit mode, cho phép user thay đổi lot mode và xử lý bình thường
        
        # Kiểm tra MT5 connection trước khi lấy symbol info
        if not mt5.initialize():
            print(f"⚠️ MT5 connection failed when getting symbol info: {selected_text}")
            return
            
        symbol_info = mt5.symbol_info(selected_text)
        if symbol_info is not None:
            if self.tradeAutoLot_radioButton.isChecked():
                self.tradeLot_spinBox.setValue(symbol_info.volume_min)
                self.tradeLot_spinBox.setEnabled(False)
                # Hiển thị max loss per trade field khi Auto mode
                self.maxLossPerTrade_label.setVisible(True)
                self.maxLossPerTrade_spinBox.setVisible(True)
                print(f"Auto mode: Set lot size to minimum {symbol_info.volume_min}")
            else:
                self.tradeLot_spinBox.setEnabled(True)
                # Ẩn max loss per trade field khi Manual mode
                self.maxLossPerTrade_label.setVisible(False)
                self.maxLossPerTrade_spinBox.setVisible(False)
                # Nếu đang trong edit mode, giữ nguyên giá trị lot size hiện tại
                if not in_edit_mode:
                    # Normal mode: có thể set về default value
                    print("Manual mode: Lot size input enabled")
                else:
                    # Edit mode: giữ nguyên lot size user đã set
                    current_lot = self.tradeLot_spinBox.value()
                    print(f"Manual mode (edit): Lot size input enabled, preserving value: {current_lot}")
        else:
            print(f"⚠️ Không thể lấy thông tin symbol: {selected_text}")
        
        mt5.shutdown()

    def on_ai_mode_changed(self):
        """Hiện/ẩn trường AI và cập nhật danh sách Symbol theo chế độ chọn."""
        use_ai = self.radioAIModel.isChecked()
        for w in [self.aiName_label, self.aiName_edit, self.aiKey_label, self.aiKey_edit, self.rr_label, self.rr_edit, self.maxloss_label, self.maxloss_edit]:
            w.setVisible(use_ai)
        # Cập nhật danh sách symbol giống logic ở handler trên
        # Hiển thị tất cả symbol có thể trade cho mọi chế độ
        try:
            trading_type = 'backtest' if self.data_mode == 'Backtest' else 'realtime'
            self.trade_all_symbols = Status0_symbol(trading_type) or list(SYMBOLS.values())
        except Exception:
            self.trade_all_symbols = list(SYMBOLS.values())
        self.populate_trade_symbol_combo(self.tradeSymbol_search.text())

    def on_ai_type_changed(self):
        """Xử lý khi chuyển đổi giữa Predictive AI và Agent AI cho cả Real-time và Backtest mode."""
        is_agent_ai = self.radioAgentAI.isChecked()
        print(f"🔄 AI Type changed ({self.data_mode}): {'Agent AI' if is_agent_ai else 'Predictive AI'}")
        
        if is_agent_ai:
            # ========== AGENT AI MODE ==========
            # Ẩn nhóm SELF-TRAIN / AI MODEL
            self.aiGroup.hide()
            
            # Ẩn nhóm Auto/Manual lot size
            self.lotGroup.hide()
            
            # Ẩn Max Loss/Trade
            self.maxLossPerTrade_label.hide()
            self.maxLossPerTrade_spinBox.hide()
            
            # Cho phép nhập lot size thủ công (không bị disable)
            self.tradeLot_spinBox.setEnabled(True)
            
            if self.data_mode == "Backtest":
                # Backtest Agent AI: 7 cột
                self.tradeSymbolPicked_tableWidget.setColumnCount(7)
                self.tradeSymbolPicked_tableWidget.setHorizontalHeaderLabels([
                    'Symbol', 'Timeframe', 'Balance', 'Lot size', 'AI Type', 'Size_data', 'Type_Data'
                ])
                print("📊 Table updated for Backtest Agent AI: 7 columns")
            else:
                # Real-time Agent AI: 5 cột (Symbol, Timeframe, Balance, Lot size, AI Type)
                self.tradeSymbolPicked_tableWidget.setColumnCount(5)
                self.tradeSymbolPicked_tableWidget.setHorizontalHeaderLabels([
                    'Symbol', 'Timeframe', 'Balance', 'Lot size', 'AI Type'
                ])
                print("📊 Table updated for Real-time Agent AI: 5 columns")
            
        else:
            # ========== PREDICTIVE AI MODE ==========
            # Hiện lại nhóm SELF-TRAIN / AI MODEL
            self.aiGroup.show()
            
            # Hiện lại nhóm Auto/Manual lot size
            self.lotGroup.show()
            
            # Hiện Max Loss/Trade nếu đang ở Auto mode
            if self.tradeAutoLot_radioButton.isChecked():
                self.maxLossPerTrade_label.show()
                self.maxLossPerTrade_spinBox.show()
                self.tradeLot_spinBox.setEnabled(False)
            else:
                self.maxLossPerTrade_label.hide()
                self.maxLossPerTrade_spinBox.hide()
                self.tradeLot_spinBox.setEnabled(True)
            
            if self.data_mode == "Backtest":
                # Backtest Predictive AI: 10 cột
                self.tradeSymbolPicked_tableWidget.setColumnCount(10)
                self.tradeSymbolPicked_tableWidget.setHorizontalHeaderLabels([
                    'Symbol', 'Timeframe', 'Balance', 'Lot size', 'AI', 'R:R', 'Max loss', 'Max Loss/Trade', 'Size_data', 'Type_Data'
                ])
                print("📊 Table updated for Backtest Predictive AI: 10 columns")
            else:
                # Real-time Predictive AI: 8 cột (giữ nguyên logic cũ)
                self.tradeSymbolPicked_tableWidget.setColumnCount(8)
                self.tradeSymbolPicked_tableWidget.setHorizontalHeaderLabels([
                    'Symbol', 'Timeframe', 'Balance', 'Lot size', 'AI', 'R:R', 'Max loss', 'Max Loss/Trade'
                ])
                print("📊 Table updated for Real-time Predictive AI: 8 columns")
            
            # Trigger AI mode change để update visibility
            self.on_ai_mode_changed()
    
    # Alias cho backward compatibility
    def on_backtest_ai_type_changed(self):
        """Backward compatibility - redirect to on_ai_type_changed"""
        self.on_ai_type_changed()

    def round_to_two_decimal_places(self,number):
        return round(number, 2)

    def is_run(self):
        text = self.tradeBalanc_textEdit.text()
        value = float(text)
        selected_text = self.tradeSymbol_comboBox.currentText()
        print(f"Checking if can run with symbol: {selected_text}, balance: {value}")
        
        # Xác định leverage dựa trên symbol
        if self._is_btc_symbol(selected_text):
            self.leverage = 400
            print(f"BTCUSD detected, using leverage: 400")
        else:
            account_info = self.get_cached_account_info()
            if account_info:
                self.leverage = account_info.leverage
                print(f"Other symbol detected, using leverage: {self.leverage}")
            else:
                self.leverage = 500
                print(f"Failed to get account info, using fallback leverage: 500")
        
        # Kiểm tra MT5 connection trước khi lấy tick data
        if not mt5.initialize():
            print(f"⚠️ MT5 connection failed when checking symbol: {selected_text}")
            return 0
        
        # Kiểm tra symbol có tồn tại không
        symbol_info = mt5.symbol_info(selected_text)
        if symbol_info is None:
            print(f"⚠️ Symbol {selected_text} không tồn tại trên MT5")
            mt5.shutdown()
            return 0
        
        print(f"📈 Symbol info: {symbol_info.name}, spread: {symbol_info.spread}")
        
        # Thử select symbol nếu chưa được select
        if not symbol_info.select:
            print(f"🔄 Trying to select symbol {selected_text}...")
            if not mt5.symbol_select(selected_text, True):
                print(f"⚠️ Cannot select symbol {selected_text}")
                mt5.shutdown()
                return 0
            else:
                print(f"✅ Symbol {selected_text} selected successfully")
        
        # Lấy tick data
        tick = mt5.symbol_info_tick(selected_text)
        if tick is None:
            print(f"⚠️ Không thể lấy tick data cho symbol: {selected_text}")
            print(f"   Có thể do: 1) Market đóng cửa, 2) Symbol không active, 3) Connection issue")
            mt5.shutdown()
            return 0
        
        # Kiểm tra giá bid/ask hợp lệ
        if tick.ask <= 0 or tick.bid <= 0:
            print(f"⚠️ Invalid tick prices - Ask: {tick.ask}, Bid: {tick.bid}")
            mt5.shutdown()
            return 0
            
        lot_size = self.tradeLot_spinBox.value()
        if lot_size <= 0:
            print(f"⚠️ Invalid lot size: {lot_size}")
            mt5.shutdown()
            return 0
            
        contract_value_ask = tick.ask * lot_size
        contract_value_bid = tick.bid * lot_size
        margin_bid = contract_value_bid / self.leverage
        margin_ask = contract_value_ask / self.leverage
        
        # Kiểm tra margin không bằng 0 trước khi chia
        if margin_bid <= 0 or margin_ask <= 0:
            print(f"⚠️ Invalid margin - Bid: {margin_bid}, Ask: {margin_ask}")
            mt5.shutdown()
            return 0
            
        margin_level_bid = self.round_to_two_decimal_places((value / margin_bid) * 100)
        margin__level_ask = self.round_to_two_decimal_places((value / margin_ask) * 100)
        
        print(f"Margin levels - Bid: {margin_level_bid}%, Ask: {margin__level_ask}%")
        
        if value < margin_ask or value < margin_bid:
            print("❌ Không đủ tiền để giao dịch")
            mt5.shutdown()
            return 0
        elif margin__level_ask < 100 or margin_level_bid < 100:
            print("⚠️ Rủi ro cao")
            mt5.shutdown()
            return 0.5
        else:
            print("✅ Có thể giao dịch an toàn")
            mt5.shutdown()
            return 1