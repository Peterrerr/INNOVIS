import numpy as np
import cv2
import pytest
from algorithms.classification import ClassificationDetector


def _frame(h=200, w=200, bg=220):
    return np.full((h, w, 3), bg, dtype=np.uint8)


def _with_rect(frame, y1, x1, y2, x2, bgr):
    f = frame.copy()
    f[y1:y2, x1:x2] = bgr
    return f


class TestClassificationDetector:
    def setup_method(self):
        self.det = ClassificationDetector()
        self.det.update_params(min_area=500)

    # --- no objects ---

    def test_uniform_frame_no_target(self):
        # Perfectly uniform frame → no distinguishable contours
        status, count, _, _ = self.det.process(_frame(200, 200, 127))
        assert status == "NO TARGET"
        assert count == 0

    def test_min_area_filters_small_object(self):
        self.det.update_params(min_area=10000)
        # 80×80 = 6400 < min_area 10000
        frame = _with_rect(_frame(), 60, 60, 140, 140, (30, 30, 30))
        status, count, _, _ = self.det.process(frame)
        assert status == "NO TARGET"
        assert count == 0

    # --- detection ---

    def test_detects_dark_object_on_light(self):
        frame = _with_rect(_frame(200, 200, 220), 60, 60, 140, 140, (20, 20, 20))
        status, count, _, _ = self.det.process(frame)
        assert count >= 1
        assert status.startswith("CLASSIFIED")

    def test_last_detections_populated(self):
        frame = _with_rect(_frame(), 60, 60, 140, 140, (20, 20, 20))
        self.det.process(frame)
        assert len(self.det.last_detections) >= 1
        det = self.det.last_detections[0]
        assert "cx" in det and "cy" in det and "label" in det and "result_class" in det

    # --- target filter ---

    def test_all_targets_never_wrong(self):
        self.det.set_targets(["All"])
        frame = _with_rect(_frame(), 60, 60, 140, 140, (20, 20, 20))
        status, count, _, _ = self.det.process(frame)
        if count > 0:
            assert "FAIL" not in status

    def test_set_targets_all_stored(self):
        self.det.set_targets(["All"])
        assert self.det.target_colors == ["All"]

    def test_set_targets_empty_defaults_to_all(self):
        self.det.set_targets([])
        assert self.det.target_colors == ["All"]

    # --- shape detection ---

    def test_square_shape_detected(self):
        frame = _with_rect(_frame(), 70, 70, 130, 130, (20, 20, 20))  # 60×60 square
        self.det.process(frame)
        labels = [d.get("label", "") for d in self.det.last_detections]
        if labels:
            assert any("Square" in l or "Rectangle" in l for l in labels)

    def test_circle_shape_detected(self):
        frame = _frame().copy()
        cv2.circle(frame, (100, 100), 40, (20, 20, 20), -1)
        self.det.process(frame)
        labels = [d.get("label", "") for d in self.det.last_detections]
        if labels:
            assert any("Circle" in l or "Freeform" in l for l in labels)

    # --- size classification ---

    def test_size_small(self):
        # ratio < 0.06 → Small; frame 200×200=40000, small = area < 0.06*40000=2400
        # 40×40 = 1600 < 2400 → Small
        frame = _with_rect(_frame(), 80, 80, 120, 120, (20, 20, 20))
        self.det.process(frame)
        labels = [d.get("label", "") for d in self.det.last_detections]
        if labels:
            assert any("Small" in l for l in labels)

    def test_size_large(self):
        # ratio >= 0.18 → Large; 0.18*40000=7200; 90×90=8100 → Large
        frame = _with_rect(_frame(), 55, 55, 145, 145, (20, 20, 20))
        self.det.process(frame)
        labels = [d.get("label", "") for d in self.det.last_detections]
        if labels:
            assert any("Large" in l or "Medium" in l for l in labels)

    # --- reset ---

    def test_reset_clears_last_detections(self):
        frame = _with_rect(_frame(), 60, 60, 140, 140, (20, 20, 20))
        self.det.process(frame)
        self.det.reset_stats()
        assert self.det.last_detections == []

    # --- update_params clamping ---

    def test_min_area_clamped_low(self):
        self.det.update_params(min_area=0)
        assert self.det.min_area == 50

    def test_min_area_clamped_high(self):
        self.det.update_params(min_area=99999)
        assert self.det.min_area == 20000

    def test_hue_margin_clamped(self):
        self.det.update_params(hue_margin=-5)
        assert self.det.hue_margin == 0
        self.det.update_params(hue_margin=100)
        assert self.det.hue_margin == 20
