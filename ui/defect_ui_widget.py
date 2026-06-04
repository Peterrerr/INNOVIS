"""Operator-friendly PyQt5 widget for the multi-angle DefectDetector.

The widget guides the operator through a four-step workflow with a banner,
a single large primary action button, and per-label sample buttons that
show their current sample count. Trained models are auto-saved to and
auto-loaded from a default folder under ``config/`` so the operator does
not have to manage files in the common case.
"""

from __future__ import annotations

import os
from collections import deque
from typing import Dict, Optional

import cv2
import numpy as np
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QImage
from PyQt5.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from algorithms.defect_detector import DEFECT_LABELS, DefectDetector
from core.settings_store import SettingsStore


# Minimum samples required before the model can usefully train.
_MIN_GOOD = 3
_MIN_DEFECT_TOTAL = 1

# Tooltips and human-friendly defect names (Thai shown in helper text).
_LABEL_DISPLAY = {
    "good":    "Good",
    "scratch": "Scratch",
    "stain":   "Stain",
    "crack":   "Crack",
    "deform":  "Deform",
}


class DefectWidget(QWidget):
    """Operator UI that drives the underlying DefectDetector."""

    inspection_done = pyqtSignal(str, int, str)  # (status, defect_count, confidence)
    # Annotated BGR-as-QImage of the last inspection — shown by CameraWindow
    # in its capture panel.
    result_image_signal = pyqtSignal(QImage)
    # Live focus-aid tuning: (min_area_percent_of_roi, polarity) where
    # polarity is "dark" or "light".
    focus_aid_params_signal = pyqtSignal(float, str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        """Build the UI, wire signals, and auto-load any existing model."""
        super().__init__(parent)
        self._detector = DefectDetector()
        self._current_frame: Optional[np.ndarray] = None
        self._last_results: Dict[str, tuple] = {}
        # Rolling buffer of recent frames — median across the buffer cancels
        # per-frame noise and auto-exposure flicker (cases A and C).
        self._frame_buffer: deque = deque(maxlen=7)
        self._label_buttons: Dict[str, QPushButton] = {}

        # Each camera trains its own defect model under config/defect_models/<cam>/.
        # The base folder is kept for a legacy (single-model) fallback.
        try:
            self._models_base_dir = os.path.join(
                SettingsStore().config_dir, "defect_models"
            )
        except Exception:
            self._models_base_dir = os.path.abspath("config/defect_models")
        self._camera_id = "cam1"
        self._auto_dir = os.path.join(self._models_base_dir, self._camera_id)

        self._build_ui()
        self._auto_load()
        self._refresh_angles_combo()
        self._refresh_all()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def set_frame(self, frame: np.ndarray) -> None:
        """Store the latest ROI frame (used by capture / train / inspect)."""
        if frame is None or frame.size == 0:
            return
        self._current_frame = frame.copy()
        self._frame_buffer.append(frame.copy())

    def capture_and_inspect(self) -> None:
        """Run inspection on the currently stored frame and update the UI."""
        if self._current_frame is None:
            self._toast("No camera frame yet — press START CAMERA first.")
            return

        # Use pixel-wise median across the rolling buffer when enough frames
        # have accumulated. The median collapses flicker from auto-exposure and
        # per-frame sensor noise (cases A and C) without blurring real defects.
        if len(self._frame_buffer) >= 3:
            stack = np.stack(list(self._frame_buffer), axis=0)
            inspect_frame = np.median(stack, axis=0).astype(np.uint8)
        else:
            inspect_frame = self._current_frame

        status, defects, conf, result = self._detector.process(inspect_frame)
        self._last_results[self._detector.active_angle()] = (status, defects, conf)
        self._refresh_results_table()
        self._refresh_last_result_banner(status, defects, conf)
        self._emit_result_image(result)
        self.inspection_done.emit(status, defects, conf)

    def _emit_result_image(self, bgr: np.ndarray) -> None:
        """Convert the BGR result frame to QImage and emit for display."""
        if bgr is None or bgr.size == 0:
            return
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, w * 3, QImage.Format_RGB888).copy()
        self.result_image_signal.emit(qimg)

    def get_detector(self) -> DefectDetector:
        """Return the underlying :class:`DefectDetector` instance."""
        return self._detector

    # ------------------------------------------------------------------ #
    # UI construction
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """Build and lay out every UI element (control panel only)."""
        self.setStyleSheet(
            "DefectWidget QGroupBox { "
            "  background:#0F1823; border:1px solid #22384E; "
            "  border-radius:8px; margin-top:14px; padding:12px 8px 8px 8px; "
            "  color:#7BC4E6; font-size:11px; font-weight:bold; "
            "} "
            "DefectWidget QGroupBox::title { "
            "  subcontrol-origin: margin; subcontrol-position: top left; "
            "  left:10px; padding:0 4px; "
            "} "
            "DefectWidget QLabel { background: transparent; }"
        )

        self._last_result_label = QLabel("No inspection yet")
        self._last_result_label.setAlignment(Qt.AlignCenter)
        self._last_result_label.setWordWrap(True)
        self._last_result_label.setStyleSheet(
            "QLabel { background:#101821; color:#9FB2C6; "
            "border:1px solid #22384E; border-radius:8px; "
            "padding:6px; font-size:12px; font-weight:bold; }"
        )

        root = QVBoxLayout(self)
        root.setSpacing(6)
        root.setContentsMargins(2, 2, 2, 2)

        root.addWidget(self._last_result_label)
        root.addWidget(self._build_step_banner())
        root.addWidget(self._build_action_button())
        # The "Angle" group is hidden: each camera now keeps its own model, so a
        # single default angle per camera is enough. The combo/buttons still
        # exist (kept off-screen) so the detector's angle logic stays intact.
        self._angle_group = self._build_angle_group()
        self._angle_group.setVisible(False)
        root.addWidget(self._angle_group)
        root.addWidget(self._build_training_group())
        root.addWidget(self._build_status_group())
        root.addWidget(self._build_focus_aid_group())
        root.addWidget(self._build_params_group())
        root.addWidget(self._build_more_actions())
        root.addWidget(self._build_results_group())
        root.addStretch(1)

    # ---- step banner --------------------------------------------------- #
    def _build_step_banner(self) -> QWidget:
        """The top instruction banner that walks the operator through steps."""
        box = QFrame()
        box.setStyleSheet(
            "QFrame { background:#0F1A24; border:1px solid #2B4566; "
            "border-radius:10px; }"
        )
        v = QVBoxLayout(box)
        v.setContentsMargins(12, 10, 12, 10)
        v.setSpacing(2)
        self._step_title = QLabel("Step 1 of 4")
        self._step_title.setStyleSheet(
            "color:#7EB8F7; font-size:11px; font-weight:bold;"
        )
        self._step_body = QLabel("")
        self._step_body.setWordWrap(True)
        self._step_body.setStyleSheet("color:#E6EDF3; font-size:13px;")
        v.addWidget(self._step_title)
        v.addWidget(self._step_body)
        return box

    # ---- big primary action button ------------------------------------- #
    def _build_action_button(self) -> QWidget:
        """One large CTA whose label changes based on the current step."""
        self._action_btn = QPushButton("CAPTURE TEMPLATE")
        self._action_btn.setMinimumHeight(42)
        self._action_btn.setStyleSheet(
            "QPushButton { background:#1F6F3D; color:white; "
            "border:1px solid #2C8C4F; border-radius:8px; "
            "font-size:13px; font-weight:bold; padding:6px; }"
            "QPushButton:hover { background:#2C8C4F; }"
            "QPushButton:disabled { background:#132117; color:#6E8375; "
            "border:1px solid #1C3828; }"
        )
        self._action_btn.clicked.connect(self._on_primary_action)
        return self._action_btn

    # ---- angle manager ------------------------------------------------- #
    def _build_angle_group(self) -> QGroupBox:
        """Angle dropdown + add/rename/remove buttons."""
        box = QGroupBox("Angle")
        v = QVBoxLayout(box)
        v.setSpacing(6)

        self._angle_combo = QComboBox()
        self._angle_combo.currentTextChanged.connect(self._on_angle_changed)
        v.addWidget(self._angle_combo)

        row = QHBoxLayout()
        btn_add = QPushButton("Add angle")
        btn_rename = QPushButton("Rename")
        btn_remove = QPushButton("Remove")
        btn_add.clicked.connect(self._on_add_angle)
        btn_rename.clicked.connect(self._on_rename_angle)
        btn_remove.clicked.connect(self._on_remove_angle)
        row.addWidget(btn_add)
        row.addWidget(btn_rename)
        row.addWidget(btn_remove)
        v.addLayout(row)
        return box

    # ---- training samples --------------------------------------------- #
    def _build_training_group(self) -> QGroupBox:
        """Per-label add-sample buttons (each shows its count)."""
        box = QGroupBox("Add training sample for the current frame")
        v = QVBoxLayout(box)
        v.setSpacing(6)

        hint = QLabel(
            "Place the part in front of the camera, then press the matching "
            f"button. Aim for at least {_MIN_GOOD} good samples and "
            f"{_MIN_DEFECT_TOTAL}+ samples of any defect type."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#95A8BC; font-size:11px;")
        v.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(4)
        grid.setHorizontalSpacing(4)
        for i, label in enumerate(DEFECT_LABELS):
            btn = QPushButton(self._label_button_text(label, 0))
            btn.setMinimumHeight(32)
            btn.setStyleSheet(
                "QPushButton { background:#162231; color:#E6EDF3; "
                "border:1px solid #30465F; border-radius:6px; "
                "font-size:11px; font-weight:bold; padding:4px; }"
                "QPushButton:hover { background:#1C2B3D; }"
                "QPushButton:disabled { background:#0E141A; color:#536577; "
                "border:1px solid #1A2531; }"
            )
            btn.clicked.connect(
                lambda _checked, lbl=label: self._on_add_sample(lbl)
            )
            self._label_buttons[label] = btn
            grid.addWidget(btn, i // 2, i % 2)
        v.addLayout(grid)
        return box

    # ---- current-state status box ------------------------------------- #
    def _build_status_group(self) -> QGroupBox:
        """Compact status block showing template / samples / model state."""
        box = QGroupBox("Current state")
        v = QVBoxLayout(box)
        v.setSpacing(4)
        self._template_status = QLabel()
        self._samples_status = QLabel()
        self._samples_status.setWordWrap(True)
        self._model_status = QLabel()
        self._model_status.setWordWrap(True)
        for lbl in (self._template_status, self._samples_status, self._model_status):
            lbl.setStyleSheet("color:#D8E2EC; font-size:12px;")
            v.addWidget(lbl)
        return box

    # ---- focus-aid tuning (live overlay) ------------------------------ #
    def _build_focus_aid_group(self) -> QGroupBox:
        """Controls for tuning the green object outline shown on live view."""
        box = QGroupBox("Focus aid (green outline on live view)")
        v = QVBoxLayout(box)
        v.setSpacing(4)

        hint = QLabel(
            "Tune until the green outline hugs the part. This is just a "
            "visual aid — it does not affect defect detection."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#95A8BC; font-size:11px;")
        v.addWidget(hint)

        # Min area slider — each tick = 0.05% of ROI area.
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Min area"))
        self._focus_min_area_slider = QSlider(Qt.Horizontal)
        self._focus_min_area_slider.setRange(1, 200)
        self._focus_min_area_slider.setValue(4)  # default 0.20% of ROI
        self._focus_min_area_slider.valueChanged.connect(self._on_focus_aid_changed)
        self._focus_min_area_value = QLabel("0.20%")
        self._focus_min_area_value.setFixedWidth(56)
        self._focus_min_area_value.setAlignment(Qt.AlignCenter)
        self._focus_min_area_value.setStyleSheet(
            "background:#0B121A; color:#EDF4FB; border:1px solid #2A4158; "
            "border-radius:6px; padding:2px; font-size:11px; font-weight:bold;"
        )
        row1.addWidget(self._focus_min_area_slider, 1)
        row1.addWidget(self._focus_min_area_value)
        v.addLayout(row1)

        # Polarity combo.
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Object"))
        self._focus_polarity_combo = QComboBox()
        self._focus_polarity_combo.addItems([
            "Dark on light background",
            "Light on dark background",
        ])
        self._focus_polarity_combo.currentIndexChanged.connect(self._on_focus_aid_changed)
        row2.addWidget(self._focus_polarity_combo, 1)
        v.addLayout(row2)
        return box

    def _on_focus_aid_changed(self) -> None:
        """Recompute % label and emit focus-aid params."""
        pct = self._focus_min_area_slider.value() * 0.05
        self._focus_min_area_value.setText(f"{pct:.2f}%")
        polarity = (
            "dark"
            if self._focus_polarity_combo.currentIndex() == 0
            else "light"
        )
        self.focus_aid_params_signal.emit(pct, polarity)

    def emit_focus_aid_params(self) -> None:
        """Push current focus-aid params — used by CameraWindow after camera start."""
        self._on_focus_aid_changed()

    # ---- parameters --------------------------------------------------- #
    def _build_params_group(self) -> QGroupBox:
        """Sensitivity slider."""
        box = QGroupBox("Detection sensitivity")
        v = QVBoxLayout(box)
        row = QHBoxLayout()
        self._sens_slider = QSlider(Qt.Horizontal)
        self._sens_slider.setRange(0, 100)
        self._sens_slider.setValue(50)
        self._sens_slider.valueChanged.connect(self._on_sensitivity_changed)
        self._sens_value_label = QLabel("0.50")
        self._sens_value_label.setFixedWidth(48)
        self._sens_value_label.setAlignment(Qt.AlignCenter)
        self._sens_value_label.setStyleSheet(
            "background:#0B121A; color:#EDF4FB; border:1px solid #2A4158; "
            "border-radius:6px; padding:4px; font-weight:bold;"
        )
        row.addWidget(QLabel("Low"))
        row.addWidget(self._sens_slider, 1)
        row.addWidget(QLabel("High"))
        row.addWidget(self._sens_value_label)
        v.addLayout(row)
        hint = QLabel(
            "Higher sensitivity catches smaller / fainter defects "
            "but may trigger on noise."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#95A8BC; font-size:11px;")
        v.addWidget(hint)
        return box

    # ---- secondary actions -------------------------------------------- #
    def _build_more_actions(self) -> QWidget:
        """Save-as / Import / Clear buttons (used less often)."""
        box = QGroupBox("Model file (auto-saved on every train)")
        v = QVBoxLayout(box)
        v.setSpacing(6)

        self._path_label = QLabel(self._auto_dir)
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet("color:#95A8BC; font-size:11px;")
        v.addWidget(self._path_label)

        row = QHBoxLayout()
        btn_save = QPushButton("Save copy to...")
        btn_load = QPushButton("Import from...")
        btn_clear = QPushButton("Clear samples")
        btn_save.clicked.connect(self._on_save_copy)
        btn_load.clicked.connect(self._on_import)
        btn_clear.clicked.connect(self._on_clear_samples)
        row.addWidget(btn_save)
        row.addWidget(btn_load)
        row.addWidget(btn_clear)
        v.addLayout(row)
        return box

    # ---- per-angle results table -------------------------------------- #
    def _build_results_group(self) -> QGroupBox:
        """Result table — one row per angle, last inspection result."""
        box = QGroupBox("Last result per angle")
        v = QVBoxLayout(box)
        self._results_table = QTableWidget(0, 4)
        self._results_table.setHorizontalHeaderLabels(
            ["Angle", "Status", "Defects", "Confidence"]
        )
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch
        )
        self._results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._results_table.setSelectionMode(QTableWidget.NoSelection)
        self._results_table.setFocusPolicy(Qt.NoFocus)
        self._results_table.setFrameShape(QFrame.StyledPanel)
        v.addWidget(self._results_table)
        return box

    # ------------------------------------------------------------------ #
    # Primary-action handler — its meaning depends on current step
    # ------------------------------------------------------------------ #
    def _on_primary_action(self) -> None:
        """Dispatch the big button to the right operation for current step."""
        step = self._current_step()
        if step == 1:
            self._on_capture_template()
        elif step == 2:
            self._toast(f"Add at least {_MIN_GOOD} GOOD samples using the buttons below.")
        elif step == 3:
            self._on_train()
        else:
            self.capture_and_inspect()

    # ------------------------------------------------------------------ #
    # Step state machine
    # ------------------------------------------------------------------ #
    def _current_step(self) -> int:
        """Return 1..4 indicating the next operator action for this angle.

        Defect samples are never required — good-only is enough to train.
        """
        if not self._detector.has_template():
            return 1
        counts = self._detector.sample_counts
        good = counts.get("good", 0)
        if good < _MIN_GOOD:
            return 2
        if not self._detector.has_ai_model():
            return 3
        return 4

    def _refresh_step_banner(self) -> None:
        """Update the banner + the big CTA label to match the current step."""
        step = self._current_step()
        if step == 1:
            self._step_title.setText("Step 1 of 4")
            self._step_body.setText(
                "Place a known-good part in the camera, then press "
                "CAPTURE TEMPLATE to save the reference image for this camera."
            )
            self._action_btn.setText("CAPTURE TEMPLATE")
            self._action_btn.setEnabled(True)
        elif step == 2:
            counts = self._detector.sample_counts
            good = counts.get("good", 0)
            self._step_title.setText("Step 2 of 4")
            self._step_body.setText(
                f"Add GOOD samples: {good}/{_MIN_GOOD} so far. "
                "You can train with good-only samples — no defect samples required. "
                "Add defect samples too if you want the model to identify defect types."
            )
            self._action_btn.setText("ADD SAMPLES BELOW")
            self._action_btn.setEnabled(False)
        elif step == 3:
            counts = self._detector.sample_counts
            good = counts.get("good", 0)
            defect = sum(v for k, v in counts.items() if k != "good")
            if defect == 0:
                body = (
                    f"Ready to train with {good} good samples. "
                    "The model will flag any part that differs from good as DEFECT "
                    "without specifying type. Add defect samples first if you want "
                    "type classification (scratch / stain / crack / deform)."
                )
            else:
                body = (
                    f"Ready to train with {good} good + {defect} defect samples. "
                    "The model will classify defect types. Press TRAIN MODEL."
                )
            self._step_title.setText("Step 3 of 4")
            self._step_body.setText(body)
            self._action_btn.setText("TRAIN MODEL")
            self._action_btn.setEnabled(True)
        else:
            self._step_title.setText("Ready")
            self._step_body.setText(
                "Model is trained. Press INSPECT NOW (or the dashboard "
                "CAPTURE button) to run a defect inspection on the current frame."
            )
            self._action_btn.setText("INSPECT NOW")
            self._action_btn.setEnabled(True)

    # ------------------------------------------------------------------ #
    # Event handlers — angle manager
    # ------------------------------------------------------------------ #
    def _on_angle_changed(self, name: str) -> None:
        """Combo selection -> activate that angle and refresh all state."""
        if not name or name == self._detector.active_angle():
            self._refresh_all()
            return
        self._detector.set_active_angle(name)
        self._refresh_all()

    def _on_add_angle(self) -> None:
        """Prompt the operator for a new angle name."""
        suggestions = ["Top", "Front", "Back", "Side Left", "Side Right"]
        existing = set(self._detector.list_angles())
        default = next((s for s in suggestions if s not in existing), "")
        name, ok = QInputDialog.getText(
            self, "Add angle", "Angle name:", text=default
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in existing:
            self._toast(f"Angle '{name}' already exists.")
            return
        self._detector.add_angle(name)
        self._detector.set_active_angle(name)
        self._refresh_angles_combo()
        self._refresh_all()

    def _on_rename_angle(self) -> None:
        """Rename the active angle (carries over result-table row)."""
        old = self._detector.active_angle()
        name, ok = QInputDialog.getText(
            self, "Rename angle", f"New name for '{old}':", text=old
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if name == old:
            return
        if name in self._detector.list_angles():
            self._toast(f"Angle '{name}' already exists.")
            return
        self._detector.rename_angle(old, name)
        if old in self._last_results:
            self._last_results[name] = self._last_results.pop(old)
        self._refresh_angles_combo()
        self._refresh_all()

    def _on_remove_angle(self) -> None:
        """Remove the active angle and all its training data."""
        if len(self._detector.list_angles()) <= 1:
            self._toast("Cannot remove the last remaining angle.")
            return
        name = self._detector.active_angle()
        ans = QMessageBox.question(
            self, "Remove angle",
            f"Remove angle '{name}' and all its training data?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._detector.remove_angle(name)
        self._last_results.pop(name, None)
        self._refresh_angles_combo()
        self._refresh_all()

    # ------------------------------------------------------------------ #
    # Event handlers — template / training / model / params
    # ------------------------------------------------------------------ #
    def _on_capture_template(self) -> None:
        """Use the current frame as the active angle's template."""
        if self._current_frame is None:
            self._toast("No camera frame yet — press START CAMERA first.")
            return
        self._detector.set_template(self._current_frame)
        self._refresh_all()
        self._toast(
            f"Template captured for angle '{self._detector.active_angle()}'."
        )

    def _on_add_sample(self, label: str) -> None:
        """Add the current frame as a labeled sample (with augmentations)."""
        if self._current_frame is None:
            self._toast("No camera frame yet — press START CAMERA first.")
            return
        if not self._detector.has_template():
            self._toast("Capture a template first (Step 1).")
            return
        self._detector.add_labeled_sample(self._current_frame, label)
        self._refresh_all()

    def _on_train(self) -> None:
        """Train the classifier for the active angle and auto-save the model."""
        ok = self._detector.train()
        if not ok:
            self._toast(f"Training failed — need at least {_MIN_GOOD} GOOD samples.")
        else:
            self._auto_save()
            self._toast(
                f"Model trained for '{self._detector.active_angle()}'. "
                "Ready to inspect."
            )
        self._refresh_all()

    def _on_clear_samples(self) -> None:
        """Confirm then clear all samples for the active angle."""
        ans = QMessageBox.question(
            self, "Clear samples",
            f"Clear all training samples for '{self._detector.active_angle()}'?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        self._detector.clear_training_data()
        self._auto_save()
        self._refresh_all()

    def _on_save_copy(self) -> None:
        """Save a copy of the model to an operator-chosen folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Save model copy — choose folder"
        )
        if not folder:
            return
        try:
            self._detector.save_ai_model(folder)
            self._toast(f"Model copy saved to:\n{folder}")
        except Exception as exc:
            self._toast(f"Save failed: {exc}")

    def _on_import(self) -> None:
        """Import a model from an operator-chosen folder."""
        folder = QFileDialog.getExistingDirectory(
            self, "Import model — choose folder"
        )
        if not folder:
            return
        try:
            self._detector.load_ai_model(folder)
            self._auto_save()  # also persist into the default folder
        except Exception as exc:
            self._toast(f"Import failed: {exc}")
            return
        self._last_results.clear()
        self._refresh_angles_combo()
        self._refresh_all()
        self._toast("Model imported successfully.")

    def _on_sensitivity_changed(self, value: int) -> None:
        """Slider 0-100 -> detector sensitivity 0.0-1.0."""
        s = value / 100.0
        self._detector.update_params(sensitivity=s)
        self._sens_value_label.setText(f"{s:.2f}")

    # ------------------------------------------------------------------ #
    # Persistence helpers
    # ------------------------------------------------------------------ #
    def _auto_load(self) -> None:
        """Load this camera's model folder if present (silent on missing).
        For the first camera, fall back to the legacy single-model folder."""
        load_dir = self._auto_dir
        if not os.path.isdir(load_dir):
            legacy = self._models_base_dir
            is_first_cam = self._auto_dir == os.path.join(self._models_base_dir, "cam1")
            if is_first_cam and os.path.isdir(legacy) and os.listdir(legacy):
                load_dir = legacy
            else:
                return
        try:
            self._detector.load_ai_model(load_dir)
        except Exception:
            pass

    def set_camera(self, camera_id: str) -> None:
        """Point training/inspection at a specific camera's model. Persists the
        current camera's model first, then loads the selected camera's model."""
        new_dir = os.path.join(self._models_base_dir, str(camera_id))
        if new_dir == self._auto_dir:
            return
        self._auto_save()
        self._camera_id = str(camera_id)
        self._auto_dir = new_dir
        self._detector = DefectDetector()
        self._auto_load()
        if hasattr(self, "_path_label"):
            self._path_label.setText(self._auto_dir)
        self._refresh_angles_combo()
        self._refresh_all()

    def _auto_save(self) -> None:
        """Save everything to the default folder (silent on failure)."""
        try:
            os.makedirs(self._auto_dir, exist_ok=True)
            self._detector.save_ai_model(self._auto_dir)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Refresh helpers
    # ------------------------------------------------------------------ #
    def _refresh_all(self) -> None:
        """Refresh every dynamic UI element after any state change."""
        self._refresh_angle_buttons_enabled()
        self._refresh_label_buttons()
        self._refresh_status_labels()
        self._refresh_results_table()
        self._refresh_step_banner()

    def _refresh_angle_buttons_enabled(self) -> None:
        """Nothing to disable on the combo box itself, kept for symmetry."""

    def _refresh_angles_combo(self) -> None:
        """Rebuild the angle combo from the detector, restore selection."""
        self._angle_combo.blockSignals(True)
        try:
            self._angle_combo.clear()
            self._angle_combo.addItems(self._detector.list_angles())
            idx = self._angle_combo.findText(self._detector.active_angle())
            if idx >= 0:
                self._angle_combo.setCurrentIndex(idx)
        finally:
            self._angle_combo.blockSignals(False)

    def _label_button_text(self, label: str, count: int) -> str:
        """Render the add-sample button label with its current count."""
        return f"{_LABEL_DISPLAY[label].upper()}  ({count})"

    def _refresh_label_buttons(self) -> None:
        """Update each per-label button's caption to include its sample count.

        Buttons are disabled until a template is captured.
        """
        counts = self._detector.sample_counts
        has_template = self._detector.has_template()
        for label, btn in self._label_buttons.items():
            btn.setText(self._label_button_text(label, counts.get(label, 0)))
            btn.setEnabled(has_template)

    def _refresh_status_labels(self) -> None:
        """Update the three status lines (template / samples / model)."""
        angle = self._detector.active_angle()
        if self._detector.has_template():
            self._template_status.setText(f"Template: set for '{angle}'")
            self._template_status.setStyleSheet(
                "color:#7BD389; font-size:12px;"
            )
        else:
            self._template_status.setText(f"Template: not set for '{angle}'")
            self._template_status.setStyleSheet(
                "color:#F4A862; font-size:12px;"
            )

        counts = self._detector.sample_counts
        good = counts.get("good", 0)
        defect_parts = [
            f"{_LABEL_DISPLAY[k].lower()}={v}"
            for k, v in counts.items() if k != "good" and v > 0
        ]
        defect_summary = ", ".join(defect_parts) if defect_parts else "none"
        self._samples_status.setText(
            f"Samples: good={good}, defects: {defect_summary}"
        )

        if self._detector.has_ai_model():
            self._model_status.setText(f"Model: trained for '{angle}'")
            self._model_status.setStyleSheet(
                "color:#7BD389; font-size:12px;"
            )
        else:
            self._model_status.setText(f"Model: not trained for '{angle}'")
            self._model_status.setStyleSheet(
                "color:#F4A862; font-size:12px;"
            )

    def _refresh_results_table(self) -> None:
        """Repaint the per-angle results table from ``_last_results``."""
        angles = self._detector.list_angles()
        self._results_table.setRowCount(len(angles))
        for row, name in enumerate(angles):
            result = self._last_results.get(name)
            if result is None:
                status, defects, conf = "-", "-", "-"
                bg = (240, 240, 240)
            else:
                status, defects_n, conf = result
                defects = str(defects_n)
                if "PASS" in status:
                    bg = (200, 235, 200)
                else:
                    bg = (245, 200, 200)

            values = [name, str(status), str(defects), str(conf)]
            for col, val in enumerate(values):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col > 0:
                    item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QBrush(QColor(*bg)))
                item.setForeground(QBrush(QColor(20, 20, 20)))
                self._results_table.setItem(row, col, item)

    def _refresh_last_result_banner(
        self, status: str, defects: int, conf: str
    ) -> None:
        """Update the bottom-left banner with the last inspection result."""
        if "PASS" in status:
            bg = "#1E3A26"
            border = "#3FAA63"
            fg = "#9BE2A8"
        else:
            bg = "#3A1E1E"
            border = "#C24D67"
            fg = "#F4A8A8"
        self._last_result_label.setText(
            f"Last result: {status}   |   Defects: {defects}   |   "
            f"Confidence: {conf}"
        )
        self._last_result_label.setStyleSheet(
            f"QLabel {{ background:{bg}; color:{fg}; "
            f"border:1px solid {border}; border-radius:8px; "
            f"padding:8px; font-size:13px; font-weight:bold; }}"
        )

    # ------------------------------------------------------------------ #
    # Misc helpers
    # ------------------------------------------------------------------ #
    def _toast(self, message: str) -> None:
        """Show a short modal information dialog (non-fatal)."""
        QMessageBox.information(self, "Defect Inspection", message)
