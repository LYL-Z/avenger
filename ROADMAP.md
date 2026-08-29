# Avenger Roadmap — 通往 V7.0 的宏伟计划

> 定位跃迁：从「本地开发者工作台」→ **「Local-First AI Agent 操作系统」**
> 一句话愿景：**Ollama 之于本地大模型 = Avenger 之于本地 Agent 工作台**——零依赖、纯本地、液态玻璃质感的开发者超级入口。

四项战略决策（已确认）：
① Agent 内核 + Web/CLI 双形态；② 技能库 = 社区聚合 + AI 生成混合；③ 桌面 = pywebview + GitHub 登录；④ 增长 = 先内功后发布。

---

## Phase 1 — V6.0「Horizon」：Agent 内核 + 3D 视觉革命（3-4 周）

### 1.1 avenger_core：自研 Agent 内核（分支核心启动）
对标 Codex CLI / Claude Code / OpenHands / Aider / Cline 的**纯标准库事件驱动内核**：

| 组件 | 设计 | 对标 |
|------|------|------|
| 事件循环 | `Session → Event Store(SQLite, append-only) → Loop(thought/tool_call/observation) → Checkpoint`，可回放可分叉 | OpenHands 事件驱动 |
| 工具注册表 | 装饰器注册 + JSON Schema 自动生成；**内置 MCP Client**（可挂接全生态任意 MCP 服务器——与顶尖 Agent 互操作的关键） | Cline/Goose |
| 上下文引擎 | repo-map（树状摘要+符号索引）+ Context Pack + 分层记忆（工作/情景/语义三级） | Aider repo-map |
| 执行沙箱 | 受限 subprocess：白名单命令、路径越界防护、超时/输出上限、dry-run 预览+人工确认门 | Codex sandbox |
| 双模式 | Plan（只读调研产出计划）→ Act（凭批准执行）→ Review（diff 审查） | Cline plan/act |
| 多 Agent | Planner / Coder / Reviewer 角色化子代理 + 消息总线 | Claude Code 子代理 |
| 模型层 | 已有 18 家 OpenAI 兼容供应商 + Ollama/llama.cpp + 任意 base_url，按任务路由模型（贵模型规划/便宜模型执行） | — |

**交付形态（双形态共享内核）**：
- **Web**：Agent 会话工作台（独有创新：**可视化轨迹瀑布图**——每步 thought/tool/耗时/成本可展开回放，Codex CLI 没有的能力）；
- **CLI**：`avenger "任务"` 单文件入口（同 codex/aider 体验），复用 REST 内核，支持流式 TUI。

**创新差异化（为何能赢）**：Agent 直接调用**工作台全部工具**（环境管理/包管理/模型库/诊断/手机端督工）——没有任何竞品的 Agent 能帮你切 Python 版本、拉模型、看 GPU 显存后再决定量化方案。

### 1.2 3D 视觉引擎（彻底去 AI 味）
- **Three.js 动态加载**（CDN + 无 WebGL 自动降级 CSS 星云，沿用粒子双引擎模式）：
  - 3D 液态玻璃背景层（折射光斑随模块切换变形）；
  - **3D 分子查看器**（化学套件）、**3D 拉伸姿态**（健康模块）、**3D 宠物**（现有 2D 宠物的空间化升级）；
  - 模块切换 3D 转场（深度推拉 + 玻璃折射）。
- 设计自主化：建立 **Avenger Design Tokens**（节奏/材质/光效三层规范文档），所有组件从 tokens 生成，形成可辨识的专属设计语言（对标 Apple HIG / HarmonyOS 设计规范的文档化路径）。

### 1.3 全场景动画清单（Anime.js v4 编排）
开机序列（升级为 3D 粒子汇聚 Logo）→ 模块切换（shared-element + 3D 转场）→ **图表线描动画**（stroke-dashoffset path reveal）→ 终端打字机 → 命令面板弹性 → 数字滚动 → 热力图错落 → **关闭/退出动画**（页面玻璃碎裂渐隐）→ 宠物全套动作（ idle/poke/drag/睡觉）。

### 1.4 领域科学套件一期（零依赖优先，重库可选 pip）
| 领域 | V6.0 内置（纯前端/标准库） | 可选扩展 |
|------|---------------------------|----------|
| 数学 | LaTeX 渲染(KaTeX CDN)、单位换算、函数绘图 canvas、矩阵/统计计算器 | SymPy 网关（检测到即启用符号计算） |
| 化学 | 周期表（118 元素全数据内置）、分子量计算、化学方程式配平 | 3D 分子（Three.js + 3Dmol） |
| 生物 | DNA↔RNA↔蛋白质翻译、反向互补、GC 含量、碱基统计 | Biopython 网关 |
| 物理 | 常数表、运动学/能量求解器 canvas 可视化 | — |
| 历史 | 时间线生成器 + AI 辅助脉络梳理 | — |

---

## Phase 2 — V6.5「Marketplace + Desktop」：技能市场 + 桌面 App + 增长引信（4-6 周）

### 2.1 Skills 市场（1000+ 路线，聚合+生成混合）
- **聚合引擎**：抓取索引 agentskills.io 生态、awesome-claude-skills、anthropics/skills、社区 SKILL.md 仓库 → 统一 schema 归一化 → 星标/更新时间/下载量评分排序；
- **生成管线**：按领域模板（数学/物理/化学/生物/运维/写作/数据…）用已接入的 AI 批量生成初稿 → 规则校验（frontmatter 合法性、长度、示例完备度）→ 人工审核标记；
- **市场 UI**：分类/搜索/评分/一键安装到 `~/.avenger/skills`，与现有技能库/组合包/Agent 内核全打通。

### 2.2 桌面 App（pywebview + GitHub 登录）
- `avenger_app.py`：pywebview 壳加载本地服务（复用 100% 后端），PyInstaller 打包（干净 venv，目标 30-80MB，附启动速度/内存对比 benchmark 页——对 Electron 系的差异化证据）；
- **GitHub OAuth 登录**：设备码流程（零回调服务器）→ 桌面内一键 Star、偏好/记忆经**私有 Gist 加密同步**（跨设备无缝接续）、Issue 一键反馈、README 贡献者墙；
- 托管小窗升级为系统托盘（tray + 通知）。

### 2.3 增长引信（先内功后发布）
- 发布前 checklist：英文为主 README（180M 开发者市场）+ GIF 演示 + 中英双语、benchmark 对比页、Trendshift/OSSInsight 徽章、中英双语文档站；
- 发布节奏：**Show HN（周二-四 7-9AM EST）+ Reddit r/LocalLLaMA r/selfhosted + 掘金/V2EX 同步**，协调初始 30-40 star 突发启动 Trending 速度算法（deviation-from-baseline）；
- 目标阶梯：发布周 500 star → 3 个月 2K → 6 个月 5K（对标 Daytona 首周 4K 案例的执行密度，而非刷量——fake star 检测已普及，真实 velocity 才可持续）。

---

## Phase 3 — V7.0「Constellation」：多 Agent 协作 + 全行业互联（长期）

- **多 Agent 编排**：可视化流程画布（DAG 拖拽），Planner/Worker/Reviewer 流水线模板市场；
- **全行业 Agent 互通**：ACP（Agent Client Protocol）服务端暴露——OpenHands SDK/Cline 等可直接驱动 Avenger；MCP 双向（已具备 Server，补 Client 后全生态工具即插即用）；
- **领域套件二期**：物理仿真（N 体/电路）、化学平衡/热力学、生物序列比对、历史地图时间轴；
- **WebGPU 渲染管线**（Three.js WebGPU 后端）：玻璃折射实时渲染、10 万粒子；
- **可选云同步服务**（开源 server，可自托管）：团队技能包共享、Agent 轨迹回放分享链接（增长飞轮：每条分享链接都是产品展示）。

---

## 里程碑与验收

| 阶段 | 时间 | 验收标准 |
|------|------|----------|
| V6.0 | 3-4 周 | Agent 完成 10 类真实任务（建项目/修 bug/切环境/拉模型）；CLI 单文件可用；3D 层 60fps；5 个领域工具上线 |
| V6.5 | +4-6 周 | 技能市场 ≥1000 条可安装；桌面安装包双击可用；GitHub 登录打通；发布周 Trending ≥1 次 |
| V7.0 | 长期 | 多 Agent 模板市场；被 ≥3 个第三方 Agent 客户端接入；WebGPU 管线落地 |

## 风险与对策
- **范围膨胀**（最大风险）：每阶段只做「内核深度 × 一个体验杀手锏」，领域套件坚持零依赖优先；
- **1000 技能质量**：聚合源白名单 + 规则校验 + 人工审核标记三道闸；
- **桌面打包体积**：干净 venv + Nuitka 备选；benchmark 页把"解释器税"转化为启动速度叙事；
- **单文件前端复杂度**：V6.0 起引入构建期拼接（仍是零运行时依赖，源码按模块拆分文件，发布时拼合为单文件）。
