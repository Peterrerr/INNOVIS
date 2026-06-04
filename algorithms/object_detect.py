import cv2


class ObjectDetector:
    def __init__(self):
        self.thresh_val = 127
        self.min_area = 500
        self.max_area = 50000
        self.auto_threshold = False
        self._last_otsu = None
        self.last_detections = []

    def update_params(self, threshold, min_area, max_area, auto_threshold=False):
        self.thresh_val = max(0, min(255, int(threshold)))
        min_area = max(1, int(min_area))
        max_area = max(1, int(max_area))
        if max_area < min_area:
            max_area = min_area
        self.min_area = min_area
        self.max_area = max_area
        self.auto_threshold = bool(auto_threshold)

    def reset_stats(self):
        self.last_detections = []

    def _clean_mask(self, mask):
        kernel_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel_open, iterations=1)
        return cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel_close, iterations=2)

    def _bbox_overlap_fraction(self, a, b):
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        ix1, iy1 = max(ax, bx), max(ay, by)
        ix2, iy2 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        if ix2 <= ix1 or iy2 <= iy1:
            return 0.0
        intersection = (ix2 - ix1) * (iy2 - iy1)
        smaller_area = min(aw * ah, bw * bh)
        return intersection / smaller_area if smaller_area > 0 else 0.0

    def _candidate_contours(self, gray):
        blur = cv2.GaussianBlur(gray, (5, 5), 0)
        if self.auto_threshold:
            otsu_val, dark_mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            _, light_mask = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            self._last_otsu = int(otsu_val)
        else:
            _, dark_mask = cv2.threshold(blur, self.thresh_val, 255, cv2.THRESH_BINARY_INV)
            _, light_mask = cv2.threshold(blur, self.thresh_val, 255, cv2.THRESH_BINARY)
            self._last_otsu = None
        return [self._clean_mask(dark_mask), self._clean_mask(light_mask)]

    def process(self, frame):
        self.last_detections = []
        result = frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        frame_area = frame.shape[0] * frame.shape[1]
        candidates = []

        for mask in self._candidate_contours(gray):
            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            for contour in contours:
                area = cv2.contourArea(contour)
                if area < self.min_area or area > self.max_area:
                    continue
                if area > frame_area * 0.96:
                    continue
                x, y, w, h = cv2.boundingRect(contour)
                candidates.append((area, x, y, w, h, contour))

        candidates.sort(key=lambda item: item[0], reverse=True)
        picked = []
        for area, x, y, w, h, contour in candidates:
            if any(self._bbox_overlap_fraction((x, y, w, h), (px, py, pw, ph)) > 0.5
                   for _, px, py, pw, ph, _ in picked):
                continue
            picked.append((area, x, y, w, h, contour))

        if not picked:
            cv2.putText(result, "NO OBJECT", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 165, 255), 2)
            if self._last_otsu is not None:
                cv2.putText(result, f"Auto T:{self._last_otsu}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 200, 255), 1)
            return "NO OBJECT", 0, "ABSENT", result

        summaries = []
        for index, (area, x, y, w, h, contour) in enumerate(picked, start=1):
            moments = cv2.moments(contour)
            if moments["m00"] == 0:
                cx, cy = x + w // 2, y + h // 2
            else:
                cx = int(moments["m10"] / moments["m00"])
                cy = int(moments["m01"] / moments["m00"])

            self.last_detections.append({
                "cx": cx,
                "cy": cy,
                "bbox": (x, y, w, h),
                "area": area,
                "result_class": "fg",
            })
            area_int = int(area)
            summaries.append(f"#{index} X:{cx} Y:{cy} A:{area_int}")

            # วาด contour ตามรูปร่างจริง + bounding box จางๆ
            cv2.drawContours(result, [contour], -1, (0, 255, 0), 2)
            cv2.rectangle(result, (x, y), (x + w, y + h), (0, 255, 0), 1)
            cv2.circle(result, (cx, cy), 5, (0, 255, 255), -1)

            # label แสดง index + area ใต้ bounding box
            label = f"#{index}  A:{area_int}"
            lx = max(0, x)
            ly = min(result.shape[0] - 4, y + h + 16)
            cv2.putText(result, label, (lx, ly), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

        count = len(self.last_detections)
        cv2.putText(result, f"OBJECT PRESENT: {count}", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 255, 0), 2)
        if self._last_otsu is not None:
            cv2.putText(result, f"Auto T:{self._last_otsu}", (10, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 220, 160), 1)
        return "OBJECT PRESENT", count, " | ".join(summaries[:3]), result
