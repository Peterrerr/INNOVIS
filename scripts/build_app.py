"""Build INNOVIS.app and place .env next to it in dist/."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / "INNOVIS.spec"
DIST = ROOT / "dist"
ENV_SRC = ROOT / ".env"
ENV_DST = DIST / ".env"


def main():
    if not SPEC.exists():
        print("ERROR: INNOVIS.spec not found. Run from project root.")
        sys.exit(1)

    if not ENV_SRC.exists():
        print("WARNING: .env not found — app will launch without credentials.")

    # clean previous build
    for folder in [DIST, ROOT / "build"]:
        if folder.exists():
            shutil.rmtree(folder)
            print(f"Cleaned {folder.name}/")

    # build
    print("Building INNOVIS.app ...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC)],
        cwd=ROOT,
    )
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed.")
        sys.exit(result.returncode)

    # copy .env next to the .app
    if ENV_SRC.exists():
        shutil.copy2(ENV_SRC, ENV_DST)
        print(f"Copied .env → dist/.env")

    app_path = DIST / "INNOVIS.app"
    print()
    print("Done!")
    print(f"  App : {app_path}")
    if ENV_DST.exists():
        print(f"  Env : {ENV_DST}")


if __name__ == "__main__":
    main()
