import copy
import json
import os
import sys

# Per-camera settings blocks. These keys move from the old flat schema into
# each camera's own block under "cameras".
PER_CAMERA_KEYS = [
    "camera", "roi", "detection", "classification",
    "code", "tracking", "sticker", "measurement",
]
CAMERA_IDS = ["cam1", "cam2", "cam3"]


class SettingsStore:
    def __init__(self, config_dir=None):
        if getattr(sys, "frozen", False):
            if sys.platform == "darwin":
                # sys.executable = .../INNOVIS.app/Contents/MacOS/INNOVIS
                # The app stores user-modifiable state next to the .app (dist/).
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(sys.executable))))
            else:
                # Windows / Linux onedir: sys.executable lives next to the
                # bundled data folders, so config/ sits beside it.
                base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.config_dir = config_dir or os.path.join(base_dir, "config")
        self.settings_path = os.path.join(self.config_dir, "settings.json")
        self.sticker_reference_path = os.path.join(self.config_dir, "sticker_reference.png")

    def sticker_reference_path_for(self, camera_id):
        """Per-camera sticker reference image path (each camera trains its own)."""
        return os.path.join(self.config_dir, f"sticker_reference_{camera_id}.png")

    def load(self):
        if not os.path.exists(self.settings_path):
            return {}

        try:
            with open(self.settings_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            return self._migrate(data) if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _migrate(self, data):
        """Upgrade the old single-camera (flat) schema to the per-camera one.

        Old: roi/detection/sticker/... live at the top level.
        New: those blocks live under data["cameras"][cam_id]. The previously
        tuned single camera becomes cam1; cam2/cam3 start as copies of it so
        every camera begins from a known-good baseline."""
        if "cameras" in data:
            return data
        block = {key: data.pop(key) for key in PER_CAMERA_KEYS if key in data}
        if block:
            data["cameras"] = {cid: copy.deepcopy(block) for cid in CAMERA_IDS}
        return data

    def save(self, data):
        os.makedirs(self.config_dir, exist_ok=True)
        temp_path = f"{self.settings_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as file:
            json.dump(data, file, indent=2, sort_keys=True)
            file.write("\n")
        os.replace(temp_path, self.settings_path)
