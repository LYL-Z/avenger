# -*- coding: utf-8 -*-
"""Avenger 托管小窗 — 仅用 Python 标准库 tkinter，关闭浏览器后仍保活服务。V4.0"""
from __future__ import print_function

import json
import os
import threading
import time
import webbrowser
from urllib.request import Request, urlopen


# 与前端 PETS 保持同 id（新宠物在旧版 HUD 中回落到 ember）
PETS = {
    "ember": ("Ember", "暖焰", "#e07856"),
    "pip": ("Pip", "小蛇", "#5ea87a"),
    "nora": ("Nora", "猫耳", "#a078c0"),
    "orb": ("Orb", "玻璃球", "#5a8fc0"),
    "bit": ("Bit", "机器人", "#4aa3c7"),
    "foxy": ("Foxy", "小狐", "#e0904a"),
    "ghost": ("Ghost", "小幽灵", "#9aa8b8"),
    "zap": ("Zap", "电球", "#d4a040"),
    "pengu": ("Pengu", "企鹅", "#5ab8b0"),
    "pixel": ("Pixel", "像素猫", "#7c6cff"),
}

BG, FG, MUTED, ACCENT = "#171412", "#f0ebe5", "#a89e94", "#e07856"
CARD = "#221e1b"
GOOD, WARN = "#5ea87a", "#d4a040"


def _get(url, token, timeout=3):
    req = Request(url, headers={"X-Avenger-Token": token, "User-Agent": "Avenger-HUD/4.0"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _post(url, token, body, timeout=3):
    data = json.dumps(body).encode("utf-8")
    req = Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Avenger-Token": token,
            "User-Agent": "Avenger-HUD/4.0",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))


def _bar(pct, width=10):
    filled = max(0, min(width, int(round(pct / 100.0 * width))))
    return "█" * filled + "░" * (width - filled)


def draw_pet(canvas, pet_id, color, blink_state=0):
    """在 72x72 canvas 上画宠物。blink_state: 0 睁眼 1 眨眼"""
    c = canvas
    c.delete("all")
    c.create_oval(10, 14, 62, 62, fill=color, outline="")
    eyes = "#ffffff" if blink_state == 0 else color
    lid = "#ffffff"

    def eye(x, y):
        if blink_state:
            c.create_line(x - 4, y + 2, x + 4, y + 2, fill=lid, width=2)
        else:
            c.create_oval(x - 4, y - 4, x + 4, y + 4, fill=eyes, outline="")

    if pet_id == "pip":
        c.create_arc(10, 34, 60, 62, start=180, extent=180, style="arc", outline=color, width=9)
        eye(48, 24)
        c.create_line(50, 32, 58, 30, fill=lid, width=2)
    elif pet_id == "nora":
        c.create_polygon(16, 26, 22, 8, 30, 20, fill=color, outline="")
        c.create_polygon(56, 26, 50, 8, 42, 20, fill=color, outline="")
        eye(27, 36); eye(45, 36)
        c.create_line(31, 48, 41, 48, fill=lid, width=2)
    elif pet_id == "orb":
        c.create_oval(12, 12, 60, 60, fill=color, outline="")
        c.create_oval(20, 18, 34, 32, fill="#ffffff", stipple="gray50", outline="")
        eye(30, 38); eye(44, 38)
    elif pet_id == "bit":
        c.create_rectangle(12, 20, 60, 62, fill=color, outline="")
        c.create_line(36, 20, 36, 10, fill=color, width=3)
        c.create_oval(32, 4, 40, 12, fill=ACCENT, outline="")
        c.create_rectangle(22, 32, 34, 40, fill=eyes, outline="")
        c.create_rectangle(38, 32, 50, 40, fill=eyes, outline="")
        c.create_line(28, 52, 46, 52, fill=lid, width=2)
    elif pet_id == "foxy":
        c.create_polygon(14, 30, 18, 10, 32, 22, fill=color, outline="")
        c.create_polygon(58, 30, 54, 10, 40, 22, fill=color, outline="")
        c.create_oval(18, 22, 54, 60, fill=color, outline="")
        eye(29, 36); eye(43, 36)
        c.create_oval(33, 44, 39, 50, fill="#ffffff", outline="")
    elif pet_id == "ghost":
        c.create_oval(12, 12, 60, 56, fill=color, outline="")
        for i in range(4):
            x = 15 + i * 12
            c.create_arc(x, 48, x + 14, 66, start=180, extent=180, fill=color, outline="", style="chord")
        eye(28, 32); eye(44, 32)
    elif pet_id == "zap":
        c.create_oval(12, 14, 60, 62, fill=color, outline="")
        c.create_polygon(34, 24, 26, 40, 34, 40, 30, 52, 42, 34, 34, 34, fill="#fff8e0", outline="")
    elif pet_id == "pengu":
        c.create_oval(14, 14, 58, 62, fill="#33393f", outline="")
        c.create_oval(22, 22, 50, 58, fill="#f4f2ee", outline="")
        eye(30, 32); eye(42, 32)
        c.create_polygon(34, 40, 38, 40, 36, 46, fill="#e0904a", outline="")
    elif pet_id == "pixel":
        for (x, y, w, h, col) in [
            (20, 12, 10, 12, color), (42, 12, 10, 12, color),
            (14, 24, 44, 30, color),
            (22, 32, 8, 8, lid), (38, 32, 8, 8, lid),
            (30, 44, 6, 6, lid),
        ]:
            c.create_rectangle(x, y, x + w, y + h, fill=col, outline="")
    else:  # ember
        c.create_polygon(36, 6, 20, 30, 26, 30, 18, 52, 54, 30, 44, 30, 52, 14, fill=color, outline="")
        eye(29, 34); eye(43, 34)
        c.create_arc(27, 40, 45, 54, start=200, extent=140, style="arc", outline=lid, width=2)


def run_hud(host, port, token, on_quit=None):
    try:
        import tkinter as tk
    except ImportError:
        raise RuntimeError("当前 Python 未带 tkinter")

    base = "http://%s:%s" % (host, port)
    root = tk.Tk()
    root.title("Avenger 托管")
    root.geometry("304x460+40+80")
    root.attributes("-topmost", True)
    root.resizable(False, False)
    root.configure(bg=BG)

    try:
        root.iconbitmap(default="")
    except Exception:
        pass

    pet_id = os.environ.get("AVENGER_PET", "ember")
    if pet_id not in PETS:
        pet_id = "ember"
    pname, ptag, pcolor = PETS[pet_id]
    accent = pcolor if pcolor else ACCENT

    head = tk.Frame(root, bg=BG)
    head.pack(fill="x", padx=18, pady=(16, 6))
    canvas = tk.Canvas(head, width=72, height=72, bg=BG, highlightthickness=0)
    canvas.pack(side="left")
    draw_pet(canvas, pet_id, pcolor)
    title = tk.Frame(head, bg=BG)
    title.pack(side="left", padx=12)
    tk.Label(title, text="Avenger", fg=FG, bg=BG, font=("Segoe UI", 14, "bold")).pack(anchor="w")
    tk.Label(title, text="%s · %s" % (pname, ptag), fg=accent, bg=BG, font=("Segoe UI", 9)).pack(anchor="w")
    tk.Label(title, text="托管中 · 关浏览器不影响", fg=MUTED, bg=BG, font=("Segoe UI", 8)).pack(anchor="w")

    status = tk.Label(root, text="● 工作台在线", fg=GOOD, bg=BG, font=("Segoe UI", 10, "bold"))
    status.pack(pady=(6, 2))

    card = tk.Frame(root, bg=CARD)
    card.pack(fill="x", padx=18, pady=8)
    lbl_env = tk.Label(card, text="环境 — · 包 —", fg=MUTED, bg=CARD, font=("Consolas", 9))
    lbl_env.pack(anchor="w", padx=12, pady=(10, 2))
    lbl_cpu = tk.Label(card, text="CPU  ░░░░░░░░░░  —", fg=FG, bg=CARD, font=("Consolas", 10))
    lbl_cpu.pack(anchor="w", padx=12, pady=2)
    lbl_mem = tk.Label(card, text="内存  ░░░░░░░░░░  —", fg=FG, bg=CARD, font=("Consolas", 10))
    lbl_mem.pack(anchor="w", padx=12, pady=2)
    lbl_upd = tk.Label(card, text="刷新于 —", fg="#6e675f", bg=CARD, font=("Segoe UI", 7.5))
    lbl_upd.pack(anchor="e", padx=12, pady=(2, 8))

    hint = tk.Label(
        root,
        text="关掉浏览器没关系，这个小窗继续保活。\n只有关掉小窗才会停止 Avenger 服务。",
        fg=MUTED, bg=BG, font=("Segoe UI", 9), justify="center",
    )
    hint.pack(pady=8)

    btnf = tk.Frame(root, bg=BG)
    btnf.pack(pady=4)

    topmost = {"v": True}

    def open_dash():
        webbrowser.open(base + "/")

    def toggle_top():
        topmost["v"] = not topmost["v"]
        root.attributes("-topmost", topmost["v"])
        btn_top.config(text="置顶:开" if topmost["v"] else "置顶:关")

    def quit_all():
        try:
            _post(base + "/api/shutdown", token, {})
        except Exception:
            pass
        if on_quit:
            try:
                on_quit()
            except Exception:
                pass
        try:
            root.destroy()
        except Exception:
            pass

    tk.Button(
        btnf, text="打开工作台", command=open_dash, bg=accent, fg="#ffffff",
        activebackground=accent, relief="flat", padx=18, pady=6,
        font=("Segoe UI", 10, "bold"), cursor="hand2", bd=0,
    ).pack(pady=3, fill="x", padx=6)
    subf = tk.Frame(btnf, bg=BG)
    subf.pack(pady=3)
    btn_top = tk.Button(
        subf, text="置顶:开", command=toggle_top, bg="#332d29", fg=FG,
        activebackground="#3a3330", relief="flat", padx=10, pady=4,
        font=("Segoe UI", 9), cursor="hand2", bd=0,
    )
    btn_top.pack(side="left", padx=4)
    tk.Button(
        subf, text="退出 Avenger", command=quit_all, bg="#332d29", fg="#d06058",
        activebackground="#3a3330", relief="flat", padx=10, pady=4,
        font=("Segoe UI", 9), cursor="hand2", bd=0,
    ).pack(side="left", padx=4)

    stop = {"v": False}
    blink = {"v": 0}

    def beat():
        while not stop["v"]:
            ok = False
            cpu = mem = 0.0
            env_txt = "环境 — · 包 —"
            try:
                _get(base + "/api/heartbeat", token)
                s = _get(base + "/api/system/stats", token)
                cpu = float(s.get("cpu_percent") or 0)
                mem = float(s.get("memory_percent") or 0)
                try:
                    ov = _get(base + "/api/overview", token, timeout=4)
                    env_txt = "环境 %s · 包 %s" % (ov.get("total_environments", "—"), ov.get("total_packages", "—"))
                except Exception:
                    pass
                ok = True
            except Exception:
                pass
            now_txt = time.strftime("%H:%M:%S")

            def ui(ok=ok, cpu=cpu, mem=mem, env_txt=env_txt, now_txt=now_txt):
                if ok:
                    status.config(text="● 工作台在线", fg=GOOD)
                    lbl_cpu.config(text="CPU  %s  %.0f%%" % (_bar(cpu), cpu))
                    lbl_mem.config(text="内存 %s  %.0f%%" % (_bar(mem), mem))
                    lbl_cpu.config(fg=FG); lbl_mem.config(fg=FG)
                else:
                    status.config(text="● 等待服务…", fg=WARN)
                    lbl_cpu.config(text="CPU  —", fg=MUTED)
                    lbl_mem.config(text="内存  —", fg=MUTED)
                lbl_env.config(text=env_txt)
                lbl_upd.config(text="刷新于 " + now_txt)

            try:
                root.after(0, ui)
            except Exception:
                return
            # 眨眼节奏：每轮随机切换
            blink["v"] = 1 if blink["v"] == 0 else 0

            def blink_ui():
                try:
                    draw_pet(canvas, pet_id, pcolor, blink_state=blink["v"])
                except Exception:
                    pass

            try:
                root.after(300, blink_ui)
            except Exception:
                return
            time.sleep(4)

    threading.Thread(target=beat, daemon=True).start()

    def on_close():
        stop["v"] = True
        quit_all()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()
    stop["v"] = True
