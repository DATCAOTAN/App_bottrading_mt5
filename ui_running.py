from PyQt5 import QtCore, QtGui, QtWidgets
import MetaTrader5 as mt5
import os
import pandas as pd
from utils_paths import current_dir_results
import utils_symbol_csv
from utils_logs import update_stop_time
class Ui_RunningBotDialog(QtWidgets.QDialog):
    def __init__(self, main_window, mode='Real-time', parent=None):
        """
        Args:
            main_window: Tham chiếu đến MainWindow
            mode: 'realtime' hoặc 'backtest'
            parent: Parent widget
        """
        super().__init__(parent)
        self.main_window = main_window  # Tham chiếu đến MainWindow
        self.live_traders = main_window.live_traders  # Dùng chung live_traders
        self.mode = mode  # Lưu chế độ trading
        print(f"Running Bot Dialog - Mode: {self.mode}")
        print(self.live_traders)
        self.setupUi()

        # Timer cập nhật dữ liệu mỗi giây
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.populate_data)
        self.timer.start(400)

    def setupUi(self):
        self.setObjectName("RunningBotDialog")
        self.resize(850, 450)  # Tăng chiều cao để chứa nút Close All
        mode_title = "Realtime" if self.mode == 'Real-time' else "Backtest"
        self.setWindowTitle(f"Running Bots - {mode_title}")

        # Table widget
        self.tableWidget = QtWidgets.QTableWidget(self)
        self.tableWidget.setGeometry(QtCore.QRect(20, 20, 800, 350))
        self.tableWidget.setObjectName("tableWidget")
        self.tableWidget.setColumnCount(6)  # Bỏ cột Equity, chỉ còn 6 cột
        self.tableWidget.setHorizontalHeaderLabels(["Symbol", "Time_Order_Bot", "Balance", "Lot_Size", "Profit/Loss", "Close"])
        self.tableWidget.setSelectionBehavior(QtWidgets.QTableView.SelectRows)
        self.tableWidget.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)  
        self.tableWidget.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)

        # Stretch the columns to fit content    
        header = self.tableWidget.horizontalHeader()
        header.setSectionResizeMode(QtWidgets.QHeaderView.Stretch)
        
        # Nút Close All Bot - nằm dưới góc trái
        self.closeAllButton = QtWidgets.QPushButton("Close All Bot", self)
        self.closeAllButton.setGeometry(QtCore.QRect(20, 385, 150, 40))
        self.closeAllButton.setObjectName("closeAllButton")
        
        # Style cho nút Close All
        self.closeAllButton.setStyleSheet("""
            QPushButton {
                background-color: #dc3545;
                color: white;
                border: none;
                border-radius: 5px;
                font-size: 14px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #c82333;
            }
            QPushButton:pressed {
                background-color: #bd2130;
            }
        """)
        
        # Kết nối sự kiện click
        self.closeAllButton.clicked.connect(self.close_all_bots)


    def get_current_profit(self,symbol):
        # Lấy vị thế hiện tại theo symbol
        positions = mt5.positions_get(symbol=symbol)
        if not positions:
            return 0  # Nếu không có vị thế mở, trả về lợi nhuận bằng 0
        # Giả sử chỉ có một vị thế m
        return positions[0].profit

    def populate_data(self):
        """ Đọc dữ liệu từ CSV, tính Profit/Loss nhưng không hiển thị Equity """
        file_path = os.path.join(current_dir_results, 'trade_history', 'real_time', "Bot_running_details.csv")

        if not os.path.exists(file_path):
            print("❌ File Bot_running_details.csv không tồn tại. Đang tạo mới...")
            try:
                os.makedirs(os.path.dirname(file_path), exist_ok=True)
                empty = pd.DataFrame(columns=[
                    "Symbol", "Time_run_bot", "Balance", "Lot_size", 
                    "Eqity_Realtime", "Eqity_Backtest",
                    "Time_stop_bot_Realtime", "Time_stop_bot_Backtest"
                ])
                empty.to_csv(file_path, index=False)
                print("✅ Đã tạo file Bot_running_details.csv rỗng.")
            except Exception as e:
                print(f"❌ Không thể tạo Bot_running_details.csv: {e}")
                return

        try:
            df = pd.read_csv(file_path)

            if df.empty:
                print("⚠️ File Bot_running_details.csv trống.")
                self.tableWidget.setRowCount(0)
                return

            # Xác định cột equity và time_stop dựa vào mode
            equity_col = 'Eqity_Realtime' if self.mode == 'Real-time' else 'Eqity_Backtest'
            time_stop_col = 'Time_stop_bot_Realtime' if self.mode == 'Real-time' else 'Time_stop_bot_Backtest'

            # Chỉ lấy bot đang chạy cho mode tương ứng
            df = df[df[time_stop_col] == "Running"]

            if df.empty:
                self.tableWidget.setRowCount(0)
                print(f"⚠️ Không có bot nào đang chạy ({self.mode}).")
                return

            # Chỉ lấy các cột cần thiết (giữ Equity để tính toán nhưng không hiển thị)
            df["Profit/Loss"] = df.apply(lambda row: round((row[equity_col] - row["Balance"]) + self.get_current_profit(row["Symbol"]),2), axis=1)
            df = df[["Symbol", "Time_run_bot", "Balance", "Lot_size", "Profit/Loss"]]  # Không lấy Equity để hiển thị

            # Chuyển DataFrame thành danh sách
            data = df.values.tolist()
            
            # Lấy số hàng hiện tại
            current_row_count = self.tableWidget.rowCount()
            new_row_count = len(data)
            
            # Chỉ thay đổi số hàng nếu khác
            if current_row_count != new_row_count:
                self.tableWidget.setRowCount(new_row_count)
            
            # Cập nhật dữ liệu cho từng hàng
            for row_index, row_data in enumerate(data):
                for col_index, item in enumerate(row_data):
                    # Lấy item hiện tại
                    current_item = self.tableWidget.item(row_index, col_index)
                    item_str = str(item)
                    
                    # Chỉ cập nhật nếu giá trị thay đổi
                    if current_item is None or current_item.text() != item_str:
                        table_item = QtWidgets.QTableWidgetItem(item_str)
                        
                        # Định dạng Profit/Loss màu xanh hoặc đỏ
                        if col_index == 4:  # Cột Profit/Loss
                            profit_loss = float(item)
                            if profit_loss >= 0:
                                table_item.setForeground(QtGui.QColor("green"))
                            else:
                                table_item.setForeground(QtGui.QColor("red"))
                        
                        self.tableWidget.setItem(row_index, col_index, table_item)
                
                # Chỉ tạo nút Close nếu chưa tồn tại
                if self.tableWidget.cellWidget(row_index, 5) is None:
                    close_button = QtWidgets.QPushButton()
                    close_button.setIcon(QtGui.QIcon("close.png"))  
                    close_button.setIconSize(QtCore.QSize(16, 16))
                    close_button.setProperty("row_index", row_index)  # Lưu row_index vào property
                    close_button.clicked.connect(lambda checked=False, btn=close_button: self.close_bot_by_button(btn))
                    self.tableWidget.setCellWidget(row_index, 5, close_button)

        except Exception as e:
            print(f"❌ Lỗi khi đọc file CSV: {e}")
    
    def close_bot_by_button(self, button):
        """Đóng bot dựa trên nút được click"""
        # Tìm vị trí của nút trong bảng
        for row in range(self.tableWidget.rowCount()):
            if self.tableWidget.cellWidget(row, 5) == button:
                self.close_bot(row)
                return
        print("⚠️ Không tìm thấy hàng tương ứng với nút được click")
    
    def close_bot(self, row_index):
        """ Đóng bot tại hàng được chọn """
        
        # Kiểm tra row_index hợp lệ
        if row_index < 0 or row_index >= self.tableWidget.rowCount():
            print(f"⚠️ Row index không hợp lệ: {row_index}")
            return
        
        # Lấy symbol từ bảng
        symbol_item = self.tableWidget.item(row_index, 0)
        if not symbol_item:
            print(f"⚠️ Không tìm thấy symbol ở row {row_index}")
            return
            
        symbol = symbol_item.text()
        print(f"🔴 Đang đóng bot cho {symbol} ({self.mode})...")
        
        # Chuẩn hóa mode thành trading_type để khớp với key trong live_traders
        trading_type = 'backtest' if self.mode == 'Backtest' else 'realtime'
        trader_key = f"{symbol}_{trading_type}"
        
        # Cập nhật CSV trước
        utils_symbol_csv.update_status(symbol, trading_type)  # Cập nhật trạng thái trong Symbol.csv
        update_stop_time(symbol, trading_type)  # Cập nhật thời gian dừng trong Bot_running_details

        # Đóng positions MT5
        orders = mt5.positions_get(symbol=symbol)
        if not orders:
            print(f"⚠️ Không tìm thấy lệnh nào để đóng cho {symbol}")
        else:
            for order in orders:
                close_request = {
                    "action": mt5.TRADE_ACTION_DEAL,  # Đóng lệnh ngay lập tức
                    "symbol": order.symbol,
                    "volume": order.volume,
                    "position": order.ticket,
                    "type": mt5.ORDER_TYPE_SELL if order.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                    "price": mt5.symbol_info_tick(symbol).bid if order.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask,
                    "deviation": 10,  # Độ trượt giá
                    "magic": order.magic,
                    "comment": "Close trade",
                }
                
                # Gửi lệnh đóng
                result = mt5.order_send(close_request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"✅ Bot {symbol} đã đóng position thành công!")
                else:
                    print(f"❌ Lỗi khi đóng position {symbol}: {result.comment}")

        # Dừng trader thread
        print(f"🔍 Tìm kiếm trader với key: {trader_key}")
        print(f"📋 Danh sách live_traders hiện có: {list(self.live_traders.keys())}")
        
        if trader_key in self.live_traders:
            try:
                trader = self.live_traders[trader_key]["trader"]  # Lấy đối tượng trader
                future = self.live_traders[trader_key]["future"]  # Lấy đối tượng future
                print(f"✅ Tìm thấy trader {trader_key}, đang dừng...")
                
                trader.stop()  # Gọi phương thức stop() để dừng giao dịch
                
                # Đợi luồng kết thúc với timeout
                try:
                    future.result(timeout=5)  # Đợi tối đa 5 giây
                    print(f"✅ Luồng {trader_key} đã kết thúc")
                except Exception as e:
                    print(f"⚠️ Timeout hoặc lỗi khi đợi luồng kết thúc: {e}")
                
                # Xóa khỏi dictionary
                del self.live_traders[trader_key]
                print(f"🗑️ Đã xóa {trader_key} khỏi live_traders")
                
            except Exception as e:
                print(f"❌ Lỗi khi dừng trader {trader_key}: {e}")
                # Vẫn cố gắng xóa khỏi dictionary
                if trader_key in self.live_traders:
                    del self.live_traders[trader_key]
        else:
            print(f"⚠️ KHÔNG TÌM THẤY trader với key: {trader_key}")
            print(f"⚠️ Có thể bot đã được đóng trước đó")
        
        # Xóa row khỏi bảng SAU KHI xử lý xong
        self.tableWidget.removeRow(row_index)
        print(f"✅ Đã xóa hàng {row_index} khỏi bảng")
    
    
    def close_all_bots(self):
        """Đóng tất cả bot đang chạy trong mode hiện tại"""
        
        # Xác nhận trước khi đóng tất cả
        reply = QtWidgets.QMessageBox.question(
            self,
            "Xác nhận đóng tất cả bot",
            f"Bạn có chắc chắn muốn đóng tất cả bot đang chạy trong chế độ {self.mode}?",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No
        )
        
        if reply != QtWidgets.QMessageBox.Yes:
            print("❌ Người dùng hủy đóng tất cả bot")
            return
        
        print(f"🔴 Đang đóng TẤT CẢ bot trong chế độ {self.mode}...")
        
        # Chuẩn hóa mode thành trading_type
        trading_type = 'backtest' if self.mode == 'Backtest' else 'realtime'
        
        # Lấy danh sách tất cả symbols đang chạy từ bảng
        row_count = self.tableWidget.rowCount()
        symbols_to_close = []
        
        for row in range(row_count):
            symbol_item = self.tableWidget.item(row, 0)
            if symbol_item:
                symbols_to_close.append(symbol_item.text())
        
        if not symbols_to_close:
            print("⚠️ Không có bot nào để đóng")
            QtWidgets.QMessageBox.information(self, "Thông báo", "Không có bot nào đang chạy")
            return
        
        print(f"📋 Danh sách symbol cần đóng: {symbols_to_close}")
        
        # Đóng từng bot
        closed_count = 0
        failed_count = 0
        
        for symbol in symbols_to_close:
            try:
                print(f"\n🔴 Đóng bot: {symbol}...")
                
                # Cập nhật CSV
                utils_symbol_csv.update_status(symbol, trading_type)
                update_stop_time(symbol, trading_type)
                
                if self.mode == 'Real-time':
                        # Đóng tất cả vị thế MT5 của symbol
                    orders = mt5.positions_get(symbol=symbol)
                    if orders:
                        for order in orders:
                            close_request = {
                                "action": mt5.TRADE_ACTION_DEAL,
                                "symbol": order.symbol,
                                "volume": order.volume,
                                "position": order.ticket,
                                "type": mt5.ORDER_TYPE_SELL if order.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                                "price": mt5.symbol_info_tick(symbol).bid if order.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask,
                                "deviation": 10,
                                "magic": order.magic,
                                "comment": "Close All Bots",
                            }
                            
                            result = mt5.order_send(close_request)
                            if result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"  ✅ Đóng position {order.ticket} thành công")
                            else:
                                print(f"  ⚠️ Lỗi đóng position {order.ticket}: {result.comment}")
                    else:
                        print(f"  ⚠️ Không tìm thấy position nào cho {symbol}")
                    
                # Dừng trader thread
                trader_key = f"{symbol}_{trading_type}"
                if trader_key in self.live_traders:
                    trader = self.live_traders[trader_key]["trader"]
                    future = self.live_traders[trader_key]["future"]
                    
                    print(f"  🛑 Dừng trader thread {trader_key}...")
                    trader.stop()
                    future.result(timeout=5)
                    
                    # Xóa khỏi dictionary
                    del self.live_traders[trader_key]
                    print(f"  🗑️ Đã xóa {trader_key} khỏi live_traders")
                else:
                    print(f"  ⚠️ Không tìm thấy trader {trader_key} trong live_traders")
                
                closed_count += 1
                print(f"✅ Đã đóng bot {symbol} thành công")
                
            except Exception as e:
                failed_count += 1
                print(f"❌ Lỗi khi đóng bot {symbol}: {str(e)}")
        
        # Xóa tất cả hàng trong bảng
        self.tableWidget.setRowCount(0)
        
        # Thông báo kết quả
        message = f"Đã đóng {closed_count}/{len(symbols_to_close)} bot thành công"
        if failed_count > 0:
            message += f"\n({failed_count} bot gặp lỗi)"
        
        print(f"\n{message}")
        QtWidgets.QMessageBox.information(self, "Kết quả", message)
        
        print("🎯 Hoàn thành đóng tất cả bot!")
        






