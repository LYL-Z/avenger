#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avenger CLI — 终端 Agent 入口（复用 avenger_core 内核，体验对标 codex/aider）

用法:
  python avenger_cli.py "修复 utils.py 的循环依赖"          # 启动任务并实时跟踪
  python avenger_cli.py --dir D:\\myapp "重构数据库模块"
  python avenger_cli.py --provider deepseek --model deepseek-chat "写个爬虫"
  python avenger_cli.py --list                              # 列出历史会话
依赖: Avenger 服务运行中（一键启动Avenger.bat）；纯标准库。
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

BASE = Path(__file__).resolve().parent


def _port():
    p = BASE / "avenger_port.txt"
    return int(p.read_text().strip()) if p.exists() else 8765


def _token():
    p = BASE / "avenger.token"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def api(path, body=None):
    url = "http://127.0.0.1:%d%s" % (_port(), path)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = Request(url, data=data, method="POST" if data else "GET",
                  headers={"Content-Type": "application/json", "X-Avenger-Token": _token()})
    with urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


C = {"reset": "\033[0m", "dim": "\033[2m", "accent": "\033[38;5;209m",
     "green": "\033[38;5;114m", "red": "\033[38;5;174m", "cyan": "\033[38;5;116m", "warn": "\033[38;5;180m"}


def paint(ev):
    t, d = ev["type"], ev.get("data", {})
    ts = ev.get("ts", "")
    if t == "user":
        print("%s %s%s %s" % (C["dim"], ts, C["reset"], d.get("text", "")))
    elif t == "assistant":
        if d.get("content"):
            print("%s ◆ %s%s" % (C["accent"], C["reset"], d["content"][:2000]))
        for c in d.get("tool_calls", []):
            print("%s  ▸ 调用 %s(%s)%s" % (C["cyan"], c.get("name"), json.dumps(c.get("args", {}), ensure_ascii=False)[:140], C["reset"]))
    elif t == "tool_result":
        ms = d.get("ms", 0)
        res = d.get("result")
        err = isinstance(res, dict) and res.get("error")
        col = C["red"] if err else C["green"]
        print("%s  ✓ %s (%dms)%s %s" % (col, d.get("name"), ms, C["reset"],
                                        (json.dumps(res, ensure_ascii=False)[:200] if not err else "错误: " + str(res.get("error"))[:150])))
    elif t == "approval":
        print("%s  ⚠ 等待审批: %s%s" % (C["warn"], d.get("name"), C["reset"]))
        print("     参数: " + json.dumps(d.get("args", {}), ensure_ascii=False)[:300])
    elif t == "error":
        print("%s  ✗ %s%s" % (C["red"], d.get("text", ""), C["reset"]))
    elif t == "system":
        print("%s  · %s%s" % (C["dim"], d.get("text", ""), C["reset"]))


def main():
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("task", nargs="?", help="任务描述")
    ap.add_argument("--dir", help="工作目录")
    ap.add_argument("--provider", default="ollama")
    ap.add_argument("--model", default="")
    ap.add_argument("--role", default="default")
    ap.add_argument("--approve", action="store_true", help="自动批准写操作（危险）")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.list:
        for s in api("/api/core/sessions").get("sessions", []):
            print("%s  %-8s  %-30s  %d 步" % (s["created"], s["status"], s["title"][:30], s["steps"]))
        return

    if not a.task:
        ap.print_help()
        return

    r = api("/api/core/session", {"title": a.task[:40], "provider": a.provider, "model": a.model,
                                  "role": a.role, "mode": "act", "auto_approve": a.approve,
                                  "workdir": a.dir, "first_message": a.task})
    if not r.get("ok"):
        print("启动失败:", r.get("error"))
        return
    sid = r["id"]
    print("%s[Avenger Agent]%s 会话 %s · %s\n" % (C["accent"], C["reset"], sid, a.task))
    after = 0
    while True:
        d = api("/api/core/session?id=%s&after=%d" % (sid, after))
        sess = d.get("session") or {}
        for ev in d.get("events", []):
            paint(ev)
            after = ev["seq"]
        st = sess.get("status")
        if st == "waiting":
            ans = input("%s批准该写操作? [y/N/s(停止)] %s" % (C["warn"], C["reset"])).strip().lower()
            if ans == "y":
                api("/api/core/approve", {"id": sid, "approve": True})
            elif ans == "s":
                api("/api/core/stop", {"id": sid})
            else:
                api("/api/core/approve", {"id": sid, "approve": False})
            continue
        if st in ("done", "stopped", "error"):
            print("%s[结束] %s%s" % (C["dim"], st, C["reset"]))
            break
        time.sleep(1.0)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已中断（会话保留，可回到工作台继续）")
