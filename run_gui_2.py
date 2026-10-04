import threading
import webview
import time

from app import app, socketio


def start_server():
    # run socketio server (blocking)
    socketio.run(app, host='127.0.0.1', port=5000)


if __name__ == '__main__':
    # start server thread
    t = threading.Thread(target=start_server, daemon=True)
    t.start()
    # wait for server to be ready
    time.sleep(1)
    # open local web UI in native window (kiosk-friendly)
    webview.create_window('LingLong 自检界面', 'http://127.0.0.1:5000', width=1280, height=720)
    webview.start()
