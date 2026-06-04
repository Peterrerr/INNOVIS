import numpy as np
import pytest
from algorithms.sticker_inspect import StickerInspector


def _sticker_frame(h=100, w=100, bg=200, sticker_val=20):
    """Light background with a dark square centred, not touching borders."""
    frame = np.full((h, w, 3), bg, dtype=np.uint8)
    frame[35:65, 35:65] = sticker_val   # 30×30, min_area(250) < 900
    return frame


def _blank(h=100, w=100, val=200):
    return np.full((h, w, 3), val, dtype=np.uint8)


class TestStickerInspector:
    def setup_method(self):
        self.si = StickerInspector(reference_path=None)

    # --- reference setup ---

    def test_no_reference_returns_correct_status(self):
        status, _, _, _ = self.si.process(_sticker_frame())
        assert status == "NO STICKER REF"

    def test_has_reference_false_initially(self):
        assert self.si.has_reference() is False

    def test_set_reference_success(self):
        detected, _ = self.si.set_reference(_sticker_frame())
        assert detected is True
        assert self.si.has_reference() is True

    def test_set_reference_blank_frame_fails(self):
        # Blank uniform frame has no contour not touching border
        detected, _ = self.si.set_reference(_blank())
        assert detected is False

    def test_set_reference_resets_stats(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        self.si.process(ref.copy())
        self.si.set_reference(ref)   # re-set → stats reset
        assert self.si.inspection_count == 0
        assert self.si.ok_count == 0

    # --- pass / fail ---

    def test_pass_with_identical_frame(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        status, _, _, _ = self.si.process(ref.copy())
        assert status == "PASS"

    def test_fail_sticker_missing(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        status, _, _, _ = self.si.process(_blank())
        assert "FAIL" in status and "Missing" in status

    def test_pass_increments_ok_count(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        _, _, _, _ = self.si.process(ref.copy())
        assert self.si.ok_count == 1

    def test_fail_does_not_increment_ok_count(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        self.si.process(_blank())
        assert self.si.ok_count == 0

    # --- event_armed debounce ---

    def test_debounce_same_frame_counted_once(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        blank = _blank()
        _, count1, _, _ = self.si.process(blank)   # delta=0 from last frame? no — first call
        _, count2, _, _ = self.si.process(blank)   # exactly same frame → delta.mean()=0 < 6.0 → no rearm
        assert count1 == count2

    def test_rearm_on_large_frame_change(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        blank = _blank()
        _, count1, _, _ = self.si.process(blank)       # fires → count=1
        self.si.process(ref.copy())                    # big delta → re-arms
        _, count3, _, _ = self.si.process(blank)       # fires again
        assert count3 > count1

    # --- reset ---

    def test_reset_stats_clears_all_counters(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        self.si.process(ref.copy())
        self.si.process(_blank())
        self.si.reset_stats()
        assert self.si.inspection_count == 0
        assert self.si.ok_count == 0
        assert self.si.last_detections == []

    def test_reset_preserves_reference(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        self.si.reset_stats()
        assert self.si.has_reference() is True

    # --- update_params clamping ---

    def test_match_threshold_clamped_low(self):
        self.si.update_params(20)   # below min 40 → 0.40
        assert self.si.match_threshold == pytest.approx(0.40)

    def test_match_threshold_clamped_high(self):
        self.si.update_params(110)  # above max 95 → 0.95
        assert self.si.match_threshold == pytest.approx(0.95)

    def test_min_area_clamped_low(self):
        self.si.update_params(70, min_area=0)
        assert self.si.min_area == 50

    def test_max_angle_error_clamped(self):
        self.si.update_params(70, max_angle_error=0)
        assert self.si.max_angle_error == pytest.approx(1.0)
        self.si.update_params(70, max_angle_error=90)
        assert self.si.max_angle_error == pytest.approx(45.0)

    # --- last_detections ---

    def test_last_detections_populated_on_detection(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        self.si.process(ref.copy())
        assert len(self.si.last_detections) == 1
        det = self.si.last_detections[0]
        assert "cx" in det and "cy" in det and "area" in det

    def test_last_detections_cleared_each_frame(self):
        ref = _sticker_frame()
        self.si.set_reference(ref)
        self.si.process(ref.copy())
        self.si.process(_blank())   # sticker missing → no detections
        assert len(self.si.last_detections) == 0
