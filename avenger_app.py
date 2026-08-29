#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avenger Desktop — pywebview 桌面壳（复用 100% 本地服务）

用法:
  python avenger_app.py             # 桌面窗口（无 pywebview 时自动降级为浏览器模式）
  python avenger_app.py --selftest  # 只检测环境，不弹窗口
依赖: 可选 pip install pywebview（缺失时自动回退浏览器模式，服务照常）
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


def start_server():
    """启动本地服务并返回 (proc, port)。"""
    if getattr(sys, "frozen", False):
        # 打包态：自举子进程运行内置服务；运行时文件落在 exe 目录
        home = os.path.dirname(sys.executable)
        os.environ["AVENGER_HOME"] = home
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            for fn in ("avenger.html", "avenger_server.py", "avenger_studio.py",
                       "avenger_agent.py", "avenger_core.py", "avenger_hud.py", "avenger_mcp_server.py"):
                src, dst = os.path.join(meipass, fn), os.path.join(home, fn)
                if os.path.exists(src) and not os.path.exists(dst):
                    try:
                        with open(src, "rb") as f1, open(dst, "wb") as f2:
                            f2.write(f1.read())
                    except Exception:
                        pass
        proc = subprocess.Popen([sys.executable, "--server-child"], env=dict(os.environ))
    else:
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
        try:
            proc.terminate()
        except Exception:
            pass
        return None, 0
    return proc, port


def main():
    if "--server-child" in sys.argv:
        sys.argv = [sys.argv[0], "--no-browser", "--no-hud"]
        import avenger_server
        avenger_server.main()
        return 0
    selftest = "--selftest" in sys.argv

    # 1) 启动后端服务（无论桌面还是浏览器模式都需要）
    proc, port = start_server()
    if not proc:
        print("[Avenger] 服务启动失败，请确认 Python 3.8+ 可用后重试。")
        return 1
    url = "http://127.0.0.1:%d/" % port
    print("[Avenger] 服务已就绪: " + url)

    # 2) 桌面窗口（pywebview 可用时）
    try:
        import webview  # noqa
        has_webview = True
    except ImportError:
        has_webview = False

    if selftest:
        print("[Avenger] selftest OK · webview=%s · 浏览器模式可用" % ("yes" if has_webview else "no"))
        try:
            proc.terminate()
        except Exception:
            pass
        return 0

    if has_webview:
        try:
            webview.create_window("Avenger — Local-First AI Agent OS", url,
                                  width=1440, height=920, min_size=(1000, 640))
            webview.start()
            return 0  # 窗口正常关闭后保留服务（由托管小窗/关闭服务控制）
        except Exception as e:
            print("[Avenger] 桌面窗口异常，自动降级浏览器模式: %r" % e)

    # 3) 降级：浏览器模式（pywebview 缺失或窗口异常）
    print("[Avenger] 浏览器模式启动（如需原生窗口请执行: pip install pywebview）")
    import webbrowser
    webbrowser.open(url)
    print("[Avenger] 关闭本窗口（Ctrl+C）将停止服务。")
    try:
        proc.wait()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            proc.terminate()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
