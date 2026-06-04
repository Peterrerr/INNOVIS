"""Two-stage defect detector with per-angle templates and SVM classifier.

Stage 1 — Localization: align frame to template (translation only),
absolute difference, threshold + morphology, connected components.
Stage 2 — Classification: extract HOG from each anomaly patch and
classify with an RBF-SVM (one classifier per angle).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import cv2
import joblib
import numpy as np
from skimage.feature import hog
from sklearn.preprocessing import StandardScaler
from sklearn.svm import OneClassSVM, SVC


DEFECT_LABELS: Tuple[str, ...] = ("good", "scratch", "stain", "crack", "deform")

# BGR colors per defect type (OpenCV uses BGR).
_DEFECT_COLORS_BGR: Dict[str, Tuple[int, int, int]] = {
    "scratch": (0, 165, 255),   # orange
    "stain":   (0, 215, 255),   # yellow
    "crack":   (0,   0, 255),   # red
    "deform":  (255, 0,   0),   # blue
    "good":    (0, 200,   0),   # green (rarely drawn)
}

# HOG parameters — fixed so saved models stay compatible.
_HOG_IMG_SIZE = (64, 64)
_HOG_ORIENTATIONS = 9
_HOG_PIXELS_PER_CELL = (8, 8)
_HOG_CELLS_PER_BLOCK = (2, 2)


@dataclass
class _AnglePack:
    """Per-angle state container."""

    template: Optional[np.ndarray] = None       # BGR template image
    samples_X: List[np.ndarray] = field(default_factory=list)  # HOG vectors
    samples_y: List[str] = field(default_factory=list)         # label strings
    svm: Optional[SVC] = None                   # multi-class (good + defect labels)
    ocsvm: Optional[OneClassSVM] = None         # good-only one-class SVM
    scaler: Optional[StandardScaler] = None
    classes_: Optional[List[str]] = None        # ordered class labels for predict_proba


class DefectDetector:
    """Per-angle two-stage defect detector.

    The detector maintains an independent template, training set, scaler and
    SVM classifier for each named angle. Exactly one angle is "active"; all
    training and inspection calls operate on that angle only.
    """

    # ------------------------------------------------------------------ #
    # Construction
    # ------------------------------------------------------------------ #
    def __init__(self) -> None:
        """Initialize the detector with a single default angle named 'Top'."""
        self._angles: Dict[str, _AnglePack] = {"Top": _AnglePack()}
        self._active: str = "Top"
        self._sensitivity: float = 0.5
        # Stats for the dashboard-style summary; not persisted.
        self._stats: Dict[str, int] = {"inspections": 0, "pass": 0, "ng": 0}

    # ------------------------------------------------------------------ #
    # Angle management
    # ------------------------------------------------------------------ #
    def set_active_angle(self, angle_name: str) -> None:
        """Make ``angle_name`` the active angle. No-op if it does not exist."""
        if angle_name in self._angles:
            self._active = angle_name

    def add_angle(self, angle_name: str) -> None:
        """Add a new angle. Silently ignored if the name already exists."""
        name = (angle_name or "").strip()
        if not name or name in self._angles:
            return
        self._angles[name] = _AnglePack()

    def remove_angle(self, angle_name: str) -> None:
        """Remove an angle. The last remaining angle cannot be removed."""
        if angle_name not in self._angles or len(self._angles) <= 1:
            return
        del self._angles[angle_name]
        if self._active == angle_name:
            # Pick any remaining angle as active.
            self._active = next(iter(self._angles))

    def rename_angle(self, old_name: str, new_name: str) -> None:
        """Rename ``old_name`` to ``new_name``. No-op on conflict / missing."""
        new = (new_name or "").strip()
        if old_name not in self._angles or not new or new in self._angles:
            return
        # Preserve insertion order by rebuilding the dict.
        rebuilt: Dict[str, _AnglePack] = {}
        for k, v in self._angles.items():
            rebuilt[new if k == old_name else k] = v
        self._angles = rebuilt
        if self._active == old_name:
            self._active = new

    def list_angles(self) -> List[str]:
        """Return the list of angle names in insertion order."""
        return list(self._angles.keys())

    def active_angle(self) -> str:
        """Return the name of the currently active angle."""
        return self._active

    # ------------------------------------------------------------------ #
    # Template
    # ------------------------------------------------------------------ #
    def set_template(self, img: np.ndarray) -> None:
        """Set the reference 'good' template image for the active angle."""
        if img is None or img.size == 0:
            return
        self._angles[self._active].template = img.copy()

    def has_template(self) -> bool:
        """Return True if the active angle has a template image set."""
        pack = self._angles.get(self._active)
        return bool(pack and pack.template is not None)

    # ------------------------------------------------------------------ #
    # Training
    # ------------------------------------------------------------------ #
    def add_labeled_sample(self, roi_bgr: np.ndarray, label: str) -> None:
        """Add one labeled training patch plus 3 augmented variants.

        Augmentations: horizontal flip, vertical flip, ±20 brightness shift
        (one of the two brightness variants is randomly chosen to keep the
        total at exactly 3 extra samples).
        """
        if roi_bgr is None or roi_bgr.size == 0:
            return
        if label not in DEFECT_LABELS:
            return

        pack = self._angles[self._active]
        variants = [roi_bgr]
        variants.append(cv2.flip(roi_bgr, 1))          # horizontal flip
        variants.append(cv2.flip(roi_bgr, 0))          # vertical flip
        # Two brightness variants (±40) so the SVM is robust to lighting drift.
        variants.append(self._adjust_brightness(roi_bgr, 40))
        variants.append(self._adjust_brightness(roi_bgr, -40))

        for v in variants:
            feat = self._hog_features(v)
            if feat is not None:
                pack.samples_X.append(feat)
                pack.samples_y.append(label)

    def clear_training_data(self) -> None:
        """Remove all training samples (and any trained model) for active angle."""
        pack = self._angles[self._active]
        pack.samples_X.clear()
        pack.samples_y.clear()
        pack.svm = None
        pack.ocsvm = None
        pack.scaler = None
        pack.classes_ = None

    def train(self) -> bool:
        """Train a classifier for the active angle. Returns True on success.

        Good-only samples → One-Class SVM (outlier = defect, no type label).
        Good + defect samples → multi-class RBF-SVM (classifies defect type).
        """
        pack = self._angles[self._active]
        if len(pack.samples_X) < 2:
            return False

        unique = set(pack.samples_y)
        X_all = np.asarray(pack.samples_X, dtype=np.float32)

        try:
            scaler = StandardScaler()
            X_scaled = scaler.fit_transform(X_all)

            if unique == {"good"}:
                # Good-only: One-Class SVM — any outlier patch is DEFECT.
                ocsvm = OneClassSVM(kernel="rbf", nu=0.05, gamma="scale")
                ocsvm.fit(X_scaled)
                pack.scaler = scaler
                pack.ocsvm = ocsvm
                pack.svm = None
                pack.classes_ = None
            else:
                if len(unique) < 2:
                    return False
                # Multi-class: classify defect types.
                svm = SVC(kernel="rbf", C=1.0, gamma="scale", probability=True)
                svm.fit(X_scaled, np.asarray(pack.samples_y))
                pack.scaler = scaler
                pack.svm = svm
                pack.ocsvm = None
                pack.classes_ = list(svm.classes_)
            return True
        except Exception:
            pack.svm = None
            pack.ocsvm = None
            pack.scaler = None
            pack.classes_ = None
            return False

    def has_ai_model(self) -> bool:
        """Return True if the active angle has a trained classifier."""
        pack = self._angles.get(self._active)
        return bool(
            pack and pack.scaler is not None
            and (pack.svm is not None or pack.ocsvm is not None)
        )

    # ------------------------------------------------------------------ #
    # Persistence
    # ------------------------------------------------------------------ #
    def save_ai_model(self, folder_path: str) -> None:
        """Save every angle as ``{angle_name}.pkl`` inside ``folder_path``."""
        try:
            os.makedirs(folder_path, exist_ok=True)
        except OSError:
            return
        for name, pack in self._angles.items():
            blob = {
                "template": pack.template,
                "samples_X": pack.samples_X,
                "samples_y": pack.samples_y,
                "svm": pack.svm,
                "ocsvm": pack.ocsvm,
                "scaler": pack.scaler,
                "classes_": pack.classes_,
            }
            safe = self._safe_filename(name)
            try:
                joblib.dump(blob, os.path.join(folder_path, f"{safe}.pkl"))
            except Exception:
                # Skip this angle on save failure; other angles still persist.
                continue
        # Also persist the angle ordering and the active angle.
        try:
            joblib.dump(
                {"order": list(self._angles.keys()), "active": self._active},
                os.path.join(folder_path, "_index.pkl"),
            )
        except Exception:
            pass

    def load_ai_model(self, folder_path: str) -> None:
        """Load every ``*.pkl`` in ``folder_path`` as an angle."""
        if not os.path.isdir(folder_path):
            return

        # Prefer the saved index for ordering, fall back to filesystem listing.
        order: Optional[List[str]] = None
        active: Optional[str] = None
        index_path = os.path.join(folder_path, "_index.pkl")
        if os.path.isfile(index_path):
            try:
                meta = joblib.load(index_path)
                order = list(meta.get("order") or [])
                active = meta.get("active")
            except Exception:
                order = None

        files = sorted(
            f for f in os.listdir(folder_path)
            if f.endswith(".pkl") and f != "_index.pkl"
        )
        loaded: Dict[str, _AnglePack] = {}
        for fname in files:
            name = os.path.splitext(fname)[0]
            try:
                blob = joblib.load(os.path.join(folder_path, fname))
            except Exception:
                continue
            pack = _AnglePack(
                template=blob.get("template"),
                samples_X=list(blob.get("samples_X") or []),
                samples_y=list(blob.get("samples_y") or []),
                svm=blob.get("svm"),
                ocsvm=blob.get("ocsvm"),
                scaler=blob.get("scaler"),
                classes_=blob.get("classes_"),
            )
            loaded[name] = pack

        if not loaded:
            return

        # Re-apply the saved order if it matches the files we loaded.
        if order:
            ordered: Dict[str, _AnglePack] = {}
            for n in order:
                if n in loaded:
                    ordered[n] = loaded.pop(n)
            ordered.update(loaded)  # any extras at the end
            self._angles = ordered
        else:
            self._angles = loaded

        if active and active in self._angles:
            self._active = active
        else:
            self._active = next(iter(self._angles))

    # ------------------------------------------------------------------ #
    # Inspection
    # ------------------------------------------------------------------ #
    def process(
        self, frame: np.ndarray
    ) -> Tuple[str, int, str, np.ndarray]:
        """Run inspection on ``frame``.

        Without a trained model: template-diff only — any region that differs
        from the reference is flagged as DEFECT without specifying type.
        With a trained model: HOG+SVM classification per anomaly patch.

        Returns ``(status, defect_count, confidence_str, result_frame)``.
        """
        if frame is None or frame.size == 0:
            return ("ERROR: Empty frame (NG)", 0, "-", np.zeros((10, 10, 3), np.uint8))

        pack = self._angles[self._active]

        if pack.template is None:
            self._stats["inspections"] += 1
            self._stats["ng"] += 1
            return ("NO TEMPLATE (NG)", 0, "-", frame.copy())

        try:
            aligned, template_match = self._align_to_template(frame, pack.template)
            anomaly_boxes = self._find_anomalies(aligned, template_match)
        except Exception as exc:
            self._stats["inspections"] += 1
            self._stats["ng"] += 1
            return (f"ERROR: {exc} (NG)", 0, "-", frame.copy())

        result = aligned.copy()
        self._stats["inspections"] += 1

        if pack.scaler is None:
            self._stats["ng"] += 1
            return ("NO MODEL (NG)", 0, "-", result)

        # ── Good-only mode (One-Class SVM) ────────────────────────────────
        if pack.ocsvm is not None:
            defect_count = 0
            for (x, y, w, h) in anomaly_boxes:
                patch = aligned[y:y + h, x:x + w]
                if patch.size == 0:
                    continue
                feat = self._hog_features(patch)
                if feat is None:
                    continue
                try:
                    X = pack.scaler.transform(feat.reshape(1, -1))
                    pred = int(pack.ocsvm.predict(X)[0])
                except Exception:
                    continue
                if pred == -1:  # outlier → defect
                    defect_count += 1
                    self._draw_box_unlabeled(result, (x, y, w, h))

            if defect_count == 0:
                self._stats["pass"] += 1
                return ("PASS (OK)", 0, "-", result)
            self._stats["ng"] += 1
            return (f"DEFECT ({defect_count}) (NG)", defect_count, "-", result)

        # ── Multi-class mode (SVM with defect type labels) ────────────────
        defect_types: List[str] = []
        confidences: List[float] = []

        for (x, y, w, h) in anomaly_boxes:
            patch = aligned[y:y + h, x:x + w]
            if patch.size == 0:
                continue
            feat = self._hog_features(patch)
            if feat is None:
                continue
            try:
                X = pack.scaler.transform(feat.reshape(1, -1))
                proba = pack.svm.predict_proba(X)[0]
                idx = int(np.argmax(proba))
                label = pack.svm.classes_[idx]
                conf = float(proba[idx])
            except Exception:
                continue

            if label == "good":
                continue

            defect_types.append(label)
            confidences.append(conf)
            self._draw_box(result, (x, y, w, h), label, conf)

        defect_count = len(defect_types)
        if defect_count == 0:
            self._stats["pass"] += 1
            status = "PASS (OK)"
            conf_str = "-"
        else:
            self._stats["ng"] += 1
            mean_conf = float(np.mean(confidences)) if confidences else 0.0
            severity = self._severity_from_confidence(mean_conf, defect_count)
            uniq = []
            for d in defect_types:
                pretty = d.capitalize()
                if pretty not in uniq:
                    uniq.append(pretty)
            status = f"DEFECT: {', '.join(uniq)} [{severity}] (NG)"
            conf_str = f"{mean_conf * 100:.1f}%"

        return (status, defect_count, conf_str, result)

    # ------------------------------------------------------------------ #
    # Parameters & stats
    # ------------------------------------------------------------------ #
    def update_params(self, sensitivity: float = 0.5) -> None:
        """Set the diff-threshold sensitivity. ``sensitivity`` is clamped to [0,1]."""
        try:
            s = float(sensitivity)
        except (TypeError, ValueError):
            return
        self._sensitivity = max(0.0, min(1.0, s))

    def reset_stats(self) -> None:
        """Reset the inspections / pass / ng counters."""
        self._stats = {"inspections": 0, "pass": 0, "ng": 0}

    @property
    def n_training_samples(self) -> int:
        """Total number of training samples across all angles."""
        return sum(len(p.samples_y) for p in self._angles.values())

    @property
    def sample_counts(self) -> Dict[str, int]:
        """Per-label sample counts for the active angle only."""
        pack = self._angles[self._active]
        counts: Dict[str, int] = {lbl: 0 for lbl in DEFECT_LABELS}
        for lbl in pack.samples_y:
            if lbl in counts:
                counts[lbl] += 1
        return counts

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _safe_filename(name: str) -> str:
        """Return a filesystem-safe version of an angle name."""
        keep = []
        for ch in name:
            if ch.isalnum() or ch in ("-", "_", " "):
                keep.append(ch)
            else:
                keep.append("_")
        return "".join(keep).strip() or "angle"

    @staticmethod
    def _adjust_brightness(img: np.ndarray, delta: int) -> np.ndarray:
        """Add ``delta`` to every pixel with clipping (no overflow)."""
        out = img.astype(np.int16) + int(delta)
        return np.clip(out, 0, 255).astype(np.uint8)

    @staticmethod
    def _hog_features(patch_bgr: np.ndarray) -> Optional[np.ndarray]:
        """Resize patch to a fixed size and return its HOG descriptor."""
        if patch_bgr is None or patch_bgr.size == 0:
            return None
        try:
            gray = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2GRAY)
            resized = cv2.resize(gray, _HOG_IMG_SIZE, interpolation=cv2.INTER_AREA)
            feat = hog(
                resized,
                orientations=_HOG_ORIENTATIONS,
                pixels_per_cell=_HOG_PIXELS_PER_CELL,
                cells_per_block=_HOG_CELLS_PER_BLOCK,
                block_norm="L2-Hys",
                feature_vector=True,
            )
            return feat.astype(np.float32)
        except Exception:
            return None

    def _align_to_template(
        self, frame: np.ndarray, template: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Resize frame to template size and correct small translation.

        Returns (aligned_frame, template) — both same size, same dtype.
        """
        th, tw = template.shape[:2]
        # Bring the frame to template resolution first.
        if frame.shape[:2] != (th, tw):
            frame_sized = cv2.resize(frame, (tw, th), interpolation=cv2.INTER_AREA)
        else:
            frame_sized = frame

        # Use phase correlation on grayscale floats to estimate translation.
        try:
            g_frame = cv2.cvtColor(frame_sized, cv2.COLOR_BGR2GRAY).astype(np.float32)
            g_tmpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY).astype(np.float32)
            (dx, dy), _ = cv2.phaseCorrelate(g_frame, g_tmpl)
            # Cap correction to a sane fraction of the image to avoid wild shifts.
            max_shift_x = tw * 0.1
            max_shift_y = th * 0.1
            dx = float(max(-max_shift_x, min(max_shift_x, dx)))
            dy = float(max(-max_shift_y, min(max_shift_y, dy)))
            M = np.float32([[1, 0, dx], [0, 1, dy]])
            aligned = cv2.warpAffine(
                frame_sized, M, (tw, th),
                flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE,
            )
        except Exception:
            aligned = frame_sized

        return aligned, template

    def _find_anomalies(
        self, aligned: np.ndarray, template: np.ndarray
    ) -> List[Tuple[int, int, int, int]]:
        """Diff vs template, threshold, clean up, return bounding boxes."""
        g_aligned = cv2.cvtColor(aligned, cv2.COLOR_BGR2GRAY)
        g_tmpl = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

        # Blur both sides equally to suppress lighting / sensor noise.
        g_aligned_b = cv2.GaussianBlur(g_aligned, (5, 5), 0).astype(np.float32)
        g_tmpl_b = cv2.GaussianBlur(g_tmpl, (5, 5), 0).astype(np.float32)

        # Illumination normalization: match the live frame's brightness AND
        # contrast to the template before differencing. This cancels global
        # lighting changes (brighter/darker/contrast) so a good part is not
        # flagged just because the lighting drifted from when the template was
        # captured. Only genuine structural differences survive.
        ma, sa = float(g_aligned_b.mean()), float(g_aligned_b.std()) + 1e-6
        mt, st = float(g_tmpl_b.mean()), float(g_tmpl_b.std()) + 1e-6
        g_aligned_b = (g_aligned_b - ma) * (st / sa) + mt

        diff = cv2.absdiff(g_aligned_b, g_tmpl_b)
        diff = np.clip(diff, 0, 255).astype(np.uint8)

        # Sensitivity = 1.0 → very low threshold (catch everything).
        # Sensitivity = 0.0 → very high threshold (catch only severe diffs).
        # Map [0,1] → threshold roughly [60, 15].
        thr_val = int(round(60 - 45 * self._sensitivity))
        thr_val = max(5, min(254, thr_val))
        _, mask = cv2.threshold(diff, thr_val, 255, cv2.THRESH_BINARY)

        # Small kernel for open (erases noise specks ≤ ~5px) but preserves
        # real defect regions. Larger kernel for close (fills gaps inside a
        # defect so it appears as one solid region).
        open_k  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        close_k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  open_k,  iterations=2)
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, close_k, iterations=2)

        num, _, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        boxes: List[Tuple[int, int, int, int]] = []
        h_img, w_img = mask.shape[:2]
        # Require each anomaly region to be at least 0.08 % of the ROI area
        # (≈ 16×16 px for a 640×480 crop). Tiny noise specks are ignored while
        # real surface defects (scratch/stain ≥ a few mm) still pass through.
        min_area = max(200, int(0.0008 * h_img * w_img))
        for i in range(1, num):
            x = int(stats[i, cv2.CC_STAT_LEFT])
            y = int(stats[i, cv2.CC_STAT_TOP])
            w = int(stats[i, cv2.CC_STAT_WIDTH])
            h = int(stats[i, cv2.CC_STAT_HEIGHT])
            area = int(stats[i, cv2.CC_STAT_AREA])
            if area < min_area:
                continue
            # Slight padding around the region for better classifier context.
            pad = 4
            x0 = max(0, x - pad)
            y0 = max(0, y - pad)
            x1 = min(w_img, x + w + pad)
            y1 = min(h_img, y + h + pad)
            boxes.append((x0, y0, x1 - x0, y1 - y0))
        return boxes

    @staticmethod
    def _draw_box(
        img: np.ndarray,
        box: Tuple[int, int, int, int],
        label: str,
        conf: float,
    ) -> None:
        """Draw a colored bounding box and label on ``img`` in-place."""
        x, y, w, h = box
        color = _DEFECT_COLORS_BGR.get(label, (255, 255, 255))
        cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
        text = f"{label.capitalize()} {conf * 100:.0f}%"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        y_text = max(th + 4, y)
        cv2.rectangle(
            img, (x, y_text - th - 4), (x + tw + 4, y_text), color, -1
        )
        cv2.putText(
            img, text, (x + 2, y_text - 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA,
        )

    @staticmethod
    def _draw_box_unlabeled(
        img: np.ndarray,
        box: Tuple[int, int, int, int],
    ) -> None:
        """Draw a red bounding box with 'DEFECT' label (no type/confidence)."""
        x, y, w, h = box
        color = (0, 0, 255)  # red
        cv2.rectangle(img, (x, y), (x + w, y + h), color, 2)
        text = "DEFECT"
        (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        y_text = max(th + 4, y)
        cv2.rectangle(img, (x, y_text - th - 4), (x + tw + 4, y_text), color, -1)
        cv2.putText(
            img, text, (x + 2, y_text - 2),
            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA,
        )

    @staticmethod
    def _severity_from_confidence(mean_conf: float, count: int) -> str:
        """Map confidence + count into LOW / MEDIUM / HIGH severity."""
        if count >= 3 or mean_conf >= 0.85:
            return "HIGH"
        if count == 2 or mean_conf >= 0.6:
            return "MEDIUM"
        return "LOW"
