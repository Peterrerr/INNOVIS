import numpy as np
import pytest
from algorithms.object_detect import ObjectDetector


def _frame(h=200, w=200, bg=200):
    return np.full((h, w, 3), bg, dtype=np.uint8)


def _draw_rect(frame, x, y, w, h, val):
    f = frame.copy()
    f[y:y + h, x:x + w] = val
    return f


class TestObjectDetector:
    def setup_method(self):
        self.det = ObjectDetector()
        self.det.update_params(127, 500, 50000)

    # --- basic detection ---

    def test_uniform_frame_no_object(self):
        # Exactly 127 → both threshold directions give empty mask
        status, count, _, _ = self.det.process(_frame(200, 200, 127))
        assert status == "NO OBJECT"
        assert count == 0

    def test_dark_object_on_light_background(self):
        frame = _draw_rect(_frame(200, 200, 200), 60, 60, 80, 80, 10)  # area=6400
        status, count, _, _ = self.det.process(frame)
        assert status == "OBJECT PRESENT"
        assert count >= 1

    def test_light_object_on_dark_background(self):
        frame = _draw_rect(_frame(200, 200, 20), 60, 60, 80, 80, 240)  # area=6400
        status, count, _, _ = self.det.process(frame)
        assert status == "OBJECT PRESENT"
        assert count >= 1

    def test_detection_populates_last_detections(self):
        frame = _draw_rect(_frame(200, 200, 200), 60, 60, 80, 80, 10)
        self.det.process(frame)
        assert len(self.det.last_detections) >= 1
        det = self.det.last_detections[0]
        assert "cx" in det and "cy" in det and "bbox" in det and "area" in det

    # --- area filters ---

    def test_area_below_min_skipped(self):
        self.det.update_params(127, 5000, 50000)
        # 20×20 = 400 px < min_area 5000
        frame = _draw_rect(_frame(200, 200, 200), 90, 90, 20, 20, 10)
        status, count, _, _ = self.det.process(frame)
        assert status == "NO OBJECT"
        assert count == 0

    def test_area_above_max_skipped(self):
        self.det.update_params(127, 500, 1000)
        # 80×80 = 6400 > max_area 1000
        frame = _draw_rect(_frame(200, 200, 200), 60, 60, 80, 80, 10)
        status, count, _, _ = self.det.process(frame)
        assert status == "NO OBJECT"

    def test_near_full_frame_object_skipped(self):
        # 198×198 ≈ 99% of 200×200 frame_area > 96% threshold
        frame = _draw_rect(_frame(200, 200, 200), 1, 1, 198, 198, 10)
        status, count, _, _ = self.det.process(frame)
        assert status == "NO OBJECT"

    # --- dedup ---

    def test_single_object_counted_once(self):
        # One dark object on light background → count must be exactly 1 (no duplicate from dual masks)
        frame = _draw_rect(_frame(200, 200, 220), 60, 60, 80, 80, 10)
        _, count, _, _ = self.det.process(frame)
        assert count == 1

    # --- param validation ---

    def test_update_params_threshold_clamped_low(self):
        self.det.update_params(-50, 500, 50000)
        assert self.det.thresh_val == 0

    def test_update_params_threshold_clamped_high(self):
        self.det.update_params(999, 500, 50000)
        assert self.det.thresh_val == 255

    def test_update_params_max_area_lt_min_fixed(self):
        self.det.update_params(127, 5000, 100)  # max < min → max promoted to min
        assert self.det.max_area >= self.det.min_area

    def test_reset_stats_clears_detections(self):
        frame = _draw_rect(_frame(200, 200, 200), 60, 60, 80, 80, 10)
        self.det.process(frame)
        assert len(self.det.last_detections) >= 1
        self.det.reset_stats()
        assert self.det.last_detections == []

    # --- bbox_overlap_fraction ---

    def test_overlap_no_intersection(self):
        assert self.det._bbox_overlap_fraction((0, 0, 10, 10), (20, 20, 10, 10)) == 0.0

    def test_overlap_identical_boxes(self):
        assert self.det._bbox_overlap_fraction((0, 0, 10, 10), (0, 0, 10, 10)) == pytest.approx(1.0)

    def test_overlap_partial(self):
        # intersection = 5×5=25, smaller_area = 10×10=100 → 0.25
        score = self.det._bbox_overlap_fraction((0, 0, 10, 10), (5, 5, 10, 10))
        assert score == pytest.approx(0.25)

    def test_overlap_one_inside_other(self):
        # Small box fully inside big box: intersection = small_area → fraction = 1.0
        score = self.det._bbox_overlap_fraction((0, 0, 100, 100), (40, 40, 10, 10))
        assert score == pytest.approx(1.0)
