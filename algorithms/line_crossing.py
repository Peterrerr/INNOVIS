import cv2
import numpy as np


class LineCrossingCounter:
    def __init__(self):
        self.total_count = 0
        self.tracked_objects = {}
        self.next_object_id = 0
        self.line_y = 50
        self.line_x = 50
        self.min_area = 1000
        self.match_distance = 80
        self.max_missed_frames = 5
        self.threshold_value = 100
        self.polarity = "dark"
        self.adaptive = False
        self.count_direction = "both"
        self.last_count_events = []

    def update_params(self, line_y_percent, line_x_percent=None, min_area=None, threshold=None, polarity=None, adaptive=None, match_distance=None, count_direction=None):
        self.line_y = max(5, min(95, int(line_y_percent)))
        if line_x_percent is not None:
            self.line_x = max(5, min(95, int(line_x_percent)))
        if min_area is not None:
            self.min_area = max(1, int(min_area))
        if threshold is not None:
            self.threshold_value = max(0, min(255, int(threshold)))
        if polarity in {"dark", "light"}:
            self.polarity = polarity
        if adaptive is not None:
            self.adaptive = bool(adaptive)
        if match_distance is not None:
            self.match_distance = max(20, min(200, int(match_distance)))
        if count_direction in {"both", "down", "up", "right", "left"}:
            self.count_direction = count_direction

    def reset_stats(self):
        self.total_count = 0
        self.tracked_objects.clear()
        self.next_object_id = 0
        self.last_count_events = []

    def _build_mask(self, blurred):
        threshold_type = cv2.THRESH_BINARY_INV if self.polarity == "dark" else cv2.THRESH_BINARY
        if self.adaptive:
            return cv2.adaptiveThreshold(
                blurred,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                threshold_type,
                31,
                5,
            )

        _, mask = cv2.threshold(blurred, self.threshold_value, 255, threshold_type)
        return mask

    def _detect_contour_objects(self, frame):
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        thresh = self._build_mask(blurred)

        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, kernel, iterations=1)
        thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        detections = []
        for cnt in contours:
            area = cv2.contourArea(cnt)
            if area <= self.min_area:
                continue

            x, y, w, h = cv2.boundingRect(cnt)
            if w < 5 or h < 5:
                continue

            detections.append({
                "cx": x + (w // 2),
                "cy": y + (h // 2),
                "bbox": (x, y, w, h),
                "area": area,
            })

        detections.sort(key=lambda item: (item["cy"], item["cx"]))
        return detections

    def _is_horizontal(self):
        return self.count_direction not in {"right", "left"}

    def _update_from_detections(self, detections, frame_shape, result_frame):
        self.last_count_events = []
        frame_h, frame_w = frame_shape[:2]
        horizontal = self._is_horizontal()

        if horizontal:
            actual_line = int(frame_h * (self.line_y / 100.0))
            cv2.line(result_frame, (0, actual_line), (frame_w, actual_line), (255, 0, 255), 2)
        else:
            actual_line = int(frame_w * (self.line_x / 100.0))
            cv2.line(result_frame, (actual_line, 0), (actual_line, frame_h), (255, 0, 255), 2)

        detections.sort(key=lambda item: item["cx"])
        updated_objects = {}
        matched_previous = set()

        for detection in detections:
            best_id = None
            best_dist = self.match_distance + 1

            for obj_id, tracked in self.tracked_objects.items():
                if obj_id in matched_previous:
                    continue

                dist = np.hypot(detection["cx"] - tracked["cx"], detection["cy"] - tracked["cy"])
                if dist <= self.match_distance and dist < best_dist:
                    best_id = obj_id
                    best_dist = dist

            if best_id is None:
                obj_id = self.next_object_id
                self.next_object_id += 1
                counted = False
            else:
                obj_id = best_id
                tracked = self.tracked_objects[obj_id]
                counted = tracked["counted"]

                if horizontal:
                    prev_pos = tracked["cy"]
                    curr_pos = detection["cy"]
                else:
                    prev_pos = tracked["cx"]
                    curr_pos = detection["cx"]

                prev_side = (prev_pos > actual_line) - (prev_pos < actual_line)
                curr_side = (curr_pos > actual_line) - (curr_pos < actual_line)
                crossed = prev_side != curr_side
                if crossed and not counted:
                    if self.count_direction == "down":
                        should_count = prev_side < 0 and curr_side > 0
                    elif self.count_direction == "up":
                        should_count = prev_side > 0 and curr_side < 0
                    elif self.count_direction == "right":
                        should_count = prev_side < 0 and curr_side > 0
                    elif self.count_direction == "left":
                        should_count = prev_side > 0 and curr_side < 0
                    else:
                        should_count = True
                    if should_count:
                        self.total_count += 1
                        counted = True
                        event = dict(detection)
                        event["object_id"] = obj_id
                        self.last_count_events.append(event)
                matched_previous.add(obj_id)

            updated_objects[obj_id] = {
                "cx": detection["cx"],
                "cy": detection["cy"],
                "counted": counted,
                "missed": 0,
            }

            x, y, w, h = detection["bbox"]
            box_color = (0, 255, 0) if counted else (255, 255, 0)
            cv2.rectangle(result_frame, (x, y), (x + w, y + h), box_color, 2)
            cv2.circle(result_frame, (detection["cx"], detection["cy"]), 5, box_color, -1)
            cv2.putText(result_frame, f"ID {obj_id}", (x, max(18, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, box_color, 1)

        for obj_id, tracked in self.tracked_objects.items():
            if obj_id in updated_objects:
                continue

            missed = tracked["missed"] + 1
            if missed <= self.max_missed_frames:
                updated_objects[obj_id] = {
                    "cx": tracked["cx"],
                    "cy": tracked["cy"],
                    "counted": tracked["counted"],
                    "missed": missed,
                }

        self.tracked_objects = updated_objects
        status = f"PASSED: {self.total_count}"
        metric2 = len(detections)
        return status, self.total_count, metric2, result_frame

    def process_detections(self, detections, frame_shape, display_frame):
        return self._update_from_detections(list(detections), frame_shape, display_frame.copy())

    def process(self, frame, display_frame=None):
        detections = self._detect_contour_objects(frame)
        result_frame = frame.copy() if display_frame is None else display_frame.copy()
        return self._update_from_detections(detections, frame.shape, result_frame)

    def process_snapshot(self, frame, display_frame=None):
        detections = self._detect_contour_objects(frame)
        result_frame = frame.copy() if display_frame is None else display_frame.copy()

        for index, detection in enumerate(detections, start=1):
            x, y, w, h = detection["bbox"]
            cv2.rectangle(result_frame, (x, y), (x + w, y + h), (0, 255, 0), 2)
            cv2.circle(result_frame, (detection["cx"], detection["cy"]), 5, (0, 255, 255), -1)
            cv2.putText(result_frame, f"#{index}", (x, max(18, y - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        count = len(detections)
        cv2.putText(result_frame, f"ITEMS: {count}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
        return f"ITEMS: {count}", count, f"Found:{count}", result_frame
