import cv2
import numpy as np


class MeasurementDetector:
    def __init__(self):
        self.thresh_val = 127
        self.min_area = 500
        self.min_width = 0
        self.max_width = 9999
        self.min_height = 0
        self.max_height = 9999
        self.px_per_mm = 0.0   # 0 = not calibrated (show px)
        self.last_detections = []

    def update_params(self, threshold, min_area, min_width, max_width, min_height, max_height):
        self.thresh_val = max(0, min(255, int(threshold)))
        self.min_area = max(1, min(50000, int(min_area)))
        self.min_width = max(0, int(min_width))
        self.max_width = max(1, int(max_width))
        self.min_height = max(0, int(min_height))
        self.max_height = max(1, int(max_height))

    def set_calibration(self, px_per_mm):
        self.px_per_mm = max(0.0, float(px_per_mm))

    def _px_to_mm(self, px):
        if self.px_per_mm > 0:
            return px / self.px_per_mm
        return None

    def _fmt(self, px):
        mm = self._px_to_mm(px)
        return f"{mm:.1f}mm" if mm is not None else f"{px}px"

    def reset_stats(self):
        self.last_detections = []

    def _find_best_contour(self, gray):
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        frame_area = gray.shape[0] * gray.shape[1]
        best_contour = None
        best_area = 0.0

        for thresh_type in (cv2.THRESH_BINARY_INV, cv2.THRESH_BINARY):
            _, mask = cv2.threshold(blur, self.thresh_val, 255, thresh_type)
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
            mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=2)
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area < self.min_area or area > frame_area * 0.96:
                    continue
                if area > best_area:
                    best_area = area
                    best_contour = cnt

        return best_contour, best_area

    def process(self, frame):
        self.last_detections = []
        result = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        contour, area = self._find_best_contour(gray)

        if contour is None:
            cv2.putText(result, "NO OBJECT", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 165, 255), 2)
            return "NO OBJECT", 0, "W:- H:- A:-", result

        x, y, w, h = cv2.boundingRect(contour)
        aspect = w / max(1, h)

        width_ok = self.min_width <= w <= self.max_width
        height_ok = self.min_height <= h <= self.max_height

        if not width_ok:
            status = "FAIL = Width"
            color = (0, 0, 255)
        elif not height_ok:
            status = "FAIL = Height"
            color = (0, 0, 255)
        else:
            status = "PASS"
            color = (0, 255, 0)

        cv2.drawContours(result, [contour], -1, color, 1)
        cv2.rectangle(result, (x, y), (x + w, y + h), color, 2)

        # Width dimension line
        mid_y = y + h // 2
        cv2.line(result, (x, mid_y), (x + w, mid_y), color, 1)
        cv2.arrowedLine(result, (x + w // 4, mid_y), (x, mid_y), color, 1, tipLength=0.15)
        cv2.arrowedLine(result, (x + w * 3 // 4, mid_y), (x + w, mid_y), color, 1, tipLength=0.15)

        # Height dimension line
        mid_x = x + w // 2
        cv2.line(result, (mid_x, y), (mid_x, y + h), color, 1)
        cv2.arrowedLine(result, (mid_x, y + h // 4), (mid_x, y), color, 1, tipLength=0.15)
        cv2.arrowedLine(result, (mid_x, y + h * 3 // 4), (mid_x, y + h), color, 1, tipLength=0.15)

        w_label = f"W:{self._fmt(w)}"
        h_label = f"H:{self._fmt(h)}"
        cv2.putText(result, w_label, (x + max(0, w // 2 - 30), max(14, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)
        cv2.putText(result, h_label, (min(x + w + 4, frame.shape[1] - 70), y + h // 2 + 5), cv2.FONT_HERSHEY_SIMPLEX, 0.48, color, 1)

        mm = self._px_to_mm(1)
        cal_tag = f"  [1px={1/self.px_per_mm:.2f}mm]" if self.px_per_mm > 0 else "  [uncalibrated]"
        cv2.putText(result, f"W:{self._fmt(w)}  H:{self._fmt(h)}  A:{int(area)}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.65, color, 2)
        cv2.putText(result, f"Ratio:{aspect:.2f}  {status}{cal_tag}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)

        result_class = "fg" if status == "PASS" else "ng"
        cx, cy = x + w // 2, y + h // 2
        self.last_detections = [{
            "cx": cx, "cy": cy,
            "bbox": (x, y, w, h),
            "area": area,
            "result_class": result_class,
        }]

        w_mm = self._px_to_mm(w)
        h_mm = self._px_to_mm(h)
        if w_mm is not None:
            metric = f"W:{w_mm:.1f}mm H:{h_mm:.1f}mm A:{int(area)} R:{aspect:.2f}"
        else:
            metric = f"W:{w}px H:{h}px A:{int(area)} R:{aspect:.2f}"
        return status, 1, metric, result
