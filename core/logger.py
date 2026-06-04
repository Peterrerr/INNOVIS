import os
import sys
import csv
import re
from datetime import datetime
from core.result_class import get_result_class


class DataLogger:
    SUMMARY_HEADER = ["Timestamp", "Operation Mode", "Event Status", "Total Count", "Secondary Metric", "FPS"]
    BASE_MODE_HEADER = ["Timestamp", "Operation Mode", "Event Status", "Result Class", "Total Count", "FPS", "Raw Metric", "Capture File"]
    MODE_HEADERS = {
        "Detection": BASE_MODE_HEADER + ["Object X", "Object Y", "Object Area", "Active Objects"],
        "Defect Inspection": BASE_MODE_HEADER + ["Defect Count", "Confidence"],
        "Classification": BASE_MODE_HEADER + ["Class Count", "Items", "NG Items"],
        "Code Reading": BASE_MODE_HEADER + ["Code Count", "Code Types", "Code Values", "QR Links"],
        "Counting / Tracking": BASE_MODE_HEADER + ["Passed Count", "Active Objects"],
        "Sticker Inspection": BASE_MODE_HEADER + ["Match Percent", "Angle Error", "Sticker Position"],
        "Measurement": BASE_MODE_HEADER + ["Width", "Height", "Area", "Aspect Ratio"],
    }

    def __init__(self, log_dir=None, on_error=None, camera_id=None):
        if log_dir:
            self.log_dir = log_dir
        elif getattr(sys, "frozen", False):
            if sys.platform == "darwin":
                # .app/Contents/MacOS/INNOVIS → up 4 = dist/
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(sys.executable))))
            else:
                # Windows / Linux onedir: logs/ sits next to the executable.
                base_dir = os.path.dirname(sys.executable)
            self.log_dir = os.path.join(base_dir, "logs")
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            self.log_dir = os.path.join(base_dir, "logs")
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir)

        self.camera_id = camera_id
        self.current_date = None
        self.filepath = None
        self.mode_filepaths = {}
        self.camera_filepaths = {}
        self._on_error = on_error
        self._last_error_repr = None

    def _get_filepath(self):
        date_str = datetime.now().strftime("%Y-%m-%d")
        if self.current_date != date_str:
            self.current_date = date_str
            self.filepath = os.path.join(self.log_dir, f"log_{self.current_date}.csv")

            if not os.path.exists(self.filepath):
                with open(self.filepath, mode="w", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)
                    writer.writerow(self.SUMMARY_HEADER)

        return self.filepath

    def _slugify_mode(self, mode_str):
        slug = re.sub(r"[^a-z0-9]+", "_", str(mode_str).strip().lower())
        return slug.strip("_") or "unknown"

    def _get_mode_filepath(self, mode_str):
        date_str = datetime.now().strftime("%Y-%m-%d")
        cache_key = (mode_str, date_str)
        if cache_key in self.mode_filepaths:
            return self.mode_filepaths[cache_key]

        mode_dir = os.path.join(self.log_dir, "by_mode", self._slugify_mode(mode_str))
        os.makedirs(mode_dir, exist_ok=True)
        filepath = os.path.join(mode_dir, f"log_{date_str}.csv")
        header = self.MODE_HEADERS.get(mode_str, self.BASE_MODE_HEADER)
        filepath = self._compatible_mode_filepath(filepath, header)
        if not os.path.exists(filepath):
            with open(filepath, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(header)
        self.mode_filepaths[cache_key] = filepath
        return filepath

    def _get_camera_filepath(self, mode_str):
        """Per-camera log: logs/by_camera/<camera_id>/<mode>/log_DATE.csv."""
        date_str = datetime.now().strftime("%Y-%m-%d")
        cache_key = (mode_str, date_str)
        if cache_key in self.camera_filepaths:
            return self.camera_filepaths[cache_key]

        cam_dir = os.path.join(self.log_dir, "by_camera", str(self.camera_id), self._slugify_mode(mode_str))
        os.makedirs(cam_dir, exist_ok=True)
        filepath = os.path.join(cam_dir, f"log_{date_str}.csv")
        header = self.MODE_HEADERS.get(mode_str, self.BASE_MODE_HEADER)
        filepath = self._compatible_mode_filepath(filepath, header)
        if not os.path.exists(filepath):
            with open(filepath, mode="w", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(header)
        self.camera_filepaths[cache_key] = filepath
        return filepath

    def _compatible_mode_filepath(self, filepath, header):
        if not os.path.exists(filepath):
            return filepath
        try:
            with open(filepath, mode="r", newline="", encoding="utf-8") as file:
                existing_header = next(csv.reader(file), [])
        except Exception:
            existing_header = []
        if existing_header == header:
            return filepath

        base, ext = os.path.splitext(filepath)
        index = 2
        while True:
            candidate = f"{base}_v{index}{ext}"
            if not os.path.exists(candidate):
                return candidate
            try:
                with open(candidate, mode="r", newline="", encoding="utf-8") as file:
                    candidate_header = next(csv.reader(file), [])
            except Exception:
                candidate_header = []
            if candidate_header == header:
                return candidate
            index += 1

    def _result_class(self, status):
        result = get_result_class(status)
        if result is None:
            return "INFO"
        return result.upper()

    def _first_match(self, pattern, text):
        match = re.search(pattern, str(text))
        return match.groups() if match else ()

    def _parse_detection_metric(self, metric):
        object_x, object_y, object_area = "", "", ""
        groups = self._first_match(r"X:(\d+)\s+Y:(\d+)\s+A:(\d+)", metric)
        if groups:
            object_x, object_y, object_area = groups
        active_objects = ""
        groups = self._first_match(r"Objects:(\d+)", metric)
        if groups:
            active_objects = groups[0]
        return {
            "Object X": object_x,
            "Object Y": object_y,
            "Object Area": object_area,
            "Active Objects": active_objects,
        }

    def _parse_defect_metric(self, metric):
        defect_count, confidence = "", ""
        groups = self._first_match(r"Defects:(\d+)", metric)
        if groups:
            defect_count = groups[0]
        groups = self._first_match(r"Conf:([0-9.]+%|-)", metric)
        if groups:
            confidence = groups[0]
        return {"Defect Count": defect_count, "Confidence": confidence}

    def _parse_classification_metric(self, status, metric):
        items = []
        ng_items = []
        for token in str(metric).split(" | "):
            token = token.strip()
            if not token or token == "-":
                continue
            _, _, item = token.partition(":")
            item = item or token
            items.append(item)
            if item.endswith("/NG"):
                ng_items.append(item)

        class_count = ""
        groups = self._first_match(r"CLASSIFIED:\s*(\d+)", status)
        if groups:
            class_count = groups[0]
        elif items:
            class_count = str(len(items))

        return {
            "Class Count": class_count,
            "Items": "; ".join(items),
            "NG Items": "; ".join(ng_items),
        }

    def _parse_code_metric(self, status, metric):
        code_types = []
        code_values = []
        qr_links = []
        for token in str(metric).split(" | "):
            token = token.strip()
            if not token or token == "QR/Barcode/DataMatrix":
                continue
            code_type, separator, value = token.partition(": ")
            if not separator:
                code_type, _, value = token.partition(":")
            code_type = code_type.strip()
            value = value.strip()
            if not code_type or not value:
                continue
            normalized_type = "QR" if code_type in {"QR LINK", "QR DATA"} else code_type
            code_types.append(normalized_type)
            code_values.append(value)
            if code_type == "QR LINK":
                qr_links.append(value)

        code_count = ""
        groups = self._first_match(r"CODE READ:\s*(\d+)", status)
        if groups:
            code_count = groups[0]
        elif code_values:
            code_count = str(len(code_values))

        return {
            "Code Count": code_count,
            "Code Types": "; ".join(code_types),
            "Code Values": "; ".join(code_values),
            "QR Links": "; ".join(qr_links),
        }

    def _parse_tracking_metric(self, status, metric):
        passed_count = ""
        groups = self._first_match(r"PASSED:\s*(\d+)", status)
        if groups:
            passed_count = groups[0]

        active_objects = ""
        groups = self._first_match(r"Objects:(\d+)", metric)
        if groups:
            active_objects = groups[0]
        groups = self._first_match(r"Found:(\d+)", metric)
        if groups:
            active_objects = groups[0]
        elif str(metric).strip().isdigit():
            active_objects = str(metric).strip()

        return {"Passed Count": passed_count, "Active Objects": active_objects}

    def _parse_measurement_metric(self, metric):
        width, height, area, aspect = "", "", "", ""
        groups = self._first_match(r"W:([0-9.]+)(?:mm|px)", metric)
        if groups:
            width = groups[0]
        groups = self._first_match(r"H:([0-9.]+)(?:mm|px)", metric)
        if groups:
            height = groups[0]
        groups = self._first_match(r"A:(\d+)", metric)
        if groups:
            area = groups[0]
        groups = self._first_match(r"R:([0-9.]+)", metric)
        if groups:
            aspect = groups[0]
        return {"Width": width, "Height": height, "Area": area, "Aspect Ratio": aspect}

    def _parse_sticker_metric(self, metric):
        match_percent, angle_error = "", ""
        groups = self._first_match(r"M:([0-9.]+)%\s+A:([0-9.]+)", metric)
        if groups:
            match_percent, angle_error = groups

        sticker_position = ""
        groups = self._first_match(r"X:(\d+)\s+Y:(\d+)", metric)
        if groups:
            sticker_position = f"X:{groups[0]} Y:{groups[1]}"

        capture_file = ""
        groups = self._first_match(r"(capture_[^|\s]+\.png)", metric)
        if groups:
            capture_file = groups[0]

        return {
            "Match Percent": match_percent,
            "Angle Error": angle_error,
            "Sticker Position": sticker_position,
            "Capture File": capture_file,
        }

    def _parse_capture_file(self, metric):
        groups = self._first_match(r"(capture_[^|\s]+\.png)", metric)
        return groups[0] if groups else ""

    def _mode_extra_fields(self, mode_str, status, metric):
        if mode_str == "Detection":
            return self._parse_detection_metric(metric)
        if mode_str == "Defect Inspection":
            return self._parse_defect_metric(metric)
        if mode_str == "Classification":
            return self._parse_classification_metric(status, metric)
        if mode_str == "Code Reading":
            return self._parse_code_metric(status, metric)
        if mode_str == "Counting / Tracking":
            return self._parse_tracking_metric(status, metric)
        if mode_str == "Sticker Inspection":
            return self._parse_sticker_metric(metric)
        if mode_str == "Measurement":
            return self._parse_measurement_metric(metric)
        return {}

    def _mode_log_row(self, timestamp, mode_str, status, count, metric2_str, fps):
        row_data = {
            "Timestamp": timestamp,
            "Operation Mode": mode_str,
            "Event Status": status,
            "Result Class": self._result_class(status),
            "Total Count": count,
            "FPS": fps,
            "Raw Metric": metric2_str,
            "Capture File": self._parse_capture_file(metric2_str),
        }
        row_data.update(self._mode_extra_fields(mode_str, status, metric2_str))
        header = self.MODE_HEADERS.get(mode_str, self.BASE_MODE_HEADER)
        return [row_data.get(column, "") for column in header]

    def log_data(self, mode_str, status, count, metric2_str, fps):
        filepath = self._get_filepath()
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        try:
            with open(filepath, mode="a", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow([timestamp, mode_str, status, count, metric2_str, fps])
            mode_row = self._mode_log_row(timestamp, mode_str, status, count, metric2_str, fps)
            mode_filepath = self._get_mode_filepath(mode_str)
            with open(mode_filepath, mode="a", newline="", encoding="utf-8") as file:
                writer = csv.writer(file)
                writer.writerow(mode_row)
            if self.camera_id:
                camera_filepath = self._get_camera_filepath(mode_str)
                with open(camera_filepath, mode="a", newline="", encoding="utf-8") as file:
                    writer = csv.writer(file)
                    writer.writerow(mode_row)
        except Exception as e:
            self._report_error(e)

    def _report_error(self, exc):
        signature = repr(exc)
        if signature == self._last_error_repr:
            return
        self._last_error_repr = signature
        if self._on_error is not None:
            try:
                self._on_error(exc)
            except Exception:
                pass
