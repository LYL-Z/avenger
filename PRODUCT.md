# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Existing: Python stdlib `http.server` backend (avenger_server.py + avenger_studio.py + avenger_hud.py) + single-file vanilla HTML/CSS/JS frontend (avenger.html). Zero third-party Python deps. V4.0 loads tsParticles dynamically (CDN) with a built-in canvas particle fallback; all other frontend remains vanilla.

## Users

Full-stack developers on Windows 10/11 who manage multiple Python environments and seek unified control over their entire local dev toolchain — languages, databases, processes, hardware — plus AI assistant access, kata practice, notes, and cheatsheets in one lightweight local dashboard.

## Product Purpose

Evolve from a Python environment manager into a one-stop local developer workstation control hub. Manage Python envs (core), other language runtimes, databases, dev tools, system hardware, and health — all visualized through a premium Liquid Glass interface, extended with an AI workshop (18 OpenAI-compatible providers, streaming), a 26-kata practice platform, SQLite notes, and an 18-sheet cheat library. Goal: make programming more convenient, safe, and healthy.

## Positioning

JetBrains Toolbox + mise + DevToys + LeetCode-lite + Obsidian-lite + local hardware monitor in a single zero-dependency local web app, with an iOS 26/visionOS Liquid Glass UI that outclasses every competing dev tool visually.

## Operating Context

- Local-only, offline-capable, no cloud dependency, no data collection
- Launched via `一键启动Avenger.bat` which starts Python backend (hidden) and opens browser
- A tkinter "托管" mini-window keeps the service alive after the browser closes; closing the mini-window stops the service
- Backend on 127.0.0.1:8765 (auto-increment if occupied)
- Python 3.8+ compatibility required
- BAT fallback script (PythonEnvManager.bat) always available

## Capabilities and Constraints

**Core (Python):** env scanning (parallel, ~3-6x faster), package management with virtual scrolling, dependency tree, version switching, conflict diagnosis, one-click fix with backup/rollback, health scoring, PATH drag-reorder, env clone, multi-env compare, cache management, requirements export, snapshots, OSV security scan.

**V4.0 additions:**
- Dashboard instant-open: snapshot cache + parallel data fetch + targeted DOM updates; particle script no longer render-blocking; canvas fallback particles
- AI workshop: streaming chat (backend SSE relay → plain-text chunked stream), 18 OpenAI-compatible providers (incl. Ollama/LM Studio local, DeepSeek, Qwen, GLM, Kimi, Gemini, OpenAI, Groq, xAI…), 6 expert roles, temperature, history, test-connection
- Dojo: 26 katas with difficulty/topic filters, solved-set progress ring, daily streak, daily challenge, drafts, timer, local isolated judging
- Notes: SQLite store, search, tag filter, pin, markdown preview, Ctrl+S, JSON import/export
- Learn: 18 cheatsheets with search + copy
- Skins: 12 curated glass skins (accent + ambient blobs) + custom accent picker; synced to HUD pet
- Pets: 10 desktop pets with speech bubbles, drag-to-position (remembered), hide toggle
- Performance settings: particle density (off/low/mid/high), glass quality (full/lite/off)
- Robustness: log rotation, job GC, strict package-name validation (anti pip-arg injection), cache-purge path whitelist, residual-delete traversal guard, graceful body-parsing errors, catch-all 500 handler

**Constraints:** 60fps performance floor, responsive, light/dark themes, keyboard nav, a11y baseline.

## Brand Commitments

- Name: Avenger
- Accent color: warm orange (default "余烬" skin, refined)
- Visual language: Apple iOS 26/visionOS Liquid Glass + Claude Code minimalism + HarmonyOS refinement
- Typography: Source Han Serif SC (serif headings) + SF Mono (code/data)
- Zero third-party Python dependencies; local-only

## Evidence on Hand

- V3.x codebase fully migrated to V4.0: avenger_server.py, avenger_studio.py, avenger_hud.py, avenger.html
- User machine: 5-6 Python environments / 700+ packages, RTX 5090 laptop, Windows 11
- liquid-glass-react reference (rdev/liquid-glass-react): displacementScale=70, blurAmount=0.0625, saturation=140, aberrationIntensity=2, elasticity=0.15

## Product Principles

1. **Python is the bedrock** — every new module must not compromise core Python env management
2. **Performance is non-negotiable** — visual effects never block function; 60fps floor; first paint first
3. **Local and private** — zero telemetry, zero cloud, works offline; AI keys stay in local file
4. **Safety first** — all destructive actions require confirmation + auto-backup + undo
5. **Plugin-ready** — core stays lean, features extend through plugin architecture
