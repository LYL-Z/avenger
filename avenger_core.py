# -*- coding: utf-8 -*-
"""avenger_core — Avenger V6.0 Agent 内核（纯标准库）

对标 Codex CLI / Claude Code / OpenHands / Aider 的事件驱动 Agent 内核：
- EventStore: append-only 事件存储（SQLite），可回放可审计
- ToolRegistry: 装饰器注册 + JSON Schema 自动生成；工作台深度工具集
- MCPClient: stdio JSON-RPC 客户端，可挂接全生态任意 MCP 服务器
- AgentLoop: thought→tool_call→observation 循环，Plan/Act 双模式，人工审批门
"""
import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

_LOCK = threading.RLock()
BASE = Path(__file__).resolve().parent

# ============================================================
# 事件存储（append-only，可回放）
# ============================================================

class EventStore:
    def __init__(self, db_path=None):
        self.path = str(db_path or (BASE / "avenger_notes.db"))
        with _LOCK:
            conn = self._conn()
            conn.execute("CREATE TABLE IF NOT EXISTS agent_sessions("
                         "id TEXT PRIMARY KEY, title TEXT, provider TEXT, model TEXT, role TEXT,"
                         "mode TEXT, status TEXT, auto_approve INTEGER, created TEXT, steps INTEGER DEFAULT 0)")
            conn.execute("CREATE TABLE IF NOT EXISTS agent_events("
                         "seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, type TEXT,"
                         "data TEXT, ts TEXT)")
            conn.commit()
            conn.close()

    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    def create_session(self, title, provider="ollama", model="", role="default", mode="plan", auto_approve=0):
        sid = uuid.uuid4().hex[:12]
        with _LOCK:
            conn = self._conn()
            conn.execute("INSERT INTO agent_sessions(id,title,provider,model,role,mode,status,auto_approve,created) VALUES(?,?,?,?,?,?,?,?,?)",
                         (sid, (title or "新任务")[:120], provider, model, role, mode, "idle", int(auto_approve),
                          time.strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()
        self.append(sid, "system", {"text": "会话创建 · mode=%s role=%s" % (mode, role)})
        return sid

    def append(self, session_id, etype, data):
        with _LOCK:
            conn = self._conn()
            cur = conn.execute("INSERT INTO agent_events(session_id,type,data,ts) VALUES(?,?,?,?)",
                               (session_id, etype, json.dumps(data, ensure_ascii=False), time.strftime("%H:%M:%S")))
            if etype in ("assistant", "tool_result"):
                conn.execute("UPDATE agent_sessions SET steps=steps+1 WHERE id=?", (session_id,))
            conn.commit()
            seq = cur.lastrowid
            conn.close()
        return seq

    def events(self, session_id, after=0):
        with _LOCK:
            conn = self._conn()
            rows = conn.execute("SELECT seq,type,data,ts FROM agent_events WHERE session_id=? AND seq>? ORDER BY seq",
                                (session_id, int(after))).fetchall()
            conn.close()
        return [{"seq": r[0], "type": r[1], "data": json.loads(r[2] or "{}"), "ts": r[3]} for r in rows]

    def sessions(self):
        with _LOCK:
            conn = self._conn()
            rows = conn.execute("SELECT id,title,provider,model,role,mode,status,auto_approve,created,steps FROM agent_sessions ORDER BY created DESC LIMIT 50").fetchall()
            conn.close()
        return [dict(r) for r in rows]

    def session(self, sid):
        with _LOCK:
            conn = self._conn()
            r = conn.execute("SELECT * FROM agent_sessions WHERE id=?", (sid,)).fetchone()
            conn.close()
        return dict(r) if r else None

    def update(self, sid, **kw):
        if not kw:
            return
        keys = ",".join(k + "=?" for k in kw)
        with _LOCK:
            conn = self._conn()
            conn.execute("UPDATE agent_sessions SET " + keys + " WHERE id=?", tuple(kw.values()) + (sid,))
            conn.commit()
            conn.close()


# ============================================================
# 工具注册表（内置工具 + Schema 自动生成）
# ============================================================

TOOLS = {}
MUTATING = set()


def tool(name, desc, params=None, mutating=False):
    """注册工具并自动生成 OpenAI function-calling schema。params: {name: {type,desc,required}}"""
    def deco(fn):
        props, required = {}, []
        for p, spec in (params or {}).items():
            props[p] = {"type": spec.get("type", "string"), "description": spec.get("desc", "")}
            if spec.get("required"):
                required.append(p)
        TOOLS[name] = {
            "fn": fn, "mutating": mutating,
            "schema": {"type": "function", "function": {
                "name": name, "description": desc,
                "parameters": {"type": "object", "properties": props, "required": required}}},
        }
        if mutating:
            MUTATING.add(name)
        return fn
    return deco


def _srv():
    import avenger_server as srv
    return srv


# ---- 工作台深度工具（竞品 Agent 没有的能力）----

@tool("wb_overview", "工作台总览：Python 环境列表、包总数、扫描状态")
def _t_overview():
    srv = _srv()
    with srv._env_lock:
        envs = list(srv._env_cache)
    return {"environments": [{"type": e["type"], "version": e["version"], "path": e["path"],
                              "health": e.get("health", {}).get("score")} for e in envs],
            "total_packages": sum(e.get("package_count", 0) for e in envs)}


@tool("wb_system", "实时 CPU/内存占用")
def _t_system():
    return _srv().get_system_stats()


@tool("wb_models", "查询适配本机显存的本地模型库推荐", {"min_vram": {"type": "number", "desc": "按此显存过滤(GB)，默认本机 GPU"}})
def _t_models(min_vram=None):
    import avenger_agent as agent
    hw = _srv()._hw_cache.get("data") or {}
    vram = float(min_vram) if min_vram else round(float((hw.get("gpu_mem") or {}).get("mem_total_mb") or 8000) / 1024, 1)
    cat = agent.model_catalog(vram, 16.0)
    fits = []
    for fam in cat:
        for v in fam["variants"]:
            if v["status"] == "fit":
                fits.append(fam["family"] + " " + v["label"] + " (" + str(v["vram_est"]) + "GB, ollama:" + v["ollama"] + ")")
    return {"gpu": hw.get("gpu"), "vram_gb": vram, "fits": fits[:12]}


@tool("wb_notes_search", "搜索开发者备忘录", {"query": {"type": "string", "required": True}})
def _t_notes(query):
    import avenger_studio as studio
    return [{"title": n["title"], "body": n["body"][:400]} for n in studio.notes_list(BASE) if query.lower() in (n["title"] + n["body"]).lower()][:8]


@tool("wb_memory_search", "搜索 Agent 长期记忆", {"query": {"type": "string", "required": True}})
def _t_mem(query):
    import avenger_agent as agent
    return [i["content"][:200] for i in agent.mem_list(BASE, q=query)][:10]


@tool("wb_memory_add", "写入长期记忆（用户偏好/项目事实/教训）", {"kind": {"type": "string", "desc": "fact/preference/project/person/insight"},
                                                                "content": {"type": "string", "required": True},
                                                                "tags": {"type": "string"}}, mutating=True)
def _t_mem_add(kind, content, tags=""):
    import avenger_agent as agent
    return agent.mem_add(BASE, {"kind": kind, "content": content, "tags": tags})


@tool("fs_read_file", "读取工作目录内文本文件（≤20KB）", {"path": {"type": "string", "required": True}})
def _t_read(path, workdir="."):
    p = os.path.abspath(os.path.join(workdir, path))
    if not p.startswith(os.path.abspath(workdir)):
        return {"error": "越界路径"}
    with open(p, "r", encoding="utf-8", errors="replace") as f:
        return f.read(20000)


@tool("fs_list_dir", "列出目录内容", {"path": {"type": "string"}})
def _t_ls(path=".", workdir="."):
    p = os.path.abspath(os.path.join(workdir, path))
    if not p.startswith(os.path.abspath(workdir)):
        return {"error": "越界路径"}
    return sorted(os.listdir(p))[:200]


@tool("fs_write_file", "写入/覆盖工作目录内文本文件", {"path": {"type": "string", "required": True},
                                                       "content": {"type": "string", "required": True}}, mutating=True)
def _t_write(path, content, workdir="."):
    p = os.path.abspath(os.path.join(workdir, path))
    if not p.startswith(os.path.abspath(workdir)):
        return {"error": "越界路径"}
    os.makedirs(os.path.dirname(p) or ".", exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        f.write(content[:100000])
    return {"ok": True, "bytes": len(content)}


@tool("shell_run", "在工作目录执行白名单 shell 命令（git/ls/dir/python/pip 等）", {"command": {"type": "string", "required": True}}, mutating=True)
def _t_shell(command, workdir="."):
    cmd0 = command.strip().split()[0].lower() if command.strip() else ""
    allowed = {"git", "python", "python3", "pip", "node", "npm", "dir", "ls", "type", "cat", "echo", "pytest"}
    if cmd0 not in allowed:
        return {"error": "命令不在白名单: " + cmd0, "allowed": sorted(allowed)}
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run(command, shell=True, capture_output=True, text=True,
                           timeout=60, cwd=workdir, errors="replace", creationflags=flags)
        return {"exit": r.returncode, "stdout": (r.stdout or "")[:6000], "stderr": (r.stderr or "")[:3000]}
    except subprocess.TimeoutExpired:
        return {"error": "超时(60s)"}


@tool("run_python", "运行一段 Python 代码并返回输出（10s 超时，隔离模式）", {"code": {"type": "string", "required": True}}, mutating=True)
def _t_py(code, workdir="."):
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        r = subprocess.run([sys.executable, "-I", "-c", code[:20000]], capture_output=True, text=True,
                           timeout=10, cwd=workdir, errors="replace", creationflags=flags)
        return {"exit": r.returncode, "stdout": (r.stdout or "")[:4000], "stderr": (r.stderr or "")[:2000]}
    except subprocess.TimeoutExpired:
        return {"error": "超时(10s)"}


def tools_payload(mode="plan"):
    """按模式输出工具 schema；plan 模式过滤掉写类工具。"""
    out = []
    for name, t in TOOLS.items():
        if mode == "plan" and name in MUTATING:
            continue
        out.append(t["schema"])
    return out


def run_tool(name, args):
    t = TOOLS.get(name)
    if not t:
        return {"error": "未知工具: " + name}
    try:
        return t["fn"](**(args or {}))
    except Exception as e:
        return {"error": repr(e)[:300]}


# ============================================================
# MCP Client（stdio JSON-RPC，可挂接任意 MCP 服务器）
# ============================================================

class MCPClient:
    def __init__(self, name, command):
        self.name = name
        self.command = command
        self.proc = None
        self.q = queue.Queue()
        self.next_id = 1
        self.tools = []
        self.lock = threading.Lock()

    def start(self):
        self.proc = subprocess.Popen(self.command, shell=True if os.name == "nt" else False,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="replace",
                                     cwd=str(BASE))
        threading.Thread(target=self._reader, daemon=True).start()
        init = self._rpc("initialize", {"protocolVersion": "2024-11-05",
                                        "capabilities": {}, "clientInfo": {"name": "avenger", "version": "6.0"}}, timeout=30)
        if isinstance(init, dict) and "error" not in init:
            self._notify("notifications/initialized", {})
            tl = self._rpc("tools/list", {})
            self.tools = [(t.get("name"), t.get("description", "")) for t in (tl.get("tools") or [])]
        return init

    def _reader(self):
        for line in self.proc.stdout:
            try:
                self.q.put(json.loads(line))
            except json.JSONDecodeError:
                continue

    def _rpc(self, method, params, timeout=60):
        with self.lock:
            self.next_id += 1
            rid = self.next_id
            req = json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            try:
                self.proc.stdin.write(req + "\n")
                self.proc.stdin.flush()
            except Exception as e:
                return {"error": str(e)}
            deadline = time.time() + timeout
            while time.time() < deadline:
                try:
                    msg = self.q.get(timeout=max(0.2, deadline - time.time()))
                except queue.Empty:
                    break
                if msg.get("id") == rid:
                    return msg.get("result") or msg
            return {"error": "MCP 超时: " + method}

    def _notify(self, method, params):
        try:
            self.proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": method, "params": params}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass

    def call(self, tool_name, args):
        r = self._rpc("tools/call", {"name": tool_name, "arguments": args or {}}, timeout=120)
        if isinstance(r, dict) and "content" in r:
            texts = [c.get("text", "") for c in r["content"] if c.get("type") == "text"]
            return {"ok": not r.get("isError"), "text": chr(10).join(texts)[:8000]}
        return r

    def stop(self):
        try:
            self.proc.terminate()
        except Exception:
            pass


MCP_SERVERS = {}


def mcp_start(name, command):
    name = re.sub(r"[^a-zA-Z0-9_-]+", "-", name)[:40]
    if name in MCP_SERVERS:
        MCP_SERVERS[name].stop()
    c = MCPClient(name, command)
    r = c.start()
    if isinstance(r, dict) and r.get("error"):
        return {"ok": False, "error": r["error"]}
    MCP_SERVERS[name] = c
    return {"ok": True, "name": name, "tools": [{"name": t[0], "desc": t[1]} for t in c.tools]}


def mcp_stop(name):
    c = MCP_SERVERS.pop(name, None)
    if c:
        c.stop()
    return {"ok": True}


def mcp_status():
    return [{"name": n, "command": c.command, "tools": [{"name": t[0], "desc": t[1]} for t in c.tools]}
            for n, c in MCP_SERVERS.items()]


def all_tools_payload(mode="act", workdir="."):
    """内置工具 + 已挂接 MCP 工具，统一 schema 列表。"""
    schemas = tools_payload(mode)
    for n, c in MCP_SERVERS.items():
        for tname, tdesc in c.tools:
            schemas.append({"type": "function", "function": {
                "name": "mcp_" + n + "_" + tname,
                "description": "[MCP:%s] %s" % (n, tdesc),
                "parameters": {"type": "object", "properties": {}, "required": []}}})
    return schemas


def dispatch_tool(name, args, workdir="."):
    if name.startswith("mcp_"):
        rest = name[4:]
        for n, c in MCP_SERVERS.items():
            if rest.startswith(n + "_"):
                return c.call(rest[len(n) + 1:], args)
        return {"error": "MCP 服务器未连接"}
    return run_tool(name, args)


# ============================================================
# Agent 循环（thought → tool_call → observation，Plan/Act + 审批门）
# ============================================================

ROLES = {
    "default": "你是 Avenger Agent——运行在用户 Windows 本机的全能开发代理。可以调用工作台工具（环境/模型库/记忆/文件/shell）。先制定简短计划，再逐步执行；每步一个工具调用；完成后给出简洁总结。始终用中文。",
    "planner": "你是规划者。只调研、不执行写操作。输出：目标拆解、每个子任务需要的工具与风险、推荐执行顺序。",
    "coder": "你是编码者。用 fs_* 工具读写文件、shell_run/python 验证。小步提交式修改，每步说明改动理由。",
    "reviewer": "你是审查者。只读代码与输出，按 P0-P3 分级给出问题与修法，没有问题明确说 PASS。",
}

PENDING = {}
THREADS = {}


class AgentLoop(threading.Thread):
    def __init__(self, store, session_id, base_dir):
        super().__init__(daemon=True, name="agent-" + session_id)
        self.store = store
        self.sid = session_id
        self.base_dir = base_dir
        self.stopped = threading.Event()

    def _llm(self, messages):
        import avenger_studio as studio
        sess = self.store.session(self.sid)
        body = {"provider": sess["provider"], "model": sess["model"], "mode": "chat",
                "messages": messages, "temperature": 0.3, "max_tokens": 4096}
        url, model, clean, temperature, max_tokens, pid = studio._build_ai_request(self.base_dir, body)
        payload = json.dumps({"model": model, "messages": clean, "temperature": temperature,
                              "max_tokens": max_tokens, "tools": all_tools_payload("act", sess.get("workdir", ".")),
                              "tool_choice": "auto"}).encode("utf-8")
        headers = {"Content-Type": "application/json", "User-Agent": "Avenger-Core/6.0"}
        key = (studio.load_secrets(self.base_dir).get("keys") or {}).get(pid)
        if key:
            headers["Authorization"] = "Bearer " + key
        from urllib.request import Request, urlopen
        from urllib.error import HTTPError, URLError
        last = None
        for attempt in range(3):
            try:
                req = Request(url, data=payload, headers=headers, method="POST")
                with urlopen(req, timeout=180) as resp:
                    return json.loads(resp.read(4 * 1024 * 1024).decode("utf-8", "replace"))
            except (HTTPError, URLError, TimeoutError, OSError) as e:
                last = e
                time.sleep(0.8 * (2 ** attempt))
        raise RuntimeError("LLM 调用失败: %r" % last)

    def _messages(self):
        sess = self.store.session(self.sid)
        workdir = sess.get("workdir") or "."
        sys_prompt = ROLES.get(sess["role"], ROLES["default"]) + "\n当前工作目录: " + str(os.path.abspath(workdir))
        msgs = [{"role": "system", "content": sys_prompt}]
        evs = self.store.events(self.sid)
        for e in evs:
            d = e["data"]
            if e["type"] == "user":
                msgs.append({"role": "user", "content": str(d.get("text", ""))[:12000]})
            elif e["type"] == "assistant":
                m = {"role": "assistant", "content": d.get("content") or ""}
                if d.get("tool_calls"):
                    m["tool_calls"] = d["tool_calls"]
                if m["content"] or m.get("tool_calls"):
                    msgs.append(m)
            elif e["type"] == "tool_result":
                msgs.append({"role": "tool", "tool_call_id": d.get("call_id", ""),
                             "content": json.dumps(d.get("result"), ensure_ascii=False)[:8000]})
        return msgs[-60:]

    def run(self):
        self.store.update(self.sid, status="running")
        max_steps = 25
        sess = self.store.session(self.sid)
        steps = int(sess.get("steps") or 0)
        pending = PENDING.pop(self.sid, None)
        try:
            while steps < max_steps and not self.stopped.is_set():
                # 1) 有待执行的已批准调用？
                if pending:
                    self._execute(pending)
                    pending = None
                    steps += 1
                    continue
                # 2) 请求模型
                data = self._llm(self._messages())
                msg = (data.get("choices") or [{}])[0].get("message") or {}
                calls = msg.get("tool_calls") or []
                self.store.append(self.sid, "assistant", {
                    "content": msg.get("content") or "",
                    "tool_calls": [{"id": c.get("id"), "name": c["function"]["name"],
                                    "args": self._safe_json(c["function"].get("arguments"))} for c in calls]})
                steps += 1
                if not calls:
                    self.store.update(self.sid, status="done")
                    self.store.append(self.sid, "system", {"text": "任务完成（共 %d 步）" % steps})
                    return
                # 3) 逐个执行工具调用（写类工具需审批）
                for c in calls:
                    if self.stopped.is_set():
                        return
                    name = c["function"]["name"]
                    args = self._safe_json(c["function"].get("arguments"))
                    t = TOOLS.get(name)
                    needs_approval = bool(t and t["mutating"]) and not int(
                        (self.store.session(self.sid) or {}).get("auto_approve") or 0)
                    if needs_approval:
                        self.store.update(self.sid, status="waiting")
                        self.store.append(self.sid, "approval", {"call_id": c.get("id"), "name": name, "args": args})
                        PENDING[self.sid] = {"id": c.get("id"), "name": name, "args": args}
                        return  # 挂起，等 /approve 恢复
                    self._execute({"id": c.get("id"), "name": name, "args": args})
                    steps += 1
            self.store.update(self.sid, status="done" if not self.stopped.is_set() else "stopped")
        except Exception as e:
            self.store.append(self.sid, "error", {"text": str(e)[:500]})
            self.store.update(self.sid, status="error")

    def _execute(self, call):
        t0 = time.time()
        sess = self.store.session(self.sid) or {}
        result = dispatch_tool(call["name"], call.get("args"), sess.get("workdir") or ".")
        ms = int((time.time() - t0) * 1000)
        self.store.append(self.sid, "tool_result", {
            "call_id": call.get("id"), "name": call["name"],
            "args": call.get("args"), "result": result, "ms": ms})

    @staticmethod
    def _safe_json(s):
        try:
            return json.loads(s) if isinstance(s, str) else (s or {})
        except json.JSONDecodeError:
            return {"_raw": str(s)[:500]}


# ---- 会话级 API（供 server 调用）----

STORE = EventStore()


def core_session_create(base_dir, body):
    b = body or {}
    sid = STORE.create_session(b.get("title") or "新任务", b.get("provider") or "ollama",
                               b.get("model") or "", b.get("role") or "default",
                               b.get("mode") or "act", 1 if b.get("auto_approve") else 0)
    if b.get("workdir"):
        STORE.update(sid, mode=b.get("mode") or "act")
        STORE.append(sid, "system", {"text": "工作目录: " + b["workdir"]})
    PENDING.clear() if False else None
    return {"ok": True, "id": sid, "session": STORE.session(sid)}


def core_send(base_dir, sid, text, workdir=None):
    if not STORE.session(sid):
        return {"ok": False, "error": "会话不存在"}
    STORE.append(sid, "user", {"text": str(text)[:12000]})
    if workdir:
        STORE.update(sid, workdir=str(workdir)[:300])
    if sid in THREADS and THREADS[sid].is_alive():
        return {"ok": True, "resumed": False, "note": "循环运行中，消息已入队"}
    th = AgentLoop(STORE, sid, base_dir)
    THREADS[sid] = th
    th.start()
    return {"ok": True, "resumed": True}


def core_approve(base_dir, sid, approve):
    sess = STORE.session(sid)
    if not sess:
        return {"ok": False, "error": "会话不存在"}
    if sess["status"] != "waiting":
        return {"ok": False, "error": "没有等待审批的步骤"}
    pending = PENDING.get(sid)
    if approve and pending:
        STORE.append(sid, "system", {"text": "用户批准: " + pending["name"]})
        th = AgentLoop(STORE, sid, base_dir)
        THREADS[sid] = th
        th.start()
        return {"ok": True, "resumed": True}
    if pending:
        STORE.append(sid, "tool_result", {"call_id": pending["id"], "name": pending["name"],
                                          "result": {"error": "用户拒绝执行"}, "ms": 0})
        PENDING.pop(sid, None)
        th = AgentLoop(STORE, sid, base_dir)
        THREADS[sid] = th
        th.start()
        return {"ok": True, "rejected": True}
    STORE.update(sid, status="idle")
    return {"ok": True}


def core_stop(sid):
    th = THREADS.get(sid)
    if th:
        th.stopped.set()
    PENDING.pop(sid, None)
    STORE.update(sid, status="stopped")
    return {"ok": True}
