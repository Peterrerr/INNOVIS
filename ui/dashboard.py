import os
import re
import sys
import subprocess
from PyQt5.QtWidgets import (
    QLabel, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFrame, QPushButton, QSizePolicy
)
from PyQt5.QtCore import Qt, pyqtSignal

from core.auth_manager import AuthManager
from ui.login_dialog import LoginDialog
from ui.settings_window import SettingsWindow
from ui.user_management_dialog import UserManagementDialog


def preferred_font_family():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


def preferred_mono_font_family():
    if sys.platform == "darwin":
        return "Menlo"
    if sys.platform == "win32":
        return "Consolas"
    return "DejaVu Sans Mono"


def hex_to_rgb(color):
    color = color.lstrip("#")
    if len(color) == 3:
        color = "".join(channel * 2 for channel in color)
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


class DashboardWindow(QWidget):
    start_camera_signal = pyqtSignal(int)
    stop_signal = pyqtSignal()
    hw_settings_signal = pyqtSignal(int, int, int, int, bool)
    roi_settings_signal = pyqtSignal(int, int, int, int)
    mode_signal = pyqtSignal(int)
    counting_method_signal = pyqtSignal(int)
    detection_params_signal = pyqtSignal(int, int, int, bool)
    tracking_params_signal = pyqtSignal(int, int, int, int, str, bool, int, str)
    sticker_params_signal = pyqtSignal(int, int, int)
    measurement_params_signal = pyqtSignal(int, int, int, int, int, int)
    measurement_calibration_signal = pyqtSignal(float)
    capture_image_signal = pyqtSignal()
    reset_signal = pyqtSignal()
    exit_signal = pyqtSignal()
    change_mode_signal = pyqtSignal()
    set_template_signal = pyqtSignal()
    classification_target_signal = pyqtSignal(list)
    classification_params_signal = pyqtSignal(int, int, int, int)
    classification_colors_signal = pyqtSignal(dict)
    color_sample_request_signal = pyqtSignal(bool)
    color_sampled_signal = pyqtSignal(int, int, int)
    code_expected_signal = pyqtSignal(str)
    admin_state_signal = pyqtSignal(bool)
    # Forwarded from DefectWidget after capture_and_inspect.
    defect_inspection_signal = pyqtSignal(str, int, str)  # (status, defect_count, confidence)

    def __init__(self):
        super().__init__()
        self.auth_manager = AuthManager()
        self.settings_window = SettingsWindow(self)
        self.camera_panel = None
        self.is_authenticated = False
        self.current_mode = self.settings_window.mode_selector.currentIndex()
        self.current_counting_method = self.settings_window.counting_method_selector.currentIndex()
        self.fg_count = 0
        self.ng_count = 0
        # Per-camera FG/NG tallies + each camera's latest result class, used to
        # show a per-camera breakdown and a combined PASS/FAIL verdict.
        self.cam_fg = {}
        self.cam_ng = {}
        self.cam_last_class = {}
        self.current_result_color = None
        self.last_measure_w_px = 0
        self.last_measure_h_px = 0
        font_family = preferred_font_family()
        mono_font_family = preferred_mono_font_family()

        self.setWindowTitle("Vision System Pro - Operator Console")
        self.setGeometry(120, 50, 1500, 860)
        self.setMinimumSize(1200, 760)
        self.setStyleSheet(f"""
            QWidget {{
                background-color: #0A0F16;
                color: #E6EDF3;
                font-family: '{font_family}';
            }}
            QLabel {{
                background: transparent;
                border: none;
            }}
            QFrame#SurfaceCard {{
                background: #111821;
                border: 1px solid #233244;
                border-radius: 18px;
            }}
            QFrame#MetricCard {{
                background: #0E151D;
                border: 1px solid #223040;
                border-radius: 16px;
            }}
            QLabel#SectionLabel {{
                color: #91A4B7;
                font-size: 11px;
                font-weight: bold;
            }}
            QLabel#ResultTag {{
                background: #16212C;
                color: #D5E2EE;
                border: 1px solid #314557;
                border-radius: 7px;
                font-size: 10px;
                font-weight: bold;
                padding: 4px 10px;
            }}
            QLabel#PanelTitle {{
                color: #FFFFFF;
                font-size: 24px;
                font-weight: bold;
            }}
            QLabel#PanelSubtitle {{
                color: #9FB0C2;
                font-size: 12px;
            }}
            QLabel#ResultHint {{
                background: transparent;
                border: none;
                color: #93A4B4;
                font-size: 13px;
                padding: 0 10px 2px 10px;
            }}
            QLabel#ResultValue {{
                background: #121A23;
                border: 1px solid #304255;
                border-radius: 24px;
                font-size: 20px;
                font-weight: bold;
                padding: 16px 20px;
            }}
            QPushButton {{
                background: #17212C;
                border: 1px solid #2A3A4D;
                border-radius: 12px;
                padding: 14px;
                font-weight: bold;
                font-size: 12px;
                min-height: 24px;
            }}
            QPushButton:hover {{
                background: #203041;
                color: white;
            }}
            QPushButton:disabled {{
                color: #607284;
                background: #121922;
                border-color: #1A2531;
            }}
        """)

        self.indicator = QLabel()
        self.indicator.setFixedSize(10, 10)
        self.indicator.setStyleSheet("background-color: #607284; border-radius: 5px;")

        self.label_panel_title = QLabel("OPERATOR CONSOLE")
        self.label_panel_title.setObjectName("PanelTitle")
        self.label_panel_subtitle = QLabel("Core vision functions screen")
        self.label_panel_subtitle.setObjectName("PanelSubtitle")

        self.label_result_title = QLabel("CURRENT RESULT")
        self.label_result_title.setObjectName("ResultTag")
        self.label_result_title.setFrameShape(QFrame.NoFrame)
        self.label_result_value = QLabel("SYSTEM READY")
        self.label_result_value.setObjectName("ResultValue")
        self.label_result_value.setAlignment(Qt.AlignCenter)
        self.label_result_value.setWordWrap(False)
        self.label_result_value.setFrameShape(QFrame.NoFrame)
        # Fixed height so the value box always occupies exactly one row and can
        # never grow over the hint below it (a Mac-only overlap was seen here).
        self.label_result_value.setFixedHeight(78)
        self.label_result_value.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.label_result_hint = QLabel("Press START CAMERA to begin inspection.")
        self.label_result_hint.setAlignment(Qt.AlignCenter)
        self.label_result_hint.setWordWrap(True)
        self.label_result_hint.setObjectName("ResultHint")
        self.label_result_hint.setFrameShape(QFrame.NoFrame)
        self.label_result_hint.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        self.label_result_hint.setMinimumHeight(20)
        self.label_result_hint.setStyleSheet(
            "border: 0px; background: transparent; color: #93A4B4; font-size: 13px; padding: 0 10px 2px 10px;"
        )

        result_header = QHBoxLayout()
        result_header.addWidget(self.indicator)
        result_header.addWidget(self.label_result_title)
        result_header.addStretch()
        result_header.setSpacing(10)

        result_layout = QVBoxLayout()
        result_layout.addLayout(result_header)
        result_layout.addWidget(self.label_result_value)
        result_layout.addWidget(self.label_result_hint)
        result_layout.setContentsMargins(18, 16, 18, 16)
        result_layout.setSpacing(10)

        self.result_card = QFrame()
        self.result_card.setObjectName("ResultCard")
        self.result_card.setLayout(result_layout)

        def create_metric_box(title, color):
            box = QFrame()
            box.setObjectName("MetricCard")
            layout = QVBoxLayout()
            title_label = QLabel(title)
            title_label.setAlignment(Qt.AlignCenter)
            title_label.setObjectName("SectionLabel")
            value_label = QLabel("0")
            value_label.setAlignment(Qt.AlignCenter)
            value_label.setStyleSheet(
                f"color: {color}; font-size: 38px; font-weight: bold; font-family: '{mono_font_family}'; padding: 4px;"
            )
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(4)
            layout.addWidget(title_label)
            layout.addWidget(value_label)
            box.setLayout(layout)
            return box, value_label

        total_box, self.val_total = create_metric_box("TOTAL COUNT", "#4CAF50")
        fg_box, self.val_fg = create_metric_box("FG", "#00C853")
        ng_box, self.val_ng = create_metric_box("NG", "#FF5252")

        stats_layout = QHBoxLayout()
        stats_layout.addWidget(total_box)
        stats_layout.addWidget(fg_box)
        stats_layout.addWidget(ng_box)
        stats_layout.setSpacing(12)

        # Combined verdict across all enabled cameras + a per-camera breakdown.
        self.combined_verdict = QLabel("All cameras: —")
        self.combined_verdict.setAlignment(Qt.AlignCenter)
        self.combined_verdict.setStyleSheet(
            "color:#90A4AE; font-size:13px; font-weight:bold; padding:4px; "
            "border:1px solid #29405A; border-radius:8px; background:#0C1219;"
        )
        self.cam_breakdown = QLabel("")
        self.cam_breakdown.setAlignment(Qt.AlignCenter)
        self.cam_breakdown.setWordWrap(True)
        self.cam_breakdown.setStyleSheet("color:#8CA2B8; font-size:11px; padding:2px;")

        self.btn_start = QPushButton("START CAMERA")
        self.btn_start.setStyleSheet(
            "QPushButton { background: #1F6F3D; color: white; border: 1px solid #2C8C4F; } "
            "QPushButton:hover { background: #2C8C4F; } "
            "QPushButton:disabled { background: #132117; color: #6E8375; border: 1px solid #1C3828; }"
        )
        self.btn_stop = QPushButton("STOP")
        self.btn_stop.setStyleSheet(
            "QPushButton { background: #9C2C2C; color: white; border: 1px solid #B53B3B; } "
            "QPushButton:hover { background: #B53B3B; } "
            "QPushButton:disabled { background: #251414; color: #8A6A6A; border: 1px solid #3B2020; }"
        )
        self.btn_capture = QPushButton("CAPTURE IMAGE")
        self.btn_capture.setStyleSheet(
            "QPushButton { background: #145A9A; color: white; border: 1px solid #1D74BF; } "
            "QPushButton:hover { background: #1D74BF; } "
            "QPushButton:disabled { background: #132234; color: #6E8298; border: 1px solid #203A55; }"
        )
        self.btn_reset = QPushButton("RESET DATA")
        self.btn_open = QPushButton("OPEN LOGS")
        self.btn_open_captures = QPushButton("OPEN CAPTURES")
        self.btn_change_mode = QPushButton("←  SELECT MODE")
        self.btn_change_mode.setStyleSheet(
            "QPushButton { background: #1A2B4A; color: #7EB8F7; border: 1px solid #2A4870; } "
            "QPushButton:hover { background: #1F3D6B; color: white; border-color: #4B8DFF; }"
        )
        self.btn_settings = QPushButton("ADMIN LOGIN")
        self.btn_exit = QPushButton("EXIT SYSTEM")

        operation_label = QLabel("OPERATION")
        operation_label.setObjectName("SectionLabel")
        operation_layout = QGridLayout()
        operation_layout.addWidget(self.btn_start, 0, 0)
        operation_layout.addWidget(self.btn_stop, 0, 1)
        operation_layout.addWidget(self.btn_capture, 1, 0, 1, 2)
        operation_layout.setHorizontalSpacing(10)
        operation_layout.setVerticalSpacing(10)

        records_label = QLabel("DATA AND HISTORY")
        records_label.setObjectName("SectionLabel")
        records_layout = QGridLayout()
        records_layout.addWidget(self.btn_reset, 0, 0)
        records_layout.addWidget(self.btn_open, 0, 1)
        records_layout.addWidget(self.btn_open_captures, 1, 0, 1, 2)
        records_layout.setHorizontalSpacing(10)
        records_layout.setVerticalSpacing(10)

        system_label = QLabel("SYSTEM")
        system_label.setObjectName("SectionLabel")
        system_layout = QGridLayout()
        system_layout.addWidget(self.btn_change_mode, 0, 0, 1, 2)
        system_layout.addWidget(self.btn_settings, 1, 0)
        system_layout.addWidget(self.btn_exit, 1, 1)
        system_layout.setHorizontalSpacing(10)
        system_layout.setVerticalSpacing(10)

        control_layout = QVBoxLayout()
        control_layout.addWidget(self.label_panel_title)
        control_layout.addWidget(self.label_panel_subtitle)
        control_layout.addSpacing(6)
        control_layout.addWidget(self.result_card)
        control_layout.addLayout(stats_layout)
        control_layout.addWidget(self.combined_verdict)
        control_layout.addWidget(self.cam_breakdown)
        control_layout.addSpacing(8)
        control_layout.addWidget(operation_label)
        control_layout.addLayout(operation_layout)
        control_layout.addSpacing(4)
        control_layout.addWidget(records_label)
        control_layout.addLayout(records_layout)
        control_layout.addSpacing(4)
        control_layout.addWidget(system_label)
        control_layout.addLayout(system_layout)
        control_layout.addStretch()
        control_layout.setContentsMargins(20, 20, 20, 20)
        control_layout.setSpacing(10)

        control_panel = QFrame()
        control_panel.setObjectName("SurfaceCard")
        control_panel.setLayout(control_layout)
        control_panel.setMinimumWidth(420)
        control_panel.setMaximumWidth(520)

        self.camera_container = QFrame()
        self.camera_container.setObjectName("SurfaceCard")
        self.camera_container_layout = QVBoxLayout()
        self.camera_container_layout.setContentsMargins(10, 10, 10, 10)
        self.camera_container_layout.setSpacing(0)
        self.camera_placeholder = QLabel("LIVE CAMERA PANEL")
        self.camera_placeholder.setAlignment(Qt.AlignCenter)
        self.camera_placeholder.setStyleSheet(
            "color:#6E7F92; font-size:24px; font-weight:bold; "
            "background:#060A10; border:1px dashed #29405A; border-radius:14px;"
        )
        self.camera_container_layout.addWidget(self.camera_placeholder)
        self.camera_container.setLayout(self.camera_container_layout)

        shell_layout = QHBoxLayout()
        shell_layout.addWidget(self.camera_container, 3)
        shell_layout.addWidget(control_panel, 1)
        shell_layout.setContentsMargins(15, 15, 15, 15)
        shell_layout.setSpacing(15)
        self.setLayout(shell_layout)

        self.btn_start.clicked.connect(self.emit_start_camera)
        self.btn_stop.clicked.connect(self.stop_signal.emit)
        self.btn_capture.clicked.connect(self.capture_image_signal.emit)
        self.btn_reset.clicked.connect(self.handle_reset)
        self.btn_open.clicked.connect(self.open_log_folder)
        self.btn_open_captures.clicked.connect(self.open_capture_folder)
        self.btn_change_mode.clicked.connect(self.change_mode_signal.emit)
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_exit.clicked.connect(self.exit_signal.emit)
        self.mode_signal.connect(self._sync_current_mode)
        self.counting_method_signal.connect(self._sync_counting_method)

        self.show_ready()
        self._update_admin_controls()

    def attach_camera_panel(self, camera_widget):
        self.camera_panel = camera_widget
        self.camera_placeholder.hide()
        self.camera_container_layout.addWidget(camera_widget)
        if hasattr(camera_widget, "on_mode_changed"):
            camera_widget.on_mode_changed(self.current_mode)
        if hasattr(camera_widget, "set_roi_edit_enabled"):
            camera_widget.set_roi_edit_enabled(self.is_authenticated)

    def set_operation_mode(self, mode_index):
        max_index = len(self.settings_window.MODE_NAMES) - 1
        normalized_index = max(0, min(max_index, int(mode_index)))
        if self.settings_window.mode_selector.currentIndex() == normalized_index:
            self.settings_window.on_mode_changed()
            return
        self.settings_window.mode_selector.setCurrentIndex(normalized_index)

    def emit_start_camera(self):
        self.start_camera_signal.emit(self.settings_window.get_camera_index())

    def open_settings(self):
        if not self.is_authenticated:
            dialog = LoginDialog(self.auth_manager, self)
            if not dialog.exec_():
                return

            if dialog.login_role == AuthManager.ROLE_DEV:
                mgmt = UserManagementDialog(self.auth_manager, self)
                mgmt.exec_()
                return

            self.is_authenticated = True
            self._update_admin_controls()

        self.settings_window.show()
        self.settings_window.raise_()
        self.settings_window.activateWindow()

    def _open_project_in_editor(self):
        project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if sys.platform == "darwin":
            vscode_cli_paths = ["/usr/local/bin/code", "/usr/bin/code",
                                "/opt/homebrew/bin/code"]
            vscode_app = "/Applications/Visual Studio Code.app"
            for cli in vscode_cli_paths:
                if os.path.exists(cli):
                    subprocess.Popen([cli, project_dir])
                    return
            if os.path.exists(vscode_app):
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

    def logout_admin(self):
        self.is_authenticated = False
        self.settings_window.hide()
        self._update_admin_controls()

    def _update_admin_controls(self):
        self.btn_settings.setText("ADMIN LOGIN")
        if self.is_authenticated:
            self.btn_settings.setStyleSheet(
                "QPushButton { background: #7A4B12; color: white; border: 1px solid #A86617; } "
                "QPushButton:hover { background: #A86617; }"
            )
            self.label_panel_subtitle.setText("Admin session active. ROI and parameters can be edited.")
        else:
            self.btn_settings.setStyleSheet(
                "QPushButton { background: #17212C; color: white; border: 1px solid #40556C; } "
                "QPushButton:hover { background: #203041; }"
            )
            self.label_panel_subtitle.setText(self._subtitle_for_mode(self.current_mode))
        self.admin_state_signal.emit(self.is_authenticated)

    def _subtitle_for_mode(self, mode):
        names = getattr(self.settings_window, "MODE_NAMES", [])
        if 0 <= mode < len(names):
            return names[mode]
        return "Core vision functions screen"

    def _set_result_card_style(self, color):
        if color == self.current_result_color:
            return

        self.current_result_color = color
        red, green, blue = hex_to_rgb(color)
        # Scope to QFrame#ResultCard — an unscoped stylesheet cascades to the
        # child labels (value + hint) and makes them overlap on macOS.
        self.result_card.setStyleSheet(
            "QFrame#ResultCard { "
            "background: qlineargradient("
            "x1:0, y1:0, x2:1, y2:1, "
            f"stop:0 rgba({red}, {green}, {blue}, 24), "
            "stop:0.22 #101721, "
            "stop:1 #0C121A"
            "); "
            f"border: 1px solid rgba({red}, {green}, {blue}, 165); "
            "border-radius: 22px; "
            "}"
        )
        self.label_result_value.setStyleSheet(
            f"color: {color}; "
            f"background: rgba({red}, {green}, {blue}, 26); "
            f"border: 1px solid rgba({red}, {green}, {blue}, 145); "
            "border-radius: 24px; "
            "font-size: 20px; "
            "font-weight: bold; "
            "padding: 16px 20px;"
        )

    def _helper_text_for_status(self, status):
        normalized_status = status
        if normalized_status == "SYSTEM READY":
            return "Press START CAMERA to begin inspection."
        if normalized_status == "DATA RESET":
            return "Inspection counters were cleared."
        if normalized_status == "READY TO CAPTURE":
            return "System is ready for the next captured image."
        if normalized_status in {"PASS", "PASS (OK)"}:
            return "Good part recorded successfully."
        if normalized_status == "OBJECT PRESENT":
            return "Object detected in ROI with position."
        if normalized_status == "NO OBJECT":
            return "No object found in ROI."
        if normalized_status.startswith("CLASSIFIED:"):
            return "Object category is available in the secondary metric."
        if normalized_status.startswith("CODE READ:"):
            return "Code value is available in the secondary metric."
        if normalized_status.startswith("ITEMS:"):
            return "Captured item count is shown here."
        if (
            normalized_status.startswith("FAIL")
            or "DEFECT" in normalized_status
            or "MISALIGNED" in normalized_status
            or "MISSING" in normalized_status
            or "UPSIDE-DOWN" in normalized_status
        ):
            return "NG part recorded for review."
        if "DISCONNECTED" in normalized_status or normalized_status == "CAMERA NOT AVAILABLE":
            return "Check macOS camera permission, camera connection, or try another device."
        if normalized_status == "NO STICKER REF":
            return "Open ADMIN LOGIN to set a valid sticker reference."
        if normalized_status == "CAPTURE SAVE FAILED":
            return "Check folder permissions or available disk space."
        if normalized_status == "REFERENCE SAVE FAILED":
            return "Check folder permissions before setting sticker reference again."
        if normalized_status == "REFERENCE NOT FOUND":
            return "No valid sticker was found in the ROI; previous reference is still kept."
        if normalized_status == "TEMPLATE UPDATE FAILED":
            return "ROI is empty or invalid; previous template is still kept."
        if normalized_status.startswith("NO TEMPLATE") or normalized_status.startswith("NO MODEL"):
            return "Capture a template and train at least one sample per defect type in the right panel."
        return "Live inspection status is shown here."

    def _set_result_state(self, status, color, helper_text=None):
        self.label_result_value.setText(status)
        self.label_result_hint.setText(helper_text or self._helper_text_for_status(status))
        self._set_result_card_style(color)
        self._set_indicator_color(color)

    def handle_reset(self):
        self.fg_count = 0
        self.ng_count = 0
        self.cam_fg.clear()
        self.cam_ng.clear()
        self.cam_last_class.clear()
        self.val_total.setText("0")
        self.val_fg.setText("0")
        self.val_ng.setText("0")
        self._refresh_camera_breakdown()
        self._set_result_state("DATA RESET", "#29B6F6")
        self.reset_signal.emit()

    def _open_path(self, path):
        if sys.platform == "win32":
            os.startfile(path)
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", path])

    def _set_indicator_color(self, color):
        self.indicator.setStyleSheet(f"background-color: {color}; border-radius: 5px;")

    def _status_to_color(self, status):
        normalized_status = status
        if normalized_status == "READY TO CAPTURE":
            return "#03A9F4"
        if normalized_status in {"OBJECT PRESENT", "PASS (OK)", "PASS"}:
            return "#4CAF50"
        if normalized_status.startswith("CLASSIFIED:") or normalized_status.startswith("CODE READ:") or normalized_status.startswith("PASSED:") or normalized_status.startswith("ITEMS:"):
            return "#03A9F4"
        if normalized_status in {"NO OBJECT", "NO CODE", "NO TARGET", "NO TEMPLATE SET", "NO AI MODEL", "ROI SIZE CHANGED", "NO STICKER REF", "REFERENCE NOT FOUND"}:
            return "#F57F17"
        if normalized_status in {"CAPTURE SAVE FAILED", "REFERENCE SAVE FAILED", "TEMPLATE UPDATE FAILED"}:
            return "#E53935"
        if "FAIL" in normalized_status or "DEFECT" in normalized_status or "DISCONNECTED" in normalized_status or "MISALIGNED" in normalized_status or "MISSING" in normalized_status:
            return "#E53935"
        return "#555"

    def record_inspection_event(self, camera_id, status, quantity, result_class, metric2_str=""):
        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return
        if quantity <= 0:
            return

        if result_class == "fg":
            self.fg_count += quantity
            self.cam_fg[camera_id] = self.cam_fg.get(camera_id, 0) + quantity
        elif result_class == "ng":
            self.ng_count += quantity
            self.cam_ng[camera_id] = self.cam_ng.get(camera_id, 0) + quantity
        else:
            return

        self.cam_last_class[camera_id] = result_class
        self.val_fg.setText(str(self.fg_count))
        self.val_ng.setText(str(self.ng_count))
        self._refresh_camera_breakdown()

    def _refresh_camera_breakdown(self):
        """Per-camera FG/NG breakdown + a combined PASS/FAIL verdict (FAIL if any
        camera's latest result is NG)."""
        from core.camera_manager import CAMERA_IDS, CAMERA_LABELS
        parts = []
        for cid in CAMERA_IDS:
            if cid in self.cam_fg or cid in self.cam_ng or cid in self.cam_last_class:
                parts.append(
                    f"{CAMERA_LABELS.get(cid, cid)}  FG:{self.cam_fg.get(cid, 0)} "
                    f"NG:{self.cam_ng.get(cid, 0)}"
                )
        self.cam_breakdown.setText("   ·   ".join(parts))

        seen = [c for c in self.cam_last_class.values()]
        if not seen:
            verdict, color = "—", "#90A4AE"
        elif any(c == "ng" for c in self.cam_last_class.values()):
            verdict, color = "FAIL", "#E53935"
        else:
            verdict, color = "PASS", "#00C853"
        self.combined_verdict.setText(f"All cameras: {verdict}")
        self.combined_verdict.setStyleSheet(
            f"color:{color}; font-size:13px; font-weight:bold; padding:4px; "
            "border:1px solid #29405A; border-radius:8px; background:#0C1219;"
        )

    def _project_root(self):
        return os.path.dirname(self.settings_window.settings_store.config_dir)

    def open_log_folder(self):
        log_dir = os.path.join(self._project_root(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        self._open_path(log_dir)

    def open_capture_folder(self):
        capture_dir = os.path.join(self._project_root(), "captures")
        os.makedirs(capture_dir, exist_ok=True)
        self._open_path(capture_dir)

    def on_mode_changed(self):
        self.current_mode = self.settings_window.mode_selector.currentIndex()
        self.settings_window.on_mode_changed()

    def _sync_current_mode(self, mode):
        self.current_mode = mode
        if not self.is_authenticated:
            self.label_panel_subtitle.setText(self._subtitle_for_mode(mode))
        self.set_running_state(getattr(self, "is_running", False))

    def _sync_counting_method(self, method):
        self.current_counting_method = method
        self.set_running_state(getattr(self, "is_running", False))

    def on_hw_settings_changed(self):
        self.settings_window.on_hw_settings_changed()

    def on_roi_changed(self):
        self.settings_window.on_roi_changed()

    def set_roi_values(self, x, y, w, h):
        self.settings_window.set_roi_values(x, y, w, h)

    def on_detection_params_changed(self):
        self.settings_window.on_detection_params_changed()

    def on_tracking_params_changed(self):
        self.settings_window.on_tracking_params_changed()

    def on_sticker_params_changed(self):
        self.settings_window.on_sticker_params_changed()

    def on_measurement_params_changed(self):
        self.settings_window.on_measurement_params_changed()

    def on_classification_selection_changed(self):
        self.settings_window.on_classification_selection_changed()

    def on_counting_method_changed(self):
        self.settings_window.on_counting_method_changed()

    def show_ready(self):
        self._set_result_state("SYSTEM READY", "#90A4AE")
        self.set_running_state(False)

    FATAL_ERRORS = {
        "CAMERA NOT AVAILABLE",
        "VIDEO THREAD ERROR",
        "STOP TIMEOUT - RESTART APP",
    }

    def show_error(self, message):
        self._set_result_state(message, "#E53935")
        if message in self.FATAL_ERRORS:
            self.set_running_state(False)

    def update_data(self, status, count, metric2_str, fps):
        self.val_total.setText(str(count))
        self._set_result_state(status, self._status_to_color(status))
        if self.current_mode == self.settings_window.MEASUREMENT_MODE and metric2_str:
            m = re.search(r'W:(\d+(?:\.\d+)?)[pm][xm].*H:(\d+(?:\.\d+)?)[pm][xm]', metric2_str)
            if m:
                try:
                    px_per_mm = getattr(self.settings_window, '_measure_px_per_mm', 0.0)
                    if px_per_mm > 0:
                        self.last_measure_w_px = round(float(m.group(1)) * px_per_mm)
                        self.last_measure_h_px = round(float(m.group(2)) * px_per_mm)
                    else:
                        self.last_measure_w_px = int(float(m.group(1)))
                        self.last_measure_h_px = int(float(m.group(2)))
                except (ValueError, AttributeError):
                    pass

    def set_running_state(self, is_running):
        self.is_running = is_running
        stop_capture_mode = self.current_counting_method == self.settings_window.COUNTING_STOP_CAPTURE
        self.btn_start.setEnabled(not is_running)
        self.btn_stop.setEnabled(is_running)
        self.btn_capture.setEnabled(is_running and stop_capture_mode)

    def closeEvent(self, event):
        if self.camera_panel and hasattr(self.camera_panel, "stop_camera"):
            if not self.camera_panel.stop_camera():
                event.ignore()
                return
        self.settings_window.close()
        event.accept()
