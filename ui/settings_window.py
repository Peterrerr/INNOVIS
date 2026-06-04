import copy
import sys

from PyQt5.QtCore import Qt, QThread, pyqtSignal as Signal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QPushButton, QRadioButton, QScrollArea, QSlider, QSpinBox, QStackedWidget,
    QVBoxLayout, QWidget,
)

from core.camera_manager import CAMERA_IDS, CAMERA_LABELS, DEFAULT_INDEX_MAP

from core.settings_store import SettingsStore
from algorithms.code_reading import BACKENDS as CODE_BACKENDS
from ui.color_edit_dialog import ColorEditDialog
from ui.defect_ui_widget import DefectWidget


class _CameraScanThread(QThread):
    result_ready = Signal(dict)  # {index: "active" | "available" | "unavailable"}

    def __init__(self, active_index, parent=None):
        super().__init__(parent)
        self._active_index = active_index

    def run(self):
        import cv2
        if sys.platform == "darwin":
            backend = cv2.CAP_AVFOUNDATION
        elif sys.platform.startswith("win"):
            backend = cv2.CAP_DSHOW
        else:
            backend = getattr(cv2, "CAP_V4L2", cv2.CAP_ANY)

        results = {}
        for i in range(4):
            if i == self._active_index:
                results[i] = "active"
                continue
            try:
                cap = cv2.VideoCapture(i, backend)
                found = cap.isOpened()
                cap.release()
                results[i] = "available" if found else "unavailable"
            except Exception:
                results[i] = "unavailable"
        self.result_ready.emit(results)


def preferred_font_family():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


class SettingsWindow(QWidget):
    DETECTION_MODE = 0
    DEFECT_MODE = 1
    CLASSIFICATION_MODE = 2
    CODE_READING_MODE = 3
    COUNT_TRACK_MODE = 4
    CAPTURE_MODE_INDEX = 5
    MEASUREMENT_MODE = 6
    COUNTING_STOP_CAPTURE = 0
    COUNTING_CONVEYOR = 1
    MODE_NAMES = [
        "Detection",
        "Defect Inspection",
        "Classification",
        "Code Reading",
        "Counting / Tracking",
        "Sticker Inspection",
        "Measurement",
    ]

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.settings_store = SettingsStore()
        self.default_hw = {"br": 128, "ct": 32, "ex": 5, "fc": 0, "af": False}
        self.counting_by_mode = self._default_counting_by_mode()
        # Per-camera settings blocks; widgets always reflect self._config_cam,
        # which tracks the primary (big) camera in the live view.
        self._camera_settings = {cid: {} for cid in CAMERA_IDS}
        self._config_cam = CAMERA_IDS[0]
        self._is_loading = True
        font_family = preferred_font_family()

        self.setObjectName("SettingsWindow")
        self.setWindowTitle("Admin Settings")
        self.resize(620, 820)
        self.setStyleSheet(f"""
            QWidget {{
                color: #E6EDF3;
                font-family: '{font_family}';
            }}
            QWidget#SettingsWindow {{
                background-color: #081019;
            }}
            QWidget#SettingsContent, QWidget#ParamPage, QWidget#SettingsViewport {{
                background: transparent;
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            QFrame#HeaderCard {{
                background: #101A25;
                border: 1px solid #22384E;
                border-radius: 20px;
            }}
            QLabel#HeaderTitle {{
                color: #FFFFFF;
                font-size: 26px;
                font-weight: bold;
            }}
            QLabel#HeaderBody {{
                color: #9FB2C6;
                font-size: 13px;
            }}
            QGroupBox {{
                background: #0F1823;
                border: 1px solid #22384E;
                border-radius: 18px;
                margin-top: 22px;
                padding: 18px 16px 16px 16px;
                color: #72D7B1;
                font-size: 13px;
                font-weight: bold;
            }}
            QGroupBox::title {{
                subcontrol-origin: margin;
                subcontrol-position: top left;
                left: 14px;
                padding: 0 6px;
                background: transparent;
            }}
            QLabel#FieldLabel {{
                color: #D8E2EC;
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#ValueBadge, QLabel#StaticValue {{
                background: #0B121A;
                color: #EDF4FB;
                border: 1px solid #2A4158;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 8px;
            }}
            QLabel#ModeValue {{
                background: #0B121A;
                color: #EDF4FB;
                border: 1px solid #2A4158;
                border-radius: 12px;
                font-size: 13px;
                font-weight: bold;
                padding: 12px 14px;
            }}
            QLabel#HintText {{
                color: #95A8BC;
                font-size: 12px;
            }}
            QLabel#NoticeLabel {{
                background: rgba(240, 177, 74, 28);
                color: #F6C76F;
                border: 1px solid rgba(240, 177, 74, 110);
                border-radius: 10px;
                font-size: 12px;
                font-weight: 600;
                padding: 10px 12px;
            }}
            QSlider {{
                min-height: 26px;
            }}
            QSlider::groove:horizontal {{
                border: 1px solid #27435C;
                height: 8px;
                background: #0A1219;
                border-radius: 4px;
                margin: 0 10px;
            }}
            QSlider::sub-page:horizontal {{
                background: #19BE93;
                border: 1px solid #19BE93;
                border-radius: 4px;
                margin: 0 10px;
            }}
            QSlider::add-page:horizontal {{
                background: #0A1219;
                border: 1px solid #27435C;
                border-radius: 4px;
                margin: 0 10px;
            }}
            QSlider::handle:horizontal {{
                background: #D9FFF3;
                border: 3px solid #19BE93;
                width: 14px;
                margin: -8px 0;
                border-radius: 10px;
            }}
            QSlider::handle:horizontal:disabled {{
                background: #7F95A8;
                border-color: #536577;
            }}
            QCheckBox {{
                background: #0D141D;
                color: #D6E1EB;
                border: 1px solid #273B4F;
                border-radius: 12px;
                spacing: 10px;
                padding: 10px 12px;
                font-size: 13px;
                font-weight: 600;
            }}
            QCheckBox:checked {{
                border-color: #2FBF90;
                background: #10221B;
            }}
            QPushButton {{
                background: #162231;
                border: 1px solid #30465F;
                border-radius: 12px;
                padding: 12px 16px;
                font-weight: bold;
                font-size: 12px;
                min-height: 18px;
            }}
            QPushButton:hover {{
                background: #1C2B3D;
                color: white;
            }}
            QPushButton#DangerButton {{
                background: #B33A54;
                border: 1px solid #C24D67;
                color: white;
            }}
            QPushButton#PrimaryButton {{
                background: #1C7C68;
                border: 1px solid #29A286;
                color: white;
            }}
            QPushButton#SecondaryButton {{
                background: #1B2735;
                border: 1px solid #35506B;
                color: #C8DAEC;
            }}
            QComboBox {{
                background: #111A24;
                color: #F5FAFF;
                border: 1px solid #324B63;
                padding: 10px 12px;
                border-radius: 12px;
                font-size: 12px;
                font-weight: bold;
                min-height: 20px;
            }}
            QComboBox QAbstractItemView {{
                background: #101822;
                color: #EAF2FB;
                border: 1px solid #30465F;
                selection-background-color: #1E7F6C;
                selection-color: #FFFFFF;
            }}
            QSpinBox, QLineEdit {{
                background: #0B121A;
                color: #EDF4FB;
                border: 1px solid #2A4158;
                border-radius: 10px;
                font-size: 12px;
                font-weight: bold;
                padding: 6px 8px;
                min-height: 20px;
            }}
            QSpinBox:focus, QLineEdit:focus {{
                border-color: #29A286;
            }}
            QStackedWidget, QScrollArea {{
                background: transparent;
                border: none;
            }}
            QScrollBar:vertical {{
                background: #0C131B;
                width: 12px;
                margin: 4px 2px 4px 2px;
                border-radius: 6px;
            }}
            QScrollBar::handle:vertical {{
                background: #2E4358;
                min-height: 36px;
                border-radius: 6px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
        """)

        def create_field_label(text):
            label = QLabel(text)
            label.setObjectName("FieldLabel")
            return label

        def create_value_badge(text, width=70):
            label = QLabel(str(text))
            label.setAlignment(Qt.AlignCenter)
            label.setObjectName("ValueBadge")
            label.setFixedWidth(width)
            return label

        def create_static_value(text):
            label = create_value_badge(text, width=180)
            label.setObjectName("StaticValue")
            return label

        def create_hint_label(text, object_name="HintText"):
            label = QLabel(text)
            label.setObjectName(object_name)
            label.setWordWrap(True)
            return label

        def create_slider(val, min_v, max_v, callback):
            slider = QSlider(Qt.Horizontal)
            slider.setRange(min_v, max_v)
            slider.setValue(val)
            value_input = QSpinBox()
            value_input.setRange(min_v, max_v)
            value_input.setValue(val)
            value_input.setAlignment(Qt.AlignCenter)
            value_input.setButtonSymbols(QSpinBox.NoButtons)
            value_input.setFixedWidth(96)
            slider._value_input = value_input
            value_input._value_slider = slider
            slider.valueChanged.connect(value_input.setValue)
            value_input.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(callback)
            return slider, value_input

        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        header_title = QLabel("ADMIN SETTINGS")
        header_title.setObjectName("HeaderTitle")
        header_title.setAlignment(Qt.AlignCenter)
        header_layout = QVBoxLayout()
        header_layout.addWidget(header_title)
        header_layout.setContentsMargins(18, 16, 18, 16)
        header_layout.setSpacing(0)
        header_card.setLayout(header_layout)

        self.btn_logout = QPushButton("ADMIN LOGOUT")
        self.btn_logout.setObjectName("DangerButton")
        self.btn_logout.clicked.connect(self.controller.logout_admin)

        mode_group = QGroupBox("OPERATION MODE")
        mode_layout = QVBoxLayout()
        self.mode_selector = QComboBox(self)
        self.mode_selector.addItems(self.MODE_NAMES)
        self.mode_selector.currentIndexChanged.connect(self.on_mode_changed)
        self.mode_selector.hide()
        self.mode_value_label = QLabel("")
        self.mode_value_label.setObjectName("ModeValue")
        self.mode_value_label.setWordWrap(True)
        self.mode_value_label.setAlignment(Qt.AlignCenter)
        mode_layout.addWidget(self.mode_value_label)
        mode_layout.setSpacing(10)
        mode_group.setLayout(mode_layout)

        count_group = QGroupBox("COUNTING METHOD")
        count_layout = QGridLayout()
        self.counting_method_selector = QComboBox()
        self.counting_method_selector.addItems(["Stop & Capture", "Continuous"])
        self.counting_method_selector.currentIndexChanged.connect(self.on_counting_method_changed)
        self.s_track_line, self.l_track_line = create_slider(50, 5, 95, self.on_tracking_params_changed)
        self.s_track_line_x, self.l_track_line_x = create_slider(50, 5, 95, self.on_tracking_params_changed)
        self.s_track_area, self.l_track_area = create_slider(1000, 100, 20000, self.on_tracking_params_changed)
        self.s_track_threshold, self.l_track_threshold = create_slider(100, 0, 255, self.on_tracking_params_changed)
        self.track_polarity_selector = QComboBox()
        self.track_polarity_selector.addItems(["Dark Object", "Light Object"])
        self.track_polarity_selector.currentIndexChanged.connect(self.on_tracking_params_changed)
        self.chk_track_adaptive = QCheckBox("Adaptive Threshold")
        self.chk_track_adaptive.stateChanged.connect(self.on_tracking_params_changed)
        self.s_track_match_dist, self.l_track_match_dist = create_slider(80, 20, 200, self.on_tracking_params_changed)
        self.track_direction_selector = QComboBox()
        self.track_direction_selector.addItems([
            "Both Directions",
            "Top → Bottom",
            "Bottom → Top",
            "Left → Right",
            "Right → Left",
        ])
        self.track_direction_selector.currentIndexChanged.connect(self.on_tracking_params_changed)
        count_layout.addWidget(create_field_label("Method"), 0, 0)
        count_layout.addWidget(self.counting_method_selector, 0, 1, 1, 2)
        count_layout.addWidget(create_field_label("Line Position (%Y)"), 1, 0)
        count_layout.addWidget(self.s_track_line, 1, 1)
        count_layout.addWidget(self.l_track_line, 1, 2)
        count_layout.addWidget(create_field_label("Line Position (%X)"), 2, 0)
        count_layout.addWidget(self.s_track_line_x, 2, 1)
        count_layout.addWidget(self.l_track_line_x, 2, 2)
        count_layout.addWidget(create_field_label("Min Area"), 3, 0)
        count_layout.addWidget(self.s_track_area, 3, 1)
        count_layout.addWidget(self.l_track_area, 3, 2)
        count_layout.addWidget(create_field_label("Threshold"), 4, 0)
        count_layout.addWidget(self.s_track_threshold, 4, 1)
        count_layout.addWidget(self.l_track_threshold, 4, 2)
        count_layout.addWidget(create_field_label("Polarity"), 5, 0)
        count_layout.addWidget(self.track_polarity_selector, 5, 1, 1, 2)
        count_layout.addWidget(self.chk_track_adaptive, 6, 1, 1, 2)
        count_layout.addWidget(create_field_label("Match Distance (px)"), 7, 0)
        count_layout.addWidget(self.s_track_match_dist, 7, 1)
        count_layout.addWidget(self.l_track_match_dist, 7, 2)
        count_layout.addWidget(create_field_label("Count Direction"), 8, 0)
        count_layout.addWidget(self.track_direction_selector, 8, 1, 1, 2)
        count_layout.setColumnStretch(1, 1)
        count_layout.setHorizontalSpacing(12)
        count_layout.setVerticalSpacing(10)
        count_group.setLayout(count_layout)

        hw_group = QGroupBox("CAMERA SETTINGS")
        hw_layout = QGridLayout()
        self.camera_selector = QComboBox()
        self.camera_selector.addItems(["Camera 0", "Camera 1", "Camera 2", "Camera 3"])
        self.camera_selector.currentIndexChanged.connect(self.on_hw_settings_changed)
        self._btn_scan_camera = QPushButton("Scan")
        self._btn_scan_camera.setObjectName("SecondaryButton")
        self._btn_scan_camera.setFixedWidth(72)
        self._btn_scan_camera.setToolTip("Check which device indices have a real camera")
        self._btn_scan_camera.clicked.connect(self._on_scan_cameras)
        self._camera_scan_thread = None

        self.s_bright, self.l_bright = create_slider(128, 0, 255, self.on_hw_settings_changed)
        self.s_contrast, self.l_contrast = create_slider(32, 0, 255, self.on_hw_settings_changed)
        self.s_exposure, self.l_exposure = create_slider(5, 1, 13, self.on_hw_settings_changed)
        self.s_focus, self.l_focus = create_slider(0, 0, 255, self.on_hw_settings_changed)
        self.chk_autofocus = QCheckBox("AUTO FOCUS CAMERA")
        self.chk_autofocus.stateChanged.connect(self.on_hw_settings_changed)
        self.chk_autofocus.stateChanged.connect(self._sync_focus_controls)

        self.btn_hw_default = QPushButton("RESTORE DEFAULTS")
        self.btn_hw_default.setObjectName("SecondaryButton")
        self.btn_hw_default.clicked.connect(self.reset_hw_defaults)

        hw_layout.addWidget(create_field_label("Device"), 0, 0)
        hw_layout.addWidget(self.camera_selector, 0, 1)
        hw_layout.addWidget(self._btn_scan_camera, 0, 2)
        hw_layout.addWidget(create_field_label("Brightness"), 1, 0)
        hw_layout.addWidget(self.s_bright, 1, 1)
        hw_layout.addWidget(self.l_bright, 1, 2)
        hw_layout.addWidget(create_field_label("Contrast"), 2, 0)
        hw_layout.addWidget(self.s_contrast, 2, 1)
        hw_layout.addWidget(self.l_contrast, 2, 2)
        hw_layout.addWidget(create_field_label("Exposure"), 3, 0)
        hw_layout.addWidget(self.s_exposure, 3, 1)
        hw_layout.addWidget(self.l_exposure, 3, 2)
        hw_layout.addWidget(create_field_label("Focus"), 4, 0)
        hw_layout.addWidget(self.s_focus, 4, 1)
        hw_layout.addWidget(self.l_focus, 4, 2)
        hw_layout.addWidget(self.btn_hw_default, 5, 0)
        hw_layout.addWidget(self.chk_autofocus, 5, 1, 1, 2)
        hw_layout.setColumnStretch(1, 1)
        hw_layout.setHorizontalSpacing(12)
        hw_layout.setVerticalSpacing(10)
        hw_group.setLayout(hw_layout)

        multicam_group = self._build_multicam_group(create_field_label)

        roi_group = QGroupBox("DETECTION WINDOW (ROI)")
        roi_layout = QGridLayout()
        self.s_x, self.l_x = create_slider(0, 0, 99, self.on_roi_changed)
        self.s_y, self.l_y = create_slider(0, 0, 99, self.on_roi_changed)
        self.s_w, self.l_w = create_slider(100, 1, 100, self.on_roi_changed)
        self.s_h, self.l_h = create_slider(100, 1, 100, self.on_roi_changed)
        roi_layout.addWidget(create_field_label("X"), 0, 0)
        roi_layout.addWidget(self.s_x, 0, 1)
        roi_layout.addWidget(self.l_x, 0, 2)
        roi_layout.addWidget(create_field_label("Y"), 1, 0)
        roi_layout.addWidget(self.s_y, 1, 1)
        roi_layout.addWidget(self.l_y, 1, 2)
        roi_layout.addWidget(create_field_label("W"), 2, 0)
        roi_layout.addWidget(self.s_w, 2, 1)
        roi_layout.addWidget(self.l_w, 2, 2)
        roi_layout.addWidget(create_field_label("H"), 3, 0)
        roi_layout.addWidget(self.s_h, 3, 1)
        roi_layout.addWidget(self.l_h, 3, 2)
        roi_layout.setColumnStretch(1, 1)
        roi_layout.setHorizontalSpacing(12)
        roi_layout.setVerticalSpacing(10)
        roi_group.setLayout(roi_layout)

        self.param_stack = QStackedWidget()

        page_detection = QWidget()
        page_detection.setObjectName("ParamPage")
        detection_layout = QGridLayout(page_detection)
        detection_layout.setContentsMargins(0, 0, 0, 0)
        self.chk_auto_thresh = QCheckBox("Auto Threshold (Otsu)  — recommended if unsure of the threshold value")
        self.chk_auto_thresh.stateChanged.connect(self.on_detection_params_changed)
        self.chk_auto_thresh.stateChanged.connect(self._sync_thresh_controls)
        self.s_detect_thresh, self.l_detect_thresh = create_slider(127, 0, 255, self.on_detection_params_changed)
        self.s_detect_min, self.l_detect_min = create_slider(500, 10, 500000, self.on_detection_params_changed)
        self.s_detect_max, self.l_detect_max = create_slider(500000, 10, 500000, self.on_detection_params_changed)

        btn_auto_setup = QPushButton("⚡ AUTO SETUP — one click to try")
        btn_auto_setup.setObjectName("PrimaryButton")
        btn_auto_setup.setToolTip("Enable Auto Threshold + widen Min/Max Area to suit typical objects")
        btn_auto_setup.clicked.connect(self._auto_setup_detection)

        detection_layout.addWidget(btn_auto_setup, 0, 0, 1, 3)
        detection_layout.addWidget(self.chk_auto_thresh, 1, 0, 1, 3)
        detection_layout.addWidget(create_field_label("Binary Thresh"), 2, 0)
        detection_layout.addWidget(self.s_detect_thresh, 2, 1)
        detection_layout.addWidget(self.l_detect_thresh, 2, 2)
        detection_layout.addWidget(create_field_label("Min Area"), 3, 0)
        detection_layout.addWidget(self.s_detect_min, 3, 1)
        detection_layout.addWidget(self.l_detect_min, 3, 2)
        detection_layout.addWidget(create_field_label("Max Area"), 4, 0)
        detection_layout.addWidget(self.s_detect_max, 4, 1)
        detection_layout.addWidget(self.l_detect_max, 4, 2)
        detection_layout.setColumnStretch(1, 1)

        self.defect_widget = DefectWidget()
        self.defect_widget.setObjectName("ParamPage")

        page_classification = QWidget()
        page_classification.setObjectName("ParamPage")
        classification_layout = QGridLayout(page_classification)
        classification_layout.setContentsMargins(0, 0, 0, 0)
        classification_layout.setVerticalSpacing(6)

        # --- built-in color checkboxes ---
        self.chk_all_colors = QCheckBox("Detect All Colors")
        self.chk_all_colors.setChecked(True)
        classification_layout.addWidget(self.chk_all_colors, 0, 0, 1, 3)
        self.color_chks = {}
        row, col = 1, 0
        for color_name in ["Red", "Pink", "Purple", "Blue", "Green", "Brown"]:
            chk = QCheckBox(color_name)
            chk.setChecked(True)
            chk.setEnabled(False)
            chk.stateChanged.connect(self.on_classification_selection_changed)
            self.color_chks[color_name] = chk
            classification_layout.addWidget(chk, row, col)
            col += 1
            if col > 2:
                col = 0
                row += 1
        self.chk_all_colors.stateChanged.connect(self.on_classification_selection_changed)

        # --- margin sliders ---
        self.s_class_min_area, self.l_class_min_area = create_slider(350, 50, 20000, self.on_classification_params_changed)
        self.s_class_hue_margin, self.l_class_hue_margin = create_slider(0, 0, 20, self.on_classification_params_changed)
        self.s_class_sat_margin, self.l_class_sat_margin = create_slider(0, 0, 60, self.on_classification_params_changed)
        self.s_class_val_margin, self.l_class_val_margin = create_slider(0, 0, 60, self.on_classification_params_changed)
        classification_layout.addWidget(create_field_label("Min Area"),    row + 1, 0)
        classification_layout.addWidget(self.s_class_min_area,             row + 1, 1)
        classification_layout.addWidget(self.l_class_min_area,             row + 1, 2)
        classification_layout.addWidget(create_field_label("Hue Margin"),  row + 2, 0)
        classification_layout.addWidget(self.s_class_hue_margin,           row + 2, 1)
        classification_layout.addWidget(self.l_class_hue_margin,           row + 2, 2)
        classification_layout.addWidget(create_field_label("Sat Margin"),  row + 3, 0)
        classification_layout.addWidget(self.s_class_sat_margin,           row + 3, 1)
        classification_layout.addWidget(self.l_class_sat_margin,           row + 3, 2)
        classification_layout.addWidget(create_field_label("Val Margin"),  row + 4, 0)
        classification_layout.addWidget(self.s_class_val_margin,           row + 4, 1)
        classification_layout.addWidget(self.l_class_val_margin,           row + 4, 2)

        # --- custom colors section ---
        custom_label = create_field_label("Custom Colors")
        classification_layout.addWidget(custom_label, row + 5, 0, Qt.AlignTop)

        custom_right = QVBoxLayout()
        custom_right.setSpacing(4)
        self.custom_color_list = QListWidget()
        self.custom_color_list.setFixedHeight(90)
        self.custom_color_list.setStyleSheet(
            "QListWidget { background:#0D1318; border:1px solid #2A3A4D; border-radius:6px; color:#C8D8E8; font-size:12px; }"
            "QListWidget::item:selected { background:#1E3A5A; }"
        )
        custom_right.addWidget(self.custom_color_list)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(4)
        self._btn_add_color = QPushButton("+ Add")
        self._btn_pick_color = QPushButton("⊕ Pick from Camera")
        self._btn_edit_color = QPushButton("Edit")
        self._btn_del_color = QPushButton("Delete")
        for btn in (self._btn_add_color, self._btn_pick_color, self._btn_edit_color, self._btn_del_color):
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton{background:#1A2A3A;border:1px solid #2A3A4D;border-radius:5px;"
                "color:#C8D8E8;font-size:11px;padding:0 8px;}"
                "QPushButton:hover{background:#2A3A50;}"
            )
        self._btn_pick_color.setStyleSheet(
            "QPushButton{background:#1A3A2A;border:1px solid #2A6040;border-radius:5px;"
            "color:#60D090;font-size:11px;padding:0 8px;}"
            "QPushButton:hover{background:#1E4A30;}"
        )
        self._btn_add_color.clicked.connect(self._on_add_custom_color)
        self._btn_pick_color.clicked.connect(self._on_pick_color_from_camera)
        self._btn_edit_color.clicked.connect(self._on_edit_custom_color)
        self._btn_del_color.clicked.connect(self._on_delete_custom_color)
        btn_row.addWidget(self._btn_add_color)
        btn_row.addWidget(self._btn_pick_color)
        btn_row.addWidget(self._btn_edit_color)
        btn_row.addWidget(self._btn_del_color)
        custom_right.addLayout(btn_row)

        custom_container = QWidget()
        custom_container.setLayout(custom_right)
        classification_layout.addWidget(custom_container, row + 5, 1, 1, 2)

        self._custom_colors = {}   # {name: {"lower":[], "upper":[]}}

        # wire color sampler signal from dashboard
        self.controller.color_sampled_signal.connect(self._on_color_sampled)
        self._pending_sample = False

        page_code = QWidget()
        page_code.setObjectName("ParamPage")
        code_layout = QGridLayout(page_code)
        code_layout.setContentsMargins(0, 0, 0, 0)
        code_layout.addWidget(create_field_label("Backends"), 0, 0, Qt.AlignTop)
        backend_widget = QWidget()
        backend_vbox = QVBoxLayout(backend_widget)
        backend_vbox.setContentsMargins(0, 0, 0, 0)
        backend_vbox.setSpacing(3)
        any_missing = False
        for name, info in CODE_BACKENDS.items():
            ok = info["available"]
            if not ok:
                any_missing = True
            icon = "✓" if ok else "✗"
            color = "#4AE080" if ok else "#FF6E6E"
            row_label = QLabel(
                f'<span style="color:{color}; font-weight:bold;">{icon}</span>'
                f' <span style="color:#C8D8E8;">{name}</span>'
                f' <span style="color:#6A8AAA; font-size:11px;">— {info["covers"]}</span>'
            )
            row_label.setTextFormat(Qt.RichText)
            backend_vbox.addWidget(row_label)
        if any_missing:
            tip = QLabel(
                '<span style="color:#F0A830; font-size:11px;">'
                'Install missing libraries:  '
                '<b>pip install pyzbar pylibdmtx</b>'
                '</span>'
            )
            tip.setTextFormat(Qt.RichText)
            tip.setWordWrap(True)
            backend_vbox.addWidget(tip)
        code_layout.addWidget(backend_widget, 0, 1, 1, 2)

        self.code_expected_input = QLineEdit()
        self.code_expected_input.setPlaceholderText("Expected QR/Barcode value (optional)")
        self.code_expected_input.textChanged.connect(self.on_code_settings_changed)
        code_layout.addWidget(create_field_label("Expected Code"), 1, 0)
        code_layout.addWidget(self.code_expected_input, 1, 1, 1, 2)

        page_tracking = QWidget()
        page_tracking.setObjectName("ParamPage")
        tracking_layout = QGridLayout(page_tracking)
        tracking_layout.setContentsMargins(0, 0, 0, 0)
        tracking_layout.addWidget(create_hint_label("Counting / Tracking uses the shared COUNTING METHOD settings above."), 0, 0, 1, 3)
        tracking_layout.setColumnStretch(1, 1)

        page_sticker = QWidget()
        page_sticker.setObjectName("ParamPage")
        sticker_layout = QGridLayout(page_sticker)
        sticker_layout.setContentsMargins(0, 0, 0, 0)
        btn_sticker_ref = QPushButton("CHANGE STICKER REFERENCE")
        btn_sticker_ref.setObjectName("PrimaryButton")
        btn_sticker_ref.clicked.connect(lambda: self.controller.set_template_signal.emit())
        self.s_sticker_match, self.l_sticker_match = create_slider(70, 40, 95, self.on_sticker_params_changed)
        self.s_sticker_min_area, self.l_sticker_min_area = create_slider(250, 50, 20000, self.on_sticker_params_changed)
        self.s_sticker_angle, self.l_sticker_angle = create_slider(12, 1, 45, self.on_sticker_params_changed)
        sticker_layout.addWidget(btn_sticker_ref, 0, 0, 1, 3)
        sticker_layout.addWidget(create_hint_label("Current job: place a good part inside the ROI, then update the reference whenever needed."), 1, 0, 1, 3)
        sticker_layout.addWidget(create_field_label("Match Threshold (%)"), 2, 0)
        sticker_layout.addWidget(self.s_sticker_match, 2, 1)
        sticker_layout.addWidget(self.l_sticker_match, 2, 2)
        sticker_layout.addWidget(create_field_label("Min Area (px)"), 3, 0)
        sticker_layout.addWidget(self.s_sticker_min_area, 3, 1)
        sticker_layout.addWidget(self.l_sticker_min_area, 3, 2)
        sticker_layout.addWidget(create_field_label("Max Angle Error (deg)"), 4, 0)
        sticker_layout.addWidget(self.s_sticker_angle, 4, 1)
        sticker_layout.addWidget(self.l_sticker_angle, 4, 2)
        sticker_layout.setColumnStretch(1, 1)

        page_measurement = QWidget()
        page_measurement.setObjectName("ParamPage")
        measurement_layout = QGridLayout(page_measurement)
        measurement_layout.setContentsMargins(0, 0, 0, 0)
        self.s_measure_thresh, self.l_measure_thresh = create_slider(127, 0, 255, self.on_measurement_params_changed)
        self.s_measure_min_area, self.l_measure_min_area = create_slider(500, 10, 50000, self.on_measurement_params_changed)
        self.s_measure_min_w, self.l_measure_min_w = create_slider(0, 0, 5000, self.on_measurement_params_changed)
        self.s_measure_max_w, self.l_measure_max_w = create_slider(9999, 1, 9999, self.on_measurement_params_changed)
        self.s_measure_min_h, self.l_measure_min_h = create_slider(0, 0, 5000, self.on_measurement_params_changed)
        self.s_measure_max_h, self.l_measure_max_h = create_slider(9999, 1, 9999, self.on_measurement_params_changed)
        self._measure_px_per_mm = 0.0
        measurement_layout.addWidget(create_hint_label("Measure object size and check against min/max limits. Calibrate to switch from px to mm."), 0, 0, 1, 3)
        measurement_layout.addWidget(create_field_label("Binary Thresh"), 1, 0)
        measurement_layout.addWidget(self.s_measure_thresh, 1, 1)
        measurement_layout.addWidget(self.l_measure_thresh, 1, 2)
        measurement_layout.addWidget(create_field_label("Min Object Area"), 2, 0)
        measurement_layout.addWidget(self.s_measure_min_area, 2, 1)
        measurement_layout.addWidget(self.l_measure_min_area, 2, 2)
        self._lbl_measure_min_w = create_field_label("Min Width (px)")
        self._lbl_measure_max_w = create_field_label("Max Width (px)")
        self._lbl_measure_min_h = create_field_label("Min Height (px)")
        self._lbl_measure_max_h = create_field_label("Max Height (px)")
        measurement_layout.addWidget(self._lbl_measure_min_w, 3, 0)
        measurement_layout.addWidget(self.s_measure_min_w, 3, 1)
        measurement_layout.addWidget(self.l_measure_min_w, 3, 2)
        measurement_layout.addWidget(self._lbl_measure_max_w, 4, 0)
        measurement_layout.addWidget(self.s_measure_max_w, 4, 1)
        measurement_layout.addWidget(self.l_measure_max_w, 4, 2)
        measurement_layout.addWidget(self._lbl_measure_min_h, 5, 0)
        measurement_layout.addWidget(self.s_measure_min_h, 5, 1)
        measurement_layout.addWidget(self.l_measure_min_h, 5, 2)
        measurement_layout.addWidget(self._lbl_measure_max_h, 6, 0)
        measurement_layout.addWidget(self.s_measure_max_h, 6, 1)
        measurement_layout.addWidget(self.l_measure_max_h, 6, 2)

        # --- calibration section ---
        measurement_layout.addWidget(create_field_label("Calibration"), 7, 0, Qt.AlignTop)
        cal_widget = QWidget()
        cal_layout = QVBoxLayout(cal_widget)
        cal_layout.setContentsMargins(0, 0, 0, 0)
        cal_layout.setSpacing(4)

        ref_row = QHBoxLayout()
        self._cal_ref_input = QSpinBox()
        self._cal_ref_input.setRange(1, 9999)
        self._cal_ref_input.setValue(100)
        self._cal_ref_input.setSuffix(" mm")
        self._cal_ref_input.setFixedWidth(90)
        self._cal_ref_input.setStyleSheet(
            "QSpinBox{background:#1C2530;color:#FFF;border:1px solid #3A5068;"
            "border-radius:6px;padding:4px 8px;}"
        )
        btn_cal_w = QPushButton("Set Width")
        btn_cal_h = QPushButton("Set Height")
        btn_cal_clear = QPushButton("Clear")
        for btn in (btn_cal_w, btn_cal_h, btn_cal_clear):
            btn.setFixedHeight(26)
            btn.setStyleSheet(
                "QPushButton{background:#1A2A3A;border:1px solid #2A3A4D;border-radius:5px;"
                "color:#C8D8E8;font-size:11px;padding:0 8px;}"
                "QPushButton:hover{background:#2A3A50;}"
            )
        btn_cal_clear.setStyleSheet(
            "QPushButton{background:#3A1A1A;border:1px solid #6A2A2A;border-radius:5px;"
            "color:#F08080;font-size:11px;padding:0 8px;}"
            "QPushButton:hover{background:#4A2020;}"
        )
        ref_row.addWidget(QLabel("Ref:"))
        ref_row.addWidget(self._cal_ref_input)
        ref_row.addWidget(btn_cal_w)
        ref_row.addWidget(btn_cal_h)
        ref_row.addWidget(btn_cal_clear)
        ref_row.addStretch()
        cal_layout.addLayout(ref_row)

        self._cal_status_lbl = QLabel("Not calibrated — thresholds in px")
        self._cal_status_lbl.setStyleSheet("font-size:11px; color:#6A8AAA;")
        cal_layout.addWidget(self._cal_status_lbl)
        measurement_layout.addWidget(cal_widget, 7, 1, 1, 2)
        measurement_layout.setColumnStretch(1, 1)

        btn_cal_w.clicked.connect(lambda: self._calibrate("w"))
        btn_cal_h.clicked.connect(lambda: self._calibrate("h"))
        btn_cal_clear.clicked.connect(self._calibrate_clear)

        for page in (page_detection, self.defect_widget, page_classification, page_code, page_tracking, page_sticker, page_measurement):
            self.param_stack.addWidget(page)

        param_group = QGroupBox("ALGORITHM PARAMETERS")
        param_layout = QVBoxLayout()
        param_layout.addWidget(self.param_stack)
        param_layout.setContentsMargins(0, 4, 0, 0)
        param_group.setLayout(param_layout)

        content_layout = QVBoxLayout()
        content_layout.addWidget(header_card)
        content_layout.addWidget(self.btn_logout)
        content_layout.addWidget(mode_group)
        content_layout.addWidget(count_group)
        content_layout.addWidget(hw_group)
        content_layout.addWidget(multicam_group)
        content_layout.addWidget(roi_group)
        content_layout.addWidget(param_group)
        content_layout.addStretch()
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(12)

        content = QWidget()
        content.setObjectName("SettingsContent")
        content.setLayout(content_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("SettingsViewport")
        scroll.setWidget(content)

        outer_layout = QVBoxLayout()
        outer_layout.addWidget(scroll)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        self.setLayout(outer_layout)

        self._apply_saved_settings()
        self._is_loading = False
        self._update_param_stack_height()
        self._sync_focus_controls()
        self.emit_all_settings()
        self._apply_initial_geometry()

    def _default_counting_by_mode(self):
        return {
            self.DETECTION_MODE: {
                "method": self.COUNTING_CONVEYOR,
                "line_y": 50,
                "line_x": 50,
                "min_area": 500,
                "threshold": 100,
                "polarity": "dark",
                "adaptive": False,
                "match_distance": 80,
                "direction": "both",
            },
            self.DEFECT_MODE: {
                "method": self.COUNTING_STOP_CAPTURE,
                "line_y": 50,
                "line_x": 50,
                "min_area": 1000,
                "threshold": 100,
                "polarity": "dark",
                "adaptive": False,
                "match_distance": 80,
                "direction": "both",
            },
            self.CLASSIFICATION_MODE: {
                "method": self.COUNTING_CONVEYOR,
                "line_y": 50,
                "line_x": 50,
                "min_area": 350,
                "threshold": 100,
                "polarity": "dark",
                "adaptive": False,
                "match_distance": 80,
                "direction": "both",
            },
            self.CODE_READING_MODE: {
                "method": self.COUNTING_CONVEYOR,
                "line_y": 50,
                "line_x": 50,
                "min_area": 250,
                "threshold": 100,
                "polarity": "dark",
                "adaptive": False,
                "match_distance": 80,
                "direction": "both",
            },
            self.COUNT_TRACK_MODE: {
                "method": self.COUNTING_CONVEYOR,
                "line_y": 50,
                "line_x": 50,
                "min_area": 1000,
                "threshold": 100,
                "polarity": "dark",
                "adaptive": False,
                "match_distance": 80,
                "direction": "both",
            },
            self.CAPTURE_MODE_INDEX: {
                "method": self.COUNTING_STOP_CAPTURE,
                "line_y": 50,
                "line_x": 50,
                "min_area": 250,
                "threshold": 100,
                "polarity": "dark",
                "adaptive": False,
                "match_distance": 80,
                "direction": "both",
            },
            self.MEASUREMENT_MODE: {
                "method": self.COUNTING_STOP_CAPTURE,
                "line_y": 50,
                "line_x": 50,
                "min_area": 500,
                "threshold": 100,
                "polarity": "dark",
                "adaptive": False,
                "match_distance": 80,
                "direction": "both",
            },
        }

    def _clamp(self, value, min_value, max_value):
        try:
            numeric_value = int(value)
        except (TypeError, ValueError):
            numeric_value = min_value
        return max(min_value, min(max_value, numeric_value))

    def _normalize_roi_values(self, x, y, w, h, changed_control=None):
        x = self._clamp(x, 0, 99)
        y = self._clamp(y, 0, 99)
        w = self._clamp(w, 1, 100)
        h = self._clamp(h, 1, 100)

        if changed_control == self.s_x:
            x = self._clamp(x, 0, 100 - w)
        elif changed_control == self.s_w:
            w = self._clamp(w, 1, 100 - x)
        elif x + w > 100:
            w = self._clamp(100 - x, 1, 100)

        if changed_control == self.s_y:
            y = self._clamp(y, 0, 100 - h)
        elif changed_control == self.s_h:
            h = self._clamp(h, 1, 100 - y)
        elif y + h > 100:
            h = self._clamp(100 - y, 1, 100)

        return x, y, w, h

    def _normalize_roi_controls(self):
        values = (self.s_x.value(), self.s_y.value(), self.s_w.value(), self.s_h.value())
        normalized = self._normalize_roi_values(*values, changed_control=self.sender())
        if values == normalized:
            return

        controls = [self.s_x, self.l_x, self.s_y, self.l_y, self.s_w, self.l_w, self.s_h, self.l_h]

        def apply_values():
            self.s_x.setValue(normalized[0])
            self.s_y.setValue(normalized[1])
            self.s_w.setValue(normalized[2])
            self.s_h.setValue(normalized[3])

        self._set_values_blocked(controls, apply_values)

    def _normalize_detection_area_controls(self):
        min_area = self.s_detect_min.value()
        max_area = self.s_detect_max.value()
        if min_area <= max_area:
            return

        changed_control = self.sender()
        controls = [self.s_detect_min, self.l_detect_min, self.s_detect_max, self.l_detect_max]

        def apply_values():
            if changed_control == self.s_detect_max:
                self.s_detect_min.setValue(max_area)
            else:
                self.s_detect_max.setValue(min_area)

        self._set_values_blocked(controls, apply_values)

    def _normalize_counting_values(self, values, mode_index):
        defaults = self._default_counting_by_mode().get(mode_index, {
            "method": self.COUNTING_CONVEYOR,
            "line_y": 50,
            "min_area": 1000,
            "threshold": 100,
            "polarity": "dark",
            "adaptive": False,
        })
        values = values if isinstance(values, dict) else {}
        method = self._clamp(
            values.get("method", defaults["method"]),
            self.COUNTING_STOP_CAPTURE,
            self.COUNTING_CONVEYOR,
        )
        if mode_index in {self.DEFECT_MODE, self.CAPTURE_MODE_INDEX}:
            method = self.COUNTING_STOP_CAPTURE
        polarity = values.get("polarity", defaults["polarity"])
        if polarity not in {"dark", "light"}:
            polarity = defaults["polarity"]
        direction = values.get("direction", defaults["direction"])
        if direction not in {"both", "down", "up", "right", "left"}:
            direction = defaults["direction"]

        return {
            "method": method,
            "line_y": self._clamp(values.get("line_y", defaults["line_y"]), 5, 95),
            "line_x": self._clamp(values.get("line_x", defaults["line_x"]), 5, 95),
            "min_area": self._clamp(values.get("min_area", defaults["min_area"]), 100, 20000),
            "threshold": self._clamp(values.get("threshold", defaults["threshold"]), 0, 255),
            "polarity": polarity,
            "adaptive": bool(values.get("adaptive", defaults["adaptive"])),
            "match_distance": self._clamp(values.get("match_distance", defaults["match_distance"]), 20, 200),
            "direction": direction,
        }

    def _load_counting_settings(self, settings):
        counting = settings.get("counting", {})
        loaded = self._default_counting_by_mode()

        if isinstance(counting, dict) and isinstance(counting.get("by_mode"), dict):
            for key, values in counting["by_mode"].items():
                try:
                    mode_index = int(key)
                except (TypeError, ValueError):
                    continue
                if 0 <= mode_index < len(self.MODE_NAMES):
                    loaded[mode_index] = self._normalize_counting_values(values, mode_index)
        elif isinstance(counting, dict):
            legacy_values = {
                "method": counting.get("method", self.COUNTING_CONVEYOR),
                "line_y": settings.get("tracking", {}).get("line_y", 50),
                "min_area": settings.get("tracking", {}).get("min_area", 1000),
                "threshold": settings.get("tracking", {}).get("threshold", 100),
                "polarity": settings.get("tracking", {}).get("polarity", "dark"),
                "adaptive": settings.get("tracking", {}).get("adaptive", False),
            }
            for mode_index in loaded:
                loaded[mode_index] = self._normalize_counting_values(legacy_values, mode_index)

        self.counting_by_mode = loaded

    def _current_counting_values(self):
        mode_index = self.mode_selector.currentIndex()
        values = self.counting_by_mode.get(mode_index)
        if values is None:
            values = self._normalize_counting_values({}, mode_index)
            self.counting_by_mode[mode_index] = values
        return values

    def _set_counting_controls_from_mode(self, mode_index):
        values = self.counting_by_mode.get(mode_index)
        if values is None:
            values = self._normalize_counting_values({}, mode_index)
            self.counting_by_mode[mode_index] = values

        controls = [
            self.counting_method_selector,
            self.s_track_line,
            self.l_track_line,
            self.s_track_line_x,
            self.l_track_line_x,
            self.s_track_area,
            self.l_track_area,
            self.s_track_threshold,
            self.l_track_threshold,
            self.track_polarity_selector,
            self.chk_track_adaptive,
            self.s_track_match_dist,
            self.l_track_match_dist,
            self.track_direction_selector,
        ]

        _dir_map = {"both": 0, "down": 1, "up": 2, "right": 3, "left": 4}

        def apply_values():
            self.counting_method_selector.setCurrentIndex(values["method"])
            self.s_track_line.setValue(values["line_y"])
            self.s_track_line_x.setValue(values["line_x"])
            self.s_track_area.setValue(values["min_area"])
            self.s_track_threshold.setValue(values["threshold"])
            self.track_polarity_selector.setCurrentIndex(0 if values["polarity"] == "dark" else 1)
            self.chk_track_adaptive.setChecked(values["adaptive"])
            self.s_track_match_dist.setValue(values["match_distance"])
            self.track_direction_selector.setCurrentIndex(_dir_map.get(values["direction"], 0))

        self._set_values_blocked(controls, apply_values)
        self._normalize_roi_controls()
        self._normalize_detection_area_controls()
        self._sync_counting_controls_enabled()

    def _sync_counting_controls_enabled(self):
        mode_index = self.mode_selector.currentIndex()
        locked_stop_capture = mode_index in {self.DEFECT_MODE, self.CAPTURE_MODE_INDEX}
        if locked_stop_capture and self.counting_method_selector.currentIndex() != self.COUNTING_STOP_CAPTURE:
            self.counting_method_selector.blockSignals(True)
            self.counting_method_selector.setCurrentIndex(self.COUNTING_STOP_CAPTURE)
            self.counting_method_selector.blockSignals(False)

        self.counting_method_selector.setEnabled(not locked_stop_capture)
        continuous_enabled = self.counting_method_selector.currentIndex() == self.COUNTING_CONVEYOR and not locked_stop_capture
        contour_counting_mode = mode_index == self.COUNT_TRACK_MODE
        area_enabled = continuous_enabled or contour_counting_mode
        threshold_enabled = contour_counting_mode
        for control in (self.s_track_line, self.l_track_line, self.s_track_line_x, self.l_track_line_x):
            control.setEnabled(continuous_enabled)
        for control in (self.s_track_area, self.l_track_area):
            control.setEnabled(area_enabled)
        for control in (self.s_track_match_dist, self.l_track_match_dist, self.track_direction_selector):
            control.setEnabled(area_enabled)
        for control in (self.s_track_threshold, self.l_track_threshold, self.track_polarity_selector, self.chk_track_adaptive):
            control.setEnabled(threshold_enabled)

    def _save_current_counting_controls(self):
        mode_index = self.mode_selector.currentIndex()
        _dir_index_map = {0: "both", 1: "down", 2: "up", 3: "right", 4: "left"}
        self.counting_by_mode[mode_index] = {
            "method": self.COUNTING_STOP_CAPTURE
            if mode_index in {self.DEFECT_MODE, self.CAPTURE_MODE_INDEX}
            else self.counting_method_selector.currentIndex(),
            "line_y": self.s_track_line.value(),
            "line_x": self.s_track_line_x.value(),
            "min_area": self.s_track_area.value(),
            "threshold": self.s_track_threshold.value(),
            "polarity": "dark" if self.track_polarity_selector.currentIndex() == 0 else "light",
            "adaptive": self.chk_track_adaptive.isChecked(),
            "match_distance": self.s_track_match_dist.value(),
            "direction": _dir_index_map.get(self.track_direction_selector.currentIndex(), "both"),
        }

    def _apply_initial_geometry(self):
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        available = screen.availableGeometry()
        max_width = max(320, available.width() - 48)
        max_height = max(480, available.height() - 56)
        target_width = min(max_width, max(580, self.sizeHint().width() + 24))
        target_height = min(max_height, max(760, self.sizeHint().height() + 24))
        self.resize(target_width, target_height)
        x = max(available.x() + 20, available.x() + available.width() - target_width - 24)
        y = available.y() + 28
        self.move(x, y)

    def _sync_focus_controls(self):
        autofocus_enabled = self.chk_autofocus.isChecked()
        self.s_focus.setEnabled(not autofocus_enabled)
        self.l_focus.setEnabled(not autofocus_enabled)

    def _update_param_stack_height(self):
        current_page = self.param_stack.currentWidget()
        if current_page is None:
            return
        if current_page is self.defect_widget:
            self.param_stack.setMinimumHeight(0)
            self.param_stack.setMaximumHeight(16777215)
        else:
            self.param_stack.setFixedHeight(current_page.sizeHint().height() + 12)

    def _set_values_blocked(self, controls, apply_values):
        expanded_controls = []
        seen = set()
        for control in controls:
            for linked_control in (control, getattr(control, "_value_input", None), getattr(control, "_value_slider", None)):
                if linked_control is None or id(linked_control) in seen:
                    continue
                expanded_controls.append(linked_control)
                seen.add(id(linked_control))

        for control in expanded_controls:
            control.blockSignals(True)
        apply_values()
        for control in expanded_controls:
            value_input = getattr(control, "_value_input", None)
            if value_input is not None:
                value_input.setValue(control.value())
        for control in expanded_controls:
            control.blockSignals(False)

    def _apply_saved_settings(self):
        settings = self.settings_store.load()
        self._load_counting_settings(settings)
        # Split per-camera blocks out, then overlay the active (primary) camera's
        # block onto the top level so the existing widget-loading code below
        # reads the right values.
        self._init_camera_settings(settings)
        settings = {**settings, **self._camera_settings.get(self._config_cam, {})}
        controls = [
            self.mode_selector, self.counting_method_selector, self.camera_selector, self.s_bright, self.s_contrast,
            self.s_exposure, self.s_focus, self.chk_autofocus, self.s_x, self.s_y,
            self.s_w, self.s_h, self.chk_auto_thresh, self.s_detect_thresh, self.s_detect_min,
            self.s_detect_max, self.s_track_line,
            self.s_track_area, self.s_track_threshold, self.track_polarity_selector,
            self.chk_track_adaptive, self.s_track_match_dist, self.s_track_line_x,
            self.track_direction_selector,
            self.s_sticker_match, self.s_sticker_min_area,
            self.s_sticker_angle, self.chk_all_colors, self.s_class_min_area,
            self.s_class_hue_margin, self.code_expected_input,
            self.s_measure_thresh, self.s_measure_min_area,
            self.s_measure_min_w, self.s_measure_max_w,
            self.s_measure_min_h, self.s_measure_max_h,
            *self.color_chks.values(),
        ]

        def apply_values():
            mode_index = int(settings.get("mode_index", self.CAPTURE_MODE_INDEX))
            self.mode_selector.setCurrentIndex(max(0, min(len(self.MODE_NAMES) - 1, mode_index)))
            self.param_stack.setCurrentIndex(self.mode_selector.currentIndex())
            counting_values = self._current_counting_values()
            self.counting_method_selector.setCurrentIndex(counting_values["method"])
            self.s_track_line.setValue(counting_values["line_y"])
            self.s_track_area.setValue(counting_values["min_area"])
            self.s_track_threshold.setValue(counting_values["threshold"])
            self.track_polarity_selector.setCurrentIndex(0 if counting_values["polarity"] == "dark" else 1)
            self.chk_track_adaptive.setChecked(counting_values["adaptive"])
            self.s_track_line_x.setValue(counting_values["line_x"])
            self.s_track_match_dist.setValue(counting_values["match_distance"])
            _dir_map = {"both": 0, "down": 1, "up": 2, "right": 3, "left": 4}
            self.track_direction_selector.setCurrentIndex(_dir_map.get(counting_values["direction"], 0))

            camera_index = int(settings.get("camera_index", 0))
            self.camera_selector.setCurrentIndex(max(0, min(self.camera_selector.count() - 1, camera_index)))

            self._apply_camera_layout(settings.get("camera_layout", {}))

            camera_settings = settings.get("camera", {})
            self.s_bright.setValue(int(camera_settings.get("brightness", self.default_hw["br"])))
            self.s_contrast.setValue(int(camera_settings.get("contrast", self.default_hw["ct"])))
            self.s_exposure.setValue(int(camera_settings.get("exposure", self.default_hw["ex"])))
            self.s_focus.setValue(int(camera_settings.get("focus", self.default_hw["fc"])))
            self.chk_autofocus.setChecked(bool(camera_settings.get("autofocus", self.default_hw["af"])))

            roi = settings.get("roi", {})
            self.s_x.setValue(int(roi.get("x", self.s_x.value())))
            self.s_y.setValue(int(roi.get("y", self.s_y.value())))
            self.s_w.setValue(int(roi.get("w", self.s_w.value())))
            self.s_h.setValue(int(roi.get("h", self.s_h.value())))

            detection = settings.get("detection", {})
            self.chk_auto_thresh.setChecked(bool(detection.get("auto_threshold", False)))
            self.s_detect_thresh.setValue(int(detection.get("threshold", self.s_detect_thresh.value())))
            self.s_detect_min.setValue(int(detection.get("min_area", self.s_detect_min.value())))
            self.s_detect_max.setValue(int(detection.get("max_area", self.s_detect_max.value())))

            sticker = settings.get("sticker", {})
            self.s_sticker_match.setValue(int(sticker.get("match_percent", self.s_sticker_match.value())))
            self.s_sticker_min_area.setValue(int(sticker.get("min_area", self.s_sticker_min_area.value())))
            self.s_sticker_angle.setValue(int(sticker.get("max_angle_error", self.s_sticker_angle.value())))

            classification = settings.get("classification", {})
            self.s_class_min_area.setValue(int(classification.get("min_area", self.s_class_min_area.value())))
            self.s_class_hue_margin.setValue(int(classification.get("hue_margin", self.s_class_hue_margin.value())))
            self.s_class_sat_margin.setValue(int(classification.get("sat_margin", self.s_class_sat_margin.value())))
            self.s_class_val_margin.setValue(int(classification.get("val_margin", self.s_class_val_margin.value())))
            targets = classification.get("targets", ["All"])
            is_all = "All" in targets
            self.chk_all_colors.setChecked(is_all)
            for name, chk in self.color_chks.items():
                chk.setEnabled(not is_all)
                chk.setChecked(is_all or name in targets)
            self._custom_colors = classification.get("custom_colors", {})

            code = settings.get("code", {})
            self.code_expected_input.setText(str(code.get("expected_value", "")))

            measurement = settings.get("measurement", {})
            self.s_measure_thresh.setValue(int(measurement.get("threshold", self.s_measure_thresh.value())))
            self.s_measure_min_area.setValue(int(measurement.get("min_area", self.s_measure_min_area.value())))
            self._measure_px_per_mm = float(measurement.get("px_per_mm", 0.0))
            self._update_measure_labels()
            self.s_measure_min_w.setValue(int(measurement.get("min_width", self.s_measure_min_w.value())))
            self.s_measure_max_w.setValue(int(measurement.get("max_width", self.s_measure_max_w.value())))
            self.s_measure_min_h.setValue(int(measurement.get("min_height", self.s_measure_min_h.value())))
            self.s_measure_max_h.setValue(int(measurement.get("max_height", self.s_measure_max_h.value())))

        self._set_values_blocked(controls, apply_values)
        self._sync_counting_controls_enabled()
        self._sync_thresh_controls()

    def _config_block_from_widgets(self):
        """Read the per-camera widgets into a settings block (for the camera
        currently being configured / shown as primary)."""
        targets = ["All"] if self.chk_all_colors.isChecked() else [
            name for name, chk in self.color_chks.items() if chk.isChecked()
        ]
        return {
            "camera": {
                "brightness": self.s_bright.value(),
                "contrast": self.s_contrast.value(),
                "exposure": self.s_exposure.value(),
                "focus": self.s_focus.value(),
                "autofocus": self.chk_autofocus.isChecked(),
            },
            "roi": {
                "x": self.s_x.value(),
                "y": self.s_y.value(),
                "w": self.s_w.value(),
                "h": self.s_h.value(),
            },
            "detection": {
                "auto_threshold": self.chk_auto_thresh.isChecked(),
                "threshold": self.s_detect_thresh.value(),
                "min_area": self.s_detect_min.value(),
                "max_area": self.s_detect_max.value(),
            },
            "classification": {
                "targets": targets,
                "min_area": self.s_class_min_area.value(),
                "hue_margin": self.s_class_hue_margin.value(),
                "sat_margin": self.s_class_sat_margin.value(),
                "val_margin": self.s_class_val_margin.value(),
                "custom_colors": self._custom_colors,
            },
            "code": {
                "expected_value": self.code_expected_input.text().strip(),
            },
            "sticker": {
                "match_percent": self.s_sticker_match.value(),
                "min_area": self.s_sticker_min_area.value(),
                "max_angle_error": self.s_sticker_angle.value(),
            },
            "measurement": {
                "threshold": self.s_measure_thresh.value(),
                "min_area": self.s_measure_min_area.value(),
                "min_width": self.s_measure_min_w.value(),
                "max_width": self.s_measure_max_w.value(),
                "min_height": self.s_measure_min_h.value(),
                "max_height": self.s_measure_max_h.value(),
                "px_per_mm": self._measure_px_per_mm,
            },
        }

    def _settings_payload(self):
        self._save_current_counting_controls()
        # Snapshot the currently-edited (primary) camera into its block.
        self._camera_settings[self._config_cam] = self._config_block_from_widgets()
        return {
            "mode_index": self.mode_selector.currentIndex(),
            "counting": {
                "by_mode": {
                    str(mode_index): values
                    for mode_index, values in sorted(self.counting_by_mode.items())
                },
            },
            "camera_index": self.camera_selector.currentIndex(),
            "camera_layout": self.get_camera_layout(),
            "cameras": {cid: self._camera_settings.get(cid, {}) for cid in CAMERA_IDS},
        }

    def _save_current_settings(self):
        if self._is_loading:
            return
        self.settings_store.save(self._settings_payload())

    def get_camera_index(self):
        return self.camera_selector.currentIndex()

    # ---- camera → device mapping + default camera ---------------------- #
    def _build_multicam_group(self, create_field_label):
        """Map each camera slot (Camera 1/2/3) to a device index and pick the
        default (start-up) camera. Cameras are switched one at a time from the
        live panel, so there is no per-camera enable here."""
        group = QGroupBox("Cameras & Devices (default camera)")
        grid = QGridLayout()
        self.cam_index_spin = {}
        self.cam_enable_chk = {}   # kept for compatibility; not shown in single-camera mode
        self.cam_primary_radio = {}
        self.cam_primary_group = QButtonGroup(self)

        grid.addWidget(create_field_label("Camera"), 0, 0)
        grid.addWidget(create_field_label("Device"), 0, 1)
        grid.addWidget(create_field_label("Default"), 0, 2)
        for row, cid in enumerate(CAMERA_IDS, start=1):
            spin = QSpinBox()
            spin.setRange(0, 9)
            spin.setValue(DEFAULT_INDEX_MAP[cid])
            spin.valueChanged.connect(self._on_camera_layout_changed)

            # Enable checkbox is no longer surfaced (single active camera), but
            # the widget still exists so the rest of the code can reference it.
            chk = QCheckBox()
            chk.setChecked(True)

            radio = QRadioButton()
            self.cam_primary_group.addButton(radio, row - 1)
            radio.toggled.connect(self._on_camera_layout_changed)

            self.cam_index_spin[cid] = spin
            self.cam_enable_chk[cid] = chk
            self.cam_primary_radio[cid] = radio

            grid.addWidget(create_field_label(CAMERA_LABELS[cid]), row, 0)
            grid.addWidget(spin, row, 1)
            grid.addWidget(radio, row, 2)

        self.cam_primary_radio[CAMERA_IDS[0]].setChecked(True)
        grid.setColumnStretch(0, 1)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        group.setLayout(grid)
        return group

    def _on_camera_layout_changed(self, *args):
        self._save_current_settings()

    def _apply_camera_layout(self, layout):
        """Load a saved camera_layout block into the multi-camera widgets.
        Falls back to "all cameras enabled" when the saved block is missing or
        uses stale ids (e.g. an older schema) so we never end up with none on."""
        index_map = layout.get("index_map", {})
        enabled = [cid for cid in layout.get("enabled", []) if cid in CAMERA_IDS]
        if not enabled:
            enabled = list(CAMERA_IDS)
        primary = layout.get("primary", CAMERA_IDS[0])
        for cid in CAMERA_IDS:
            self.cam_index_spin[cid].setValue(int(index_map.get(cid, DEFAULT_INDEX_MAP[cid])))
            self.cam_enable_chk[cid].setChecked(cid in enabled)
        if primary not in enabled:
            primary = enabled[0]
        self.cam_primary_radio[primary].setChecked(True)

    def get_camera_layout(self):
        """Return the camera layout for CameraManager.configure(). Single-camera
        mode: every camera is selectable; 'primary' is the default/active one."""
        primary = next(
            (cid for cid in CAMERA_IDS if self.cam_primary_radio[cid].isChecked()),
            CAMERA_IDS[0],
        )
        return {
            "index_map": {cid: self.cam_index_spin[cid].value() for cid in CAMERA_IDS},
            "enabled": list(CAMERA_IDS),
            "primary": primary,
        }

    def set_primary_camera(self, camera_id):
        if camera_id not in self.cam_primary_radio:
            return
        # Set the radio without blocking signals so QButtonGroup exclusivity
        # unchecks the others (blocking it leaves stale checked radios, which
        # makes get_camera_layout() read the wrong primary).
        self.cam_primary_radio[camera_id].setChecked(True)
        # The primary camera is also the one whose settings/training we edit.
        self.set_config_camera(camera_id)
        self._save_current_settings()

    def set_camera_layout(self, enabled=None, primary=None):
        if enabled is not None:
            for cid in CAMERA_IDS:
                chk = self.cam_enable_chk[cid]
                chk.blockSignals(True)
                chk.setChecked(cid in enabled)
                chk.blockSignals(False)
        if primary is not None and primary in self.cam_primary_radio:
            radio = self.cam_primary_radio[primary]
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)
        self._save_current_settings()

    # ---- per-camera settings store ------------------------------------- #
    def _init_camera_settings(self, settings):
        """Populate self._camera_settings from a loaded settings dict and pick
        the config camera (the saved primary)."""
        cameras = settings.get("cameras", {})
        layout = settings.get("camera_layout", {})
        primary = layout.get("primary", CAMERA_IDS[0])
        if primary not in CAMERA_IDS:
            primary = CAMERA_IDS[0]
        self._config_cam = primary
        base = cameras.get(CAMERA_IDS[0], {})
        self._camera_settings = {
            cid: copy.deepcopy(cameras.get(cid, base) or {}) for cid in CAMERA_IDS
        }

    def get_camera_settings(self, cam_id):
        """Return a camera's full settings block (used by CameraManager to seed
        that camera's thread). Captures the latest edits to the active camera."""
        self._camera_settings[self._config_cam] = self._config_block_from_widgets()
        return copy.deepcopy(self._camera_settings.get(cam_id, {}))

    def _per_camera_controls(self):
        return [
            self.s_bright, self.s_contrast, self.s_exposure, self.s_focus, self.chk_autofocus,
            self.s_x, self.s_y, self.s_w, self.s_h,
            self.chk_auto_thresh, self.s_detect_thresh, self.s_detect_min, self.s_detect_max,
            self.s_sticker_match, self.s_sticker_min_area, self.s_sticker_angle,
            self.s_class_min_area, self.s_class_hue_margin, self.s_class_sat_margin,
            self.s_class_val_margin, self.chk_all_colors, self.code_expected_input,
            self.s_measure_thresh, self.s_measure_min_area, self.s_measure_min_w,
            self.s_measure_max_w, self.s_measure_min_h, self.s_measure_max_h,
            *self.color_chks.values(),
        ]

    def _apply_block_to_widgets(self, block):
        """Load a per-camera settings block into the per-camera widgets,
        without emitting change signals (display-only switch of the active cam)."""
        block = block or {}

        def apply_values():
            cam = block.get("camera", {})
            self.s_bright.setValue(int(cam.get("brightness", self.default_hw["br"])))
            self.s_contrast.setValue(int(cam.get("contrast", self.default_hw["ct"])))
            self.s_exposure.setValue(int(cam.get("exposure", self.default_hw["ex"])))
            self.s_focus.setValue(int(cam.get("focus", self.default_hw["fc"])))
            self.chk_autofocus.setChecked(bool(cam.get("autofocus", self.default_hw["af"])))

            roi = block.get("roi", {})
            self.s_x.setValue(int(roi.get("x", self.s_x.value())))
            self.s_y.setValue(int(roi.get("y", self.s_y.value())))
            self.s_w.setValue(int(roi.get("w", self.s_w.value())))
            self.s_h.setValue(int(roi.get("h", self.s_h.value())))

            detection = block.get("detection", {})
            self.chk_auto_thresh.setChecked(bool(detection.get("auto_threshold", False)))
            self.s_detect_thresh.setValue(int(detection.get("threshold", self.s_detect_thresh.value())))
            self.s_detect_min.setValue(int(detection.get("min_area", self.s_detect_min.value())))
            self.s_detect_max.setValue(int(detection.get("max_area", self.s_detect_max.value())))

            sticker = block.get("sticker", {})
            self.s_sticker_match.setValue(int(sticker.get("match_percent", self.s_sticker_match.value())))
            self.s_sticker_min_area.setValue(int(sticker.get("min_area", self.s_sticker_min_area.value())))
            self.s_sticker_angle.setValue(int(sticker.get("max_angle_error", self.s_sticker_angle.value())))

            classification = block.get("classification", {})
            self.s_class_min_area.setValue(int(classification.get("min_area", self.s_class_min_area.value())))
            self.s_class_hue_margin.setValue(int(classification.get("hue_margin", self.s_class_hue_margin.value())))
            self.s_class_sat_margin.setValue(int(classification.get("sat_margin", self.s_class_sat_margin.value())))
            self.s_class_val_margin.setValue(int(classification.get("val_margin", self.s_class_val_margin.value())))
            targets = classification.get("targets", ["All"])
            is_all = "All" in targets
            self.chk_all_colors.setChecked(is_all)
            for name, chk in self.color_chks.items():
                chk.setEnabled(not is_all)
                chk.setChecked(is_all or name in targets)
            self._custom_colors = classification.get("custom_colors", {})

            code = block.get("code", {})
            self.code_expected_input.setText(str(code.get("expected_value", "")))

            measurement = block.get("measurement", {})
            self.s_measure_thresh.setValue(int(measurement.get("threshold", self.s_measure_thresh.value())))
            self.s_measure_min_area.setValue(int(measurement.get("min_area", self.s_measure_min_area.value())))
            self._measure_px_per_mm = float(measurement.get("px_per_mm", 0.0))
            self._update_measure_labels()
            self.s_measure_min_w.setValue(int(measurement.get("min_width", self.s_measure_min_w.value())))
            self.s_measure_max_w.setValue(int(measurement.get("max_width", self.s_measure_max_w.value())))
            self.s_measure_min_h.setValue(int(measurement.get("min_height", self.s_measure_min_h.value())))
            self.s_measure_max_h.setValue(int(measurement.get("max_height", self.s_measure_max_h.value())))

        self._set_values_blocked(self._per_camera_controls(), apply_values)
        self._sync_thresh_controls()

    def set_config_camera(self, camera_id):
        """Switch which camera the settings widgets edit. Snapshots the current
        camera, then loads the selected one. Called when the primary changes."""
        if camera_id not in CAMERA_IDS or camera_id == self._config_cam:
            return
        self._camera_settings[self._config_cam] = self._config_block_from_widgets()
        self._config_cam = camera_id
        self._apply_block_to_widgets(self._camera_settings.get(camera_id, {}))
        self._save_current_settings()

    def set_roi_values(self, x, y, w, h):
        sliders = [self.s_x, self.s_y, self.s_w, self.s_h]

        def apply_values():
            self.s_x.setValue(x)
            self.s_y.setValue(y)
            self.s_w.setValue(w)
            self.s_h.setValue(h)

        self._set_values_blocked(sliders, apply_values)
        self.on_roi_changed()

    def reset_hw_defaults(self):
        self.s_bright.setValue(self.default_hw["br"])
        self.s_contrast.setValue(self.default_hw["ct"])
        self.s_exposure.setValue(self.default_hw["ex"])
        self.s_focus.setValue(self.default_hw["fc"])
        self.chk_autofocus.setChecked(self.default_hw["af"])
        self._sync_focus_controls()
        self.on_hw_settings_changed()

    def emit_all_settings(self):
        self.on_mode_changed()
        self.on_counting_method_changed()
        self.on_hw_settings_changed()
        self.on_roi_changed()
        self.on_detection_params_changed()
        self.on_tracking_params_changed()
        self.on_classification_selection_changed()
        self.on_classification_params_changed()
        self.controller.classification_colors_signal.emit(dict(self._custom_colors))
        self.on_code_settings_changed()
        self.on_sticker_params_changed()
        self.on_measurement_params_changed()
        self.controller.measurement_calibration_signal.emit(self._measure_px_per_mm)

    def on_mode_changed(self):
        idx = self.mode_selector.currentIndex()
        self.param_stack.setCurrentIndex(idx)
        if 0 <= idx < len(self.MODE_NAMES):
            self.mode_value_label.setText(self.MODE_NAMES[idx])
        self._set_counting_controls_from_mode(idx)
        self._update_param_stack_height()
        self.controller.mode_signal.emit(idx)
        self.controller.counting_method_signal.emit(self.counting_method_selector.currentIndex())
        _dir_index_map = {0: "both", 1: "down", 2: "up", 3: "right", 4: "left"}
        self.controller.tracking_params_signal.emit(
            self.s_track_line.value(),
            self.s_track_line_x.value(),
            self.s_track_area.value(),
            self.s_track_threshold.value(),
            "dark" if self.track_polarity_selector.currentIndex() == 0 else "light",
            self.chk_track_adaptive.isChecked(),
            self.s_track_match_dist.value(),
            _dir_index_map.get(self.track_direction_selector.currentIndex(), "both"),
        )
        self._save_current_settings()

    def on_counting_method_changed(self):
        self._save_current_counting_controls()
        self._sync_counting_controls_enabled()
        self.controller.counting_method_signal.emit(self.counting_method_selector.currentIndex())
        self._save_current_settings()

    def on_hw_settings_changed(self):
        self.controller.hw_settings_signal.emit(
            self.s_bright.value(),
            self.s_contrast.value(),
            self.s_exposure.value(),
            self.s_focus.value(),
            self.chk_autofocus.isChecked(),
        )
        self._save_current_settings()

    def on_roi_changed(self):
        self._normalize_roi_controls()
        self.controller.roi_settings_signal.emit(
            self.s_x.value(),
            self.s_y.value(),
            self.s_w.value(),
            self.s_h.value(),
        )
        self._save_current_settings()

    def _auto_setup_detection(self):
        self.chk_auto_thresh.setChecked(True)
        self.s_detect_min.setValue(100)
        self.s_detect_max.setValue(500000)
        self.on_detection_params_changed()

    def _sync_thresh_controls(self):
        auto = self.chk_auto_thresh.isChecked()
        self.s_detect_thresh.setEnabled(not auto)
        self.l_detect_thresh.setEnabled(not auto)

    def on_detection_params_changed(self):
        self._normalize_detection_area_controls()
        self.controller.detection_params_signal.emit(
            self.s_detect_thresh.value(),
            self.s_detect_min.value(),
            self.s_detect_max.value(),
            self.chk_auto_thresh.isChecked(),
        )
        self._save_current_settings()

    def on_tracking_params_changed(self):
        self._save_current_counting_controls()
        _dir_index_map = {0: "both", 1: "down", 2: "up", 3: "right", 4: "left"}
        self.controller.tracking_params_signal.emit(
            self.s_track_line.value(),
            self.s_track_line_x.value(),
            self.s_track_area.value(),
            self.s_track_threshold.value(),
            "dark" if self.track_polarity_selector.currentIndex() == 0 else "light",
            self.chk_track_adaptive.isChecked(),
            self.s_track_match_dist.value(),
            _dir_index_map.get(self.track_direction_selector.currentIndex(), "both"),
        )
        self._save_current_settings()

    def on_classification_selection_changed(self):
        is_all = self.chk_all_colors.isChecked()
        for chk in self.color_chks.values():
            chk.setEnabled(not is_all)
        targets = ["All"] if is_all else [name for name, chk in self.color_chks.items() if chk.isChecked()]
        self.controller.classification_target_signal.emit(targets)
        self._save_current_settings()

    def on_classification_params_changed(self):
        self.controller.classification_params_signal.emit(
            self.s_class_min_area.value(),
            self.s_class_hue_margin.value(),
            self.s_class_sat_margin.value(),
            self.s_class_val_margin.value(),
        )
        self._save_current_settings()

    # --- custom color helpers ---
    def _refresh_custom_color_list(self):
        self.custom_color_list.clear()
        for name, info in self._custom_colors.items():
            item = QListWidgetItem(f"  {name}")
            lo, hi = info["lower"], info["upper"]
            h_mid = (lo[0] + hi[0]) // 2
            s_mid = (lo[1] + hi[1]) // 2
            v_mid = (lo[2] + hi[2]) // 2
            import colorsys
            r, g, b = colorsys.hsv_to_rgb(h_mid / 179, s_mid / 255, v_mid / 255)
            item.setBackground(QColor(int(r * 255), int(g * 255), int(b * 255)))
            text_lum = 0.299 * r + 0.587 * g + 0.114 * b
            item.setForeground(QColor(0, 0, 0) if text_lum > 0.5 else QColor(255, 255, 255))
            self.custom_color_list.addItem(item)
        self.controller.classification_colors_signal.emit(dict(self._custom_colors))
        self._save_current_settings()

    def _on_add_custom_color(self):
        dlg = ColorEditDialog(parent=self)
        if dlg.exec_():
            self._custom_colors[dlg.result_name] = {
                "lower": dlg.result_lower, "upper": dlg.result_upper
            }
            self._refresh_custom_color_list()

    def _on_pick_color_from_camera(self):
        self._pending_sample = True
        self.controller.color_sample_request_signal.emit(True)
        self._btn_pick_color.setText("Click on camera…")
        self._btn_pick_color.setEnabled(False)

    def _on_color_sampled(self, h, s, v):
        if not self._pending_sample:
            return
        self._pending_sample = False
        self.controller.color_sample_request_signal.emit(False)
        self._btn_pick_color.setText("⊕ Pick from Camera")
        self._btn_pick_color.setEnabled(True)
        dlg = ColorEditDialog(parent=self)
        dlg.set_hsv(h, s, v)
        if dlg.exec_():
            self._custom_colors[dlg.result_name] = {
                "lower": dlg.result_lower, "upper": dlg.result_upper
            }
            self._refresh_custom_color_list()

    def _on_edit_custom_color(self):
        item = self.custom_color_list.currentItem()
        if not item:
            return
        name = item.text().strip()
        info = self._custom_colors.get(name)
        if not info:
            return
        dlg = ColorEditDialog(name=name, lower=info["lower"], upper=info["upper"], parent=self)
        if dlg.exec_():
            del self._custom_colors[name]
            self._custom_colors[dlg.result_name] = {
                "lower": dlg.result_lower, "upper": dlg.result_upper
            }
            self._refresh_custom_color_list()

    def _on_delete_custom_color(self):
        item = self.custom_color_list.currentItem()
        if not item:
            return
        name = item.text().strip()
        self._custom_colors.pop(name, None)
        self._refresh_custom_color_list()

    def on_code_settings_changed(self):
        self.controller.code_expected_signal.emit(self.code_expected_input.text().strip())
        self._save_current_settings()

    def on_sticker_params_changed(self):
        self.controller.sticker_params_signal.emit(
            self.s_sticker_match.value(),
            self.s_sticker_min_area.value(),
            self.s_sticker_angle.value(),
        )
        self._save_current_settings()

    def on_measurement_params_changed(self):
        ppm = self._measure_px_per_mm
        def to_px(v): return round(v * ppm) if ppm > 0 else v
        self.controller.measurement_params_signal.emit(
            self.s_measure_thresh.value(),
            self.s_measure_min_area.value(),
            to_px(self.s_measure_min_w.value()),
            to_px(self.s_measure_max_w.value()),
            to_px(self.s_measure_min_h.value()),
            to_px(self.s_measure_max_h.value()),
        )
        self._save_current_settings()

    def _calibrate(self, axis):
        ref_mm = self._cal_ref_input.value()
        if ref_mm <= 0:
            return
        px = self.controller.last_measure_w_px if axis == "w" else self.controller.last_measure_h_px
        if px <= 0:
            self._cal_status_lbl.setText("No object detected — start camera and aim at reference object.")
            self._cal_status_lbl.setStyleSheet("font-size:11px; color:#F0A830;")
            return
        ppm = px / ref_mm
        self._measure_px_per_mm = ppm
        self.controller.measurement_calibration_signal.emit(ppm)
        self._update_measure_labels()
        self.on_measurement_params_changed()

    def _calibrate_clear(self):
        self._measure_px_per_mm = 0.0
        self.controller.measurement_calibration_signal.emit(0.0)
        self._update_measure_labels()
        self.on_measurement_params_changed()

    def _on_scan_cameras(self):
        if self._camera_scan_thread and self._camera_scan_thread.isRunning():
            return
        self._btn_scan_camera.setEnabled(False)
        self._btn_scan_camera.setText("…")
        active = self.camera_selector.currentIndex()
        self._camera_scan_thread = _CameraScanThread(active, self)
        self._camera_scan_thread.result_ready.connect(self._on_scan_result)
        self._camera_scan_thread.start()

    def _on_scan_result(self, results):
        current_idx = self.camera_selector.currentIndex()
        self.camera_selector.blockSignals(True)
        self.camera_selector.clear()
        for i in range(4):
            status = results.get(i, "unavailable")
            if status == "active":
                label = f"Camera {i}  (active)"
            elif status == "available":
                label = f"Camera {i}  ✓"
            else:
                label = f"Camera {i}"
            self.camera_selector.addItem(label)
        self.camera_selector.setCurrentIndex(current_idx)
        self.camera_selector.blockSignals(False)
        self._btn_scan_camera.setEnabled(True)
        self._btn_scan_camera.setText("Scan")

    def _update_measure_labels(self):
        ppm = self._measure_px_per_mm
        if ppm > 0:
            unit = "mm"
            self._cal_status_lbl.setText(f"Calibrated: 1mm = {ppm:.2f}px  ({1/ppm:.3f}mm per pixel)")
            self._cal_status_lbl.setStyleSheet("font-size:11px; color:#4AE080;")
            max_mm = int(9999 / ppm)
            for slider in (self.s_measure_min_w, self.s_measure_max_w,
                           self.s_measure_min_h, self.s_measure_max_h):
                slider.setMaximum(max_mm)
        else:
            unit = "px"
            self._cal_status_lbl.setText("Not calibrated — thresholds in px")
            self._cal_status_lbl.setStyleSheet("font-size:11px; color:#6A8AAA;")
            for slider in (self.s_measure_min_w, self.s_measure_max_w):
                slider.setMaximum(5000)
            for slider in (self.s_measure_min_h, self.s_measure_max_h):
                slider.setMaximum(9999)
        self._lbl_measure_min_w.setText(f"Min Width ({unit})")
        self._lbl_measure_max_w.setText(f"Max Width ({unit})")
        self._lbl_measure_min_h.setText(f"Min Height ({unit})")
        self._lbl_measure_max_h.setText(f"Max Height ({unit})")
