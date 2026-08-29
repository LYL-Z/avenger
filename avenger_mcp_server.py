#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Avenger MCP Server — 把 Avenger 工作台能力以 MCP 工具暴露给任意 AI 客户端。

协议: Model Context Protocol (stdio 传输, 换行分隔 JSON-RPC 2.0)，仅标准库。

接入示例（Claude Desktop / Cursor / VS Code 的 mcp.json）:
{
  "mcpServers": {
    "avenger": { "command": "python", "args": ["D:/Avenger/avenger_mcp_server.py"] }
  }
}
CLI: claude mcp add avenger -- python D:/Avenger/avenger_mcp_server.py
"""
import json
import os
import sys
import traceback

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "avenger", "version": "5.0.0"}


def _backend():
    """延迟导入 Avenger 后端（避免无谓启动扫描）。"""
    import avenger_server as srv
    return srv


# ---------------- 工具实现 ----------------

def tool_overview(_args):
    srv = _backend()
    with srv._env_lock:
        envs = list(srv._env_cache)
    return {
        "python_environments": len(envs),
        "total_packages": sum(e.get("package_count", 0) for e in envs),
        "envs": [{"type": e["type"], "version": e["version"], "path": e["path"]} for e in envs[:10]],
        "scan_status": dict(srv._scan_status),
    }


def tool_system_stats(_args):
    srv = _backend()
    return srv.get_system_stats()


def tool_ports(_args):
    srv = _backend()
    return {"ports": srv.get_listening_ports()[:50]}


def tool_notes_search(args):
    import avenger_studio as studio
    from pathlib import Path
    base = Path(__file__).resolve().parent
    q = (args or {}).get("query", "")
    notes = studio.notes_list(base)
    if q:
        ql = q.lower()
        notes = [n for n in notes if ql in (n["title"] + n["body"] + n["tags"]).lower()]
    return {"count": len(notes), "notes": [{"title": n["title"], "body": n["body"][:500], "tags": n["tags"]} for n in notes[:10]]}


def tool_agent_memory_search(args):
    import avenger_agent as agent
    from pathlib import Path
    base = Path(__file__).resolve().parent
    items = agent.mem_list(base, q=(args or {}).get("query", ""))
    return {"count": len(items), "memories": items[:15]}


TOOLS = [
    {"name": "avenger_overview", "description": "Avenger 工作台总览：Python 环境列表、包总数、扫描状态",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "avenger_system_stats", "description": "实时 CPU / 内存占用",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "avenger_ports", "description": "本机 TCP 监听端口与进程名",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "avenger_notes_search", "description": "搜索 Avenger 开发者备忘录",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "description": "关键词"}}, "required": []}},
    {"name": "avenger_memory_search", "description": "搜索 Agent 长期记忆库",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": []}},
]

_HANDLERS = {
    "avenger_overview": tool_overview,
    "avenger_system_stats": tool_system_stats,
    "avenger_ports": tool_ports,
    "avenger_notes_search": tool_notes_search,
    "avenger_memory_search": tool_agent_memory_search,
}


def _reply(msg_id, result):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "result": result}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _error(msg_id, code, message):
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main():
    for raw in sys.stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            req = json.loads(raw)
        except json.JSONDecodeError:
            _error(None, -32700, "Parse error")
            continue
        method = req.get("method", "")
        msg_id = req.get("id")
        try:
            if method == "initialize":
                _reply(msg_id, {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO,
                })
            elif method == "notifications/initialized":
                pass
            elif method == "tools/list":
                _reply(msg_id, {"tools": TOOLS})
            elif method == "resources/list":
                try:
                    import avenger_studio as studio
                    from pathlib import Path
                    notes = studio.notes_list(Path(__file__).resolve().parent)
                    resources = [{"uri": "avenger://notes/" + n["id"], "name": n["title"] or "无标题",
                                  "description": (n["body"] or "")[:80], "mimeType": "text/plain"} for n in notes[:50]]
                except Exception:
                    resources = []
                resources.append({"uri": "avenger://memory/all", "name": "Agent 全部记忆", "mimeType": "text/plain"})
                _reply(msg_id, {"resources": resources})
            elif method == "resources/read":
                uri = (req.get("params") or {}).get("uri", "")
                if uri == "avenger://memory/all":
                    import avenger_agent as agent
                    from pathlib import Path
                    items = agent.mem_list(Path(__file__).resolve().parent)
                    text = chr(10).join("- [%s] %s" % (i["kind"], i["content"]) for i in items) or "(空)"
                elif uri.startswith("avenger://notes/"):
                    import avenger_studio as studio
                    from pathlib import Path
                    nid = uri.rsplit("/", 1)[-1]
                    note = next((n for n in studio.notes_list(Path(__file__).resolve().parent) if n["id"] == nid), None)
                    text = (note["title"] + chr(10) + note["body"]) if note else "未找到"
                else:
                    _error(msg_id, -32602, "Unknown uri")
                    continue
                _reply(msg_id, {"contents": [{"uri": uri, "mimeType": "text/plain", "text": text[:20000]}]})
            elif method == "prompts/list":
                _reply(msg_id, {"prompts": [
                    {"name": "env-health-check", "description": "让 AI 检查本机 Python 环境健康度",
                     "arguments": [], "messages": []}]})
            elif method == "tools/call":
                name = (req.get("params") or {}).get("name", "")
                args = (req.get("params") or {}).get("arguments") or {}
                handler = _HANDLERS.get(name)
                if not handler:
                    _error(msg_id, -32602, "Unknown tool: %s" % name)
                    continue
                data = handler(args)
                _reply(msg_id, {"content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, default=str)}]})
            elif method == "ping":
                _reply(msg_id, {})
            elif msg_id is not None:
                _error(msg_id, -32601, "Method not found: %s" % method)
        except Exception:
            _error(msg_id, -32603, "Internal error: " + traceback.format_exc()[-400:])


if __name__ == "__main__":
    main()
