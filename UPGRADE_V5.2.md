# Avenger V5.2 升级方案与落地细则

> 本文档对应 V5.2 修复提升版：Agent 生态六模块补强 / 训练工作流闭环 / UI·UX 动效升级 / 手机直连电脑。
> 架构原则不变：零第三方 Python 依赖、单文件前端、纯本地优先。

## 一、总体架构

```
┌────────────────────────── Avenger V5.2 ──────────────────────────┐
│                                                                   │
│  avenger.html（单文件前端 · 液态玻璃 + Anime.js v4 动效编排）        │
│  ├─ 19 模块：驾驶舱/Python/运行时/包/AI工坊/Agent工坊/记忆上下文     │
│  │           模型工坊/备忘录/练习场/速查/数据库/Git/端口/硬件/健康    │
│  │           插件/设置(+手机直连)                                   │
│  └─ 动效层：choreo() 弹簧入场 · countUp 数字滚动 · popCells 错落弹入 │
│                    │ REST + SSE（同源）                             │
│  avenger_server.py（ThreadingHTTPServer · 双栈监听）                │
│  ├─ 环境扫描/包管理/诊断/硬件(nvidia-smi+ctypes)/健康/插件          │
│  ├─ AI 代理：18 供应商 · 流式 SSE 转发 · 用量入库                    │
│  ├─ Agent 生态：skills/mcp/harness/memory/context/vram/models      │
│  ├─ 训练：playbooks/validate/clean/advise/datasets/script          │
│  └─ 手机直连：LAN 0.0.0.0 ↔ 127.0.0.1 热切换 + 6位配对码换令牌       │
│                    │                                                │
│  avenger_agent.py（生态引擎） · avenger_studio.py（AI/练习/速查）    │
│  avenger_hud.py（托管小窗） · avenger_mcp_server.py（stdio MCP）     │
│  存储：avenger_notes.db(SQLite: notes/agent_memory/ai_usage/        │
│        train_datasets) + avenger_secrets.json + localStorage        │
└───────────────────────────────────────────────────────────────────┘
```

## 二、六大生态模块落地细则（v5.2 修复点）

| 模块 | v5.0 已有 | v5.2 新增/修复 |
|------|-----------|----------------|
| 1. Skills 技能库 | 12 技能 SKILL.md 标准、安装/卸载/自建、Claude 目录扫描 | **组合技能包**（多选合并为 skill-pack.md，含冲突消解规则）；移动端适配；安装路径校验防注入 |
| 2. MCP 生态 | 18 服务器目录、5 客户端配置扫描、内置 stdio Server(5 工具) | **协议补全**：resources/list + resources/read（笔记/记忆作为资源）+ prompts/list；**配置体检器**（JSON/结构/command-args 校验） |
| 3. Harness 框架 | 单文件 Python 生成器 | **双语言**（Python/Node.js）；**指数退避重试×3**；token 预算；工具结果截断；越界防护保留 |
| 4. 记忆 & 上下文 | 5 类目记忆 + Context Pack | **关联记忆**（标签+关键词重合度评分推荐）；**批量清理**（按类目/按天数）；上下文匹配精度提升 |
| 5. 本地部署/量化 | 13 模型库×22 变体、三态显存判定、Ollama 探测 | **一键部署 BAT**（检测→winget 装 Ollama→pull→run 全自动）；模型卡直出部署脚本下载 |
| 6. AI-IDE 插件 | CLAUDE.md/AGENTS.md/.cursorrules/copilot 生成 | **VS Code/Cursor 扩展脚手架**（package.json+extension.js+README，vsce package 即得 .vsix；解释/优化/审查三命令 + 快捷键） |

## 三、训练/微调/数据工作流（v5.2 闭环）

```
定目标 → 备数据 → 体检(validate) → 清洗(clean) → 登记(datasets)
   → 选配方(playbooks) → 顾问(advise:耗时+过拟合) → 显存估算
   → 生成配方(script) → 训练 → 盲测 → 导出 GGUF → 模型库部署 → AI 工坊对话
```
- **数据清洗器**：去重（前 400 字符指纹）、去空输出、截超长、剥控制符，输出统计与可直接下载的 JSONL；
- **耗时预估**：tokens = 样本×~1.2k；吞吐 ≈ GPU 有效算力×0.35 / (6×params)；QLoRA×1.15、全参×2.2；
- **过拟合顾问**：样本量×epochs 联合判定（<800×≥5 高风险 / ≥5000×≤1 欠拟合），输出早停判据与三件套对策；
- **数据集登记库**：体检结果一键登记 SQLite，训练配方直接引用，形成可迭代个人数据库。

## 四、手机直连电脑（v5.2 新增）

- **协议**：设置 →「开启局域网访问」→ 服务热切换监听 0.0.0.0（自动关闭旧套接字，防回环黑洞）；桌面端点「生成配对码」（6 位，5 分钟 TTL）；手机浏览器访问 `http://<局域网IP>:8765/`，任意写操作输入配对码 → `POST /api/pair/claim` 换取会话令牌（后续自动携带）。**手机获得与电脑完全一致的 19 模块操控权，数据同源零同步成本**。
- **稳定性设计**：配对码防暴力（5 分钟过期 + 单码单用换取后仍需令牌）；关闭 LAN 立即回到仅 127.0.0.1；Host 守卫仅在 LAN 模式放行外网段。
- **云端/跨网模式**：两端安装 Tailscale 并登录同一账号（WireGuard 端到端加密），用 Tailscale IP 替代局域网 IP，同样两步配对。无需暴露公网端口。
- **全平台**：手机端走浏览器（Android/iOS 通用），无需安装 App；Windows 为主控端，Mac/Linux 理论兼容（标准库实现，无 Win 专属启动路径的模块自动降级）。

## 五、UI/UX（v5.2）

- **开机动画**：Logo 弹入（旋转+缩放弹簧）+ 品牌字浮现 + 进度条扫光，1.25s 自动淡出（每会话一次，`sessionStorage` 控制）；
- **动效引擎**：Anime.js **v4**（animejs.com 新 API `animate/stagger/ease`），内置 v4/v3 双版本适配器与无网络 CSS 降级；
- **多分辨率**：≤720px 台账行转流式布局、统计行紧凑化、量化卡双列、masthead 字号降档——修复小屏溢出；
- **去 AI 味**：编辑部式 masthead、发丝线台账、非对称栅格（V5.0 引入）继续深化，本轮修复视觉错位类问题（转义破坏的模板、动效降级计数器停 0 等）。

## 六、v5.0→v5.2 Bug 修复清单（摘要）

1. 粒子/Anime CDN 加载失败时计数器停在 0 → 降级路径补齐直出；
2. LAN 热切换后回环请求黑洞（旧套接字未 close）→ `server_close()` 强制释放；
3. 模型按钮引号嵌套导致的运行时语法错误 → 统一转义规范并全局归一化；
4. 请求体非 UTF-8 导致断连 → 优雅忽略（V4 引入，本轮回归验证）；
5. 记忆无清理手段 → 类目/天数双维度批量清理 + 操作日志留痕；
6. MCP 协议缺 resources/prompts → 补全，客户端可浏览笔记/记忆资源；
7. 训练"耗时未知、效果不可判" → 耗时公式 + 过拟合风险分级 + 早停判据。

## 七、验证记录

- 全部 Python 模块 `py_compile` 通过；前端整脚本 `node --check` 通过；
- 端点实测：模型库(13 家族/22 变体/三态判定)、使用统计(热力图)、数据集登记、技能组合包、部署 BAT、训练顾问、数据清洗、IDE 扩展、记忆关联/清理、MCP resources；
- 手机直连实测：LAN 开启 → 回环与局域网双 200 → 配对码签发 → claim 换取 43 位令牌成功 → 关闭恢复仅本机。
