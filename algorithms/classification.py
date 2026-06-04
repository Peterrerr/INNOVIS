import cv2
import numpy as np


class ClassificationDetector:
    COLOR_ORDER = ["Red", "Pink", "Purple", "Blue", "Green", "Brown"]

    def __init__(self):
        self._builtin_ranges = {
            "Red":    ([0, 120, 70],   [10, 255, 255]),
            "Red2":   ([170, 120, 70], [180, 255, 255]),
            "Pink":   ([155, 80, 70],  [170, 255, 255]),
            "Purple": ([125, 45, 30],  [155, 255, 255]),
            "Blue":   ([90, 70, 50],   [130, 255, 255]),
            "Green":  ([40, 55, 45],   [85, 255, 255]),
            "Brown":  ([10, 65, 60],   [35, 255, 220]),
        }
        self.color_ranges = dict(self._builtin_ranges)
        self.custom_colors = {}   # {"Orange": {"lower": [...], "upper": [...]}}
        self.draw_colors = {
            "Red": (0, 0, 255),
            "Pink": (147, 20, 255),
            "Purple": (255, 0, 255),
            "Blue": (255, 150, 0),
            "Green": (0, 255, 0),
            "Brown": (0, 165, 255),
            "Unknown": (180, 180, 180),
        }
        self.target_colors = ["All"]
        self.min_area = 350
        self.hue_margin = 0
        self.sat_margin = 0
        self.val_margin = 0
        self.last_detections = []

    def set_targets(self, targets):
        self.target_colors = targets or ["All"]

    def update_params(self, min_area=None, hue_margin=None, sat_margin=None, val_margin=None):
        if min_area is not None:
            self.min_area = max(50, min(20000, int(min_area)))
        if hue_margin is not None:
            self.hue_margin = max(0, min(20, int(hue_margin)))
        if sat_margin is not None:
            self.sat_margin = max(0, min(60, int(sat_margin)))
        if val_margin is not None:
            self.val_margin = max(0, min(60, int(val_margin)))

    def set_custom_colors(self, colors_dict):
        """colors_dict: {name: {"lower": [H,S,V], "upper": [H,S,V]}}"""
        self.custom_colors = colors_dict or {}
        self.color_ranges = dict(self._builtin_ranges)
        for name, info in self.custom_colors.items():
            self.color_ranges[name] = (info["lower"], info["upper"])

    def reset_stats(self):
        self.last_detections = []

    def _range_mask(self, hsv, lower, upper):
        lower = list(lower)
        upper = list(upper)
        lower[0] = max(0,   lower[0] - self.hue_margin)
        upper[0] = min(180, upper[0] + self.hue_margin)
        lower[1] = max(0,   lower[1] - self.sat_margin)
        upper[1] = min(255, upper[1] + self.sat_margin)
        lower[2] = max(0,   lower[2] - self.val_margin)
        upper[2] = min(255, upper[2] + self.val_margin)
        return cv2.inRange(hsv, np.array(lower), np.array(upper))

    def _build_color_mask(self, hsv, color_name):
        lower, upper = self.color_ranges[color_name]
        mask = self._range_mask(hsv, lower, upper)
        if color_name == "Red":
            red2_lower, red2_upper = self.color_ranges["Red2"]
            mask2 = self._range_mask(hsv, red2_lower, red2_upper)
            mask = cv2.bitwise_or(mask, mask2)
        return mask

    def _detect_color(self, hsv, contour, color_names=None):
        mask = np.zeros(hsv.shape[:2], dtype=np.uint8)
        cv2.drawContours(mask, [contour], -1, 255, -1)
        best_color = "Unknown"
        best_pixels = 0

        search_names = color_names or (self.COLOR_ORDER + list(self.custom_colors.keys()))
        for color_name in search_names:
            if color_name not in self.color_ranges and color_name != "Red":
                continue
            color_mask = cv2.bitwise_and(self._build_color_mask(hsv, color_name), mask)
            pixels = cv2.countNonZero(color_mask)
            if pixels > best_pixels:
                best_pixels = pixels
                best_color = color_name

        return best_color

    def _detect_shape(self, contour):
        perimeter = cv2.arcLength(contour, True)
        if perimeter <= 0:
            return "Unknown"

        approx = cv2.approxPolyDP(contour, 0.04 * perimeter, True)
        vertices = len(approx)
        area = cv2.contourArea(contour)
        circularity = 4 * np.pi * area / max(1.0, perimeter * perimeter)
        x, y, w, h = cv2.boundingRect(contour)
        aspect = w / max(1, h)

        if vertices == 3:
            return "Triangle"
        if vertices == 4:
            return "Square" if 0.85 <= aspect <= 1.15 else "Rectangle"
        if circularity >= 0.72:
            return "Circle"
        return "Freeform"

    def _detect_size(self, area, frame_area):
        ratio = area / max(1.0, frame_area)
        if ratio < 0.06:
            return "Small"
        if ratio < 0.18:
            return "Medium"
        return "Large"

    def _foreground_mask(self, gray):
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        _, dark = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        _, light = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        masks = []
        for mask in (dark, light):
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            masks.append(mask)
        return masks

    def process(self, frame):
        self.last_detections = []
        result = frame.copy()
        hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_area = frame.shape[0] * frame.shape[1]
        candidates = []

        for mask in self._foreground_mask(gray):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < self.min_area or area > frame_area * 0.96:
                    continue
                candidates.append((area, contour))

        candidates.sort(key=lambda item: item[0], reverse=True)
        picked = []
        for area, contour in candidates:
            x, y, w, h = cv2.boundingRect(contour)
            if any(abs(x - px) < 5 and abs(y - py) < 5 for px, py, *_ in picked):
                continue
            picked.append((x, y, w, h, area, contour))

        summaries = []
        target_colors = {color for color in self.target_colors if color != "All"}
        target_filter_enabled = bool(target_colors)
        wrong_target_found = False
        for index, (x, y, w, h, area, contour) in enumerate(picked[:8], start=1):
            color = self._detect_color(hsv, contour)
            shape = self._detect_shape(contour)
            size = self._detect_size(area, frame_area)
            target_match = not target_filter_enabled or color in target_colors
            if not target_match:
                wrong_target_found = True
            result_class = "fg" if target_match else "ng"
            draw_color = self.draw_colors.get(color, self.draw_colors["Unknown"])
            if result_class == "ng":
                draw_color = (0, 0, 255)
            label = f"{index}:{color}/{shape}/{size}"
            if not target_match:
                label = f"{label}/NG"
            summaries.append(label)
            self.last_detections.append({
                "cx": x + (w // 2),
                "cy": y + (h // 2),
                "bbox": (x, y, w, h),
                "area": area,
                "label": label,
                "result_class": result_class,
            })
            cv2.rectangle(result, (x, y), (x + w, y + h), draw_color, 2)
            cv2.putText(result, label, (x, max(18, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, draw_color, 1)

        if not summaries:
            cv2.putText(result, "NO CLASSIFICATION TARGET", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 165, 255), 2)
            return "NO TARGET", 0, "-", result

        metric = " | ".join(summaries[:3])
        if wrong_target_found:
            cv2.putText(result, "FAIL: WRONG CLASS", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 255), 2)
            return "FAIL = Wrong Classification", len(summaries), metric, result

        cv2.putText(result, f"CLASSIFIED: {len(summaries)}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 255, 0), 2)
        return f"CLASSIFIED: {len(summaries)}", len(summaries), metric, result
