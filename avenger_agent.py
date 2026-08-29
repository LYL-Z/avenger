# -*- coding: utf-8 -*-
"""Avenger V5.0 Agent 生态引擎：技能库 / MCP / 记忆 / 代码库上下文 / 本地大模型部署量化 /
Agent Harness 生成 / 训练微调工作流 / AI-IDE 配置生成。仅标准库。

Agent Skills 遵循开放标准：目录 + SKILL.md（YAML frontmatter: name/description + Markdown 正文）
参考: https://agentskills.io/specification
"""
import json
import os
import re
import sqlite3
import time
import uuid
from datetime import datetime
from pathlib import Path

_MEM_LOCK = __import__("threading").Lock()

# ============================================================
# 1. Agent Skills 技能库（开放标准 SKILL.md）
# ============================================================

def _skill_md(name, description, body):
    return "---\nname: %s\ndescription: %s\n---\n\n%s\n" % (name, description, body.strip())

SKILLS_REGISTRY = [
    {"id": "code-review", "name": "Code Reviewer", "desc": "逐层代码审查：正确性→边界→并发→性能→可读性", "tags": ["开发"],
     "body": """# 代码审查技能

## 审查顺序（由重到轻）
1. **正确性**：逻辑是否解决真问题？边界条件（空/零/负/极大）？
2. **错误路径**：异常是否被吞掉？失败是否可恢复、可观测？
3. **并发**：共享状态？锁粒度？竞态窗口？
4. **性能**：循环内的 IO/N+1 查询、不必要的拷贝、算法复杂度。
5. **可读性**：命名、函数长度、注释只解释“为什么”。

## 输出格式
每条意见 = `[P0-P3] 标题 + 位置 + 问题 + 建议修法`。
P0=会出事故，P1=会出错，P2=应当改，P3=锦上添花。最后给一行总评。"""},
    {"id": "git-master", "name": "Git Master", "desc": "分支策略、rebase/merge 决策、冲突急救、历史清理", "tags": ["开发"],
     "body": """# Git 高手技能

## 决策树
- 分叉要合并历史 → `git merge --no-ff`；要线性历史 → `git rebase`（公共分支禁 rebase）。
- 改错分支刚提交 → `git reset --soft HEAD~1` → `git stash` → 切分支 → `git stash pop`。
- 找哪次提交弄坏 → `git bisect start` + 二分 good/bad。
- 冲突急救：`git checkout --ours/--theirs <file>`；先 `git diff` 看双方意图再合并语义。

## 提交规范
`type(scope): 祈使句摘要`，正文讲 why。禁止 "fix" "update" 这类零信息提交。"""},
    {"id": "py-debug", "name": "Python Debugger", "desc": "系统性排障：复现→二分→假设→验证", "tags": ["Python"],
     "body": """# Python 排障技能

## 流程
1. **复现**：最小复现脚本 > 一切猜测。`python -X dev -m pdb app.py`。
2. **读 traceback 从最底向上**：最后一行是结论，第一帧是入口，你的代码帧是现场。
3. **二分注释**：定位到函数后，二分注释语句块验证假设。
4. **常见坑**：可变默认参数、闭包晚绑定、is vs ==、循环引用 import、浮点累加。

## 工具
`breakpoint()` > print；`python -m pdb -c continue script.py`；日志用 `logging` 带 stack_info=True。"""},
    {"id": "sql-optimizer", "name": "SQL Optimizer", "desc": "执行计划阅读、索引设计、慢查询改造", "tags": ["数据"],
     "body": """# SQL 优化技能

## 步骤
1. `EXPLAIN (ANALYZE, BUFFERS)` / `EXPLAIN QUERY PLAN` 先看，不猜。
2. 找全表扫描与大排序；确认 WHERE/JOIN/ORDER BY 列的选择性。
3. 索引设计：等值列在前、范围列在后；覆盖索引避免回表；注意最左前缀。
4. 改写：子查询→JOIN、OR→UNION、函数包列→改用表达式索引。
5. 验证：对比前后执行计划与耗时，警惕统计信息过期（ANALYZE）。"""},
    {"id": "regex-cook", "name": "Regex Cookbook", "desc": "正则构造与调试方法论", "tags": ["开发"],
     "body": """# 正则技能

## 方法论
1. 先举 3 正 3 反例，再写模式；用 (?P<name>) 命名一切分组。
2. 贪婪 vs 懒惰：`.*?` 用于边界内最短匹配；嵌套结构正则力不从心时用解析器。
3. 性能：避免嵌套量词回溯爆炸 (a+)+；长 alternation 把高频分支放前面。

## 万能调试循环
写 → 测反例 → 失败则收窄字符类 → 再测。re.DEBUG 看编译结果。"""},
    {"id": "api-design", "name": "API Designer", "desc": "REST 资源建模、版本策略、错误契约", "tags": ["架构"],
     "body": """# API 设计技能

## 原则
1. 资源名词复数 `/users/{id}/orders`；动作走子资源 `POST /orders/{id}/cancellation`。
2. 错误契约统一：`{code, message, details, trace_id}`；4xx 客户端错、5xx 服务端错，别滥用 200 包错误。
3. 分页游标优先于 offset；过滤参数白名单化；幂等键用于 POST 重试。
4. 版本：URL `/v1/` 起步；破坏性改动 = 新版本，不做静默语义变更。"""},
    {"id": "test-writer", "name": "Test Writer", "desc": "测试金字塔、AAA 结构、参数化与边界表", "tags": ["测试"],
     "body": """# 测试编写技能

## 结构
- 每个 test = Arrange-Act-Assert 三段；一个测试只断言一个行为。
- 测行为不测实现；mock 只 mock 边界（网络/时钟/随机），不 mock 被测对象内部。
- 边界表参数化：空、单元素、满、溢出、非法、并发。
- 命名：`test_<行为>_<条件>_<预期>`。覆盖率是仪表不是目标。"""},
    {"id": "tech-writer", "name": "Tech Writer", "desc": "README/ADR/接口文档写作规范", "tags": ["文档"],
     "body": """# 技术写作技能

## 结构
- README 五要素：一句话是什么 → 解决什么痛点 → 30 秒跑起来 → 截图 → 进阶配置。
- ADR：背景 / 决策 / 备选与取舍 / 后果，一页纸，不可变只追加。
- 文档句子规则：一段一个观点；先结论后展开；代码示例可直接复制运行。"""},
    {"id": "frontend-craft", "name": "Frontend Craft", "desc": "布局系统、动效预算、可访问性基线", "tags": ["前端"],
     "body": """# 前端工艺技能

## 布局
- 先决定文档流：Flex 一维 / Grid 二维；`min-width:0` 防溢出是铁律。
- 间距用 4px 基线；层级靠 字号/字重/留白，不靠线框堆砌。

## 动效预算
- 只动 transform/opacity；单元素动效 ≤300ms，入场 stagger ≤60ms 步长。
- `prefers-reduced-motion` 必须尊重。

## A11y 基线
语义标签、focus-visible 可见、对比度 4.5:1、交互元素 ≥40px 触达。"""},
    {"id": "data-viz", "name": "Data Viz", "desc": "图表选型、色彩语义、Canvas 性能", "tags": ["数据"],
     "body": """# 数据可视化技能

## 选型
趋势→折线；对比→条形（分类多时优于饼）；构成→堆叠/占比条；分布→直方/箱线；关系→散点。
饼图类别 >5 时改条形。

## 规则
- 轴从 0 开始（条形）；颜色 = 语义（红=危险）而非装饰；同屏系列 ≤4。
- 大数据集用 Canvas + 降采样；hover 用最近点吸附。"""},
    {"id": "deploy-helper", "name": "Deploy Helper", "desc": "打包、环境变量、回滚清单", "tags": ["运维"],
     "body": """# 部署技能

## 清单
1. 配置全部走环境变量，.env 只存样例；密钥不入镜像不入 git。
2. 构建可重现：锁版本（requirements.txt lock / package-lock）。
3. 健康检查端点 /healthz；优雅退出处理 SIGTERM。
4. 回滚方案先于发布存在：镜像 tag 化，数据库迁移向后兼容。
5. 灰度：小流量 → 观察 error 率/延迟 → 全量。"""},
    {"id": "prompt-eng", "name": "Prompt Engineer", "desc": "系统提示词架构、少样本、结构化输出", "tags": ["AI"],
     "body": """# 提示词工程技能

## 架构
1. 系统提示词分层：角色 → 规则（可枚举）→ 输出格式 → 示例；越靠前权重越高。
2. 少样本示例 > 形容词堆砌；给 2-3 个覆盖边界的示例。
3. 结构化输出：JSON Schema + “只输出 JSON”，并在代码侧校验重试。
4. 让模型先列计划再执行（plan-then-act），长任务分步确认。"""},
]


def skill_dirs():
    home = os.path.expanduser("~")
    return {
        "avenger": str(Path(home) / ".avenger" / "skills"),
        "claude": str(Path(home) / ".claude" / "skills"),
        "project": str(Path.cwd() / ".claude" / "skills"),
    }


def skills_list():
    builtin = [{"id": s["id"], "name": s["name"], "desc": s["desc"], "tags": s["tags"], "installed": False, "builtin": True} for s in SKILLS_REGISTRY]
    installed = []
    seen = set()
    for scope, root in skill_dirs().items():
        root_p = Path(root)
        if not root_p.is_dir():
            continue
        try:
            for d in sorted(root_p.iterdir()):
                md = d / "SKILL.md"
                if not md.is_file():
                    continue
                try:
                    text = md.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                m = re.match(r"^---\s*\nname:\s*(.+?)\s*\ndescription:\s*(.+?)\s*\n", text)
                name = m.group(1) if m else d.name
                desc = m.group(2) if m else ""
                installed.append({"id": d.name, "name": name, "desc": desc[:160], "scope": scope, "path": str(md)})
                seen.add(d.name)
        except OSError:
            continue
    for b in builtin:
        if b["id"] in seen:
            b["installed"] = True
    return {"builtin": builtin, "installed": installed, "dirs": skill_dirs()}


def skill_body(skill_id):
    s = next((x for x in SKILLS_REGISTRY if x["id"] == skill_id), None)
    if not s:
        return None
    return _skill_md(s["id"], s["desc"], s["body"])


def skill_install(skill_id):
    s = next((x for x in SKILLS_REGISTRY if x["id"] == skill_id), None)
    if not s:
        return {"ok": False, "error": "未知技能"}
    target = Path(skill_dirs()["avenger"]) / s["id"]
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(_skill_md(s["id"], s["desc"], s["body"]), encoding="utf-8")
    return {"ok": True, "path": str(target / "SKILL.md")}


def skill_uninstall(skill_id):
    target = Path(skill_dirs()["avenger"]) / skill_id
    if not target.is_dir():
        return {"ok": False, "error": "该技能不在 Avenger 技能目录"}
    import shutil
    shutil.rmtree(target, ignore_errors=True)
    return {"ok": True}


def skill_create(name, description, body):
    n = re.sub(r"[^a-z0-9-]+", "-", (name or "").strip().lower()).strip("-")[:64]
    if not n:
        return {"ok": False, "error": "技能名仅允许小写字母/数字/连字符"}
    target = Path(skill_dirs()["avenger"]) / n
    target.mkdir(parents=True, exist_ok=True)
    (target / "SKILL.md").write_text(_skill_md(n, (description or "")[:200], body or "（在这里写技能指令）"), encoding="utf-8")
    return {"ok": True, "id": n, "path": str(target / "SKILL.md")}


# ============================================================
# 2. MCP 协议生态
# ============================================================

MCP_REGISTRY = [
    {"id": "filesystem", "name": "Filesystem", "cat": "官方参考", "desc": "受控目录读写/搜索/移动，最常用入门服务", "cmd": "npx -y @modelcontextprotocol/server-filesystem C:\\path\\to\\dir"},
    {"id": "github", "name": "GitHub", "cat": "官方参考", "desc": "仓库/PR/Issue/文件全操作（配 GitHub Token）", "cmd": "npx -y @modelcontextprotocol/server-github"},
    {"id": "fetch", "name": "Fetch", "cat": "官方参考", "desc": "抓取网页并转 Markdown 给模型阅读", "cmd": "uvx mcp-server-fetch"},
    {"id": "memory", "name": "Memory", "cat": "官方参考", "desc": "知识图谱式长期记忆（本地持久化）", "cmd": "npx -y @modelcontextprotocol/server-memory"},
    {"id": "sequential-thinking", "name": "Sequential Thinking", "cat": "官方参考", "desc": "结构化分步思考，复杂推理必备", "cmd": "npx -y @modelcontextprotocol/server-sequential-thinking"},
    {"id": "time", "name": "Time", "cat": "官方参考", "desc": "时区查询与时间换算", "cmd": "uvx mcp-server-time"},
    {"id": "sqlite", "name": "SQLite", "cat": "官方参考", "desc": "本地 SQLite 只读/分析", "cmd": "uvx mcp-server-sqlite --db-path D:\\data\\app.db"},
    {"id": "playwright", "name": "Playwright", "cat": "浏览器自动化", "desc": "浏览器操控/截图/表单/E2E，头部热门", "cmd": "npx -y @playwright/mcp@latest"},
    {"id": "puppeteer", "name": "Puppeteer", "cat": "浏览器自动化", "desc": "无头浏览器自动化经典款", "cmd": "npx -y @modelcontextprotocol/server-puppeteer"},
    {"id": "context7", "name": "Context7", "cat": "文档增强", "desc": "实时拉取库的最新官方文档，治幻觉 API", "cmd": "npx -y @upstash/context7-mcp"},
    {"id": "git", "name": "Git", "cat": "开发工具", "desc": "本地仓库 diff/commit/分支操作", "cmd": "uvx mcp-server-git --repository D:\\your\\repo"},
    {"id": "desktop-commander", "name": "Desktop Commander", "cat": "开发工具", "desc": "终端命令 + 文件编辑，本地自动化利器", "cmd": "npx -y @wonderwhy-er/desktop-commander"},
    {"id": "postgres", "name": "PostgreSQL", "cat": "数据库", "desc": "Postgres 只读 schema 探查与查询", "cmd": "npx -y @modelcontextprotocol/server-postgres postgresql://localhost/db"},
    {"id": "brave-search", "name": "Brave Search", "cat": "搜索", "desc": "网页/本地搜索（需免费 API Key）", "cmd": "npx -y @modelcontextprotocol/server-brave-search"},
    {"id": "exa", "name": "Exa", "cat": "搜索", "desc": "面向 LLM 的语义搜索", "cmd": "npx -y exa-mcp-server"},
    {"id": "notion", "name": "Notion", "cat": "办公协同", "desc": "Notion 页面/数据库读写", "cmd": "npx -y @notionhq/notion-mcp-server"},
    {"id": "slack", "name": "Slack", "cat": "办公协同", "desc": "频道读取与消息发送", "cmd": "npx -y @modelcontextprotocol/server-slack"},
    {"id": "docker", "name": "Docker", "cat": "运维", "desc": "容器/镜像/日志管理", "cmd": "uvx mcp-server-docker"},
]


def _read_json_safe(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def mcp_local_configs():
    """扫描本机常见 AI 客户端的 MCP 配置文件。"""
    home = os.path.expanduser("~")
    appdata = os.environ.get("APPDATA", "")
    candidates = [
        ("Claude Desktop", os.path.join(appdata, "Claude", "claude_desktop_config.json"), "mcpServers"),
        ("Claude Code", os.path.join(home, ".claude.json"), "mcpServers"),
        ("Cursor", os.path.join(home, ".cursor", "mcp.json"), "mcpServers"),
        ("VS Code", os.path.join(appdata, "Code", "User", "mcp.json"), "servers"),
        ("项目 .mcp.json", os.path.join(os.getcwd(), ".mcp.json"), "mcpServers"),
    ]
    out = []
    for client, path, key in candidates:
        data = _read_json_safe(path) if path else None
        servers = []
        if isinstance(data, dict):
            block = data.get(key)
            if isinstance(block, dict):
                for name, cfg in block.items():
                    cmd = ""
                    if isinstance(cfg, dict):
                        args = cfg.get("args") or []
                        cmd = " ".join([str(cfg.get("command") or "")] + [str(a) for a in args]).strip()
                    servers.append({"name": name, "command": cmd[:180]})
        out.append({"client": client, "path": path, "exists": bool(path and os.path.isfile(path)), "servers": servers})
    return out


def mcp_snippet(client, server_id, extra):
    reg = next((m for m in MCP_REGISTRY if m["id"] == server_id), None)
    if not reg:
        return {"ok": False, "error": "未知 MCP 服务器"}
    parts = reg["cmd"].split(" ", 1)
    command = parts[0]
    args = parts[1].split() if len(parts) > 1 else []
    args = [a.replace("C:\\path\\to\\dir", (extra or "").strip() or "C:\\path\\to\\dir") for a in args]
    entry = {"command": command, "args": args}
    wrapped = {"mcpServers": {reg["name"]: entry}}
    if client == "vscode":
        wrapped = {"servers": {reg["name"]: {"command": command, "args": args, "type": "stdio"}}}
    elif client == "claude-code":
        wrapped = {"mcpServers": {reg["id"]: entry}}
    return {"ok": True, "json": json.dumps(wrapped, ensure_ascii=False, indent=2),
            "cli": "claude mcp add %s -- %s" % (reg["id"], reg["cmd"]) if client == "claude-code" else ""}


# ============================================================
# 3. Agent 记忆（SQLite）
# ============================================================

def _mem_db(base_dir):
    path = Path(base_dir) / "avenger_notes.db"
    conn = sqlite3.connect(str(path), timeout=8)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS agent_memory("
        "id TEXT PRIMARY KEY, kind TEXT, content TEXT, tags TEXT, source TEXT, created TEXT)"
    )
    conn.commit()
    return conn


def mem_add(base_dir, body):
    kind = (body.get("kind") or "fact")[:24]
    content = (body.get("content") or "").strip()[:8000]
    tags = (body.get("tags") or "")[:200]
    source = (body.get("source") or "manual")[:40]
    if not content:
        return {"ok": False, "error": "内容不能为空"}
    mid = uuid.uuid4().hex[:12]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _MEM_LOCK:
        conn = _mem_db(base_dir)
        conn.execute("INSERT INTO agent_memory(id,kind,content,tags,source,created) VALUES(?,?,?,?,?,?)",
                      (mid, kind, content, tags, source, now))
        conn.commit()
        conn.close()
    return {"ok": True, "id": mid, "created": now}


def mem_list(base_dir, q="", kind=""):
    with _MEM_LOCK:
        conn = _mem_db(base_dir)
        rows = conn.execute("SELECT id,kind,content,tags,source,created FROM agent_memory ORDER BY created DESC").fetchall()
        conn.close()
    q = (q or "").lower()
    out = []
    for r in rows:
        if kind and r[1] != kind:
            continue
        if q and q not in (r[2] or "").lower() and q not in (r[3] or "").lower():
            continue
        out.append({"id": r[0], "kind": r[1], "content": r[2], "tags": r[3] or "", "source": r[4] or "", "created": r[5] or ""})
    return out[:300]


def mem_delete(base_dir, mid):
    with _MEM_LOCK:
        conn = _mem_db(base_dir)
        conn.execute("DELETE FROM agent_memory WHERE id=?", (mid,))
        conn.commit()
        conn.close()
    return {"ok": True}


def mem_export(base_dir):
    items = mem_list(base_dir)
    return {"ok": True, "items": items, "markdown": "\n".join("- [%s] %s" % (i["kind"], i["content"]) for i in items)}


# ============================================================
# 4. 代码库上下文（Context Pack）
# ============================================================

_SKIP_DIRS = {"node_modules", "__pycache__", ".git", "venv", ".venv", "env", "dist", "build",
              "site-packages", ".next", ".nuxt", "target", ".idea", ".vscode", ".gradle"}
_CODE_EXT = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".tsx": "TypeScript", ".jsx": "JavaScript",
             ".java": "Java", ".go": "Go", ".rs": "Rust", ".c": "C", ".h": "C", ".cpp": "C++", ".cs": "C#",
             ".php": "PHP", ".rb": "Ruby", ".swift": "Swift", ".kt": "Kotlin", ".sql": "SQL", ".sh": "Shell",
             ".html": "HTML", ".css": "CSS", ".vue": "Vue"}
_KEY_FILES = ["README.md", "readme.md", "pyproject.toml", "requirements.txt", "package.json",
              "go.mod", "Cargo.toml", "pom.xml", "composer.json", "Gemfile", "Makefile", "Dockerfile"]
_SYMBOL_RE = re.compile(r"^(?:def |class |async def |function |export (?:function|class|const) |func |fn |public |impl )")


def context_scan(path):
    p = Path(path)
    if not p.is_dir():
        return {"ok": False, "error": "目录不存在"}
    stats = {}
    files_total = 0
    loc_total = 0
    tree_lines = []
    key_hits = []

    def walk(d, depth):
        nonlocal files_total, loc_total
        if depth > 4 or files_total > 3000:
            return
        try:
            entries = sorted(d.iterdir(), key=lambda x: (x.is_file(), x.name.lower()))
        except OSError:
            return
        for e in entries:
            if e.name.startswith(".") and e.name not in (".venv",):
                continue
            if e.is_dir():
                if e.name.lower() in _SKIP_DIRS:
                    continue
                tree_lines.append("  " * depth + e.name + "/")
                walk(e, depth + 1)
            else:
                files_total += 1
                ext = e.suffix.lower()
                if ext in _CODE_EXT:
                    stats[_CODE_EXT[ext]] = stats.get(_CODE_EXT[ext], 0) + 1
                if e.name in _KEY_FILES and len(key_hits) < 12:
                    key_hits.append(str(e))
                tree_lines.append("  " * depth + e.name)
                if ext in _CODE_EXT and loc_total < 400000:
                    try:
                        with open(e, "rb") as f:
                            loc_total += sum(1 for _ in f)
                    except OSError:
                        pass

    walk(p, 0)
    frameworks = []
    for kf in key_hits:
        name = os.path.basename(kf)
        if name == "package.json":
            data = _read_json_safe(kf) or {}
            deps = set(list((data.get("dependencies") or {}).keys()) + list((data.get("devDependencies") or {}).keys()))
            for fw in ("react", "vue", "next", "svelte", "vite", "express", "electron"):
                if fw in deps:
                    frameworks.append(fw.capitalize())
        elif name in ("pyproject.toml", "requirements.txt"):
            frameworks.append("Python 项目")
        elif name == "go.mod":
            frameworks.append("Go")
        elif name == "Cargo.toml":
            frameworks.append("Rust")
        elif name == "Dockerfile":
            frameworks.append("Docker")
    return {
        "ok": True, "path": str(p), "files": files_total, "loc": loc_total,
        "languages": sorted(stats.items(), key=lambda x: -x[1])[:10],
        "frameworks": sorted(set(frameworks))[:8],
        "tree": "\n".join(tree_lines[:160]),
        "tree_truncated": len(tree_lines) > 160,
        "key_files": key_hits,
    }


_SYMBOL_CAP = 120


def context_pack(path):
    scan = context_scan(path)
    if not scan.get("ok"):
        return scan
    root = Path(scan["path"])
    lines = ["# %s — Context Pack" % root.name, "",
             "> 由 Avenger V5 生成的代码库上下文摘要（供 AI 助手快速了解本仓库）。生成时间 %s。" % datetime.now().strftime("%Y-%m-%d %H:%M"), ""]
    lines.append("## 概况")
    lines.append("- 路径: `%s`" % scan["path"])
    lines.append("- 规模: %s 个文件, 约 %s 行代码" % (scan["files"], format_loc(scan["loc"])))
    if scan["languages"]:
        lines.append("- 语言: " + ", ".join("%s×%d" % (l, c) for l, c in scan["languages"]))
    if scan["frameworks"]:
        lines.append("- 技术栈线索: " + ", ".join(scan["frameworks"]))
    lines.append("")
    lines.append("## 目录结构")
    lines.append("```")
    lines.append(scan["tree"])
    lines.append("```")
    for kf in scan["key_files"][:3]:
        try:
            text = Path(kf).read_text(encoding="utf-8", errors="replace")[:1800]
        except OSError:
            continue
        lines += ["", "## 关键文件: %s" % os.path.basename(kf), "```", text, "```"]
    symbols = []
    for e in sorted(root.rglob("*.py"))[:400]:
        if any(part.lower() in _SKIP_DIRS for part in e.parts):
            continue
        try:
            for ln in e.read_text(encoding="utf-8", errors="replace").splitlines():
                if _SYMBOL_RE.match(ln):
                    symbols.append("%s: %s" % (e.name, ln.strip()[:100]))
                    if len(symbols) >= _SYMBOL_CAP:
                        break
        except OSError:
            continue
        if len(symbols) >= _SYMBOL_CAP:
            break
    if symbols:
        lines += ["", "## 关键符号（前 %d 个）" % len(symbols), "```"] + symbols + ["```"]
    return {"ok": True, "pack": "\n".join(lines), "chars": len("\n".join(lines))}


def format_loc(n):
    if n >= 10000:
        return "%.1fk" % (n / 10000 * 10 / 10) if n < 1000000 else "%.1fM" % (n / 1000000)
    return str(n)


def context_pack_save(path):
    r = context_pack(path)
    if not r.get("ok"):
        return r
    out = Path(path) / "CONTEXT_PACK.md"
    out.write_text(r["pack"], encoding="utf-8")
    r["saved"] = str(out)
    return r


# ============================================================
# 5. 本地大模型部署 / 量化 / 显存适配
# ============================================================

# 每参数字节数（近似 GGUF 实测均值）
QUANTS = [
    {"id": "fp16", "name": "FP16/BF16", "bpw": 2.0, "note": "全精度，质量基线，显存翻倍"},
    {"id": "q8", "name": "Q8_0", "bpw": 1.06, "note": "近无损，质量 ≈99.9%"},
    {"id": "q6", "name": "Q6_K", "bpw": 0.81, "note": "极高质量损失可忽略"},
    {"id": "q5", "name": "Q5_K_M", "bpw": 0.71, "note": "推荐：质量/体积甜点"},
    {"id": "q4km", "name": "Q4_K_M", "bpw": 0.60, "note": "最热门默认：质量损失 <3%"},
    {"id": "iq4xs", "name": "IQ4_XS", "bpw": 0.52, "note": "再省 15% 显存"},
    {"id": "q3", "name": "Q3_K_M", "bpw": 0.48, "note": "紧显存可用，质量开始下滑"},
    {"id": "q2", "name": "Q2_K", "bpw": 0.35, "note": "最后手段，质量明显受损"},
]

# 近似架构参数：层数 / KV 维度（GQA kv_heads×128），KV 每 token 字节 = 2(K+V)×kv_dim×2B
LLM_ARCH = {
    "0.5B": {"layers": 24, "kv_dim": 896, "hidden": 896},
    "1.5B": {"layers": 28, "kv_dim": 1024, "hidden": 1536},
    "3B": {"layers": 36, "kv_dim": 1024, "hidden": 2048},
    "7B": {"layers": 32, "kv_dim": 1024, "hidden": 4096},
    "8B": {"layers": 32, "kv_dim": 1024, "hidden": 4096},
    "14B": {"layers": 48, "kv_dim": 1024, "hidden": 5120},
    "32B": {"layers": 64, "kv_dim": 1024, "hidden": 5120},
    "70B": {"layers": 80, "kv_dim": 1024, "hidden": 8192},
}

KV_BYTES_PER_TOKEN_PER_LAYER = 2 * 2  # K+V × fp16(2B)，再乘 kv_dim


def vram_calc(params_b, quant_id, ctx_k=8):
    q = next((x for x in QUANTS if x["id"] == quant_id), QUANTS[4])
    arch = LLM_ARCH.get(str(params_b), LLM_ARCH["7B"])
    weights_gb = params_b * q["bpw"]
    kv_gb = arch["layers"] * KV_BYTES_PER_TOKEN_PER_LAYER * arch["kv_dim"] * ctx_k * 1000 / (1024 ** 3)
    overhead_gb = 0.6  # CUDA/激活/计算缓冲
    total = weights_gb + kv_gb + overhead_gb
    return {
        "params_b": params_b, "quant": q["name"], "bpw": q["bpw"], "ctx_k": ctx_k,
        "weights_gb": round(weights_gb, 2), "kv_gb": round(kv_gb, 2),
        "overhead_gb": overhead_gb, "total_gb": round(total, 2),
        "note": q["note"],
    }


def vram_recommend(vram_gb, ctx_k=8):
    """给定可用显存，给出可跑的模型×量化组合（从大到小）。"""
    fits = []
    for p in sorted(LLM_ARCH.keys(), key=lambda x: float(x[:-1])):
        for q in QUANTS:
            r = vram_calc(float(p[:-1]), q["id"], ctx_k)
            if r["total_gb"] <= vram_gb * 0.94:
                fits.append({"model": p, "quant": q["name"], "quant_id": q["id"],
                             "total_gb": r["total_gb"], "note": q["note"]})
            break  # 每个尺寸只取最大可用量化？反转：下面单独再补 q4
    # 补充每个尺寸的 Q4_K_M（若装得下）
    for p in sorted(LLM_ARCH.keys(), key=lambda x: float(x[:-1])):
        r = vram_calc(float(p[:-1]), "q4km", ctx_k)
        if r["total_gb"] <= vram_gb * 0.94:
            fits.append({"model": p, "quant": "Q4_K_M", "quant_id": "q4km", "total_gb": r["total_gb"], "note": "质量甜点档"})
    seen = set()
    uniq = []
    for f in fits:
        k = (f["model"], f["quant"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(f)
    uniq.sort(key=lambda x: (-float(x["model"][:-1]), -x["total_gb"]))
    return {"vram_gb": vram_gb, "ctx_k": ctx_k, "fits": uniq[:14],
            "ollama_gpu_hint": "ollama 自动分层到 GPU；设置 OLLAMA_NUM_GPU 层控 / OLLAMA_FLASH_ATTENTION=1 省显存"}


def deploy_commands(params_b, quant_id, ctx_k=8):
    r = vram_calc(params_b, quant_id, ctx_k)
    qmap = {"fp16": "f16", "q8": "q8_0", "q6": "q6_K", "q5": "q5_K_M", "q4km": "q4_K_M",
            "iq4xs": "iq4_xs", "q3": "q3_K_M", "q2": "q2_K"}
    gguf_tag = qmap.get(quant_id, "q4_K_M")
    ollama = "ollama run llama3.1:%s-instruct-%s" % (("70b" if params_b >= 70 else ("8b" if params_b >= 7 else params_b)), {"fp16": "f16", "q8": "q8_0", "q6": "q6_K", "q5": "q5_K_M", "q4km": "q4_K_M", "iq4xs": "q4_K_M", "q3": "q3_K_M", "q2": "q2_K"}[quant_id]) if params_b >= 7 else "ollama run qwen2.5:%sb-instruct" % params_b
    llamacpp = (
        "llama-server -m model-%s.gguf -c %d -ngl 999 --flash-attn --host 127.0.0.1 --port 8080\n"
        "# 预计占用 %.1f GB（权重 %.1f + KV %.1f + 开销 %.1f）"
        % (gguf_tag, ctx_k * 1024, r["total_gb"], r["weights_gb"], r["kv_gb"], r["overhead_gb"])
    )
    env = "OLLAMA_FLASH_ATTENTION=1  # KV 省显存\nOLLAMA_KV_CACHE_TYPE=q8_0    # KV 量化，再省约 50%%\nOLLAMA_NUM_PARALLEL=1"
    return {"vram": r, "ollama": ollama, "llamacpp": llamacpp, "env": env,
            "openai_compat": "llama-server / Ollama 均提供 OpenAI 兼容端点，Avenger AI 工坊选「自定义」即可接入"}


# ============================================================
# 6. Coding-Agent Harness 生成器
# ============================================================

HARNESS_TOOL_CATALOG = [
    {"id": "read_file", "desc": "读取文本文件（限项目目录）"},
    {"id": "list_dir", "desc": "列出目录内容"},
    {"id": "run_python", "desc": "运行一段 Python 并回传 stdout（沙箱提示）"},
    {"id": "http_get", "desc": "GET 一个 URL（本机或 https）"},
    {"id": "remember", "desc": "写入本地记忆文件 memory.md"},
]

_HARNESS_TEMPLATE = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Avenger Harness — 单文件 Coding Agent 运行框架（OpenAI 兼容 / 纯标准库）
由 Avenger V5 生成于 __DATE__
用法: python agent_harness.py "你的任务描述"
"""
import json, os, re, subprocess, sys, urllib.request

BASE_URL = os.environ.get("AGENT_BASE_URL", "__BASE_URL__")
API_KEY = os.environ.get("AGENT_API_KEY", "__API_KEY__")
MODEL = os.environ.get("AGENT_MODEL", "__MODEL__")
MAX_STEPS = __MAX_STEPS__
WORKDIR = os.path.abspath(os.environ.get("AGENT_WORKDIR", "."))
MEMORY_FILE = os.path.join(WORKDIR, "agent_memory.md")

# ---------------- 工具集 ----------------
def _safe_path(rel):
    p = os.path.abspath(os.path.join(WORKDIR, rel))
    if not p.startswith(WORKDIR):
        raise ValueError("越界路径: " + rel)
    return p

def tool_read_file(path):
    with open(_safe_path(path), "r", encoding="utf-8", errors="replace") as f:
        return f.read(20000)

def tool_list_dir(path="."):
    p = _safe_path(path)
    return "\\n".join(sorted(os.listdir(p))[:200])

def tool_run_python(code):
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30)
    return ("exit=%d\\nSTDOUT:\\n%s\\nSTDERR:\\n%s" % (r.returncode, r.stdout[:4000], r.stderr[:2000]))

def tool_http_get(url):
    if not (url.startswith("https://") or url.startswith("http://127.0.0.1")):
        return "仅允许 https 或本机地址"
    with urllib.request.urlopen(url, timeout=15) as resp:
        return resp.read(20000).decode("utf-8", "replace")

def tool_remember(text):
    with open(MEMORY_FILE, "a", encoding="utf-8") as f:
        f.write("- [%s] %s\\n" % (time.strftime("%H:%M"), text[:500]))
    return "已记忆"

TOOLS = __TOOLS_IMPL__

TOOL_SCHEMAS = __TOOL_SCHEMAS__

def call_llm(messages):
    body = json.dumps({"model": MODEL, "messages": messages, "tools": TOOL_SCHEMAS, "temperature": 0.3}).encode()
    req = urllib.request.Request(BASE_URL, data=body, method="POST",
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + API_KEY})
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8", "replace"))

def run_agent(task):
    messages = [
        {"role": "system", "content": "你是运行在 %s 的编码代理。先计划再动手，每步用一个工具，完成后给出总结。不要越出工作目录。" % WORKDIR},
        {"role": "user", "content": task},
    ]
    for step in range(MAX_STEPS):
        data = call_llm(messages)
        msg = data["choices"][0]["message"]
        messages.append(msg)
        calls = msg.get("tool_calls") or []
        if not calls:
            print("\\n=== 最终回答 ===\\n" + msg.get("content", ""))
            return
        for tc in calls:
            name = tc["function"]["name"]
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            print("[step %d] %s %s" % (step + 1, name, json.dumps(args, ensure_ascii=False)[:120]))
            try:
                result = str(TOOLS[name](**args))[:8000]
            except Exception as e:
                result = "工具错误: %r" % e
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
    print("已达最大步数 MAX_STEPS=%d，任务中止。" % MAX_STEPS)

if __name__ == "__main__":
    import time
    task = sys.argv[1] if len(sys.argv) > 1 else input("任务: ")
    run_agent(task)
'''


def harness_generate(body):
    tool_ids = body.get("tools") or ["read_file", "list_dir", "run_python", "remember"]
    tool_ids = [t for t in tool_ids if any(c["id"] == t for c in HARNESS_TOOL_CATALOG)][:8]
    if not tool_ids:
        tool_ids = ["read_file", "list_dir"]
    impl_lines = []
    schema_lines = []
    for tid in tool_ids:
        impl_lines.append('    "%s": %s,' % (tid, "tool_" + tid))
        desc = next(c["desc"] for c in HARNESS_TOOL_CATALOG if c["id"] == tid)
        schema = {"type": "function", "function": {"name": tid, "description": desc, "parameters": {"type": "object", "properties": {}, "required": []}}}
        if tid in ("read_file", "list_dir"):
            schema["function"]["parameters"]["properties"]["path"] = {"type": "string", "description": "相对工作目录的路径"}
        if tid == "run_python":
            schema["function"]["parameters"]["properties"]["code"] = {"type": "string", "description": "要执行的 Python 代码"}
            schema["function"]["parameters"]["required"] = ["code"]
        if tid == "http_get":
            schema["function"]["parameters"]["properties"]["url"] = {"type": "string"}
            schema["function"]["parameters"]["required"] = ["url"]
        if tid == "remember":
            schema["function"]["parameters"]["properties"]["text"] = {"type": "string"}
            schema["function"]["parameters"]["required"] = ["text"]
        schema_lines.append(json.dumps(schema, ensure_ascii=False))
    script = (
        _HARNESS_TEMPLATE
        .replace("__DATE__", datetime.now().strftime("%Y-%m-%d %H:%M"))
        .replace("__BASE_URL__", (body.get("base_url") or "https://api.deepseek.com/v1/chat/completions"))
        .replace("__API_KEY__", os.environ.get("AGENT_API_KEY", "sk-填你的Key"))
        .replace("__MODEL__", (body.get("model") or "deepseek-chat"))
        .replace("__MAX_STEPS__", str(min(int(body.get("max_steps") or 15), 40)))
        .replace("__TOOLS_IMPL__", "{\n" + "\n".join(impl_lines) + "\n}")
        .replace("__TOOL_SCHEMAS__", "[\n    " + ",\n    ".join(schema_lines) + "\n]")
    )
    return {"ok": True, "filename": "agent_harness.py", "script": script,
            "usage": "AGENT_API_KEY=sk-xxx python agent_harness.py \"重构 utils.py 并补测试\"",
            "tools": tool_ids}


# ============================================================
# 7. 训练 / 微调工作流
# ============================================================

TRAIN_PLAYBOOKS = [
    {"id": "unsloth", "name": "Unsloth", "tag": "单卡首选", "min_vram": 6,
     "when": "单张消费级显卡（6-24GB）做 LoRA/QLoRA，速度最快、显存最省（约省 30-70%）",
     "pros": "速度 2-5×、显存占用最低、Colab 免费卡可跑", "cons": "主要覆盖 Llama/Qwen/Mistral/Gemma 等热门架构",
     "install": "pip install unsloth",
     "code": '''from unsloth import FastLanguageModel
from trl import SFTTrainer
from transformers import TrainingArguments
from datasets import load_dataset

model, tokenizer = FastLanguageModel.from_pretrained(
    "Qwen/Qwen2.5-7B-Instruct", max_seq_length=2048, load_in_4bit=True)
model = FastLanguageModel.get_peft_model(
    model, r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"])
ds = load_dataset("json", data_files="train.jsonl", split="train")
trainer = SFTTrainer(model=model, tokenizer=tokenizer, train_dataset=ds,
    args=TrainingArguments(per_device_train_batch_size=2, gradient_accumulation_steps=4,
        num_train_epochs=3, learning_rate=2e-4, fp16=True, logging_steps=10, output_dir="out"))
trainer.train()
model.save_pretrained_gguf("gguf_out", tokenizer, quantization_method="q4_k_m")'''},
    {"id": "llamafactory", "name": "LLaMA-Factory", "tag": "全家桶", "min_vram": 8,
     "when": "想要 WebUI 点选配置 + 覆盖全方法（LoRA/全参/DPO/奖励模型）+ 多后端",
     "pros": "零代码 YAML/WebUI、方法最全、中文文档好", "cons": "抽象层厚，极限性能不如 Unsloth",
     "install": "git clone https://github.com/hiyouga/LLaMA-Factory && pip install -e '.[torch,metrics]'",
     "code": '''# train_lora.yaml
model_name_or_path: Qwen/Qwen2.5-7B-Instruct
stage: sft
finetuning_type: lora
lora_rank: 16
lora_target: all
dataset: my_data          # 在 data/dataset_info.json 注册
template: qwen
cutoff_len: 2048
per_device_train_batch_size: 2
gradient_accumulation_steps: 4
learning_rate: 5.0e-5
num_train_epochs: 3.0
output_dir: saves/qwen7b-lora
# 运行: llamafactory-cli train train_lora.yaml
# 合并: llamafactory-cli export merge_lora.yaml'''},
    {"id": "trl-peft", "name": "HF TRL + PEFT", "tag": "标准路线", "min_vram": 8,
     "when": "需要完全控制训练循环 / 生态兼容最大化 / 上多卡 DeepSpeed",
     "pros": "HuggingFace 生态原生、可组合 RLHF/DPO 全流程", "cons": "样板代码较多，显存优化要手动拼 bitsandbytes",
     "install": "pip install trl peft bitsandbytes datasets accelerate",
     "code": '''from trl import SFTTrainer, SFTConfig
from peft import LoraConfig
from datasets import load_dataset

ds = load_dataset("json", data_files="train.jsonl", split="train")
trainer = SFTTrainer(
    "Qwen/Qwen2.5-7B-Instruct",
    train_dataset=ds,
    peft_config=LoraConfig(r=16, lora_alpha=32, task_type="CAUSAL_LM"),
    args=SFTConfig(per_device_train_batch_size=2, gradient_accumulation_steps=4,
                   num_train_epochs=3, learning_rate=2e-4, output_dir="out"),
)
trainer.train()'''},
    {"id": "axolotl", "name": "Axolotl", "tag": "YAML 复杂配方", "min_vram": 10,
     "when": "多卡训练、复杂多阶段（预训练续训 + SFT + DPO）配方复用",
     "pros": "YAML 配方可版本化、社区配方库丰富、多卡成熟", "cons": "入门曲线较陡",
     "install": "pip install axolotl",
     "code": '''# config.yaml
base_model: Qwen/Qwen2.5-7B-Instruct
load_in_4bit: true
adapter: lora
lora_r: 16
lora_alpha: 32
datasets:
  - path: train.jsonl
    type: alpaca
sequence_len: 2048
num_epochs: 3
micro_batch_size: 2
gradient_accumulation_steps: 4
output_dir: ./out
# 运行: axolotl train config.yaml'''},
    {"id": "torchtune", "name": "torchtune", "tag": "PyTorch 原生", "min_vram": 8,
     "when": "想贴着 PyTorch 原语改训练内行、不引重依赖",
     "pros": "官方 PyTorch 出品、配方即 Python、易于魔改", "cons": "模型覆盖比社区全家桶少",
     "install": "pip install torchtune",
     "code": '''# 下载并 LoRA 微调（命令行配方）
tune download Qwen/Qwen2.5-7B-Instruct --output-dir /tmp/qwen7b
tune run lora_finetune_single_device \\
  --config qwen2_5/7B_lora_single_device \\
  data.files=train.jsonl epochs=3 batch_size=2'''},
    {"id": "from-scratch", "name": "从零小模型", "tag": "nanoGPT 路线", "min_vram": 4,
     "when": "学习目的：亲手训练一个 10M-124M 的小模型（分词→预训练→SFT）",
     "pros": "理解 LLM 全栈内幕的最佳路径", "cons": "产出模型只适合学习/玩具场景",
     "install": "pip install torch tiktoken datasets",
     "code": '''# 1) 语料 → 二进制 (prepare.py 参考 nanoGPT)
# 2) 训练:
# torchrun --standalone --nproc_per_node=1 train.py \\
#   --n_layer=6 --n_head=6 --n_embd=384   # ~10M 参数
#   --batch_size=12 --max_iters=5000 --lr_decay=cosine
# 3) 采样: python sample.py --prompt="一旦"'''},
]


def train_playbooks():
    return {"playbooks": TRAIN_PLAYBOOKS,
            "pipeline": [
                {"step": 1, "name": "定目标", "detail": "先问：提示工程/RAG 能否解决？微调适合 稳定风格/格式/领域知识/小模型降本"},
                {"step": 2, "name": "备数据", "detail": "1k-1万条高质量样本 > 十万条噪声。JSONL，去重去脏，留 5% 验证集"},
                {"step": 3, "name": "选配方", "detail": "单卡消费级→Unsloth QLoRA；多卡/复杂→Axolotl；标准可控→TRL"},
                {"step": 4, "name": "训练", "detail": "lr 1e-4~2e-4(LoRA)，3 epochs 起步，盯 loss 曲线防过拟合"},
                {"step": 5, "name": "评测", "detail": "验证集 + 真实任务盲测；和基座模型 A/B 对比，别只看 loss"},
                {"step": 6, "name": "部署", "detail": "合并 LoRA → 导出 GGUF(Q4_K_M) → Ollama/llama-server 上线"},
            ]}


def train_vram(params_b, method, ctx_k=2, batch=2):
    """训练显存估算：method in full/lora/qlora"""
    if method == "full":
        bytes_per = 16.0  # bf16 权重2 + 梯度2 + AdamW状态8 + 主权重4（混合精度）
        act_gb = 0.35 * ctx_k * batch
        total = params_b * bytes_per / 2 + act_gb  # 粗估减半经验系数
        note = "全参微调极吃显存，7B 需要 ≥60GB（或 DeepSpeed ZeRO-3/FSDP 多卡）"
    elif method == "lora":
        act_gb = 0.10 * ctx_k * batch
        total = params_b * 2.0 + params_b * 0.05 + act_gb + 1.0
        note = "LoRA：基座 bf16 载入 + 适配器训练，7B≈16-18GB 起步"
    else:  # qlora
        act_gb = 0.06 * ctx_k * batch
        total = params_b * 0.60 + params_b * 0.02 + act_gb + 1.5
        note = "QLoRA：基座 4bit 载入，7B≈5-6GB 可跑，消费级单卡首选"
    return {"params_b": params_b, "method": method, "ctx_k": ctx_k, "batch": batch,
            "total_gb": round(total, 1), "note": note}


def dataset_validate(text):
    """校验 JSONL 训练集：schema 识别 + 质量统计。"""
    lines = [l for l in (text or "").splitlines() if l.strip()]
    if not lines:
        return {"ok": False, "error": "没有内容"}
    n_ok, n_bad = 0, 0
    schemas = {"alpaca": 0, "sharegpt": 0, "messages": 0, "unknown": 0}
    lens = []
    seen = set()
    dup = 0
    too_long = 0
    empty_out = 0
    sample_bad = ""
    for ln in lines[:20000]:
        try:
            obj = json.loads(ln)
        except json.JSONDecodeError:
            n_bad += 1
            if not sample_bad:
                sample_bad = ln[:120]
            continue
        n_ok += 1
        if isinstance(obj, dict):
            if "instruction" in obj and ("output" in obj or "response" in obj):
                schemas["alpaca"] += 1
                text_all = str(obj.get("instruction", "")) + str(obj.get("input", "")) + str(obj.get("output", ""))
                if not str(obj.get("output", obj.get("response", ""))).strip():
                    empty_out += 1
            elif "conversations" in obj:
                schemas["sharegpt"] += 1
                text_all = json.dumps(obj.get("conversations"), ensure_ascii=False)
            elif "messages" in obj:
                schemas["messages"] += 1
                text_all = json.dumps(obj.get("messages"), ensure_ascii=False)
            else:
                schemas["unknown"] += 1
                text_all = json.dumps(obj, ensure_ascii=False)
        else:
            schemas["unknown"] += 1
            text_all = str(obj)
        L = len(text_all)
        lens.append(L)
        if L > 12000:
            too_long += 1
        key = text_all[:300]
        if key in seen:
            dup += 1
        seen.add(key)
    import statistics
    total_chars = sum(lens)
    est_tokens = int(total_chars / 2.2)  # 中英混合粗估
    warnings = []
    if dup:
        warnings.append("发现 %d 条疑似重复样本，建议去重" % dup)
    if too_long:
        warnings.append("%d 条样本超过 12k 字符，会拖慢训练并稀释梯度" % too_long)
    if empty_out:
        warnings.append("%d 条样本输出为空" % empty_out)
    if schemas["unknown"] and (schemas["alpaca"] + schemas["sharegpt"] + schemas["messages"]) == 0:
        warnings.append("未识别到 alpaca/sharegpt/messages 任何标准结构，请检查字段名")
    if n_bad:
        warnings.append("%d 行不是合法 JSON" % n_bad)
    if n_ok < 200:
        warnings.append("样本量 %d 偏少：风格/格式类 ≥500 条，知识类 ≥2000 条效果更稳" % n_ok)
    return {
        "ok": True, "total": len(lines), "valid": n_ok, "bad_json": n_bad,
        "schemas": schemas, "dup": dup, "too_long": too_long, "empty_output": empty_out,
        "avg_chars": int(statistics.mean(lens)) if lens else 0,
        "max_chars": max(lens) if lens else 0,
        "est_tokens": est_tokens,
        "warnings": warnings,
        "splits": "建议切分 train %.0f%% / eval %.0f%%（至少 50 条验证集）" % (95, 5) if n_ok >= 1000 else "建议切分 train 90% / eval 10%",
    }


def train_script_generate(body):
    fw = body.get("framework") or "unsloth"
    book = next((p for p in TRAIN_PLAYBOOKS if p["id"] == fw), None)
    if not book:
        return {"ok": False, "error": "未知框架"}
    model = body.get("model") or "Qwen/Qwen2.5-7B-Instruct"
    dataset = body.get("dataset") or "train.jsonl"
    epochs = int(body.get("epochs") or 3)
    lr = body.get("lr") or ("2e-4" if fw in ("unsloth", "trl-peft") else "5e-5")
    header = (
        "# ===== Avenger 训练配方（%s）=====\n"
        "# 基座: %s | 数据: %s | epochs: %d | lr: %s\n"
        "# 工作流: 备数据 → 校验(Avenger 数据集校验器) → 训练 → 盲测 → 合并导出 GGUF\n\n"
        % (book["name"], model, dataset, epochs, lr)
    )
    code = header + book["code"]
    export_hint = (
        "\n\n# ===== 部署衔接 =====\n"
        "# 合并 LoRA 后导出 GGUF:\n"
        "#   python convert_hf_to_gguf.py ./merged --outfile model-q4km.gguf --outtype q4_k_m  (llama.cpp)\n"
        "#   或 Unsloth: model.save_pretrained_gguf('out', tokenizer, quantization_method='q4_k_m')\n"
        "# 运行: llama-server -m model-q4km.gguf -c 4096 -ngl 999 --port 8080\n"
        "# Avenger AI 工坊 → 自定义 → http://127.0.0.1:8080/v1/chat/completions 即刻接入你自己的模型"
    )
    return {"ok": True, "framework": book["name"], "script": code + export_hint, "filename": "train_%s.py" % fw if fw != "llamafactory" else "train_lora.yaml"}


# ============================================================
# 8. AI-IDE 配置生成（CLAUDE.md / AGENTS.md / .cursorrules / copilot）
# ============================================================

def ide_generate(body):
    kind = body.get("kind") or "claude-md"
    scan = context_scan(body.get("path") or ".") if (body.get("path")) else {"languages": [], "frameworks": [], "files": 0, "loc": 0}
    langs = ", ".join(l for l, _ in scan.get("languages", [])[:5]) or "未知"
    stacks = ", ".join(scan.get("frameworks", [])) or "未检测到"
    build = body.get("build") or ""
    test = body.get("test") or ""
    style = body.get("style") or "遵循现有代码风格；改动最小化；不做无关重构。"
    name = (scan.get("path") and Path(scan["path"]).name) or "项目"
    if kind == "claude-md":
        title, bodytext = "CLAUDE.md", (
            "# %s — 项目指南\n\n## 技术栈\n- 语言: %s\n- 线索: %s\n\n## 常用命令\n%s\n%s\n\n## 约定\n%s\n\n## 边界\n- 不要提交密钥；不要动 .env；依赖变更必须说明理由。\n"
            % (name, langs, stacks,
               ("- 构建: `%s`" % build) if build else "- 构建: （补充）",
               ("- 测试: `%s`" % test) if test else "- 测试: （补充）",
               style))
    elif kind == "agents-md":
        title, bodytext = "AGENTS.md", (
            "# AGENTS.md\n\n%s 是一个 %s 项目（%s）。\n\n## 工作规则\n1. %s\n2. 修改前先阅读相关模块；改动保持聚焦，一个 PR 一个主题。\n3. 提交信息用 `type(scope): summary` 祈使句。\n4. 测试优先：修复必须带回归测试。\n%s\n"
            % (name, langs, stacks, style, ("- 验证命令: `%s`" % test) if test else ""))
    elif kind == "cursorrules":
        title, bodytext = ".cursorrules", (
            "You are working on %s (%s; %s).\n\nRules:\n- %s\n- Prefer minimal diffs; match existing naming and file layout.\n- Never invent APIs; check imports before use.\n- Run `%s` before claiming done.\n"
            % (name, langs, stacks, style, test or "the test command"))
    else:  # copilot
        title, bodytext = ".github/copilot-instructions.md", (
            "# Copilot Instructions\n\n## 项目\n%s：语言 %s；%s。\n\n## 代码风格\n%s\n\n## 验证\n%s\n"
            % (name, langs, stacks, style, ("- `%s`" % test) if test else "- （补充测试命令）"))
    return {"ok": True, "kind": kind, "filename": title, "content": bodytext}


# ============================================================
# 9. V5.1 模型库（对标 FreeToken / LM Studio 的模型目录）
# ============================================================

MODEL_CATALOG = [
    dict(family="Qwen3-235B-A22B", org="Alibaba Qwen", params=235, ctx=131072, tags=["CHAT", "MoE"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="qwen3:235b-q4_K_M"),
                   dict(label="Q3_K_M", fmt="GGUF", bpw=0.48, ollama="qwen3:235b")]),
    dict(family="Qwen3-32B", org="Alibaba Qwen", params=32, ctx=131072, tags=["CHAT", "FTW"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="qwen3:32b"),
                   dict(label="Q8_0", fmt="GGUF", bpw=1.06, ollama="qwen3:32b-q8_0")]),
    dict(family="Qwen3-14B", org="Alibaba Qwen", params=14, ctx=131072, tags=["CHAT"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="qwen3:14b"),
                   dict(label="Q8_0", fmt="GGUF", bpw=1.06, ollama="qwen3:14b-q8_0"),
                   dict(label="BF16", fmt="safetensors", bpw=2.0, ollama="qwen3:14b-fp16")]),
    dict(family="Qwen3-8B", org="Alibaba Qwen", params=8, ctx=131072, tags=["CHAT"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="qwen3:8b"),
                   dict(label="BF16", fmt="safetensors", bpw=2.0, ollama="qwen3:8b-fp16")]),
    dict(family="Qwen2.5-Coder-7B", org="Alibaba Qwen", params=7, ctx=32768, tags=["CODE"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="qwen2.5-coder:7b"),
                   dict(label="Q8_0", fmt="GGUF", bpw=1.06, ollama="qwen2.5-coder:7b-q8_0")]),
    dict(family="DeepSeek-R1-Distill-32B", org="DeepSeek", params=32, ctx=65536, tags=["REASON"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="deepseek-r1:32b"),
                   dict(label="Q8_0", fmt="GGUF", bpw=1.06, ollama="deepseek-r1:32b-q8_0")]),
    dict(family="DeepSeek-R1-Distill-7B", org="DeepSeek", params=7, ctx=32768, tags=["REASON"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="deepseek-r1:7b")]),
    dict(family="Llama-3.3-70B", org="Meta", params=70, ctx=131072, tags=["CHAT"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="llama3.3:70b"),
                   dict(label="Q3_K_M", fmt="GGUF", bpw=0.48, ollama="llama3.3:70b-q3_K_M")]),
    dict(family="Llama-3.1-8B", org="Meta", params=8, ctx=131072, tags=["CHAT"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="llama3.1:8b"),
                   dict(label="BF16", fmt="safetensors", bpw=2.0, ollama="llama3.1:8b-fp16")]),
    dict(family="GLM-4-9B", org="Zhipu AI", params=9, ctx=131072, tags=["CHAT"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="glm4:9b")]),
    dict(family="Phi-4", org="Microsoft", params=14, ctx=16384, tags=["CHAT", "REASON"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="phi4")]),
    dict(family="Gemma-3-27B", org="Google", params=27, ctx=131072, tags=["CHAT"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="gemma3:27b")]),
    dict(family="Mistral-Nemo-12B", org="Mistral AI", params=12, ctx=131072, tags=["CHAT"],
         variants=[dict(label="Q4_K_M", fmt="GGUF", bpw=0.60, ollama="mistral-nemo")]),
]


def _ollama_tags():
    """探测本机 Ollama 已下载模型（2s 超时，未运行返回 None）。"""
    try:
        from urllib.request import urlopen
        with urlopen("http://127.0.0.1:11434/api/tags", timeout=2) as r:
            data = json.loads(r.read().decode("utf-8", "replace"))
        return [str(m.get("name") or "") for m in data.get("models", [])]
    except Exception:
        return None


def _arch_for(params):
    for k in sorted(LLM_ARCH.keys(), key=lambda x: float(x[:-1])):
        if float(k[:-1]) >= params:
            return LLM_ARCH[k]
    return LLM_ARCH["70B"]


def model_catalog(vram_gb, ram_avail_gb, ctx_k=8):
    """为每个变体计算体积/显存预估/三态状态：fit(显存充裕) / partial(可内存卸载) / nofit(显存不足)；并标记 Ollama 已下载。"""
    ollama = _ollama_tags()
    out = []
    for fam in MODEL_CATALOG:
        arch = _arch_for(fam["params"])
        variants = []
        for v in fam["variants"]:
            size_gb = round(fam["params"] * v["bpw"] * 1.08, 1)
            kv_gb = arch["layers"] * KV_BYTES_PER_TOKEN_PER_LAYER * arch["kv_dim"] * ctx_k * 1000 / (1024 ** 3)
            vram_est = round(fam["params"] * v["bpw"] + kv_gb + 0.6, 1)
            if vram_est <= vram_gb * 0.94:
                status = "fit"
            elif vram_est <= vram_gb * 0.94 + max(ram_avail_gb - 4, 0) * 0.8:
                status = "partial"
            else:
                status = "nofit"
            downloaded = False
            if ollama:
                base = v["ollama"].split(":")[0]
                for o in ollama:
                    if o == v["ollama"] or (o.startswith(base + ":") and base in v["ollama"]):
                        downloaded = True
                        break
            variants.append(dict(label=v["label"], fmt=v["fmt"], size_gb=size_gb, vram_est=vram_est,
                                 status=status, ollama=v["ollama"], downloaded=downloaded))
        out.append(dict(family=fam["family"], org=fam["org"], params=fam["params"], ctx=fam["ctx"],
                        tags=fam["tags"], variants=variants))
    return out


# ============================================================
# 10. V5.1 AI 使用量追踪 + 使用统计（对标 Claude Code Usage）
# ============================================================

def _usage_db(base_dir):
    conn = sqlite3.connect(str(Path(base_dir) / "avenger_notes.db"), timeout=8)
    conn.execute("CREATE TABLE IF NOT EXISTS ai_usage("
                 "id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, provider TEXT, model TEXT, "
                 "prompt_chars INTEGER, completion_tokens INTEGER)")
    conn.commit()
    return conn


def usage_add(base_dir, provider, model, prompt_chars, completion_tokens):
    try:
        with _MEM_LOCK:
            conn = _usage_db(base_dir)
            conn.execute("INSERT INTO ai_usage(ts,provider,model,prompt_chars,completion_tokens) VALUES(?,?,?,?,?)",
                         (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), (provider or "?")[:40], (model or "?")[:80],
                          int(prompt_chars or 0), int(completion_tokens or 0)))
            conn.commit()
            conn.close()
    except Exception:
        pass
    return {"ok": True}


def usage_summary(base_dir):
    from collections import Counter
    days = Counter()
    hours = Counter()
    models = Counter()
    total_tokens = 0
    total_msgs = 0
    with _MEM_LOCK:
        try:
            conn = _usage_db(base_dir)
            rows = conn.execute("SELECT ts,provider,model,completion_tokens FROM ai_usage").fetchall()
            conn.close()
        except Exception:
            rows = []
    for ts, provider, model, toks in rows:
        d = str(ts)[:10]
        days[d] += 1
        try:
            hours[str(ts)[11:13]] += 1
        except Exception:
            pass
        models[(provider or "?", model or "?")] += 1
        total_msgs += 1
        total_tokens += int(toks or 0)
    try:
        log = Path(base_dir) / "avenger_operations.log"
        if log.exists():
            for ln in log.read_text(encoding="utf-8", errors="replace").splitlines()[-4000:]:
                m = re.match(r"\[(\d{4}-\d{2}-\d{2}) ", ln)
                if m:
                    days[m.group(1)] += 1
    except Exception:
        pass

    def streaks(dset):
        from datetime import date, timedelta
        if not dset:
            return 0, 0
        def to_d(s):
            y, m, dd = s.split("-")
            return date(int(y), int(m), int(dd))
        today = date.today()
        cur = 0
        check = today if today.strftime("%Y-%m-%d") in dset else today - timedelta(days=1)
        while check.strftime("%Y-%m-%d") in dset:
            cur += 1
            check -= timedelta(days=1)
        longest = 0
        run = 0
        prev = None
        for s in sorted(dset):
            dcur = to_d(s)
            run = run + 1 if (prev is not None and (dcur - prev).days == 1) else 1
            longest = max(longest, run)
            prev = dcur
        return cur, longest

    active_days = sorted(days.keys())
    cur_streak, long_streak = streaks(set(active_days))
    peak = max(hours.items(), key=lambda x: x[1])[0] + ":00" if hours else "—"
    fav = models.most_common(1)[0][0][1] if models else "—"
    from datetime import date, timedelta
    today = date.today()
    heat = []
    for i in range(118, -1, -1):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        heat.append({"date": d, "count": days.get(d, 0)})
    return {
        "sessions": len(active_days),
        "messages": total_msgs,
        "total_tokens": total_tokens,
        "active_days": len(active_days),
        "current_streak": cur_streak,
        "longest_streak": long_streak,
        "peak_hour": peak,
        "favorite_model": fav,
        "top_models": [[m[1], c] for m, c in models.most_common(5)],
        "heatmap": heat,
    }


# ============================================================
# 11. V5.1 数据集登记库（微调"数据库"闭环）
# ============================================================

def _ds_db(base_dir):
    conn = sqlite3.connect(str(Path(base_dir) / "avenger_notes.db"), timeout=8)
    conn.execute("CREATE TABLE IF NOT EXISTS train_datasets("
                 "id TEXT PRIMARY KEY, name TEXT, path TEXT, samples INTEGER, est_tokens INTEGER, "
                 "tags TEXT, note TEXT, created TEXT)")
    conn.commit()
    return conn


def ds_register(base_dir, body):
    name = (body.get("name") or "").strip()[:80]
    if not name:
        return {"ok": False, "error": "数据集名称不能为空"}
    did = uuid.uuid4().hex[:10]
    with _MEM_LOCK:
        conn = _ds_db(base_dir)
        conn.execute("INSERT INTO train_datasets(id,name,path,samples,est_tokens,tags,note,created) VALUES(?,?,?,?,?,?,?,?)",
                     (did, name, (body.get("path") or "")[:400], int(body.get("samples") or 0),
                      int(body.get("est_tokens") or 0), (body.get("tags") or "")[:120],
                      (body.get("note") or "")[:200], datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        conn.commit()
        conn.close()
    return {"ok": True, "id": did}


def ds_list(base_dir):
    with _MEM_LOCK:
        conn = _ds_db(base_dir)
        rows = conn.execute("SELECT id,name,path,samples,est_tokens,tags,note,created FROM train_datasets ORDER BY created DESC").fetchall()
        conn.close()
    return [{"id": r[0], "name": r[1], "path": r[2], "samples": r[3], "est_tokens": r[4],
             "tags": r[5] or "", "note": r[6] or "", "created": r[7] or ""} for r in rows]


def ds_delete(base_dir, did):
    with _MEM_LOCK:
        conn = _ds_db(base_dir)
        conn.execute("DELETE FROM train_datasets WHERE id=?", (did,))
        conn.commit()
        conn.close()
    return {"ok": True}
