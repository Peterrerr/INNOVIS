import cv2

try:
    from pyzbar.pyzbar import decode as pyzbar_decode
    _PYZBAR_OK = True
except Exception:
    pyzbar_decode = None
    _PYZBAR_OK = False

try:
    from pylibdmtx.pylibdmtx import decode as dmtx_decode
    _DMTX_OK = True
except Exception:
    dmtx_decode = None
    _DMTX_OK = False

# Backend availability — readable by UI for status display
BACKENDS = {
    "QR (OpenCV)":   {"available": True,       "covers": "QR Code"},
    "Barcode (OpenCV)": {"available": hasattr(cv2, "barcode_BarcodeDetector"),
                         "covers": "1D Barcodes (EAN, CODE128, …)"},
    "pyzbar":        {"available": _PYZBAR_OK,  "covers": "1D/2D Barcodes"},
    "pylibdmtx":     {"available": _DMTX_OK,    "covers": "Data Matrix"},
}


class CodeReader:
    def __init__(self):
        self.qr_detector = cv2.QRCodeDetector()
        self.last_detections = []
        self.expected_value = ""
        self.barcode_detector = None
        if hasattr(cv2, "barcode_BarcodeDetector"):
            try:
                self.barcode_detector = cv2.barcode_BarcodeDetector()
            except Exception:
                self.barcode_detector = None

    def update_expected_value(self, expected_value):
        self.expected_value = self._clean_value(expected_value)

    def reset_stats(self):
        self.last_detections = []

    def _clean_value(self, value):
        return " ".join(str(value).strip().split())

    def _as_link(self, value):
        value = self._clean_value(value)
        lowered = value.lower()
        if lowered.startswith(("http://", "https://")):
            return value
        if lowered.startswith("www."):
            return f"https://{value}"
        return ""

    def _add_result(self, results, code_type, value, points=None):
        value = self._clean_value(value)
        if not value:
            return
        key = (code_type, value)
        if key in {(item["type"], item["value"]) for item in results}:
            return
        results.append({
            "type": code_type,
            "value": value,
            "link": self._as_link(value),
            "points": points,
        })

    def _is_qr_type(self, code_type):
        normalized = str(code_type or "").upper().replace("_", "").replace(" ", "")
        return normalized in {"QR", "QRCODE"}

    def _metric_item(self, item):
        code_type = str(item["type"] or "Code")
        value = item["value"]
        link = item.get("link", "")
        if self._is_qr_type(code_type) and link:
            return f"QR LINK: {link}"
        if self._is_qr_type(code_type):
            return f"QR DATA: {value}"
        return f"{code_type}: {value}"

    def _metric_text(self, results):
        return " | ".join(self._metric_item(item) for item in results[:3])

    def _matches_expected(self, item):
        expected = self._clean_value(self.expected_value)
        if not expected:
            return True
        return item["value"] == expected or item.get("link", "") == expected

    def _apply_expectations(self, results):
        any_match = False
        for item in results:
            matched = self._matches_expected(item)
            item["result_class"] = "fg" if matched else "ng"
            any_match = any_match or matched
        return any_match

    def _decode_qr(self, frame, results):
        try:
            ok, decoded_info, points, _ = self.qr_detector.detectAndDecodeMulti(frame)
            if ok and decoded_info:
                point_items = points if points is not None else [None] * len(decoded_info)
                for value, pts in zip(decoded_info, point_items):
                    self._add_result(results, "QR", value, pts)
                return
        except Exception:
            pass

        try:
            value, points, _ = self.qr_detector.detectAndDecode(frame)
            self._add_result(results, "QR", value, points)
        except Exception:
            pass

    def _decode_barcode(self, frame, results):
        if self.barcode_detector is None:
            return

        try:
            decoded = self.barcode_detector.detectAndDecode(frame)
            try:
                _, decoded_info, decoded_type, points = decoded   # cv2 >= 4.8 returns (retval, ...)
            except ValueError:
                decoded_info, decoded_type, points = decoded      # older cv2 returns 3-tuple
            if isinstance(decoded_info, str):
                self._add_result(results, decoded_type or "Barcode", decoded_info, points)
                return

            decoded_values = decoded_info or []
            decoded_types = decoded_type or ["Barcode"] * len(decoded_values)
            if isinstance(decoded_types, str):
                decoded_types = [decoded_types] * len(decoded_values)
            point_items = points if points is not None else [None] * len(decoded_values)
            for value, code_type, pts in zip(decoded_values, decoded_types, point_items):
                self._add_result(results, code_type or "Barcode", value, pts)
        except Exception:
            pass

    def _decode_optional_libraries(self, frame, results):
        if pyzbar_decode is not None:
            try:
                for code in pyzbar_decode(frame):
                    value = code.data.decode("utf-8", errors="replace")
                    code_type = str(code.type or "Barcode")
                    self._add_result(results, code_type, value)
            except Exception:
                pass

        if dmtx_decode is not None:
            try:
                for code in dmtx_decode(frame):
                    value = code.data.decode("utf-8", errors="replace")
                    self._add_result(results, "DataMatrix", value)
            except Exception:
                pass

    def _draw_results(self, frame, results):
        for index, item in enumerate(results, start=1):
            result_class = item.get("result_class", "fg")
            color = (0, 255, 0) if result_class == "fg" else (0, 0, 255)
            points = item.get("points")
            if points is not None:
                try:
                    pts = points.reshape(-1, 2).astype(int)
                    if len(pts) >= 2:
                        for i in range(len(pts)):
                            cv2.line(frame, tuple(pts[i]), tuple(pts[(i + 1) % len(pts)]), color, 2)
                except Exception:
                    pass

            value = self._metric_item(item)[:40]
            text = f"{index}:{value}"
            if result_class == "ng":
                text = f"{text} / NG"
            cv2.putText(frame, text, (10, 24 + index * 22), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)

    def _result_detections(self, frame, results):
        detections = []
        for item in results:
            points = item.get("points")
            bbox = None
            if points is not None:
                try:
                    pts = points.reshape(-1, 2).astype(int)
                    if len(pts) >= 2:
                        x, y, w, h = cv2.boundingRect(pts)
                        bbox = (x, y, w, h)
                except Exception:
                    bbox = None

            if bbox is None:
                continue

            x, y, w, h = bbox
            detections.append({
                "cx": x + (w // 2),
                "cy": y + (h // 2),
                "bbox": bbox,
                "area": w * h,
                "label": self._metric_item(item),
                "result_class": item.get("result_class", "fg"),
            })
        return detections

    def process(self, frame):
        self.last_detections = []
        result = frame.copy()
        results = []
        self._decode_qr(frame, results)
        self._decode_barcode(frame, results)
        self._decode_optional_libraries(frame, results)

        if not results:
            cv2.putText(result, "NO CODE", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 165, 255), 2)
            return "NO CODE", 0, "QR/Barcode/DataMatrix", result

        expected_matched = self._apply_expectations(results)
        self._draw_results(result, results)
        self.last_detections = self._result_detections(frame, results)
        metric = self._metric_text(results)
        if self.expected_value and not expected_matched:
            cv2.putText(result, "FAIL: CODE MISMATCH", (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (0, 0, 255), 2)
            return "FAIL = Code Mismatch", len(results), metric, result
        return f"CODE READ: {len(results)}", len(results), metric, result
