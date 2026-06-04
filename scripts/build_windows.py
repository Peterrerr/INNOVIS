"""Build INNOVIS.exe on Windows and place .env next to dist/INNOVIS/."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "INNOVIS.spec"
DIST = ROOT / "dist"
ENV_SRC = ROOT / ".env"


def main():
    if sys.platform != "win32":
        print("ERROR: This script is for Windows only. Use build_app.py on macOS.")
        sys.exit(1)

    if not SPEC.exists():
        print("ERROR: INNOVIS.spec not found.")
        sys.exit(1)

    # PyInstaller is a build-time tool, not a runtime dep — make sure it's
    # installed before invoking the spec.
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("ERROR: PyInstaller not installed. Run:  pip install pyinstaller")
        sys.exit(1)

    if not ENV_SRC.exists():
        print("WARNING: .env not found — app will launch without saved credentials.")

    # clean previous build
    for folder in (DIST, ROOT / "build"):
        if folder.exists():
            shutil.rmtree(folder)
            print(f"Cleaned {folder.name}\\")

    print("Building INNOVIS.exe ...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC)],
        cwd=ROOT,
    )
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed.")
        sys.exit(result.returncode)

    # copy .env next to the dist/INNOVIS/ folder (same level as INNOVIS.exe)
    exe_dir = DIST / "INNOVIS"
    if ENV_SRC.exists() and exe_dir.exists():
        shutil.copy2(ENV_SRC, exe_dir / ".env")
        print(f"Copied .env → dist\\INNOVIS\\.env")

    exe_path = exe_dir / "INNOVIS.exe"
    print()
    print("Done!")
    print(f"  Exe : {exe_path}")
    print()
    print("To run: double-click dist\\INNOVIS\\INNOVIS.exe")
    print("        (keep the entire dist\\INNOVIS\\ folder together — do not move only the .exe)")


if __name__ == "__main__":
    main()
