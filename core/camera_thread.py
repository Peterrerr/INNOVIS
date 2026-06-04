# core/camera_thread.py
import os
import sys
import cv2
import time
import json
import traceback
from datetime import datetime
from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtGui import QImage

from algorithms.object_detect import ObjectDetector
from algorithms.classification import ClassificationDetector
from algorithms.line_crossing import LineCrossingCounter
from algorithms.sticker_inspect import StickerInspector
from algorithms.code_reading import CodeReader
from algorithms.measurement import MeasurementDetector
from core.logger import DataLogger
from core.settings_store import SettingsStore
from core.result_class import get_result_class

class VideoThread(QThread):
    DETECTION_MODE = 0
    DEFECT_MODE = 1
    CLASSIFICATION_MODE = 2
    CODE_READING_MODE = 3
    COUNT_TRACK_MODE = 4
    STICKER_MODE = 5
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

    change_pixmap_signal = pyqtSignal(QImage)
    capture_pixmap_signal = pyqtSignal(QImage)
    update_data_signal = pyqtSignal(str, int, str, int)
    inspection_event_signal = pyqtSignal(str, int, str, str)
    error_signal = pyqtSignal(str)
    # Defect mode now delegates inspection to DefectWidget — VideoThread just
    # forwards the latest raw BGR frame so the widget can preview / inspect.
    defect_frame_signal = pyqtSignal(object)

    def __init__(self, camera_index=0, camera_id="cam1"):
        super().__init__()
        self.camera_index = camera_index
        # Stable identifier for this camera slot (cam1 / cam2 / cam3). Used to
        # tag results + logs and to let CameraManager route signals per camera.
        self.camera_id = camera_id
        # When several cameras run at once, falling back to other indices makes
        # two threads fight over the same device. CameraManager turns this off.
        self.allow_index_fallback = True
        self._run_flag = True
        self.cap = None

        self.detection_algo = ObjectDetector()
        self.classification_algo = ClassificationDetector()
        self.tracking_algo = LineCrossingCounter()
        self.counting_tracker = LineCrossingCounter()
        self.code_algo = CodeReader()
        self.settings_store = SettingsStore()
        # Each camera trains its own sticker reference image.
        self.sticker_algo = StickerInspector(
            reference_path=self.settings_store.sticker_reference_path_for(camera_id)
        )
        self.measurement_algo = MeasurementDetector()

        base_dir = os.path.dirname(self.settings_store.config_dir)  # frozen-aware via SettingsStore
        self.logger = DataLogger(log_dir=os.path.join(base_dir, "logs"), on_error=self._on_logger_error, camera_id=camera_id)
        self.total_count = 0
        self.last_count = 0
        self.last_status = None
        self.mode = 0
        self.counting_method = self.COUNTING_CONVEYOR
        self._last_error_message = ""
        self._last_error_time = 0.0
        self._capture_flag = False
        self._inspection_capture_flag = False
        self._captured_display_frame = None
        self._captured_status = "READY TO CAPTURE"
        self._captured_count = 0
        self._captured_metric = "PRESS CAPTURE"

        self.rx, self.ry, self.rw, self.rh = 0, 0, 100, 100
        self.br, self.ct, self.ex, self.fc, self.af = 128, 32, 5, 0, False
        # Focus aid (live preview overlay in defect mode) — controlled by
        # DefectWidget. min_area_pct is a fraction of ROI area; polarity is
        # "dark" (dark object on light bg) or "light" (light object on dark bg).
        self._focus_aid_min_area_pct = 0.2
        self._focus_aid_polarity = "dark"
        self.last_hw = None
        self.capture_dir = os.path.join(base_dir, "captures")
        os.makedirs(self.capture_dir, exist_ok=True)

    def set_mode(self, mode):
        self.mode = mode
        self.total_count = 0
        self.counting_tracker.reset_stats()
        self.tracking_algo.reset_stats()
        self.last_count = 0
        self.last_status = None
        self._inspection_capture_flag = False
        self._captured_display_frame = None
        if self.mode in {self.DEFECT_MODE, self.STICKER_MODE}:
            self.counting_method = self.COUNTING_STOP_CAPTURE

    def update_counting_method(self, method):
        if self.mode in {self.DEFECT_MODE, self.STICKER_MODE}:
            next_method = self.COUNTING_STOP_CAPTURE
        else:
            next_method = self.COUNTING_STOP_CAPTURE if method == self.COUNTING_STOP_CAPTURE else self.COUNTING_CONVEYOR
        if next_method != self.counting_method:
            self.total_count = 0
            self.counting_tracker.reset_stats()
            self.last_count = 0
            self.last_status = None
        self.counting_method = next_method
        self._inspection_capture_flag = False
        self._captured_display_frame = None

    def update_roi(self, x, y, w, h):
        x = max(0, min(99, int(x)))
        y = max(0, min(99, int(y)))
        w = max(1, min(100 - x, int(w)))
        h = max(1, min(100 - y, int(h)))
        self.rx, self.ry, self.rw, self.rh = x, y, w, h
    def update_hw(self, br, ct, ex, fc, af): self.br, self.ct, self.ex, self.fc, self.af = br, ct, ex, fc, af

    def update_detection_params(self, threshold, min_area, max_area, auto_threshold=False): self.detection_algo.update_params(threshold, min_area, max_area, auto_threshold)

    def update_tracking_params(self, line_y, line_x, min_area, threshold=None, polarity=None, adaptive=None, match_distance=None, count_direction=None):
        self.tracking_algo.update_params(line_y, line_x, min_area, threshold, polarity, adaptive, match_distance, count_direction)
        self.counting_tracker.update_params(line_y, line_x, min_area, threshold, polarity, adaptive, match_distance, count_direction)
    def update_classification_targets(self, targets): self.classification_algo.set_targets(targets)
    def update_classification_params(self, min_area, hue_margin, sat_margin=0, val_margin=0):
        self.classification_algo.update_params(min_area, hue_margin, sat_margin, val_margin)
    def update_classification_colors(self, colors_dict): self.classification_algo.set_custom_colors(colors_dict)
    def update_code_expected(self, expected_value): self.code_algo.update_expected_value(expected_value)
    def update_sticker_params(self, match_percent, min_area, max_angle_error):
        self.sticker_algo.update_params(match_percent, min_area, max_angle_error)

    def update_measurement_params(self, threshold, min_area, min_width, max_width, min_height, max_height):
        self.measurement_algo.update_params(threshold, min_area, min_width, max_width, min_height, max_height)
    def update_measurement_calibration(self, px_per_mm):
        self.measurement_algo.set_calibration(px_per_mm)

    def update_focus_aid(self, min_area_pct: float, polarity: str):
        """Tune the live focus-aid contour overlay (defect mode only)."""
        try:
            self._focus_aid_min_area_pct = max(0.0, min(20.0, float(min_area_pct)))
        except (TypeError, ValueError):
            pass
        if polarity in {"dark", "light"}:
            self._focus_aid_polarity = polarity

    def apply_settings(self, block):
        """Apply a full per-camera settings block (the dict stored under
        settings['cameras'][camera_id]) to this thread's algorithms. Used by
        CameraManager so each camera starts with its own saved settings."""
        if not isinstance(block, dict):
            return
        cam = block.get("camera", {})
        if cam:
            self.update_hw(
                int(cam.get("brightness", self.br)),
                int(cam.get("contrast", self.ct)),
                int(cam.get("exposure", self.ex)),
                int(cam.get("focus", self.fc)),
                bool(cam.get("autofocus", self.af)),
            )
        roi = block.get("roi", {})
        if roi:
            self.update_roi(roi.get("x", self.rx), roi.get("y", self.ry),
                            roi.get("w", self.rw), roi.get("h", self.rh))
        det = block.get("detection", {})
        if det:
            self.update_detection_params(
                det.get("threshold", 127), det.get("min_area", 0),
                det.get("max_area", 0), det.get("auto_threshold", False),
            )
        cls = block.get("classification", {})
        if cls:
            self.update_classification_colors(cls.get("custom_colors", {}))
            self.update_classification_targets(cls.get("targets", []))
            self.update_classification_params(
                cls.get("min_area", 0), cls.get("hue_margin", 0),
                cls.get("sat_margin", 0), cls.get("val_margin", 0),
            )
        code = block.get("code", {})
        if code:
            self.update_code_expected(code.get("expected_value", ""))
        trk = block.get("tracking", {})
        if trk:
            self.update_tracking_params(
                trk.get("line_y", 50), trk.get("line_x", 50), trk.get("min_area", 0),
                trk.get("threshold"), trk.get("polarity"), trk.get("adaptive"),
                trk.get("match_distance"), trk.get("count_direction"),
            )
        stk = block.get("sticker", {})
        if stk:
            self.update_sticker_params(
                stk.get("match_percent", 0), stk.get("min_area", 0),
                stk.get("max_angle_error", 0),
            )
        meas = block.get("measurement", {})
        if meas:
            self.update_measurement_params(
                meas.get("threshold", 127), meas.get("min_area", 0),
                meas.get("min_width", 0), meas.get("max_width", 0),
                meas.get("min_height", 0), meas.get("max_height", 0),
            )
            if "px_per_mm" in meas:
                self.update_measurement_calibration(meas.get("px_per_mm"))

    def reset_stats(self):
        self.detection_algo.reset_stats()
        self.classification_algo.reset_stats()
        self.tracking_algo.reset_stats()
        self.counting_tracker.reset_stats()
        self.code_algo.reset_stats()
        self.sticker_algo.reset_stats()
        self.measurement_algo.reset_stats()
        self.total_count = 0
        self.last_count = 0
        self.last_status = None
        self._inspection_capture_flag = False
        self._captured_display_frame = None
        self._captured_status = "READY TO CAPTURE"
        self._captured_count = 0
        self._captured_metric = "PRESS CAPTURE"

    def _should_log_event(self, status, count):
        if count != self.last_count:
            if status.startswith("ITEMS:") or status.startswith("PASSED:") or count > 0:
                return True

        if status != self.last_status and status not in {"WAITING"}:
            if not status.startswith("ITEMS:") and not status.startswith("PASSED:"):
                return True

        return False

    def capture_template(self):
        self._capture_flag = True

    def request_inspection_capture(self):
        self._inspection_capture_flag = True

    def _safe_emit_error(self, message, min_interval=1.0):
        now = time.time()
        if message != self._last_error_message or now - self._last_error_time >= min_interval:
            self.error_signal.emit(message)
            self._last_error_message = message
            self._last_error_time = now

    def _write_thread_exception(self, prefix, exc):
        try:
            os.makedirs(self.logger.log_dir, exist_ok=True)
            path = os.path.join(self.logger.log_dir, f"thread_errors_{datetime.now().strftime('%Y-%m-%d')}.log")
            timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            with open(path, "a", encoding="utf-8") as file:
                file.write(f"[{timestamp}] {prefix}: {exc!r}\n")
                file.write(traceback.format_exc())
                file.write("\n")
        except Exception as log_error:
            print(f"Error writing thread exception log: {log_error}")

    def _handle_thread_exception(self, prefix, exc, user_message):
        self._write_thread_exception(prefix, exc)
        self._safe_emit_error(user_message)

    def _on_logger_error(self, exc):
        self._write_thread_exception("Log write failed", exc)
        self._safe_emit_error("LOG WRITE ERROR", min_interval=10.0)

    def run(self):
        cap = None
        try:
            cap = self._open_camera()
            if cap is None:
                if not self._run_flag:
                    return
                self._safe_emit_error("CAMERA NOT AVAILABLE")
                return
            self.cap = cap

            fps_s, last_t = 0, time.time()
            self._capture_flag = False

            while self._run_flag:
                try:
                    ret, frame = cap.read()
                except Exception as exc:
                    self._handle_thread_exception("Camera read failed", exc, "CAMERA READ ERROR")
                    ret, frame = False, None

                if not self._run_flag:
                    break

                if not ret or frame is None:
                    if not self._run_flag:
                        break
                    self._safe_emit_error("CAMERA DISCONNECTED")
                    time.sleep(0.2)
                    if not self._run_flag:
                        break
                    if cap is not None:
                        cap.release()
                        cap = None
                    cap = self._open_camera()
                    self.cap = cap
                    if cap is None:
                        time.sleep(0.5)
                        continue
                    continue

                frame = self._apply_sw_adjustments(frame)

                current_hw = (self.br, self.ct, self.ex, self.fc, self.af)
                if current_hw != self.last_hw:
                    try:
                        self._apply_hw_settings(cap)
                        self.last_hw = current_hw
                    except Exception as exc:
                        self._handle_thread_exception("Camera settings failed", exc, "CAMERA SETTING ERROR")

                curr_t = time.time()
                fps = 1 / (curr_t - last_t) if (curr_t - last_t) > 0 else 0
                fps_s = (fps_s * 0.9) + (fps * 0.1)
                last_t = curr_t

                try:
                    fh, fw = frame.shape[:2]
                    processed_frame, status, count, metric2 = self._process_frame(frame, fw, fh)
                except Exception as exc:
                    self._handle_thread_exception("Frame processing failed", exc, "PROCESSING ERROR")
                    processed_frame = frame
                    status, count, metric2 = "PROCESSING ERROR", 0, type(exc).__name__

                if isinstance(metric2, float):
                    metric2_str = f"{metric2:.2f}"
                else:
                    metric2_str = str(metric2)

                mode_str = self.MODE_NAMES[self.mode] if 0 <= self.mode < len(self.MODE_NAMES) else "Unknown"

                if self._should_log_event(status, count):
                    self.logger.log_data(mode_str, status, count, metric2_str, int(fps_s))

                self.update_data_signal.emit(status, count, metric2_str, int(fps_s))
                self.last_count = count
                self.last_status = status

                try:
                    self._emit_image(processed_frame)
                except Exception as exc:
                    self._handle_thread_exception("Frame display failed", exc, "DISPLAY ERROR")
        except Exception as exc:
            if self._run_flag:
                self._handle_thread_exception("Video thread failed", exc, "VIDEO THREAD ERROR")
        finally:
            if cap is not None:
                cap.release()
            self.cap = None
            self._run_flag = False

    def _camera_backends(self):
        default_backend = getattr(cv2, "CAP_ANY", 0)
        if sys.platform == "darwin":
            return [cv2.CAP_AVFOUNDATION, default_backend]
        if sys.platform.startswith("win"):
            return [cv2.CAP_DSHOW, cv2.CAP_MSMF, default_backend]
        return [getattr(cv2, "CAP_V4L2", default_backend), default_backend]

    def _camera_indices_to_try(self):
        if not self.allow_index_fallback:
            return [self.camera_index]
        fallback_indices = [0, 1, 2, 3]
        indices = [self.camera_index]
        indices.extend(index for index in fallback_indices if index != self.camera_index)
        return indices

    def _open_camera(self):
        for camera_index in self._camera_indices_to_try():
            for backend in self._camera_backends():
                cap = cv2.VideoCapture(camera_index, backend)
                if cap is not None and cap.isOpened():
                    self.camera_index = camera_index
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    self.last_hw = None
                    return cap
                if cap is not None:
                    cap.release()
        return None

    def _apply_hw_settings(self, cap):
        cap.set(cv2.CAP_PROP_BRIGHTNESS, self.br)
        cap.set(cv2.CAP_PROP_CONTRAST, self.ct)
        cap.set(cv2.CAP_PROP_EXPOSURE, -self.ex)
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 1 if self.af else 0)
        if not self.af: cap.set(cv2.CAP_PROP_FOCUS, self.fc)

    def _apply_sw_adjustments(self, frame):
        # ct default=32 → alpha=1.0 (no change); br default=128 → beta=0 (no change)
        alpha = max(0.0, self.ct / 32.0)
        beta = float(self.br - 128)
        if abs(alpha - 1.0) < 0.02 and abs(beta) < 1:
            return frame
        return cv2.convertScaleAbs(frame, alpha=alpha, beta=beta)

    def _capture_metadata(self, status, count, metric2, quantity=0, result_class="info"):
        mode_str = self.MODE_NAMES[self.mode] if 0 <= self.mode < len(self.MODE_NAMES) else "Unknown"
        return {
            "timestamp": datetime.now().isoformat(timespec="milliseconds"),
            "mode": mode_str,
            "status": str(status),
            "result_class": str(result_class or "info").upper(),
            "total_count": int(count),
            "event_quantity": int(quantity or 0),
            "metric": str(metric2),
            "roi_percent": {
                "x": int(self.rx),
                "y": int(self.ry),
                "w": int(self.rw),
                "h": int(self.rh),
            },
            "counting_method": "Stop & Capture"
            if self.counting_method == self.COUNTING_STOP_CAPTURE
            else "Continuous",
        }

    def _save_capture_images(self, raw_frame, result_frame, status, metadata=None):
        date_dir = os.path.join(self.capture_dir, datetime.now().strftime("%Y-%m-%d"))
        os.makedirs(date_dir, exist_ok=True)

        capture_id = datetime.now().strftime("%H%M%S_%f")[:-3]
        status_slug = "".join(ch.lower() if ch.isalnum() else "_" for ch in status).strip("_") or "result"
        base_name = f"capture_{capture_id}_{status_slug}"
        raw_path = os.path.join(date_dir, f"{base_name}_raw.png")
        result_path = os.path.join(date_dir, f"{base_name}_result.png")
        metadata_path = os.path.join(date_dir, f"{base_name}_meta.json")

        if not cv2.imwrite(raw_path, raw_frame):
            raise IOError(f"Could not save raw capture: {raw_path}")
        if not cv2.imwrite(result_path, result_frame):
            raise IOError(f"Could not save result capture: {result_path}")
        if metadata is not None:
            metadata = dict(metadata)
            metadata["raw_image"] = os.path.basename(raw_path)
            metadata["result_image"] = os.path.basename(result_path)
            with open(metadata_path, "w", encoding="utf-8") as file:
                json.dump(metadata, file, ensure_ascii=False, indent=2)
        return raw_path, result_path

    def _build_capture_preview(self, frame, x, y, w, h):
        preview = frame.copy()
        has_reference = self.sticker_algo.has_reference()
        color = (255, 193, 7) if has_reference else (0, 165, 255)
        roi = preview[y:y+h, x:x+w]
        preview_roi, found_sticker, detected_pos = self.sticker_algo.draw_preview(roi)
        preview[y:y+h, x:x+w] = preview_roi
        cv2.rectangle(preview, (x, y), (x + w, y + h), color, 2)

        lines = [
            "PHOTO CAPTURE MODE",
            "Press CAPTURE IMAGE to save and inspect",
        ]
        if has_reference:
            lines.append("Sticker reference ready")
        else:
            lines.append("Set sticker reference first")
        if found_sticker:
            lines.append(f"Detected position: {detected_pos}")
        else:
            lines.append("Waiting sticker inside ROI")

        for index, line in enumerate(lines):
            y_pos = 22 + (index * 20)
            cv2.putText(preview, line, (10, y_pos), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2 if index == 0 else 1)

        status = "READY TO CAPTURE" if has_reference else "NO STICKER REF"
        metric = detected_pos if found_sticker else "PRESS CAPTURE"
        return preview, status, self.total_count, metric

    def _process_capture_mode(self, frame, roi, x, y, w, h):
        preview_frame, preview_status, preview_count, preview_metric = self._build_capture_preview(frame, x, y, w, h)

        if self._inspection_capture_flag:
            self._inspection_capture_flag = False

            raw_frame = frame.copy()
            captured_frame = raw_frame.copy()
            self.sticker_algo.prepare_single_capture()
            status, count, metric2, processed_roi = self.sticker_algo.process(roi.copy())
            captured_frame[y:y+h, x:x+w] = processed_roi
            cv2.rectangle(captured_frame, (x, y), (x + w, y + h), (33, 150, 243), 2)
            quantity = 1 if self._is_countable_status(status) else 0
            result_class = self._result_class(status) or "info"
            self.total_count += quantity
            count = self.total_count

            try:
                _, result_path = self._save_capture_images(
                    raw_frame,
                    captured_frame,
                    status,
                    self._capture_metadata(status, count, metric2, quantity, result_class),
                )
                saved_name = os.path.basename(result_path)
                capture_status = status
                capture_metric = f"{metric2} | {saved_name}"
            except OSError:
                capture_status = "CAPTURE SAVE FAILED"
                capture_metric = "CHECK CAPTURES FOLDER"
                self.error_signal.emit(capture_status)

            self._emit_inspection_event(status, quantity, metric2, result_class)
            self._captured_display_frame = captured_frame
            self._captured_status = capture_status
            self._captured_count = count
            self._captured_metric = capture_metric
            self._emit_capture_image(self._captured_display_frame)

        if self._captured_display_frame is not None:
            return preview_frame, self._captured_status, self._captured_count, self._captured_metric

        return preview_frame, preview_status, preview_count, preview_metric

    def _process_count_snapshot_mode(self, frame, roi, x, y, w, h):
        preview_frame = frame.copy()
        cv2.rectangle(preview_frame, (x, y), (x + w, y + h), (255, 100, 100), 2)
        cv2.putText(preview_frame, "Press CAPTURE IMAGE to count items", (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

        if self._inspection_capture_flag:
            self._inspection_capture_flag = False
            raw_frame = frame.copy()
            status, count, metric2, processed_roi = self.tracking_algo.process_snapshot(roi)
            captured_frame = frame.copy()
            captured_frame[y:y+h, x:x+w] = processed_roi
            cv2.rectangle(captured_frame, (x, y), (x + w, y + h), (255, 100, 100), 2)

            self.total_count = count
            capture_status = status
            capture_metric = metric2
            try:
                _, result_path = self._save_capture_images(
                    raw_frame,
                    captured_frame,
                    status,
                    self._capture_metadata(status, self.total_count, metric2, count, "info"),
                )
                capture_metric = f"{metric2} | {os.path.basename(result_path)}"
            except OSError:
                capture_status = "CAPTURE SAVE FAILED"
                capture_metric = "CHECK CAPTURES FOLDER"
                self.error_signal.emit(capture_status)

            self._captured_display_frame = captured_frame
            self._captured_status = capture_status
            self._captured_count = count
            self._captured_metric = capture_metric
            self._emit_capture_image(self._captured_display_frame)

        if self._captured_display_frame is not None:
            return preview_frame, self._captured_status, self._captured_count, self._captured_metric

        return preview_frame, "READY TO CAPTURE", self.total_count, "PRESS CAPTURE"

    def _process_defect_mode(self, frame, x, y, w, h):
        """Forward the ROI to DefectWidget and draw focus-aid boxes on live.

        DefectWidget owns the multi-angle DefectDetector, template management
        and training UI. VideoThread just emits the cropped ROI so the widget
        can capture / train / inspect on demand, and draws lightweight contour
        bounding boxes on the live preview so the operator can confirm the
        part is in focus and well-centered inside the ROI.
        """
        roi_crop = frame[y:y + h, x:x + w]
        try:
            if roi_crop.size > 0:
                self.defect_frame_signal.emit(roi_crop.copy())
        except Exception:
            pass

        preview = frame.copy()
        cv2.rectangle(preview, (x, y), (x + w, y + h), (0, 255, 255), 2)

        # Trace candidate object outlines inside the ROI as a focus aid.
        focus_box_count = 0
        if roi_crop.size > 0:
            try:
                gray = cv2.cvtColor(roi_crop, cv2.COLOR_BGR2GRAY)
                gray = cv2.GaussianBlur(gray, (5, 5), 0)
                thresh_type = (
                    cv2.THRESH_BINARY_INV
                    if self._focus_aid_polarity == "dark"
                    else cv2.THRESH_BINARY
                )
                _, mask = cv2.threshold(
                    gray, 0, 255, thresh_type | cv2.THRESH_OTSU,
                )
                kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
                mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
                mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
                # ``offset`` shifts contour coordinates back into full-frame
                # space so we can draw directly on ``preview`` without slicing.
                contours, _ = cv2.findContours(
                    mask,
                    cv2.RETR_EXTERNAL,
                    cv2.CHAIN_APPROX_SIMPLE,
                    offset=(x, y),
                )
                min_area = max(
                    40,
                    int((self._focus_aid_min_area_pct / 100.0) * w * h),
                )
                # Smooth the polyline a little so it doesn't look jagged.
                for c in contours:
                    if cv2.contourArea(c) < min_area:
                        continue
                    peri = cv2.arcLength(c, True)
                    smooth = cv2.approxPolyDP(c, 0.003 * peri, True)
                    cv2.drawContours(
                        preview, [smooth], -1, (76, 220, 120), 2, cv2.LINE_AA,
                    )
                    focus_box_count += 1
            except Exception:
                pass

        cv2.putText(preview, "DEFECT INSPECTION  (drag inside ROI to resize)",
                    (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
        focus_msg = (
            f"Focus aid: {focus_box_count} object(s) detected in ROI"
            if focus_box_count > 0
            else "Focus aid: no object detected — adjust lighting or ROI"
        )
        cv2.putText(preview, focus_msg, (10, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 220, 240), 1)
        return preview, "READY TO CAPTURE", self.total_count, "PRESS CAPTURE"

    def _is_countable_status(self, status):
        if status in {"OBJECT PRESENT", "PASS", "PASS (OK)"}:
            return True
        if status.startswith("CLASSIFIED:") or status.startswith("CODE READ:"):
            return True
        if status.startswith("PASSED:"):
            return True
        if (
            status.startswith("FAIL")
            or "DEFECT" in status
            or status in {"NO CODE", "NO TARGET"}
        ):
            return True
        return False

    def _result_class(self, status):
        return get_result_class(status)

    def _emit_inspection_event(self, status, quantity, metric2, result_class=None):
        if quantity <= 0:
            return
        result_class = result_class or self._result_class(status)
        if result_class not in {"fg", "ng"}:
            return
        self.inspection_event_signal.emit(str(status), int(quantity), result_class, str(metric2))

    def _emit_detection_events(self, status, detections, metric2, fallback_quantity=0):
        grouped = {"fg": 0, "ng": 0}
        fallback_class = self._result_class(status)
        for detection in detections or []:
            result_class = detection.get("result_class") or fallback_class
            if result_class in grouped:
                grouped[result_class] += 1

        emitted = 0
        for result_class, quantity in grouped.items():
            if quantity > 0:
                emitted += quantity
                self._emit_inspection_event(status, quantity, metric2, result_class)

        remaining = max(0, int(fallback_quantity) - emitted)
        if remaining > 0:
            self._emit_inspection_event(status, remaining, metric2, fallback_class)

    def _stop_capture_quantity(self, status, result_count, detections):
        if not self._is_countable_status(status):
            return 0
        if detections:
            return len(detections)
        try:
            result_count = int(result_count)
        except (TypeError, ValueError):
            result_count = 0
        if self.mode in {self.DETECTION_MODE, self.CLASSIFICATION_MODE, self.CODE_READING_MODE} and result_count > 0:
            return result_count
        return 1

    def _apply_counting_method(self, frame, processed_roi, detections, status, metric2, x, y, w, h, raw_frame=None, result_count=0):
        if self.counting_method == self.COUNTING_STOP_CAPTURE:
            frame[y:y+h, x:x+w] = processed_roi
            if self._inspection_capture_flag:
                self._inspection_capture_flag = False
                quantity = self._stop_capture_quantity(status, result_count, detections)
                self.total_count += quantity
                capture_frame = frame.copy()
                raw_capture = raw_frame.copy() if raw_frame is not None else capture_frame.copy()
                result_class = self._result_class(status) or "info"
                capture_status = status
                capture_metric = metric2
                try:
                    _, result_path = self._save_capture_images(
                        raw_capture,
                        capture_frame,
                        status,
                        self._capture_metadata(status, self.total_count, metric2, quantity, result_class),
                    )
                    capture_metric = f"{metric2} | {os.path.basename(result_path)}"
                except OSError:
                    capture_status = "CAPTURE SAVE FAILED"
                    capture_metric = "CHECK CAPTURES FOLDER"
                    self.error_signal.emit(capture_status)

                self._emit_detection_events(status, detections, metric2, quantity)
                self._captured_display_frame = capture_frame
                self._captured_status = capture_status
                self._captured_count = self.total_count
                self._captured_metric = capture_metric
                self._emit_capture_image(self._captured_display_frame)
                return frame, capture_status, self.total_count, capture_metric

            return frame, "READY TO CAPTURE", self.total_count, "PRESS CAPTURE"

        previous_count = self.total_count
        _, conveyor_count, active_objects, counted_roi = self.counting_tracker.process_detections(
            detections,
            processed_roi.shape,
            processed_roi,
        )
        self.total_count = conveyor_count
        frame[y:y+h, x:x+w] = counted_roi
        counted_events = self.counting_tracker.last_count_events
        fallback_quantity = max(0, self.total_count - previous_count)
        self._emit_detection_events(status, counted_events, metric2, fallback_quantity)
        return frame, status, self.total_count, f"{metric2} | Objects:{active_objects}"

    def _process_frame(self, frame, fw, fh):
        raw_frame = frame.copy()
        x = max(0, int(self.rx * fw / 100))
        y = max(0, int(self.ry * fh / 100))
        w = min(int(self.rw * fw / 100), fw - x)
        h = min(int(self.rh * fh / 100), fh - y)

        status, count, metric2 = "WAITING", 0, 0.0

        if w > 0 and h > 0:
            roi = frame[y:y+h, x:x+w]

            if self.mode == self.DETECTION_MODE:
                status, count, metric2, processed_roi = self.detection_algo.process(roi)
                color = (76, 175, 80) if count > 0 else (0, 165, 255)
                cv2.rectangle(frame, (x, y), (x+w, y+h), color, 2)
                frame, status, count, metric2 = self._apply_counting_method(
                    frame, processed_roi, self.detection_algo.last_detections, status, metric2, x, y, w, h, raw_frame, count
                )

            elif self.mode == self.DEFECT_MODE:
                frame, status, count, metric2 = self._process_defect_mode(frame, x, y, w, h)

            elif self.mode == self.CLASSIFICATION_MODE:
                status, count, metric2, processed_roi = self.classification_algo.process(roi)
                cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 255, 0), 1)
                frame, status, count, metric2 = self._apply_counting_method(
                    frame, processed_roi, self.classification_algo.last_detections, status, metric2, x, y, w, h, raw_frame, count
                )

            elif self.mode == self.CODE_READING_MODE:
                status, count, metric2, processed_roi = self.code_algo.process(roi)
                cv2.rectangle(frame, (x, y), (x+w, y+h), (156, 204, 101), 2)
                frame, status, count, metric2 = self._apply_counting_method(
                    frame, processed_roi, self.code_algo.last_detections, status, metric2, x, y, w, h, raw_frame, count
                )

            elif self.mode == self.COUNT_TRACK_MODE:
                if self.counting_method == self.COUNTING_STOP_CAPTURE:
                    frame, status, count, metric2 = self._process_count_snapshot_mode(frame, roi, x, y, w, h)
                else:
                    previous_count = self.total_count
                    status, count, metric2, processed_roi = self.tracking_algo.process(roi)
                    cv2.rectangle(frame, (x, y), (x+w, y+h), (255, 100, 100), 2)
                    self.total_count = count
                    frame[y:y+h, x:x+w] = processed_roi
                    event_quantity = max(0, self.total_count - previous_count)
                    self._emit_detection_events(status, self.tracking_algo.last_count_events, metric2, event_quantity)

            elif self.mode == self.STICKER_MODE:
                if self._capture_flag:
                    detected, saved = self.sticker_algo.set_reference(roi)
                    if not detected:
                        self.error_signal.emit("NO STICKER FOUND IN ROI — move ROI over the sticker")
                    elif not saved:
                        self.error_signal.emit("REFERENCE SAVED IN MEMORY ONLY — disk write failed (check config folder permissions)")
                    self._capture_flag = False

                frame, status, count, metric2 = self._process_capture_mode(frame, roi, x, y, w, h)
                self.total_count = count

            elif self.mode == self.MEASUREMENT_MODE:
                status, count, metric2, processed_roi = self.measurement_algo.process(roi)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (255, 193, 7), 1)
                frame, status, count, metric2 = self._apply_counting_method(
                    frame, processed_roi, self.measurement_algo.last_detections,
                    status, metric2, x, y, w, h, raw_frame, count
                )

        return frame, status, count, metric2

    def _frame_to_qimage(self, frame):
        if frame is None:
            raise ValueError("Cannot display an empty frame")

        fh, fw = frame.shape[:2]
        if len(frame.shape) == 2:
            rgb = cv2.cvtColor(frame, cv2.COLOR_GRAY2RGB)
        elif frame.shape[2] == 4:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGRA2RGB)
        else:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return QImage(rgb.data, fw, fh, 3 * fw, QImage.Format_RGB888).copy()

    def _emit_image(self, frame):
        self.change_pixmap_signal.emit(self._frame_to_qimage(frame))

    def _emit_capture_image(self, frame):
        self.capture_pixmap_signal.emit(self._frame_to_qimage(frame))

    def stop(self):
        self._run_flag = False
        if not self.isRunning():
            self.cap = None
            return True

        stopped = self.wait(3000)
        if stopped:
            self.cap = None
        return stopped
