"""
CHRONOS // Build script for Windows .exe
Usage: python build.py

Requires: pip install pyinstaller pywebview
Optional: place ffmpeg.exe + ffprobe.exe in project root to bundle them.
"""

import sys
import shutil
import subprocess
from pathlib import Path

BASE = Path(__file__).parent.resolve()


def _check(name, cmd, args=["--version"]):
    print(f"Checking {name} ...", end=" ")
    if shutil.which(cmd):
        print("OK")
        return True
    print("NOT FOUND")
    return False


def _main():
    if not _check("PyInstaller", "pyinstaller"):
        print("\nInstall it:  pip install pyinstaller")
        sys.exit(1)

    if not _check("pywebview", "python", ["-c", "import webview; print('ok')"]):
        print("\nInstall it:  pip install pywebview")
        sys.exit(1)

    has_ffmpeg = (BASE / "ffmpeg.exe").exists() and (BASE / "ffprobe.exe").exists()
    if has_ffmpeg:
        print("Bundling ffmpeg.exe + ffprobe.exe (found in project root)")
    else:
        print("WARNING: ffmpeg.exe / ffprobe.exe not found in project root.")
        print("The exe will still work if FFmpeg is in the system PATH or C:\\ffmpeg\\bin.")
        print("To bundle: copy ffmpeg.exe + ffprobe.exe into the project folder.\n")

    # Build command
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "CHRONOS",
        "--windowed",          # no console window
        "--onefile",           # single .exe (change to --onedir for faster startup / smaller footprint)
        "--add-data", f"templates{os.pathsep}templates",
        "--add-data", f"static{os.pathsep}static",
        "--add-data", f"app.py{os.pathsep}.",
        "--add-data", f"wa-bridge.js{os.pathsep}.",
        "--add-data", f"package.json{os.pathsep}.",
        "--hidden-import", "flask",
        "--hidden-import", "werkzeug",
        "--hidden-import", "jinja2",
        "--hidden-import", "markupsafe",
        "--hidden-import", "psutil",
        "--hidden-import", "webview",
        "--hidden-import", "pkgutil",
        "--hidden-import", "pkg_resources",
    ]

    if has_ffmpeg:
        cmd += ["--add-binary", f"ffmpeg.exe{os.pathsep}.", "--add-binary", f"ffprobe.exe{os.pathsep}."]

    # Optional icon (if you add an icon.ico later)
    icon = BASE / "icon.ico"
    if icon.exists():
        cmd += ["--icon", str(icon)]

    cmd += [str(BASE / "main.py")]

    print("\nBuilding ...")
    print(" ".join(cmd))
    print()
    subprocess.run(cmd, check=False)

    exe_path = BASE / "dist" / "CHRONOS.exe"
    if exe_path.exists():
        print(f"\n✅ Build complete: {exe_path}")
        if not has_ffmpeg:
            print("⚠️  Remember: ffmpeg.exe + ffprobe.exe must be in PATH or next to the exe.")
    else:
        print("\n❌ Build failed. Check output above.")


if __name__ == "__main__":
    import os
    _main()
