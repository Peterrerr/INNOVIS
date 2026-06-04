import sys

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QLineEdit,
    QPushButton, QHBoxLayout
)


def preferred_font_family():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


class LoginDialog(QDialog):
    def __init__(self, auth_manager, parent=None):
        super().__init__(parent)
        self.auth_manager = auth_manager
        font_family = preferred_font_family()
        credentials_ready = self.auth_manager.is_configured()
        self.login_role = None
        self.setWindowTitle("Admin Login")
        self.setModal(True)
        self.setFixedSize(340, 220)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #0A0F16;
                color: #E6EDF3;
                font-family: '{font_family}';
            }}
            QLineEdit {{
                background: #10161D;
                color: #FFF;
                border: 1px solid #304054;
                border-radius: 10px;
                padding: 10px;
            }}
            QPushButton {{
                background: #17212C;
                border: 1px solid #2A3A4D;
                border-radius: 10px;
                padding: 10px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background: #203041;
                color: white;
            }}
        """)

        if credentials_ready:
            title = QLabel("Settings are restricted to authorized users.")
        else:
            title = QLabel("Admin login is disabled until credentials are configured.")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.Password)
        self.password_input.returnPressed.connect(self.try_login)

        self.error_label = QLabel("")
        self.error_label.setStyleSheet("color: #FF6E6E; font-size: 11px;")

        login_button = QPushButton("LOGIN")
        cancel_button = QPushButton("CANCEL")
        login_button.clicked.connect(self.try_login)
        cancel_button.clicked.connect(self.reject)
        login_button.setEnabled(credentials_ready)

        if not credentials_ready:
            self.error_label.setText("Set VISION_ADMIN_PASSWORD (or ADMIN_PASSWORD) before using admin settings.")

        button_layout = QHBoxLayout()
        button_layout.addWidget(cancel_button)
        button_layout.addWidget(login_button)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addWidget(self.username_input)
        layout.addWidget(self.password_input)
        layout.addWidget(self.error_label)
        layout.addStretch()
        layout.addLayout(button_layout)
        self.setLayout(layout)

    def try_login(self):
        if not self.auth_manager.is_configured():
            self.error_label.setText("Admin credentials are not configured in the environment.")
            return

        role = self.auth_manager.verify(self.username_input.text(), self.password_input.text())
        if role is not None:
            self.login_role = role
            self.accept()
            return

        self.error_label.setText("Invalid username or password.")
        self.password_input.selectAll()
        self.password_input.setFocus()
