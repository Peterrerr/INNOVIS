# ui/camera_view.py
import sys

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QApplication, QFrame, QSizePolicy,
    QPushButton,
)
from PyQt5.QtCore import Qt, pyqtSignal, QRect
from PyQt5.QtGui import QPixmap

from core.camera_thread import VideoThread
from core.camera_manager import CameraManager, CAMERA_IDS, CAMERA_LABELS


def preferred_font_family():
    if sys.platform == "darwin":
        return "Helvetica Neue"
    if sys.platform == "win32":
        return "Segoe UI"
    return "DejaVu Sans"


class InteractiveLabel(QLabel):
    roi_dragged_signal = pyqtSignal(int, int, int, int)
    color_sampled_signal = pyqtSignal(int, int, int)   # H, S, V (OpenCV range)
    clicked = pyqtSignal()   # plain click (no ROI edit / no colour sample)

    def __init__(self, text):
        super().__init__(text)
        self.start_point = None
        self.drawing = False
        self.roi_edit_enabled = False
        self.color_sample_mode = False
        self.setCursor(Qt.ArrowCursor)

    def set_roi_edit_enabled(self, enabled):
        self.roi_edit_enabled = enabled
        if not enabled:
            self.drawing = False
            self.start_point = None
        if not self.color_sample_mode:
            self.setCursor(Qt.CrossCursor if enabled else Qt.ArrowCursor)

    def set_color_sample_mode(self, enabled):
        self.color_sample_mode = enabled
        if enabled:
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.CrossCursor if self.roi_edit_enabled else Qt.ArrowCursor)

    def _sample_color_at(self, pos):
        rect = self._pixmap_display_rect()
        if rect is None:
            return
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return
        img_x = pos.x() - rect.x()
        img_y = pos.y() - rect.y()
        if img_x < 0 or img_y < 0 or img_x >= pixmap.width() or img_y >= pixmap.height():
            return
        qimg = pixmap.toImage()
        qcolor = qimg.pixelColor(img_x, img_y)
        import colorsys
        r, g, b = qcolor.redF(), qcolor.greenF(), qcolor.blueF()
        h, s, v = colorsys.rgb_to_hsv(r, g, b)
        h_cv = int(h * 179)
        s_cv = int(s * 255)
        v_cv = int(v * 255)
        self.color_sampled_signal.emit(h_cv, s_cv, v_cv)

    def _pixmap_display_rect(self):
        pixmap = self.pixmap()
        if pixmap is None or pixmap.isNull():
            return None

        x = (self.width() - pixmap.width()) // 2
        y = (self.height() - pixmap.height()) // 2
        return QRect(x, y, pixmap.width(), pixmap.height())

    def _clamp_to_pixmap(self, point, rect):
        max_x = rect.x() + rect.width() - 1
        max_y = rect.y() + rect.height() - 1
        clamped_x = min(max(point.x(), rect.x()), max_x)
        clamped_y = min(max(point.y(), rect.y()), max_y)
        return clamped_x, clamped_y

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            return
        rect = self._pixmap_display_rect()
        if rect is None or not rect.contains(event.pos()):
            return
        if self.color_sample_mode:
            self._sample_color_at(event.pos())
            return
        if not self.roi_edit_enabled:
            # A plain click on a non-editable pane (e.g. a thumbnail) asks to
            # promote that camera to the primary view.
            self.clicked.emit()
            return
        self.start_point = event.pos()
        self.drawing = True

    def mouseMoveEvent(self, event):
        if not self.roi_edit_enabled:
            return
        if self.drawing and self.start_point:
            self._calculate_and_emit(event.pos())

    def mouseReleaseEvent(self, event):
        if not self.roi_edit_enabled:
            return
        if event.button() == Qt.LeftButton and self.drawing:
            self._calculate_and_emit(event.pos())
            self.drawing = False
            self.start_point = None

    def _calculate_and_emit(self, end_point):
        rect = self._pixmap_display_rect()
        if rect is None or rect.width() <= 0 or rect.height() <= 0:
            return

        x1, y1 = self._clamp_to_pixmap(self.start_point, rect)
        x2, y2 = self._clamp_to_pixmap(end_point, rect)

        img_x1 = x1 - rect.x()
        img_y1 = y1 - rect.y()
        img_x2 = x2 - rect.x()
        img_y2 = y2 - rect.y()

        rx = min(img_x1, img_x2)
        ry = min(img_y1, img_y2)
        rw = abs(img_x1 - img_x2)
        rh = abs(img_y1 - img_y2)

        width_den = max(1, rect.width() - 1)
        height_den = max(1, rect.height() - 1)

        px = max(0, min(100, int(round((rx / width_den) * 100))))
        py = max(0, min(100, int(round((ry / height_den) * 100))))
        pw = max(0, min(100, int(round((rw / width_den) * 100))))
        ph = max(0, min(100, int(round((rh / height_den) * 100))))

        self.roi_dragged_signal.emit(px, py, pw, ph)


class CameraWindow(QWidget):
    def __init__(self, dashboard, embedded=False):
        super().__init__()
        self.dashboard = dashboard
        self.embedded = embedded
        self.current_mode = self.dashboard.settings_window.mode_selector.currentIndex()
        self.current_counting_method = self.dashboard.settings_window.counting_method_selector.currentIndex()
        self.last_capture_image = None
        self._running = False
        self._roi_edit_enabled = False
        self._color_sample_mode = False
        font_family = preferred_font_family()

        # Owns the per-camera threads and routes their signals (tagged with
        # camera_id) back to this view + the dashboard.
        self.manager = CameraManager(self.dashboard)

        if not self.embedded:
            self.setWindowTitle("Live Camera Feed")
            self.setGeometry(50, 50, 820, 760)
        else:
            self.setMinimumSize(760, 720)
        self.setStyleSheet(f"""
            QWidget {{
                background: transparent;
                font-family: '{font_family}';
            }}
            QFrame#CameraPanel {{
                background: #0C1219;
                border: 1px solid #243244;
                border-radius: 16px;
            }}
        """)

        # ---- single active camera + a selector row to switch between them ----
        # macOS/OpenCV can't reliably open several cameras at once, so only one
        # camera runs at a time; the buttons switch which one is live.
        self.active_cam = self.manager.primary

        self.live_title = QLabel(CAMERA_LABELS[self.active_cam])
        self.live_title.setAlignment(Qt.AlignCenter)
        self.live_title.setStyleSheet("color: #98AABC; font-size: 11px; font-weight: bold; padding-top: 2px;")
        self.live_label = InteractiveLabel("CAMERA OFF")
        self.live_label.setAlignment(Qt.AlignCenter)
        self.live_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.live_label.roi_dragged_signal.connect(self.sync_roi_to_dashboard)
        self.live_label.color_sampled_signal.connect(self.dashboard.color_sampled_signal)
        self.live_panel = self._create_panel(self.live_title, self.live_label)
        self._set_placeholder(self.live_label, "CAMERA OFF", "#555")

        self.capture_title = QLabel("CAPTURE RESULT")
        self.capture_title.setAlignment(Qt.AlignCenter)
        self.capture_title.setStyleSheet("color: #98AABC; font-size: 11px; font-weight: bold; padding-top: 2px;")

        self.capture_image_label = QLabel("")
        self.capture_image_label.setAlignment(Qt.AlignCenter)
        self.capture_image_label.setWordWrap(True)
        self.capture_image_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self.capture_panel = self._create_panel(self.capture_title, self.capture_image_label)

        # DefectWidget lives in SettingsWindow (admin panel) — get reference
        # so we can still wire thread signals and route the CAPTURE button.
        self.defect_widget = self.dashboard.settings_window.defect_widget
        self.defect_widget.inspection_done.connect(self._on_defect_inspection_done)
        self.defect_widget.result_image_signal.connect(self.update_capture_image)

        # ---- camera selector row (click to switch the active camera) ----
        self.selector_row = QHBoxLayout()
        self.selector_row.setContentsMargins(0, 0, 0, 0)
        self.selector_row.setSpacing(8)
        self.cam_buttons = {}
        for cid in CAMERA_IDS:
            btn = QPushButton(CAMERA_LABELS[cid])
            btn.setCheckable(True)
            btn.setChecked(cid == self.active_cam)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(
                "QPushButton { color:#98AABC; background:#0C1219; border:1px solid #243244;"
                " border-radius:8px; padding:6px 14px; font-size:11px; font-weight:bold; }"
                "QPushButton:checked { color:#0C1219; background:#4FC3F7; border-color:#4FC3F7; }"
            )
            btn.clicked.connect(lambda _checked, c=cid: self._select_camera(c))
            self.cam_buttons[cid] = btn
            self.selector_row.addWidget(btn)
        self.selector_row.addStretch(1)

        layout = QVBoxLayout()
        layout.addLayout(self.selector_row)
        layout.addWidget(self.live_panel, 3)
        layout.addWidget(self.capture_panel, 2)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        self.setLayout(layout)

        self._set_capture_placeholder()
        self.capture_panel.setVisible(False)

        # ---- route manager outputs (all tagged with camera_id) ----
        self.manager.live_frame_signal.connect(self._on_live_frame)
        self.manager.capture_frame_signal.connect(self._on_capture_frame)
        self.manager.data_signal.connect(self._on_data)
        self.manager.inspection_signal.connect(self._on_inspection)
        self.manager.error_signal.connect(self._on_error)
        self.manager.defect_frame_signal.connect(self._on_defect_frame)

        self._defect_parts_inspected = 0
        self.dashboard.reset_signal.connect(self._reset_defect_counter)
        self.dashboard.start_camera_signal.connect(self.start_camera)
        self.dashboard.stop_signal.connect(self.stop_camera)
        self.dashboard.exit_signal.connect(self.close_application)
        self.dashboard.mode_signal.connect(self.on_mode_changed)
        self.dashboard.counting_method_signal.connect(self.on_counting_method_changed)
        self.dashboard.reset_signal.connect(self.clear_capture_result)
        self.dashboard.admin_state_signal.connect(self.set_roi_edit_enabled)
        self.dashboard.color_sample_request_signal.connect(self.set_color_sample_mode)
        # Route the CAPTURE button: in Defect mode it triggers DefectWidget;
        # in other modes it requests a normal inspection capture from the thread.
        self.dashboard.capture_image_signal.connect(self._on_capture_pressed)
        self.on_mode_changed(self.current_mode)
        self.set_roi_edit_enabled(self.dashboard.is_authenticated)

    def _create_panel(self, title_label, image_label):
        panel = QFrame()
        panel.setObjectName("CameraPanel")

        layout = QVBoxLayout()
        layout.addWidget(title_label)
        layout.addWidget(image_label, 1)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        panel.setLayout(layout)
        return panel

    # ---- camera selection ------------------------------------------------ #
    def _sync_selector_buttons(self):
        for cid, btn in self.cam_buttons.items():
            btn.blockSignals(True)
            btn.setChecked(cid == self.active_cam)
            btn.blockSignals(False)

    def _select_camera(self, camera_id):
        """Make camera_id the active (and only) live camera. If running, switch
        the feed over to it; settings/training follow the active camera."""
        if camera_id not in CAMERA_IDS:
            return
        self.active_cam = camera_id
        self._sync_selector_buttons()
        self.live_title.setText(CAMERA_LABELS[camera_id])
        self.manager.set_primary(camera_id)
        if hasattr(self.dashboard.settings_window, "set_primary_camera"):
            self.dashboard.settings_window.set_primary_camera(camera_id)
        # Training/inspection (sticker + defect) follows the active camera.
        self.defect_widget.set_camera(camera_id)
        if self._running:
            self._set_placeholder(self.live_label, f"{CAMERA_LABELS[camera_id]}\nOpening…", "#90CAF9")
            self.manager.switch_to(camera_id)
            self.manager.push_all_settings()
        self._refresh_edit_targets()

    def _refresh_edit_targets(self):
        """ROI editing / colour sampling apply to the single live pane."""
        self.live_label.set_roi_edit_enabled(self._roi_edit_enabled)
        self.live_label.set_color_sample_mode(self._color_sample_mode)

    def _set_placeholder(self, label, text, color="#555"):
        label.clear()
        label.setText(text)
        label.setAlignment(Qt.AlignCenter)
        label.setStyleSheet(
            f"background:#060A10; border:1px dashed #29405A; color:{color}; "
            "font-size: 22px; font-weight: bold; border-radius: 12px; padding: 24px;"
        )

    def _set_label_image(self, label, image):
        pixmap = QPixmap.fromImage(image).scaled(
            label.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        label.setPixmap(pixmap)
        label.setStyleSheet("background:#060A10; border:1px solid #29405A; border-radius: 12px;")

    def _set_capture_placeholder(self):
        if self._uses_stop_capture():
            self._set_placeholder(self.capture_image_label, "NO CAPTURE YET\nPress CAPTURE IMAGE", "#90CAF9")
        else:
            self._set_placeholder(self.capture_image_label, "Capture result appears in\nStop & Capture mode", "#666")

    # ---- manager output handlers ----------------------------------------- #
    def _on_live_frame(self, camera_id, image):
        if camera_id == self.active_cam:
            self._set_label_image(self.live_label, image)

    def _on_capture_frame(self, camera_id, image):
        if camera_id == self.active_cam:
            self.update_capture_image(image)

    def _on_data(self, camera_id, status, count, metric2_str, fps):
        if camera_id == self.active_cam:
            self.dashboard.update_data(status, count, metric2_str, fps)

    def _on_inspection(self, camera_id, status, quantity, result_class, metric2_str):
        # The active camera's results feed its own FG/NG tally + the verdict.
        self.dashboard.record_inspection_event(camera_id, status, quantity, result_class, metric2_str)

    def _on_error(self, camera_id, message):
        if camera_id != self.active_cam:
            return
        idx = self.manager.index_map.get(camera_id, "?")
        # Surface the error on both the result card and the live pane so the
        # operator can see which device failed.
        self.dashboard.show_error(message)
        self._set_placeholder(
            self.live_label,
            f"{CAMERA_LABELS.get(camera_id, camera_id)} (Device {idx})\n{message}",
            "#E53935",
        )

    def _on_defect_frame(self, camera_id, frame):
        if camera_id == self.active_cam:
            self.defect_widget.set_frame(frame)

    def update_capture_image(self, image):
        self.last_capture_image = image
        self._set_label_image(self.capture_image_label, image)

    def sync_roi_to_dashboard(self, x, y, w, h):
        if not self.dashboard.is_authenticated:
            return
        self.dashboard.set_roi_values(x, y, w, h)

    def set_roi_edit_enabled(self, enabled):
        self._roi_edit_enabled = enabled
        self._refresh_edit_targets()

    def set_color_sample_mode(self, enabled):
        self._color_sample_mode = enabled
        self._refresh_edit_targets()

    def on_mode_changed(self, mode):
        self.current_mode = mode
        self._sync_capture_panel()

    def on_counting_method_changed(self, method):
        self.current_counting_method = method
        self._sync_capture_panel()

    def _uses_stop_capture(self):
        return self.current_counting_method == self.dashboard.settings_window.COUNTING_STOP_CAPTURE

    def _sync_capture_panel(self):
        uses_stop_capture = self._uses_stop_capture()
        self.capture_title.setText("CAPTURE RESULT")
        self.capture_panel.setVisible(uses_stop_capture)

        if self.last_capture_image is not None and uses_stop_capture:
            self._set_label_image(self.capture_image_label, self.last_capture_image)
        else:
            self._set_capture_placeholder()

    def clear_capture_result(self):
        self.last_capture_image = None
        self._set_capture_placeholder()

    def _on_capture_pressed(self):
        """Route the dashboard CAPTURE button to the right consumer per mode."""
        if self.current_mode == VideoThread.DEFECT_MODE:
            self.defect_widget.capture_and_inspect()
            return
        self.manager.request_inspection_capture()

    def _reset_defect_counter(self):
        self._defect_parts_inspected = 0

    def _on_defect_inspection_done(self, status: str, defects: int, conf: str):
        """Forward DefectWidget results to the dashboard result card + counters."""
        self._defect_parts_inspected += 1
        metric = f"Defects:{defects} Conf:{conf}"
        # Update the main result card. Total count tracks parts inspected,
        # not the number of defect regions found in the last frame.
        self.dashboard.update_data(status, self._defect_parts_inspected, metric, 0)
        # Drive FG/NG counters via the dashboard inspection-event hook.
        result_class = "fg" if "PASS" in status.upper() else "ng"
        self.dashboard.record_inspection_event(self.manager.primary, status, 1, result_class, metric)
        # Re-emit on the dashboard so anyone else who cares can listen.
        self.dashboard.defect_inspection_signal.emit(status, defects, conf)
        # Mirror to log + per-mode CSV.
        thread = self.manager.primary_thread()
        if thread is not None and hasattr(thread, "logger"):
            try:
                thread.logger.log_data(
                    "Defect Inspection", status, self._defect_parts_inspected, metric, 0
                )
            except Exception:
                pass

    def start_camera(self, cam_index=0):
        if self.manager.is_running():
            return

        if hasattr(self.dashboard.settings_window, "get_camera_layout"):
            self.manager.configure(**self.dashboard.settings_window.get_camera_layout())
        # Run only the active (selected) camera.
        self.active_cam = self.manager.primary
        self._sync_selector_buttons()
        self.live_title.setText(CAMERA_LABELS[self.active_cam])
        self.defect_widget.set_camera(self.active_cam)
        self.manager.start_active()
        self.dashboard.set_running_state(True)
        self._running = True
        self.manager.push_all_settings()
        self._refresh_edit_targets()

    def stop_camera(self):
        stopped = self.manager.stop_all()
        self._running = False
        if not stopped:
            self.dashboard.show_error("STOP TIMEOUT - RESTART APP")
            return False

        self._set_placeholder(self.live_label, "CAMERA STOPPED", "#E53935")
        self.clear_capture_result()
        self.dashboard.show_ready()
        return True

    def close_application(self):
        if not self.stop_camera():
            return False
        QApplication.instance().quit()
        return True

    def closeEvent(self, event):
        if self.close_application():
            event.accept()
        else:
            event.ignore()
