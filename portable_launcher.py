"""Ubuntu launcher for the LingLong local web UI."""

import os
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path


def _runtime_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


RUNTIME_DIR = _runtime_dir()
os.chdir(RUNTIME_DIR)
os.environ.setdefault("LINGLONG_RUNTIME_DIR", str(RUNTIME_DIR))

from app import app, socketio  # noqa: E402


HOST = os.environ.get("LINGLONG_HOST", "0.0.0.0")
LOCAL_HOST = "127.0.0.1"
PORT = int(os.environ.get("LINGLONG_PORT", "5000"))
URL = f"http://{LOCAL_HOST}:{PORT}"


def _port_is_available() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, PORT))
            return True
        except OSError:
            return False


def _open_browser_when_ready() -> None:
    if os.environ.get("LINGLONG_NO_BROWSER") == "1":
        return
    for _ in range(60):
        try:
            with socket.create_connection((LOCAL_HOST, PORT), timeout=0.3):
                webbrowser.open(URL)
                return
        except OSError:
            time.sleep(0.2)


def main() -> int:
    if not _port_is_available():
        print(f"端口 {PORT} 已被占用。请关闭已运行的程序后重试。")
        return 1

    (RUNTIME_DIR / "logs" / "pdf").mkdir(parents=True, exist_ok=True)
    print("=" * 54)
    print(" LingLong 自检系统已启动")
    print(f" 网页地址：{URL}")
    print(" 请勿关闭此窗口；关闭窗口即停止服务。")
    print("=" * 54)

    threading.Thread(target=_open_browser_when_ready, daemon=True).start()
    socketio.run(app, host=HOST, port=PORT, debug=False, allow_unsafe_werkzeug=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
