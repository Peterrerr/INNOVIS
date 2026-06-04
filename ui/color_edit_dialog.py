"""Dialog for creating / editing a custom classification color (HSV range)."""
import sys
import colorsys

from PyQt5.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QSlider, QFrame,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor


def preferred_font_family():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


# OpenCV HSV: H 0-179, S 0-255, V 0-255
_HSV_LIMITS = {"H": (0, 179), "S": (0, 255), "V": (0, 255)}

_STYLE = """
QDialog {{ background: #12181F; font-family: '{font}'; }}
QLabel  {{ color: #C8D8E8; background: transparent; }}
QLineEdit {{
    background: #1C2530; color: #FFF;
    border: 1px solid #3A5068; border-radius: 6px; padding: 6px 10px;
}}
QLineEdit:focus {{ border: 1px solid #5AA0D9; }}
QSlider::groove:horizontal {{
    background: #1C2530; height: 4px; border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: #5AA0D9; width: 14px; height: 14px;
    margin: -5px 0; border-radius: 7px;
}}
QSlider::sub-page:horizontal {{ background: #3A7AAA; border-radius: 2px; }}
QPushButton {{
    background: #1E2A38; color: #C8D8E8;
    border: 1px solid #3A5068; border-radius: 6px;
    padding: 8px 16px; font-weight: bold; font-size: 12px;
}}
QPushButton:hover {{ background: #2A3A50; color: #FFF; }}
QPushButton#save_btn {{
    background: #1A5C35; border: 1px solid #28A060; color: #60F090;
}}
QPushButton#save_btn:hover {{ background: #206840; }}
"""


def _hsv_to_qcolor(h_cv, s_cv, v_cv):
    h = (h_cv / 179.0)
    s = s_cv / 255.0
    v = v_cv / 255.0
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return QColor(int(r * 255), int(g * 255), int(b * 255))


class _HSVRow:
    """One row: channel label + lower slider + upper slider + value labels."""

    def __init__(self, channel, lo_val, hi_val, layout, base_row, callback):
        lo_min, hi_max = _HSV_LIMITS[channel]
        self.channel = channel

        lbl = QLabel(channel)
        lbl.setStyleSheet("font-weight: bold; font-size: 12px; color: #7AAAC8;")
        layout.addWidget(lbl, base_row, 0, Qt.AlignVCenter)

        lo_lbl = QLabel("Low")
        lo_lbl.setStyleSheet("font-size: 10px; color: #6A8AAA;")
        layout.addWidget(lo_lbl, base_row, 1)

        self.lo_slider = QSlider(Qt.Horizontal)
        self.lo_slider.setRange(lo_min, hi_max)
        self.lo_slider.setValue(lo_val)
        self.lo_val_lbl = QLabel(str(lo_val))
        self.lo_val_lbl.setFixedWidth(30)
        self.lo_val_lbl.setStyleSheet("font-size: 11px; color: #90B8D8;")
        self.lo_slider.valueChanged.connect(
            lambda v: (self.lo_val_lbl.setText(str(v)), callback())
        )
        layout.addWidget(self.lo_slider, base_row, 2)
        layout.addWidget(self.lo_val_lbl, base_row, 3)

        hi_lbl = QLabel("High")
        hi_lbl.setStyleSheet("font-size: 10px; color: #6A8AAA;")
        layout.addWidget(hi_lbl, base_row, 4)

        self.hi_slider = QSlider(Qt.Horizontal)
        self.hi_slider.setRange(lo_min, hi_max)
        self.hi_slider.setValue(hi_val)
        self.hi_val_lbl = QLabel(str(hi_val))
        self.hi_val_lbl.setFixedWidth(30)
        self.hi_val_lbl.setStyleSheet("font-size: 11px; color: #90B8D8;")
        self.hi_slider.valueChanged.connect(
            lambda v: (self.hi_val_lbl.setText(str(v)), callback())
        )
        layout.addWidget(self.hi_slider, base_row, 5)
        layout.addWidget(self.hi_val_lbl, base_row, 6)

    def lower(self):
        return self.lo_slider.value()

    def upper(self):
        return self.hi_slider.value()

    def set_values(self, lo, hi):
        self.lo_slider.setValue(lo)
        self.hi_slider.setValue(hi)


class ColorEditDialog(QDialog):
    def __init__(self, name="", lower=None, upper=None, parent=None):
        super().__init__(parent)
        font = preferred_font_family()
        self.setWindowTitle("Edit Color" if name else "Add Color")
        self.setModal(True)
        self.setFixedSize(520, 320)
        self.setStyleSheet(_STYLE.format(font=font))

        self.result_name = None
        self.result_lower = None
        self.result_upper = None

        lower = lower or [0, 100, 100]
        upper = upper or [20, 255, 255]

        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        # name row
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Color Name"))
        self.name_input = QLineEdit(name)
        self.name_input.setPlaceholderText("e.g. Orange, Yellow, White …")
        name_row.addWidget(self.name_input, 1)
        layout.addLayout(name_row)

        divider = QFrame()
        divider.setFrameShape(QFrame.HLine)
        divider.setStyleSheet("background: #2A3A4D; max-height: 1px; border: none;")
        layout.addWidget(divider)

        # HSV sliders
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        self._h = _HSVRow("H", lower[0], upper[0], grid, 0, self._update_preview)
        self._s = _HSVRow("S", lower[1], upper[1], grid, 1, self._update_preview)
        self._v = _HSVRow("V", lower[2], upper[2], grid, 2, self._update_preview)
        layout.addLayout(grid)

        # preview + error
        preview_row = QHBoxLayout()
        preview_lbl = QLabel("Preview")
        preview_lbl.setStyleSheet("font-size: 11px; color: #6A8AAA;")
        self.preview_box = QLabel()
        self.preview_box.setFixedSize(80, 24)
        self.preview_box.setStyleSheet("border-radius: 4px; border: 1px solid #3A5068;")
        self.error_lbl = QLabel("")
        self.error_lbl.setStyleSheet("font-size: 11px; color: #FF6E6E;")
        preview_row.addWidget(preview_lbl)
        preview_row.addWidget(self.preview_box)
        preview_row.addStretch()
        preview_row.addWidget(self.error_lbl)
        layout.addLayout(preview_row)

        # buttons
        btn_row = QHBoxLayout()
        cancel = QPushButton("CANCEL")
        save = QPushButton("SAVE")
        save.setObjectName("save_btn")
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self._save)
        btn_row.addWidget(cancel)
        btn_row.addWidget(save)
        layout.addLayout(btn_row)

        self.setLayout(layout)
        self._update_preview()

    def set_hsv(self, h, s, v):
        """Pre-fill sliders from a sampled pixel (OpenCV HSV values)."""
        margin_h = 10
        margin_s = 50
        margin_v = 50
        self._h.set_values(max(0, h - margin_h), min(179, h + margin_h))
        self._s.set_values(max(0, s - margin_s), min(255, s + margin_s))
        self._v.set_values(max(0, v - margin_v), min(255, v + margin_v))
        self._update_preview()

    def _update_preview(self):
        h_mid = (self._h.lower() + self._h.upper()) // 2
        s_mid = (self._s.lower() + self._s.upper()) // 2
        v_mid = (self._v.lower() + self._v.upper()) // 2
        color = _hsv_to_qcolor(h_mid, s_mid, v_mid)
        self.preview_box.setStyleSheet(
            f"background: {color.name()}; border-radius: 4px; border: 1px solid #3A5068;"
        )

    def _save(self):
        name = self.name_input.text().strip()
        if not name:
            self.error_lbl.setText("Name is required.")
            return
        self.result_name = name
        self.result_lower = [self._h.lower(), self._s.lower(), self._v.lower()]
        self.result_upper = [self._h.upper(), self._s.upper(), self._v.upper()]
        self.accept()
