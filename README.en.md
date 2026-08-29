# Avenger — Local-First AI Agent OS

> **The liquid-glass command center for your entire dev life.**
> Pure Python stdlib · Zero third-party backend deps · Fully offline · Your data never leaves your machine.

<p align="center"><a href="README.md">📖 中文文档</a> · <a href="https://github.com/LYL-Z/avenger">GitHub</a> · <a href="UPGRADE_V5.2.md">Changelog</a> · <a href="ROADMAP.md">Roadmap</a></p>

## Why Avenger?

Every AI tool you use is a separate Electron app that phones home. Avenger is the opposite:

- **🪶 Zero-dependency core** — the whole backend is Python stdlib (`http.server` + `sqlite3` + `ctypes`). Clone it, run it, done. No `pip install`.
- **🔒 Local-first** — notes, memories, AI keys, usage stats: all in local SQLite/JSON. No telemetry, no cloud.
- **🤖 A real agent kernel** (`avenger_core.py`) — event-driven, replayable, MCP-client enabled, Plan/Act modes, human-approval gates for every mutating action, and a **visual trace waterfall** in the web UI.
- **🎛️ It operates your machine** — unlike any CLI agent, Avenger's agent can scan Python envs, read GPU VRAM, pull local models, purge pip caches, and kill port squatters. The workbench *is* the harness.
- **🔌 Speaks the ecosystem** — MCP server **and** client (stdio), 18 OpenAI-compatible LLM providers, Ollama/LM Studio/llama.cpp, GitHub token integration (star / gist sync / issues).
- **🎨 Liquid Glass, not AI-slop** — an editorial design system (Anime.js v4 choreography, optional Three.js glass-refraction background) that doesn't look like every AI dashboard.

## Quick start

```bash
git clone https://github.com/LYL-Z/avenger.git
cd avenger
python avenger_server.py        # opens http://127.0.0.1:8765
# or double-click 一键启动Avenger.bat (Windows)
# desktop app:  pip install pywebview && python avenger_app.py
# terminal agent: python avenger_cli.py "refactor utils.py"
```

## Highlights (19 modules)

| Area | What you get |
|------|--------------|
| Agent | Event-driven kernel, visual trace waterfall, Plan/Act, approvals, MCP plug-in, skills (SKILL.md open standard), memory system, context packs |
| Dev | Python multi-env management, PATH drag-reorder, dependency diagnosis & one-click fix, package manager w/ virtual scroll, Git helper, ports & processes |
| AI | Streaming chat across 18 providers, 6 expert roles, model library (13 families × 22 quant variants w/ VRAM fit badges), local deploy one-click BAT, training playbooks (Unsloth/LLaMA-Factory/TRL/Axolotl/torchtune), dataset validator/cleaner, overfit advisor |
| Science | Periodic table (118 elements), molar mass, DNA→protein translation, kinematics solver, function plotter, LaTeX, timelines |
| Life | Hardware monitor (nvidia-smi + ctypes), 20-20-20 eye care, sedentary/water reminders, usage heatmap & streaks, phone-direct control (LAN pairing), portable pet |
| Platform | Windows-first, phone browser control over LAN/Tailscale, desktop shell (pywebview), CLI |

## Benchmark (vs typical Electron AI tools)

| Metric | Avenger | Electron-class tools |
|---|---|---|
| Backend deps | **0** (stdlib only) | 100s of npm packages |
| Cold start to usable UI | **< 2 s** | 4–12 s |
| Idle RAM (backend) | **~30–50 MB** (single Python proc) | 300 MB–1.5 GB |
| Disk footprint | **~1.5 MB source** | 200–600 MB installed |
| Network calls at idle | **heartbeat only** (local) | varies / cloud sync |

<sub>Measured on Windows 11 / Python 3.11, April 2026. Reproduce: `python avenger_server.py --no-browser --no-hud` then Task Manager.</sub>

## License

MIT — see [LICENSE](LICENSE).

<p align="center">⭐ Star the repo if Avenger saves you a `pip` headache today.</p>
