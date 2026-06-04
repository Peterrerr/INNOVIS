import os
import cv2
import numpy as np


class StickerInspector:
    def __init__(self, reference_path=None):
        self.reference_path = reference_path
        self.reference_patch = None
        self.reference_contour = None
        self.reference_area = 0.0
        self.reference_angle = 0.0
        self.reference_aspect = 1.0

        self.min_area = 250
        self.match_threshold = 0.70
        self.flip_margin = 0.08
        self.max_angle_error = 12.0
        self.min_area_ratio = 0.75
        self.max_area_ratio = 1.35
        self.max_aspect_error = 0.35
        self.max_shape_error = 0.18

        self.inspection_count = 0
        self.ok_count = 0
        self.ok_latched = False
        self.last_gray = None
        self.event_armed = True
        self.last_detections = []
        self.rearm_diff_threshold = 6.0
        self._load_reference()

    def reset_stats(self):
        self.inspection_count = 0
        self.ok_count = 0
        self.ok_latched = False
        self.last_gray = None
        self.event_armed = True
        self.last_detections = []

    def update_params(self, match_percent, min_area=None, max_angle_error=None):
        self.match_threshold = max(0.40, min(0.95, match_percent / 100.0))
        if min_area is not None:
            self.min_area = max(50, min(20000, int(min_area)))
        if max_angle_error is not None:
            self.max_angle_error = max(1.0, min(45.0, float(max_angle_error)))

    def has_reference(self):
        return self.reference_patch is not None and self.reference_contour is not None

    def prepare_single_capture(self):
        self.ok_latched = False
        self.event_armed = True

    def draw_preview(self, frame):
        result_frame = frame.copy()
        gray = self._prepare_gray(frame)
        contour, _ = self._find_best_contour(gray)
        if contour is None:
            cv2.putText(
                result_frame,
                "Sticker not detected",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 165, 255),
                2,
            )
            return result_frame, False, "-"

        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            cv2.putText(
                result_frame,
                "Sticker not detected",
                (10, 24),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 165, 255),
                2,
            )
            return result_frame, False, "-"

        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect).astype(np.int32)

        cv2.drawContours(result_frame, [contour], -1, (0, 255, 255), 2)
        cv2.polylines(result_frame, [box], True, (255, 255, 0), 1)
        cv2.circle(result_frame, (cx, cy), 5, (0, 255, 0), -1)
        cv2.putText(
            result_frame,
            f"Sticker @ ({cx},{cy})",
            (10, 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
        )
        cv2.putText(
            result_frame,
            "Live detect preview",
            (10, 44),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (255, 255, 255),
            1,
        )
        return result_frame, True, f"X:{cx} Y:{cy}"

    def _clear_reference(self, remove_file=False):
        self.reference_patch = None
        self.reference_contour = None
        self.reference_area = 0.0
        self.reference_angle = 0.0
        self.reference_aspect = 1.0
        if remove_file and self.reference_path and os.path.exists(self.reference_path):
            try:
                os.remove(self.reference_path)
            except OSError:
                pass

    def _load_reference(self):
        if not self.reference_path or not os.path.exists(self.reference_path):
            return

        image = cv2.imread(self.reference_path)
        if image is not None and image.size > 0:
            self._set_reference_from_roi(image, persist=False, clear_on_failure=False)

    def _refresh_event_arm(self, gray):
        if self.last_gray is None or self.last_gray.shape != gray.shape:
            self.event_armed = True
        else:
            frame_delta = cv2.absdiff(gray, self.last_gray)
            if float(frame_delta.mean()) >= self.rearm_diff_threshold:
                self.event_armed = True

        self.last_gray = gray.copy()

    def _prepare_gray(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        return cv2.GaussianBlur(gray, (5, 5), 0)

    def _touches_border(self, bbox, shape, margin=2):
        x, y, w, h = bbox
        frame_h, frame_w = shape
        return x <= margin or y <= margin or (x + w) >= (frame_w - margin) or (y + h) >= (frame_h - margin)

    def _clean_mask(self, mask):
        kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
        cleaned = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open, iterations=1)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_CLOSE, kernel_close, iterations=2)
        return cleaned

    def _find_best_contour(self, gray):
        _, thresh_light = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        _, thresh_dark = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

        masks = [self._clean_mask(thresh_light), self._clean_mask(thresh_dark)]
        best_contour = None
        best_area = 0.0

        for mask in masks:
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area <= self.min_area:
                    continue

                bbox = cv2.boundingRect(cnt)
                if self._touches_border(bbox, gray.shape):
                    continue

                if area > best_area:
                    best_area = area
                    best_contour = cnt

        return best_contour, best_area

    def _normalize_contour(self, contour):
        x, y, _, _ = cv2.boundingRect(contour)
        normalized = contour.copy()
        normalized[:, :, 0] -= x
        normalized[:, :, 1] -= y
        return normalized

    def _extract_patch(self, gray, contour):
        x, y, w, h = cv2.boundingRect(contour)
        if w < 4 or h < 4:
            return None

        roi = gray[y:y+h, x:x+w]
        mask = np.zeros((h, w), dtype=np.uint8)
        local_contour = self._normalize_contour(contour)
        cv2.drawContours(mask, [local_contour], -1, 255, -1)

        patch = np.full((h, w), 255, dtype=np.uint8)
        patch[mask == 255] = roi[mask == 255]
        return patch

    def _contour_geometry(self, contour):
        (_, _), (w, h), angle = cv2.minAreaRect(contour)
        if w <= 0 or h <= 0:
            return 0.0, 1.0

        if w < h:
            w, h = h, w
            angle += 90.0

        if angle < 0:
            angle += 180.0

        aspect = w / max(1.0, h)
        return angle, aspect

    def _angle_difference(self, angle_a, angle_b):
        diff = abs(angle_a - angle_b) % 180.0
        return min(diff, 180.0 - diff)

    def _persist_reference(self, reference_roi):
        """Save reference image to disk. Returns True on success, False on failure."""
        if not self.reference_path:
            return True

        try:
            dir_path = os.path.dirname(self.reference_path)
            if dir_path:
                os.makedirs(dir_path, exist_ok=True)
            return bool(cv2.imwrite(self.reference_path, reference_roi))
        except OSError:
            return False

    def _set_reference_from_roi(self, reference_roi, persist, clear_on_failure=True):
        if reference_roi is None or reference_roi.size == 0:
            if clear_on_failure:
                self._clear_reference(remove_file=persist)
            self.ok_latched = False
            return False, False

        gray = self._prepare_gray(reference_roi)
        contour, area = self._find_best_contour(gray)
        if contour is None:
            if clear_on_failure:
                self._clear_reference(remove_file=persist)
            self.ok_latched = False
            return False, False

        patch = self._extract_patch(gray, contour)
        if patch is None:
            if clear_on_failure:
                self._clear_reference(remove_file=persist)
            self.ok_latched = False
            return False, False

        angle, aspect = self._contour_geometry(contour)

        # Always commit to memory first
        self.reference_patch = patch
        self.reference_contour = self._normalize_contour(contour)
        self.reference_area = area
        self.reference_angle = angle
        self.reference_aspect = aspect
        self.inspection_count = 0
        self.ok_count = 0
        self.ok_latched = False
        self.last_gray = None
        self.event_armed = True

        saved = self._persist_reference(reference_roi) if persist else True
        return True, saved

    def set_reference(self, reference_roi):
        """Returns (detected, saved) tuple."""
        return self._set_reference_from_roi(reference_roi, persist=True, clear_on_failure=False)

    def process(self, frame):
        self.last_detections = []
        result_frame = frame.copy()
        gray = self._prepare_gray(frame)
        self._refresh_event_arm(gray)
        contour, contour_area = self._find_best_contour(gray)

        if self.reference_patch is None or self.reference_contour is None:
            self.ok_latched = False
            cv2.rectangle(result_frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (0, 165, 255), 2)
            cv2.putText(result_frame, "NO STICKER REF", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 165, 255), 2)
            cv2.putText(result_frame, "Set one good sample in Admin Settings", (10, max(42, frame.shape[0] - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)
            return "NO STICKER REF", self.inspection_count, "CAPTURE REF", result_frame

        if contour is None:
            self.ok_latched = False
            cv2.rectangle(result_frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (0, 0, 255), 2)
            cv2.putText(result_frame, "FAIL: Sticker Missing", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            if self.event_armed:
                self.inspection_count += 1
                self.event_armed = False
            return "FAIL = Sticker Missing", self.inspection_count, "MISSING", result_frame

        moments = cv2.moments(contour)
        if moments["m00"] == 0:
            self.ok_latched = False
            cv2.rectangle(result_frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (0, 0, 255), 2)
            cv2.putText(result_frame, "FAIL: Sticker Missing", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            if self.event_armed:
                self.inspection_count += 1
                self.event_armed = False
            return "FAIL = Sticker Missing", self.inspection_count, "INVALID", result_frame

        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
        bbox = cv2.boundingRect(contour)
        self.last_detections = [{"cx": cx, "cy": cy, "bbox": bbox, "area": contour_area}]
        rect = cv2.minAreaRect(contour)
        box = cv2.boxPoints(rect).astype(np.int32)

        cv2.drawContours(result_frame, [contour], -1, (0, 255, 255), 2)
        cv2.polylines(result_frame, [box], True, (255, 255, 0), 1)
        cv2.circle(result_frame, (cx, cy), 5, (0, 255, 0), -1)
        cv2.putText(result_frame, f"C({cx},{cy})", (cx + 8, max(18, cy - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1)

        patch = self._extract_patch(gray, contour)
        if patch is None:
            self.ok_latched = False
            cv2.rectangle(result_frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), (0, 0, 255), 2)
            cv2.putText(result_frame, "FAIL: Sticker Missing", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            if self.event_armed:
                self.inspection_count += 1
                self.event_armed = False
            return "FAIL = Sticker Missing", self.inspection_count, "INVALID", result_frame

        ref_h, ref_w = self.reference_patch.shape[:2]
        resized_patch = cv2.resize(patch, (ref_w, ref_h), interpolation=cv2.INTER_LINEAR)
        rotated_patch = cv2.rotate(resized_patch, cv2.ROTATE_180)

        normal_score = float(cv2.matchTemplate(resized_patch, self.reference_patch, cv2.TM_CCOEFF_NORMED)[0][0])
        flipped_score = float(cv2.matchTemplate(rotated_patch, self.reference_patch, cv2.TM_CCOEFF_NORMED)[0][0])
        shape_score = float(cv2.matchShapes(self._normalize_contour(contour), self.reference_contour, cv2.CONTOURS_MATCH_I1, 0.0))

        angle, aspect = self._contour_geometry(contour)
        angle_error = self._angle_difference(angle, self.reference_angle)
        aspect_error = abs(aspect - self.reference_aspect)
        area_ratio = contour_area / max(1.0, self.reference_area)

        is_upside_down = flipped_score > max(normal_score + self.flip_margin, self.match_threshold)
        is_skewed = angle_error > self.max_angle_error
        is_damaged = (
            normal_score < self.match_threshold
            or shape_score > self.max_shape_error
            or aspect_error > self.max_aspect_error
            or area_ratio < self.min_area_ratio
            or area_ratio > self.max_area_ratio
        )

        if is_upside_down:
            status = "FAIL = Sticker Upside-Down"
            color = (0, 0, 255)
            self.ok_latched = False
            if self.event_armed:
                self.inspection_count += 1
                self.event_armed = False
        elif is_skewed:
            status = "FAIL = Sticker Skewed"
            color = (0, 0, 255)
            self.ok_latched = False
            if self.event_armed:
                self.inspection_count += 1
                self.event_armed = False
        elif is_damaged:
            status = "FAIL = Sticker Damaged"
            color = (0, 0, 255)
            self.ok_latched = False
            if self.event_armed:
                self.inspection_count += 1
                self.event_armed = False
        else:
            status = "PASS"
            color = (0, 255, 0)
            if self.event_armed:
                self.inspection_count += 1
                self.ok_count += 1
                self.event_armed = False
            self.ok_latched = True

        cv2.rectangle(result_frame, (0, 0), (frame.shape[1] - 1, frame.shape[0] - 1), color, 2)
        cv2.putText(result_frame, status.replace(" = ", ": "), (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
        cv2.putText(
            result_frame,
            f"Match:{normal_score * 100:.1f}%  Angle:{angle_error:.1f}  Area:{area_ratio:.2f}",
            (10, max(42, frame.shape[0] - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            color,
            1,
        )

        if self.last_detections:
            self.last_detections[-1]["result_class"] = "fg" if status == "PASS" else "ng"

        metric = f"M:{normal_score * 100:.1f}% A:{angle_error:.1f}"
        return status, self.inspection_count, metric, result_frame
