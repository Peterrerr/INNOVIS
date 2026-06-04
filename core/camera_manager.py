# core/camera_manager.py
"""Owns up to three VideoThreads (Camera 1 / 2 / 3) and routes
signals between the dashboard UI and the per-camera threads.

Design (Phase 1):
  * Input signals from the dashboard/settings (mode, ROI, params, ...) are
    fanned out to *every* running thread — all cameras share one mode and one
    set of settings for now (per-camera settings arrive in Phase 2).
  * Output signals from each thread are re-emitted here tagged with the
    camera_id, so the view can route a live frame to the correct pane and the
    dashboard can show the primary camera's result.

The manager is a QObject so it can own Qt signal/slot connections.
"""

from PyQt5.QtCore import QObject, pyqtSignal
from PyQt5.QtGui import QImage

from core.camera_thread import VideoThread


# Camera slots, labelled generically by number — angles/positions may be
# swapped around in the field, so we don't bake an angle into the name.
CAMERA_IDS = ["cam1", "cam2", "cam3"]
CAMERA_LABELS = {"cam1": "Camera 1", "cam2": "Camera 2", "cam3": "Camera 3"}
DEFAULT_INDEX_MAP = {"cam1": 0, "cam2": 1, "cam3": 2}


class CameraManager(QObject):
    # All outputs are tagged with the originating camera_id.
    live_frame_signal = pyqtSignal(str, QImage)
    capture_frame_signal = pyqtSignal(str, QImage)
    data_signal = pyqtSignal(str, str, int, str, int)
    inspection_signal = pyqtSignal(str, str, int, str, str)
    error_signal = pyqtSignal(str, str)
    defect_frame_signal = pyqtSignal(str, object)

    def __init__(self, dashboard):
        super().__init__()
        self.dashboard = dashboard
        self.threads = {}  # camera_id -> VideoThread (only while running)
        self.index_map = dict(DEFAULT_INDEX_MAP)
        self.enabled = list(CAMERA_IDS)
        self.primary = CAMERA_IDS[0]
        self._input_forwarders = []
        self._wire_dashboard_inputs()

    # ---- configuration ------------------------------------------------- #
    def configure(self, index_map=None, enabled=None, primary=None):
        """Apply camera layout (device indices, which cameras are on, primary).
        Has no effect on already-running threads except recording the choice."""
        if index_map:
            self.index_map.update({cid: int(index_map[cid]) for cid in index_map if cid in CAMERA_IDS})
        if enabled is not None:
            self.enabled = [cid for cid in CAMERA_IDS if cid in enabled] or [CAMERA_IDS[0]]
        if primary is not None and primary in CAMERA_IDS:
            self.primary = primary
        if self.primary not in self.enabled and self.enabled:
            self.primary = self.enabled[0]

    # ---- lifecycle ----------------------------------------------------- #
    def is_running(self):
        return any(t.isRunning() for t in self.threads.values())

    def start_enabled(self):
        """Start a thread for every enabled camera that isn't already running."""
        for camera_id in self.enabled:
            self.start(camera_id)

    def start(self, camera_id):
        if camera_id not in CAMERA_IDS:
            return None
        existing = self.threads.get(camera_id)
        if existing is not None and existing.isRunning():
            return existing
        thread = VideoThread(camera_index=self.index_map.get(camera_id, 0), camera_id=camera_id)
        # Each camera sticks to its assigned device index — no fallback that
        # could collide with another running camera.
        thread.allow_index_fallback = False
        self._connect_outputs(thread)
        self.threads[camera_id] = thread
        self._apply_initial_settings(thread)
        thread.start()
        return thread

    def _apply_initial_settings(self, thread):
        """Seed a freshly created thread with the global mode + its own
        per-camera settings block, so each camera runs with its own config."""
        db = self.dashboard
        thread.set_mode(getattr(db, "current_mode", 0))
        thread.update_counting_method(getattr(db, "current_counting_method", 0))
        block = {}
        getter = getattr(db.settings_window, "get_camera_settings", None)
        if callable(getter):
            try:
                block = getter(thread.camera_id)
            except Exception:
                block = {}
        thread.apply_settings(block)

    def stop(self, camera_id):
        thread = self.threads.pop(camera_id, None)
        if thread is None:
            return True
        stopped = thread.stop()
        self._disconnect_outputs(thread)
        return stopped

    def stop_all(self):
        all_stopped = True
        for camera_id in list(self.threads.keys()):
            if not self.stop(camera_id):
                all_stopped = False
        return all_stopped

    def set_primary(self, camera_id):
        if camera_id in CAMERA_IDS:
            self.primary = camera_id

    def start_active(self):
        """Single-camera mode: run only the active (primary) camera."""
        return self.start(self.primary)

    def switch_to(self, camera_id):
        """Stop whatever is running and start the chosen camera instead."""
        if camera_id not in CAMERA_IDS:
            return None
        self.stop_all()
        self.set_primary(camera_id)
        return self.start(camera_id)

    def primary_thread(self):
        return self.threads.get(self.primary)

    def request_inspection_capture(self):
        """Capture on the primary camera (Phase 1: single result source)."""
        thread = self.primary_thread()
        if thread is not None:
            thread.request_inspection_capture()

    # ---- input routing (dashboard -> threads) -------------------------- #
    def _wire_dashboard_inputs(self):
        db = self.dashboard
        dw = db.settings_window.defect_widget
        # Global: the mode is shared by every camera, so these go to all threads.
        global_inputs = [
            (db.mode_signal, "set_mode"),
            (db.counting_method_signal, "update_counting_method"),
            (db.reset_signal, "reset_stats"),
            # Counting / tracking is stored per-mode (not per-camera), so it is
            # shared by every camera.
            (db.tracking_params_signal, "update_tracking_params"),
        ]
        # Per-camera: ROI / params / training edits target only the camera
        # currently being configured (== the primary / big view).
        per_camera_inputs = [
            (db.roi_settings_signal, "update_roi"),
            (db.hw_settings_signal, "update_hw"),
            (db.detection_params_signal, "update_detection_params"),
            (db.sticker_params_signal, "update_sticker_params"),
            (db.measurement_params_signal, "update_measurement_params"),
            (db.classification_target_signal, "update_classification_targets"),
            (db.classification_params_signal, "update_classification_params"),
            (db.classification_colors_signal, "update_classification_colors"),
            (db.measurement_calibration_signal, "update_measurement_calibration"),
            (db.code_expected_signal, "update_code_expected"),
            (db.set_template_signal, "capture_template"),
            (dw.focus_aid_params_signal, "update_focus_aid"),
        ]
        for signal, method_name in global_inputs:
            forwarder = self._make_forwarder(method_name, primary_only=False)
            signal.connect(forwarder)
            self._input_forwarders.append(forwarder)  # keep refs alive
        for signal, method_name in per_camera_inputs:
            forwarder = self._make_forwarder(method_name, primary_only=True)
            signal.connect(forwarder)
            self._input_forwarders.append(forwarder)

    def _make_forwarder(self, method_name, primary_only):
        def forward(*args):
            if primary_only:
                thread = self.primary_thread()
                targets = [thread] if thread is not None else []
            else:
                targets = list(self.threads.values())
            for thread in targets:
                getattr(thread, method_name)(*args)
        return forward

    def push_all_settings(self):
        """Re-seed every running thread with the global mode + its own block,
        then re-emit the global signals (mode/counting/tracking) to all."""
        for thread in list(self.threads.values()):
            self._apply_initial_settings(thread)
        emit = getattr(self.dashboard.settings_window, "emit_all_settings", None)
        if callable(emit):
            emit()

    # ---- output routing (thread -> tagged manager signals) ------------- #
    def _connect_outputs(self, thread):
        cid = thread.camera_id
        thread._mgr_slots = {
            thread.change_pixmap_signal: lambda img, c=cid: self.live_frame_signal.emit(c, img),
            thread.capture_pixmap_signal: lambda img, c=cid: self.capture_frame_signal.emit(c, img),
            thread.update_data_signal: lambda s, n, m, f, c=cid: self.data_signal.emit(c, s, n, m, f),
            thread.inspection_event_signal: lambda s, q, rc, m, c=cid: self.inspection_signal.emit(c, s, q, rc, m),
            thread.error_signal: lambda msg, c=cid: self.error_signal.emit(c, msg),
            thread.defect_frame_signal: lambda frame, c=cid: self.defect_frame_signal.emit(c, frame),
        }
        for signal, slot in thread._mgr_slots.items():
            signal.connect(slot)

    def _disconnect_outputs(self, thread):
        for signal, slot in getattr(thread, "_mgr_slots", {}).items():
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        thread._mgr_slots = {}
