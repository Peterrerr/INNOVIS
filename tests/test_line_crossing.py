import numpy as np
import pytest
from algorithms.line_crossing import LineCrossingCounter


FRAME_SHAPE = (100, 100, 3)


def _display():
    return np.zeros(FRAME_SHAPE, dtype=np.uint8)


def _det(cx, cy, area=200):
    return {"cx": cx, "cy": cy, "bbox": (cx - 5, cy - 5, 10, 10), "area": area}


class TestLineCrossingCounter:
    def setup_method(self):
        self.c = LineCrossingCounter()
        self.c.update_params(line_y_percent=50, min_area=50)

    def _run(self, detections):
        return self.c.process_detections(detections, FRAME_SHAPE, _display())

    # --- crossing logic ---

    def test_no_crossing_object_stays_above(self):
        self._run([_det(50, 20)])
        self._run([_det(50, 30)])   # both above line (y=50)
        assert self.c.total_count == 0

    def test_no_crossing_object_stays_below(self):
        self._run([_det(50, 70)])
        self._run([_det(50, 80)])   # both below line
        assert self.c.total_count == 0

    def test_crossing_above_to_below(self):
        self._run([_det(50, 20)])   # above line
        self._run([_det(50, 80)])   # below line → crosses
        assert self.c.total_count == 1

    def test_crossing_below_to_above(self):
        self._run([_det(50, 80)])   # below line
        self._run([_det(50, 20)])   # above line → crosses
        assert self.c.total_count == 1

    def test_object_on_line_then_crosses_below(self):
        # Object sitting exactly on line (side=0), then moves below (side=+1) → crossed
        self._run([_det(50, 50)])   # on the line → side=0
        self._run([_det(50, 80)])   # below → side=+1 → 0 != +1 → crossed
        assert self.c.total_count == 1

    def test_object_on_line_then_crosses_above(self):
        self._run([_det(50, 50)])   # on the line
        self._run([_det(50, 20)])   # above → side=-1 → 0 != -1 → crossed
        assert self.c.total_count == 1

    # --- double-count prevention ---

    def test_no_double_count_after_crossing(self):
        self._run([_det(50, 20)])
        self._run([_det(50, 80)])   # crosses → count=1, counted=True
        self._run([_det(50, 90)])   # still below, already counted → no increment
        assert self.c.total_count == 1

    def test_two_objects_count_independently(self):
        self._run([_det(30, 20), _det(70, 20)])
        self._run([_det(30, 80), _det(70, 80)])
        assert self.c.total_count == 2

    def test_only_matching_object_gets_counted(self):
        # One object crosses, other stays above
        self._run([_det(30, 20), _det(70, 20)])
        self._run([_det(30, 80), _det(70, 30)])   # only first crosses
        assert self.c.total_count == 1

    # --- missed frames eviction ---

    def test_object_evicted_after_max_missed_frames(self):
        self._run([_det(50, 20)])  # track object above
        for _ in range(self.c.max_missed_frames + 1):
            self._run([])          # object disappears
        # Object reappears below line — treated as brand-new → no crossing yet
        self._run([_det(50, 80)])
        assert self.c.total_count == 0

    def test_object_retained_within_max_missed_frames(self):
        self._run([_det(50, 20)])
        for _ in range(self.c.max_missed_frames - 1):
            self._run([])          # disappears but within tolerance
        # Object reappears below line — same object, should count
        self._run([_det(50, 80)])
        assert self.c.total_count == 1

    # --- reset ---

    def test_reset_clears_count_and_objects(self):
        self._run([_det(50, 20)])
        self._run([_det(50, 80)])
        assert self.c.total_count == 1
        self.c.reset_stats()
        assert self.c.total_count == 0
        assert len(self.c.tracked_objects) == 0
        assert self.c.next_object_id == 0

    def test_after_reset_can_count_again(self):
        self._run([_det(50, 20)])
        self._run([_det(50, 80)])
        self.c.reset_stats()
        self._run([_det(50, 20)])
        self._run([_det(50, 80)])
        assert self.c.total_count == 1

    # --- update_params clamping ---

    def test_line_y_clamped_low(self):
        self.c.update_params(0, 50)
        assert self.c.line_y == 5

    def test_line_y_clamped_high(self):
        self.c.update_params(100, 50)
        assert self.c.line_y == 95

    def test_threshold_clamped(self):
        self.c.update_params(50, 50, threshold=-10)
        assert self.c.threshold_value == 0
        self.c.update_params(50, 50, threshold=300)
        assert self.c.threshold_value == 255

    def test_polarity_accepted(self):
        self.c.update_params(50, 50, polarity="light")
        assert self.c.polarity == "light"
        self.c.update_params(50, 50, polarity="dark")
        assert self.c.polarity == "dark"

    def test_invalid_polarity_ignored(self):
        self.c.update_params(50, 50, polarity="invalid")
        assert self.c.polarity in {"dark", "light"}

    # --- process_snapshot ---

    def test_snapshot_does_not_update_tracking_state(self):
        frame = np.zeros(FRAME_SHAPE, dtype=np.uint8)
        frame[15:45, 15:45] = 255   # bright object
        self.c.process_snapshot(frame)
        # snapshot should not affect tracked_objects or total_count
        assert self.c.total_count == 0
        assert len(self.c.tracked_objects) == 0

    def test_snapshot_returns_item_count(self):
        frame = np.zeros(FRAME_SHAPE, dtype=np.uint8)
        _, count, _, _ = self.c.process_snapshot(frame)
        assert isinstance(count, int)
