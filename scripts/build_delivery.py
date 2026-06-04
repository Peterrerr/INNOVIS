from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "delivery"
OUTPUT_PATH = OUTPUT_DIR / "INNOVICH_Project-3_client.zip"

EXCLUDED_DIRS = {
    ".git",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    ".vscode",
    "__pycache__",
    "build",
    "captures",
    "defect_models",
    "delivery",
    "dist",
    "logs",
    "venv",
}
EXCLUDED_FILES = {".DS_Store", ".env", "yolov8n.pt"}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".pkl"}
EXCLUDED_RELATIVE_PATHS = {
    "config/settings.json",
    "config/sticker_reference.png",
}


def should_include(path):
    relative_path = path.relative_to(ROOT)
    relative_parts = set(relative_path.parts)
    if relative_parts & EXCLUDED_DIRS:
        return False
    if path.name in EXCLUDED_FILES:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if relative_path.as_posix() in EXCLUDED_RELATIVE_PATHS:
        return False
    return True


def main():
    OUTPUT_DIR.mkdir(exist_ok=True)
    if OUTPUT_PATH.exists():
        OUTPUT_PATH.unlink()

    included_count = 0
    with ZipFile(OUTPUT_PATH, "w", ZIP_DEFLATED) as archive:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or not should_include(path):
                continue
            archive.write(path, path.relative_to(ROOT))
            included_count += 1

    print(f"Created {OUTPUT_PATH}")
    print(f"Included {included_count} files")


if __name__ == "__main__":
    main()
