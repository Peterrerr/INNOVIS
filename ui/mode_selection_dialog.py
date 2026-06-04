import sys

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QMenu, QPushButton,
    QSizePolicy, QToolButton, QVBoxLayout,
)


def preferred_font_family():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


class ModeTile(QFrame):
    def __init__(self, title, mode_indices, mode_names, select_callback, parent=None):
        super().__init__(parent)
        self.mode_indices = list(mode_indices)
        self.mode_names = mode_names
        self.select_callback = select_callback
        self.menu = None

        self.setObjectName("ModeTile")
        self.setProperty("selected", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.title_button = QPushButton(title)
        self.title_button.setObjectName("ModeTileButton")
        self.title_button.setCursor(Qt.PointingHandCursor)
        self.title_button.clicked.connect(self._handle_primary_click)
        self.title_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        layout = QHBoxLayout()
        layout.addWidget(self.title_button, 1)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        if len(self.mode_indices) > 1:
            self.menu = self._create_menu()
            self.menu_button = QToolButton()
            self.menu_button.setObjectName("ModeMenuButton")
            self.menu_button.setArrowType(Qt.DownArrow)
            self.menu_button.setCursor(Qt.PointingHandCursor)
            self.menu_button.clicked.connect(self._show_menu)
            self.menu_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
            self.menu_button.setFixedWidth(58)
            layout.addWidget(self.menu_button)

        self.setLayout(layout)

    def _create_menu(self):
        menu = QMenu(self)
        for mode_index in self.mode_indices:
            action = menu.addAction(self.mode_names[mode_index])
            action.triggered.connect(lambda _checked=False, index=mode_index: self.select_callback(index))
        return menu

    def _handle_primary_click(self):
        if self.menu:
            self._show_menu()
            return
        self.select_callback(self.mode_indices[0])

    def _show_menu(self):
        if self.menu:
            self.menu.popup(self.mapToGlobal(self.rect().bottomLeft()))

    def set_selected(self, selected):
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()


class ModeSelectionDialog(QDialog):
    DETECTION_MODE = 0
    DEFECT_MODE = 1
    CLASSIFICATION_MODE = 2
    CODE_READING_MODE = 3
    COUNT_TRACK_MODE = 4
    STICKER_MODE = 5
    MEASUREMENT_MODE = 6

    def __init__(self, mode_names, current_index=0, parent=None):
        super().__init__(parent)
        self.mode_names = list(mode_names)
        self.selected_mode = self._normalized_index(current_index)
        self.mode_tiles = []
        font_family = preferred_font_family()

        self.setWindowTitle("Select Mode")
        self.setModal(True)
        self.setMinimumSize(700, 500)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #12161C;
                color: #EAF0F6;
                font-family: '{font_family}';
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            QLabel#TitleLabel {{
                color: #F7FAFC;
                font-size: 30px;
                font-weight: bold;
            }}
            QFrame#ModeTile {{
                background: #1C232D;
                border: 1px solid #344050;
                border-radius: 14px;
            }}
            QFrame#ModeTile:hover {{
                background: #263241;
                border-color: #5B6B80;
            }}
            QFrame#ModeTile[selected="true"] {{
                background: #1F4E8C;
                border-color: #4B8DFF;
            }}
            QPushButton#ModeTileButton {{
                background: transparent;
                border: none;
                color: #F7FAFC;
                font-size: 19px;
                font-weight: bold;
                min-height: 96px;
                padding: 16px 20px;
                text-align: center;
            }}
            QPushButton#ModeTileButton:hover {{
                background: transparent;
                color: white;
            }}
            QToolButton#ModeMenuButton {{
                background: rgba(255, 255, 255, 18);
                border: none;
                border-left: 1px solid #344050;
                border-top-right-radius: 14px;
                border-bottom-right-radius: 14px;
                color: #F7FAFC;
                min-height: 96px;
            }}
            QToolButton#ModeMenuButton:hover {{
                background: rgba(255, 255, 255, 32);
                border-left-color: #5B6B80;
            }}
            QPushButton {{
                background: #1C232D;
                border: 1px solid #344050;
                border-radius: 10px;
                padding: 12px 16px;
                font-weight: bold;
                font-size: 13px;
                min-height: 22px;
            }}
            QPushButton:hover {{
                background: #263241;
                border-color: #5B6B80;
                color: white;
            }}
            QPushButton#ExitButton {{
                background: #191F27;
                color: #C7D1DC;
                min-width: 120px;
            }}
            QMenu {{
                background: #171D26;
                border: 1px solid #435267;
                border-radius: 8px;
                padding: 6px;
            }}
            QMenu::item {{
                color: #F7FAFC;
                font-size: 15px;
                font-weight: bold;
                padding: 12px 28px;
                border-radius: 6px;
            }}
            QMenu::item:selected {{
                background: #1F4E8C;
            }}
        """)

        title = QLabel("SELECT MODE")
        title.setObjectName("TitleLabel")
        title.setAlignment(Qt.AlignCenter)

        mode_grid = QGridLayout()
        mode_grid.setHorizontalSpacing(14)
        mode_grid.setVerticalSpacing(14)
        mode_grid.setColumnStretch(0, 1)
        mode_grid.setColumnStretch(1, 1)

        groups = list(self._mode_groups())
        for i, (title_index, mode_indices) in enumerate(groups):
            tile = ModeTile(
                self.mode_names[title_index],
                mode_indices,
                self.mode_names,
                self._select_mode,
                self,
            )
            self.mode_tiles.append(tile)
            row = i // 2
            col = i % 2
            mode_grid.addWidget(tile, row, col)
            mode_grid.setRowStretch(row, 1)

        cancel_button = QPushButton("EXIT")
        cancel_button.setObjectName("ExitButton")
        cancel_button.clicked.connect(self.reject)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        button_layout.addWidget(cancel_button)

        layout = QVBoxLayout()
        layout.addWidget(title)
        layout.addSpacing(18)
        layout.addLayout(mode_grid, 1)
        layout.addSpacing(4)
        layout.addLayout(button_layout)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        self.setLayout(layout)
        self._update_button_states()

    def _mode_groups(self):
        groups = [
            (self.DETECTION_MODE, [self.DETECTION_MODE, self.STICKER_MODE]),
            (self.DEFECT_MODE, [self.DEFECT_MODE]),
            (self.CLASSIFICATION_MODE, [self.CLASSIFICATION_MODE]),
            (self.CODE_READING_MODE, [self.CODE_READING_MODE]),
            (self.COUNT_TRACK_MODE, [self.COUNT_TRACK_MODE]),
            (self.MEASUREMENT_MODE, [self.MEASUREMENT_MODE]),
        ]
        return [
            (title_index, [index for index in indices if index < len(self.mode_names)])
            for title_index, indices in groups
            if title_index < len(self.mode_names)
        ]

    def _normalized_index(self, index):
        if not self.mode_names:
            return 0
        return max(0, min(len(self.mode_names) - 1, int(index)))

    def _select_mode(self, index):
        self.selected_mode = self._normalized_index(index)
        self._update_button_states()
        self.accept()

    def _update_button_states(self):
        for tile in self.mode_tiles:
            tile.set_selected(self.selected_mode in tile.mode_indices)

    def accept(self):
        super().accept()
