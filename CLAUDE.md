# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Setup (first time)
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # then edit .env with admin credentials

# Run
python main.py
```

## Testing

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/test_patch_anomaly.py

# Run a single test case
pytest tests/test_patch_anomaly.py::TestPatchAnomalyDetector::test_fit_valid_returns_true
```

Tests are headless (no Qt/camera required). `conftest.py` only inserts the project root into `sys.path`.

## Build Delivery Package

```bash
python3 scripts/build_delivery.py
# Output: delivery/INNOVICH_Project-3_client.zip
```

The delivery zip excludes: `.env`, `config/settings.json`, `config/sticker_reference.png`, `logs/`, `captures/`, `__pycache__/`, `.venv/`.

## Build Standalone App (macOS)

```bash
python3 scripts/build_app.py
# Output: dist/INNOVIS.app  (and dist/.env copied alongside it)
```

Uses `INNOVIS.spec` (PyInstaller). Bundles `assets/` and `config/` into the app. Cleans `dist/` and `build/` before each run.

## Build Standalone App (Windows)

```bash
python3 scripts/build_windows.py
```

## Architecture Overview

**Startup flow:** `main.py` shows `ModeSelectionDialog`, then constructs `DashboardWindow` + `CameraWindow(embedded=True)` and attaches the camera panel to the dashboard. Mode can be changed mid-session via `change_mode_signal` which re-opens `ModeSelectionDialog`.

**Mode selection UI:** `ModeSelectionDialog._mode_groups()` groups Detection (mode 0) and Sticker Inspection (mode 5) under a single tile with a dropdown arrow — they are not separate tiles. Clicking the Detection tile directly selects mode 0; the dropdown reveals mode 5.

**PyQt5 signal/slot wiring** is the backbone of the app. `DashboardWindow` (`ui/dashboard.py`) declares all signals (e.g. `start_camera_signal`, `roi_settings_signal`, `detection_params_signal`). `CameraWindow` (`ui/camera_view.py`) connects those signals to methods on `VideoThread`. Settings changes in `SettingsWindow` call `DashboardWindow` methods that re-emit the appropriate signals.

**`VideoThread`** (`core/camera_thread.py`) is a `QThread` that owns all algorithm instances and runs the per-frame processing loop. Mode constants live here (`DETECTION_MODE=0` … `STICKER_MODE=5`). It emits:
- `change_pixmap_signal` — live preview frame (every frame)
- `capture_pixmap_signal` — frozen result frame after a capture
- `update_data_signal(status, count, metric2, fps)` — drives the dashboard result card
- `inspection_event_signal(status, quantity, result_class, metric2)` — drives FG/NG counters
- `error_signal(message)` — shown on the dashboard

**Algorithm layer** (`algorithms/`): each file exposes a class with a `process(roi)` method returning `(status, count, metric2, processed_roi)`. Algorithms hold no UI state; all parameters are set via `update_params()` calls forwarded from `VideoThread`.

| File | Class | Mode |
|---|---|---|
| `object_detect.py` | `ObjectDetector` | Detection |
| `defect_detect.py` | `DefectDetector` | Defect Inspection |
| `classification.py` | `ClassificationDetector` | Classification |
| `code_reading.py` | `CodeReader` | Code Reading |
| `line_crossing.py` | `LineCrossingCounter` | Counting / Tracking |
| `sticker_inspect.py` | `StickerInspector` | Sticker Inspection |
| `measurement.py` | `MeasurementDetector` | _(not yet wired to a mode)_ |
| `patch_anomaly.py` | `PatchAnomalyDetector` | _(not yet wired to a mode; used as a helper by `DefectDetector`)_ |

**Counting methods:**
- `COUNTING_STOP_CAPTURE` (0): operator presses CAPTURE IMAGE; `VideoThread._apply_counting_method` saves raw + result PNGs + JSON metadata to `captures/YYYY-MM-DD/`.
- `COUNTING_CONVEYOR` (1): automatic count on every frame using `LineCrossingCounter.process_detections()`. Defect Inspection and Sticker Inspection are hard-locked to Stop & Capture.

**ROI** coordinates are stored as percentages (0–100) in `VideoThread.rx/ry/rw/rh` and converted to pixels each frame using actual frame dimensions. This keeps settings resolution-independent. ROI dragging on the live view is only allowed when `is_authenticated=True`.

**Persistence:**
- `core/settings_store.py` — atomic JSON write to `config/settings.json` (writes `.tmp` then `os.replace`)
- `core/auth_manager.py` — reads `.env` for `VISION_ADMIN_USERNAME` / `VISION_ADMIN_PASSWORD`; stores SHA-256 hash; uses `hmac.compare_digest` for timing-safe comparison
- `core/logger.py` — writes two CSVs per event: `logs/log_YYYY-MM-DD.csv` (summary) and `logs/by_mode/<mode_slug>/log_YYYY-MM-DD.csv` (mode-specific columns). If the header of an existing file doesn't match the expected header, the logger creates a versioned file (`_v2`, `_v3`, …) rather than overwriting.

## Environment / Credentials

`.env.example` defines two credential pairs:
- `VISION_ADMIN_USERNAME` / `VISION_ADMIN_PASSWORD` — the live admin password shown to operators.
- `VISION_DEV_USERNAME` / `VISION_DEV_PASSWORD` — a dev backdoor that bypasses the admin lock; used for development/testing without changing the operator password.

Both are read by `core/auth_manager.py`. If no `VISION_ADMIN_PASSWORD` is set the admin gate is blocked entirely.

## Key Conventions

- `metric2` / `metric2_str` is the secondary display metric (mode-dependent string, e.g. `X:135 Y:120 A:10578` for Detection, `M:97.4% A:1.2` for Sticker).
- `result_class` is `"fg"` (good part) or `"ng"` (bad part) — used to drive the FG/NG counters on the dashboard and the `Result Class` column in logs. The mapping from status strings to `"fg"`/`"ng"` is centralised in `core/result_class.py::get_result_class(status)`.
- Thread exceptions are caught inside `VideoThread.run()` and written to `logs/thread_errors_YYYY-MM-DD.log` via `_write_thread_exception`, then surfaced to the UI through `error_signal`.
- Camera open order: platform-preferred backend first (`CAP_AVFOUNDATION` on macOS, `CAP_DSHOW` on Windows), falling back to `CAP_ANY`. If `camera_index` fails, indices 0–3 are tried automatically.
