"""
CHRONOS // Desktop Launcher
Starts Flask in background + opens native WebView2 window.
Build with: python build.py
"""

import os
import sys
import socket
import threading
import webview

# Add bundle root to path (for PyInstaller compat)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app


def _find_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_flask(port):
    os.environ["FLASK_ENV"] = "production"
    app.run(host="127.0.0.1", port=port, threaded=True, debug=False)


if __name__ == "__main__":
    port = _find_free_port()
    t = threading.Thread(target=_start_flask, args=(port,), daemon=True)
    t.start()

    webview.create_window(
        "CHRONOS // Temporal Engine v4.0",
        f"http://127.0.0.1:{port}",
        width=1500,
        height=950,
        min_size=(1200, 700),
        text_select=True,
    )
    webview.start()
