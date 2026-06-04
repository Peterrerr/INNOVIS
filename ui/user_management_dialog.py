import os
import subprocess
import sys

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QFrame
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPalette, QColor


def preferred_font_family():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


STYLE = """
QDialog {{
    background-color: #12181F;
    font-family: '{font}';
}}
QLabel {{
    color: #E6EDF3;
    background: transparent;
}}
QLineEdit {{
    background-color: #1C2530;
    color: #FFFFFF;
    border: 1px solid #3A5068;
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
    min-height: 32px;
    selection-background-color: #2A6496;
}}
QLineEdit:focus {{
    border: 1px solid #5AA0D9;
    background-color: #1E2A38;
}}
QLineEdit:disabled {{
    background-color: #161D26;
    color: #8AA0B8;
    border: 1px solid #2A3A4D;
}}
QLineEdit[placeholderText] {{
    color: #FFFFFF;
}}
QPushButton {{
    background-color: #1E2A38;
    color: #C8D8E8;
    border: 1px solid #3A5068;
    border-radius: 8px;
    padding: 9px 18px;
    font-weight: bold;
    font-size: 12px;
}}
QPushButton:hover {{
    background-color: #2A3A50;
    color: #FFFFFF;
    border: 1px solid #5A80A0;
}}
QPushButton#save_btn {{
    background-color: #1A5C35;
    border: 1px solid #28A060;
    color: #60F090;
}}
QPushButton#save_btn:hover {{
    background-color: #206840;
    color: #FFFFFF;
}}
QPushButton#open_code_btn {{
    background-color: #1A2E4A;
    border: 1px solid #2A5888;
    color: #7EB8F7;
}}
QPushButton#open_code_btn:hover {{
    background-color: #1F3D6B;
    color: #FFFFFF;
    border: 1px solid #4B8DFF;
}}
QFrame#divider {{
    background-color: #2A3A4D;
    max-height: 1px;
    border: none;
}}
"""


class UserManagementDialog(QDialog):
    def __init__(self, auth_manager, parent=None):
        super().__init__(parent)
        self.auth_manager = auth_manager
        font = preferred_font_family()

        self.setWindowTitle("User Management — Dev")
        self.setModal(True)
        self.setFixedSize(440, 530)
        self.setStyleSheet(STYLE.format(font=font))

        # force light placeholder text on macOS
        palette = self.palette()
        palette.setColor(QPalette.PlaceholderText, QColor(140, 170, 200))
        self.setPalette(palette)

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        # header
        header = QLabel("Set Admin Credentials")
        header.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        sub = QLabel("Changes will be saved and take effect immediately.")
        sub.setStyleSheet("font-size: 11px; color: #6A8AAA;")
        sub.setWordWrap(True)

        divider = QFrame()
        divider.setObjectName("divider")
        divider.setFrameShape(QFrame.HLine)

        # current username (read-only display)
        current_label = QLabel("Current admin username")
        current_label.setStyleSheet("font-size: 11px; color: #6A8AAA;")
        self.current_user_display = QLineEdit(self.auth_manager.username)
        self.current_user_display.setDisabled(True)

        # new username
        new_user_label = QLabel("New username")
        new_user_label.setStyleSheet("font-size: 11px; color: #6A8AAA;")
        self.new_username = QLineEdit()
        self.new_username.setPlaceholderText("Leave blank to keep current")

        # new password
        new_pass_label = QLabel("New password")
        new_pass_label.setStyleSheet("font-size: 11px; color: #6A8AAA;")
        self.new_password = QLineEdit()
        self.new_password.setPlaceholderText("Leave blank to keep current")
        self.new_password.setEchoMode(QLineEdit.Password)

        # confirm password
        confirm_label = QLabel("Confirm password")
        confirm_label.setStyleSheet("font-size: 11px; color: #6A8AAA;")
        self.confirm_password = QLineEdit()
        self.confirm_password.setPlaceholderText("Repeat new password")
        self.confirm_password.setEchoMode(QLineEdit.Password)
        self.confirm_password.returnPressed.connect(self.save)

        # status
        self.status_label = QLabel("")
        self.status_label.setStyleSheet("font-size: 11px;")
        self.status_label.setWordWrap(True)

        # dev tools
        dev_divider = QFrame()
        dev_divider.setObjectName("divider")
        dev_divider.setFrameShape(QFrame.HLine)
        open_code_btn = QPushButton("◈  OPEN PROJECT CODE")
        open_code_btn.setObjectName("open_code_btn")
        open_code_btn.clicked.connect(self._open_project_in_editor)

        # buttons
        save_btn = QPushButton("SAVE")
        save_btn.setObjectName("save_btn")
        close_btn = QPushButton("CLOSE")
        save_btn.clicked.connect(self.save)
        close_btn.clicked.connect(self.reject)

        btn_row = QHBoxLayout()
        btn_row.addWidget(close_btn)
        btn_row.addWidget(save_btn)

        layout.addWidget(header)
        layout.addWidget(sub)
        layout.addWidget(divider)
        layout.addWidget(current_label)
        layout.addWidget(self.current_user_display)
        layout.addWidget(new_user_label)
        layout.addWidget(self.new_username)
        layout.addWidget(new_pass_label)
        layout.addWidget(self.new_password)
        layout.addWidget(confirm_label)
        layout.addWidget(self.confirm_password)
        layout.addWidget(self.status_label)
        layout.addWidget(dev_divider)
        layout.addWidget(open_code_btn)
        layout.addLayout(btn_row)
        self.setLayout(layout)

    def save(self):
        new_user = self.new_username.text().strip()
        new_pass = self.new_password.text()
        confirm = self.confirm_password.text()

        if not new_user and not new_pass:
            self._set_status("Nothing to save — fill in username or password.", error=True)
            return

        if new_pass and new_pass != confirm:
            self._set_status("Passwords do not match.", error=True)
            self.confirm_password.selectAll()
            self.confirm_password.setFocus()
            return

        username = new_user if new_user else self.auth_manager.username
        password = new_pass if new_pass else None

        ok, msg = self.auth_manager.set_admin_credentials(username, password)
        if ok:
            self.current_user_display.setText(self.auth_manager.username)
            self.new_username.clear()
            self.new_password.clear()
            self.confirm_password.clear()
            self._set_status("Saved successfully.", error=False)
        else:
            self._set_status(f"Error: {msg}", error=True)

    def _open_project_in_editor(self):
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if sys.platform == "darwin":
            for cli in ("/usr/local/bin/code", "/usr/bin/code", "/opt/homebrew/bin/code"):
                if os.path.exists(cli):
                    subprocess.Popen([cli, project_dir])
                    return
            if os.path.exists("/Applications/Visual Studio Code.app"):
                subprocess.Popen(["open", "-a", "Visual Studio Code", project_dir])
            else:
                subprocess.Popen(["open", project_dir])
        elif sys.platform == "win32":
            try:
                subprocess.Popen(["code", project_dir], shell=True)
            except FileNotFoundError:
                subprocess.Popen(["explorer", project_dir])
        else:
            subprocess.Popen(["xdg-open", project_dir])

    def _set_status(self, text, error=True):
        color = "#FF6E6E" if error else "#4AE080"
        self.status_label.setStyleSheet(f"font-size: 11px; color: {color};")
        self.status_label.setText(text)
