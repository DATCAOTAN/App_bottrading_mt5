
from PyQt5.QtWidgets import QMessageBox
def show_message(title, message, icon=QMessageBox.Information):
        """Hiển thị hộp thoại thông báo với biểu tượng tùy chọn."""
        msg = QMessageBox()
        msg.setWindowTitle(title)
        msg.setText(message)
        msg.setIcon(icon)
        msg.exec_()
