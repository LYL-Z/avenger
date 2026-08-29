# -*- coding: utf-8 -*-
"""Avenger Desktop — pywebview 桌面壳（复用 100% 本地服务）

依赖: pip install pywebview （可选打包: pip install pyinstaller）
用法: python avenger_app.py
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent


def wait_port(port, timeout=40):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


def main():
    try:
        import webview
    except ImportError:
        print("未安装 pywebview。请执行:  pip install pywebview")
        print("然后重新运行:        python avenger_app.py")
        try:
            os.startfile("https://pywebview.flowrl.com/")
        except Exception:
            pass
        return 1

    proc = subprocess.Popen([sys.executable, str(BASE / "avenger_server.py"), "--no-browser", "--no-hud"],
                            cwd=str(BASE))
    port = 8765
    pf = BASE / "avenger_port.txt"
    t0 = time.time()
    while time.time() - t0 < 40:
        if pf.exists():
            try:
                port = int(pf.read_text().strip())
                break
            except ValueError:
                pass
        time.sleep(0.4)
    if not wait_port(port):
        print("服务启动超时")
        proc.terminate()
        return 1

    webview.create_window(
        "Avenger V6.5 — Local-First AI Agent OS",
        "http://127.0.0.1:%d/" % port,
        width=1440, height=920, min_size=(1000, 640),
    )
    try:
        webview.start()
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
