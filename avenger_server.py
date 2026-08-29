#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
============================================================
  Avenger V4.0 全栈开发者全景工作台 后端服务
  纯 Python 标准库实现, 零第三方依赖
  兼容: Windows 10/11, Python 3.8+
============================================================
"""

import argparse
import ctypes
import http.server
import json
import os
import sys
import subprocess
import threading
import time
import uuid
import re
import glob
import shutil
import socket
import platform
import zipfile
import sqlite3
import secrets
import ipaddress
from ctypes import wintypes
from pathlib import Path
from urllib.parse import urlparse, parse_qs
from urllib.request import Request, urlopen
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

try:
    import avenger_studio as studio
except ImportError:
    studio = None

# Windows 专属模块
try:
    import winreg
except ImportError:
    winreg = None

# ============================================================
#  全局配置
# ============================================================
HOST = "127.0.0.1"
PORT = 8765
BASE_DIR = Path(__file__).resolve().parent
LOG_FILE = BASE_DIR / "avenger_operations.log"
BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(exist_ok=True)
TOKEN_FILE = BASE_DIR / "avenger.token"
SESSION_TOKEN = secrets.token_urlsafe(32)
MAX_BODY = 10 * 1024 * 1024
WATCHDOG_SEC = 90
CACHE_META = BASE_DIR / "avenger_cache_meta.json"
UI_PREFS_FILE = BASE_DIR / "avenger_ui.json"

# 线程锁
_lock = threading.Lock()
_jobs = {}
_last_heartbeat = time.time()
_http_server = None
_overview_cache = {"t": 0, "total": 0, "human": "—"}
_undo_stack = []
UNDO_FILE = BACKUP_DIR / "undo_stack.json"
_pip_refreshing = False
_hw_refreshing = False
_lang_refreshing = False
_cpu_sample = {"t": 0, "idle": 0, "kernel": 0, "user": 0, "pct": 0.0}

# 环境缓存与扫描状态
_env_cache = []
_env_lock = threading.Lock()
_scan_status = {"scanning": False, "progress": 0, "message": "", "started": None, "finished": None}

# 包列表缓存 (避免短时间重复调用 pip list)
_pkg_cache = {}
_pkg_cache_lock = threading.Lock()
_PKG_CACHE_TTL = 30  # 秒


# ============================================================
#  工具函数
# ============================================================

def load_ui_prefs():
    try:
        return json.loads(UI_PREFS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"pet": "ember", "skin": "ember", "skinAccent": ""}


def save_ui_prefs(data):
    try:
        UI_PREFS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _rotate_log_locked():
    """日志超过 512KB 时裁剪到最近 1500 行，避免无限增长。"""
    try:
        if LOG_FILE.exists() and LOG_FILE.stat().st_size > 512 * 1024:
            lines = LOG_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
            LOG_FILE.write_text("\n".join(lines[-1500:]) + "\n", encoding="utf-8")
    except Exception:
        pass


def log_op(message):
    """记录操作日志（自动轮转）"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {message}"
    with _lock:
        _rotate_log_locked()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def run_cmd(args, timeout=120, cwd=None):
    """运行子进程命令, 返回 (returncode, stdout, stderr)"""
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=cwd,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", "命令执行超时"
    except FileNotFoundError:
        return -1, "", f"找不到可执行文件: {args[0]}"
    except Exception as e:
        return -1, "", str(e)


def run_cmd_streaming(args, job_id, timeout=600):
    """流式运行命令, 实时写入 job 输出"""
    try:
        proc = subprocess.Popen(
            args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=None,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        _jobs[job_id]["status"] = "running"
        _jobs[job_id]["pid"] = proc.pid
        for line in proc.stdout:
            with _lock:
                _jobs[job_id]["output"] += line
        proc.wait(timeout=timeout)
        with _lock:
            _jobs[job_id]["status"] = "success" if proc.returncode == 0 else "failed"
            _jobs[job_id]["returncode"] = proc.returncode
            _jobs[job_id]["done_ts"] = time.time()
    except Exception as e:
        with _lock:
            _jobs[job_id]["status"] = "failed"
            _jobs[job_id]["output"] += f"\n[错误] {e}"
            _jobs[job_id]["done_ts"] = time.time()


def _jobs_gc_loop():
    """定期清理已结束超过 30 分钟的任务，防止 _jobs 无限增长。"""
    while True:
        time.sleep(120)
        now = time.time()
        with _lock:
            stale = [j for j, v in _jobs.items()
                     if v.get("status") in ("success", "failed") and now - float(v.get("done_ts") or 0) > 1800]
            for j in stale:
                _jobs.pop(j, None)


def get_dir_size(path):
    """计算目录大小(字节)"""
    total = 0
    try:
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
    except (OSError, PermissionError):
        pass
    return total


def format_size(size_bytes):
    """字节数人类可读"""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def normalize_path(p):
    try:
        return str(Path(p).resolve())
    except Exception:
        return p


def get_python_version(python_exe):
    rc, out, _ = run_cmd([python_exe, "--version"], timeout=10)
    if rc == 0 and out.startswith("Python"):
        return out.split()[1]
    return "未知"


def get_pip_version(python_exe):
    rc, out, _ = run_cmd([python_exe, "-m", "pip", "--version"], timeout=10)
    if rc == 0:
        parts = out.split()
        if len(parts) >= 2:
            return parts[1]
    return "未知"


def get_site_packages(python_exe):
    code = "import site; print(site.getsitepackages()[0] if site.getsitepackages() else '')"
    rc, out, _ = run_cmd([python_exe, "-c", code], timeout=10)
    if rc == 0 and out:
        return out.strip()
    return ""


def get_pip_cache_dir(python_exe):
    rc, out, _ = run_cmd([python_exe, "-m", "pip", "cache", "dir"], timeout=10)
    if rc == 0 and out:
        return out.strip()
    return ""


def version_tuple(v):
    """版本号转可比较元组"""
    parts = []
    for x in re.findall(r"\d+", v):
        parts.append(int(x))
    while len(parts) < 3:
        parts.append(0)
    return tuple(parts[:3])


# ============================================================
#  环境扫描引擎
# ============================================================

def compute_health(ver, pip_ver, in_path, path, pkg_count):
    """计算环境健康度评分 (0-100)"""
    score = 100
    issues_list = []
    # Python 版本 (3.8+ 满分, 越新越好但不惩罚太狠)
    try:
        vt = version_tuple(ver)
        if vt < (3, 8, 0):
            score -= 30; issues_list.append("Python 版本过低")
        elif vt < (3, 10, 0):
            score -= 10; issues_list.append("Python 版本较旧")
    except Exception:
        pass
    # pip 版本
    if pip_ver != "未知":
        try:
            pt = version_tuple(pip_ver)
            if pt < (21, 0, 0):
                score -= 15; issues_list.append("pip 版本过低")
            elif pt < (23, 0, 0):
                score -= 5; issues_list.append("pip 可更新")
        except Exception:
            pass
    else:
        score -= 20; issues_list.append("pip 不可用")
    # PATH
    if not in_path:
        score -= 5; issues_list.append("未加入 PATH")
    # 路径合法性
    if " " in path and "WindowsApps" not in path:
        pass  # 空格路径不扣分但标注
    try:
        if not os.access(path, os.R_OK):
            score -= 10; issues_list.append("权限受限")
    except Exception:
        pass
    score = max(0, min(100, score))
    level = "优" if score >= 85 else "良" if score >= 70 else "中" if score >= 50 else "差"
    return {"score": score, "level": level, "issues": issues_list}


def check_path_priority(py_dir):
    path_entries = os.environ.get("PATH", "").split(os.pathsep)
    for i, entry in enumerate(path_entries):
        if entry and os.path.normcase(os.path.normpath(entry)) == os.path.normcase(os.path.normpath(py_dir)):
            return True, i + 1
    return False, 0


def count_packages(python_exe):
    """优先用 importlib.metadata 快速计数（比 pip list 快约 10 倍），失败回退 pip freeze。"""
    code = "import sys;import importlib.metadata as m;sys.stdout.write(str(sum(1 for _ in m.distributions())))"
    rc, out, _ = run_cmd([python_exe, "-I", "-c", code], timeout=15)
    if rc == 0 and out.strip().isdigit():
        return int(out.strip())
    rc, out, _ = run_cmd([python_exe, "-m", "pip", "list", "--format=freeze"], timeout=30)
    if rc == 0:
        return len([l for l in out.splitlines() if "==" in l])
    return 0


def _enrich_env(idx, env_type, path, source):
    """单个环境的重量级信息（版本/pip/包数/健康度），供并行执行。"""
    path = normalize_path(path)
    ver = get_python_version(path)
    if ver == "未知" or not os.path.isfile(path):
        return None
    py_dir = str(Path(path).parent)
    if env_type in ("全局", "WinStore"):
        parent = Path(py_dir).parent
        if (parent / "pyvenv.cfg").exists():
            env_type = "venv"
    pip_ver = get_pip_version(path)
    pkg_count = count_packages(path)
    in_path, priority = check_path_priority(py_dir)
    health = compute_health(ver, pip_ver, in_path, path, pkg_count)
    created = ""
    try:
        created = datetime.fromtimestamp(os.path.getctime(path)).strftime("%Y-%m-%d")
    except OSError:
        pass
    return {
        "id": f"env_{idx}",
        "type": env_type,
        "version": ver,
        "pip_version": pip_ver,
        "path": path,
        "dir": py_dir,
        "source": source,
        "package_count": pkg_count,
        "in_path": in_path,
        "priority": priority,
        "health": health,
        "created": created,
    }


def scan_environments():
    """扫描系统中所有 Python 环境（候选收集后并行富化，速度提升约 3-6 倍）"""
    global _scan_status
    _scan_status["scanning"] = True
    _scan_status["progress"] = 0
    _scan_status["started"] = datetime.now().strftime("%H:%M:%S")
    candidates = []
    seen = set()

    def add_candidate(env_type, path, source=""):
        try:
            path = normalize_path(path)
            n = os.path.normcase(path)
        except Exception:
            return
        if n in seen or not os.path.isfile(path):
            return
        seen.add(n)
        candidates.append((env_type, path, source))

    steps = [
        ("扫描 PATH 环境变量", 15),
        ("扫描注册表", 30),
        ("扫描常见安装目录", 45),
        ("扫描 Conda 环境", 65),
        ("扫描 venv 虚拟环境", 85),
        ("并行计算健康度评分", 95),
    ]

    # 1. PATH
    _scan_status["message"] = steps[0][0]
    _scan_status["progress"] = steps[0][1]
    for p in os.environ.get("PATH", "").split(os.pathsep):
        for exe in ("python.exe", "python3.exe"):
            candidate = os.path.join(p, exe)
            if os.path.isfile(candidate):
                add_candidate("全局", candidate, "PATH")

    # 2. 注册表
    _scan_status["message"] = steps[1][0]
    _scan_status["progress"] = steps[1][1]
    if winreg:
        reg_roots = [
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Python\PythonCore"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Python\PythonCore"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\WOW6432Node\Python\PythonCore"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Python\PythonCore"),
        ]
        for root, subkey in reg_roots:
            try:
                with winreg.OpenKey(root, subkey) as k:
                    i = 0
                    while True:
                        try:
                            ver_key = winreg.EnumKey(k, i)
                            i += 1
                            try:
                                with winreg.OpenKey(k, f"{ver_key}\\InstallPath") as ip:
                                    install_path, _ = winreg.QueryValueEx(ip, "")
                                    if install_path:
                                        candidate = os.path.join(install_path, "python.exe")
                                        add_candidate("全局", candidate, f"注册表({ver_key})")
                            except OSError:
                                pass
                        except OSError:
                            break
            except OSError:
                pass

    # 3. 常见目录
    _scan_status["message"] = steps[2][0]
    _scan_status["progress"] = steps[2][1]
    common_dirs = [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Python"),
        r"C:\Python39", r"C:\Python310", r"C:\Python311", r"C:\Python312", r"C:\Python313",
    ]
    for d in common_dirs:
        if os.path.isdir(d):
            for sub in os.listdir(d):
                candidate = os.path.join(d, sub, "python.exe") if os.path.isdir(os.path.join(d, sub)) else os.path.join(d, "python.exe")
                if os.path.isfile(candidate):
                    add_candidate("全局", candidate, "常见目录")

    # 4. Conda
    _scan_status["message"] = steps[3][0]
    _scan_status["progress"] = steps[3][1]
    conda_dirs = [
        os.path.expanduser("~\\anaconda3"),
        os.path.expanduser("~\\miniconda3"),
        r"C:\ProgramData\anaconda3",
        r"C:\ProgramData\miniconda3",
        os.path.expandvars(r"%LOCALAPPDATA%\anaconda3"),
        os.path.expandvars(r"%LOCALAPPDATA%\miniconda3"),
    ]
    for d in conda_dirs:
        if os.path.isfile(os.path.join(d, "python.exe")):
            add_candidate("Conda(base)", os.path.join(d, "python.exe"), "Conda")
        envs_dir = os.path.join(d, "envs")
        if os.path.isdir(envs_dir):
            for sub in os.listdir(envs_dir):
                candidate = os.path.join(envs_dir, sub, "python.exe")
                if os.path.isfile(candidate):
                    add_candidate("Conda", candidate, f"Conda env: {sub}")

    rc, out, _ = run_cmd(["conda", "env", "list"], timeout=15)
    if rc == 0:
        for line in out.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if parts:
                candidate = os.path.join(parts[-1], "python.exe")
                if os.path.isfile(candidate):
                    add_candidate("Conda", candidate, "conda env list")

    # 5. venv
    _scan_status["message"] = steps[4][0]
    _scan_status["progress"] = steps[4][1]
    venv_roots = [
        os.path.expanduser("~\\Desktop"),
        os.path.expanduser("~\\Documents"),
        str(BASE_DIR),
    ]
    for root in venv_roots:
        if not os.path.isdir(root):
            continue
        if os.path.isfile(os.path.join(root, "pyvenv.cfg")):
            for exe in ("Scripts\\python.exe", "bin\\python.exe"):
                candidate = os.path.join(root, exe)
                if os.path.isfile(candidate):
                    add_candidate("venv", candidate, "venv")
        try:
            for sub in os.listdir(root):
                sub_path = os.path.join(root, sub)
                if os.path.isdir(sub_path) and os.path.isfile(os.path.join(sub_path, "pyvenv.cfg")):
                    for exe in ("Scripts\\python.exe", "bin\\python.exe"):
                        candidate = os.path.join(sub_path, exe)
                        if os.path.isfile(candidate):
                            add_candidate("venv", candidate, f"venv: {sub}")
        except PermissionError:
            pass

    # 6. Windows Store
    winstore = os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe")
    if os.path.isfile(winstore):
        add_candidate("WinStore", winstore, "Microsoft Store")

    # 并行富化（版本 / pip / 包数 / 健康度互相独立）
    _scan_status["message"] = steps[5][0]
    _scan_status["progress"] = steps[5][1]
    envs = []
    if candidates:
        workers = min(8, max(2, len(candidates)))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futures = [ex.submit(_enrich_env, i + 1, t, p, s) for i, (t, p, s) in enumerate(candidates)]
            for fut in futures:
                try:
                    env = fut.result()
                except Exception:
                    env = None
                if env:
                    envs.append(env)
        for i, env in enumerate(envs, 1):
            env["id"] = f"env_{i}"

    _scan_status["message"] = "扫描完成"
    _scan_status["progress"] = 100
    _scan_status["scanning"] = False
    _scan_status["finished"] = datetime.now().strftime("%H:%M:%S")
    return envs


def get_env_by_id(env_id):
    with _env_lock:
        for env in _env_cache:
            if env["id"] == env_id:
                return env
    return None


# ============================================================
#  包管理
# ============================================================

def list_packages(python_exe, outdated=False):
    """获取包列表, 带短期缓存"""
    cache_key = f"{python_exe}_{outdated}"
    now = time.time()
    with _pkg_cache_lock:
        if cache_key in _pkg_cache:
            ts, data = _pkg_cache[cache_key]
            if now - ts < _PKG_CACHE_TTL:
                return data
    cmd = [python_exe, "-m", "pip", "list", "--format=json"]
    if outdated:
        cmd.append("--outdated")
    rc, out, _ = run_cmd(cmd, timeout=60)
    result = []
    if rc == 0 and out:
        try:
            result = json.loads(out)
        except json.JSONDecodeError:
            pass
    with _pkg_cache_lock:
        _pkg_cache[cache_key] = (now, result)
    return result


def package_details(python_exe, name):
    rc, out, _ = run_cmd([python_exe, "-m", "pip", "show", name], timeout=15)
    if rc != 0:
        return None
    info = {}
    for line in out.splitlines():
        if ":" in line:
            key, _, val = line.partition(":")
            info[key.strip()] = val.strip()
    loc = info.get("Location", "")
    if loc:
        for pkg_dir_name in (name.replace("-", "_"), name):
            pkg_dir = os.path.join(loc, pkg_dir_name)
            if os.path.isdir(pkg_dir):
                info["size"] = get_dir_size(pkg_dir)
                info["size_human"] = format_size(info["size"])
                break
        else:
            info["size"] = 0
            info["size_human"] = "未知"
    return info


def get_package_versions(python_exe, name):
    """获取包的所有可用版本 (pip index versions)"""
    rc, out, err = run_cmd([python_exe, "-m", "pip", "index", "versions", name], timeout=20)
    versions = []
    if rc == 0 and out:
        # 解析 "pip index versions" 输出
        m = re.search(r"Available versions:\s*(.+)", out)
        if m:
            versions = [v.strip() for v in m.group(1).split(",") if v.strip()]
    if not versions:
        # 回退: 从 PyPI JSON API 获取 (但要求零依赖, 用 urllib)
        try:
            import urllib.request
            req = urllib.request.Request(
                f"https://pypi.org/pypi/{name}/json",
                headers={"User-Agent": "Avenger/2.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                versions = sorted(data.get("releases", {}).keys(), key=version_tuple, reverse=True)
        except Exception:
            pass
    return versions[:50]  # 最多返回50个版本


def get_package_deps_tree(python_exe, name, depth=0, max_depth=3, seen=None):
    """递归获取依赖树"""
    if seen is None:
        seen = set()
    if name.lower() in seen or depth > max_depth:
        return {"name": name, "version": "...", "deps": [], "cyclic": name.lower() in seen}
    seen.add(name.lower())
    info = package_details(python_exe, name)
    deps = []
    if info and info.get("Requires"):
        for dep in info["Requires"].split(","):
            dep = dep.strip()
            if dep:
                dep_name = re.split(r"[<>=!~;\[\(]", dep)[0].strip()
                dep_info = package_details(python_exe, dep_name)
                deps.append({
                    "name": dep_name,
                    "spec": dep,
                    "version": dep_info.get("Version", "未安装") if dep_info else "未安装",
                    "installed": dep_info is not None,
                    "deps": get_package_deps_tree(python_exe, dep_name, depth + 1, max_depth, seen.copy())["deps"] if depth < max_depth else [],
                })
    return {"name": name, "version": info.get("Version", "?") if info else "?", "deps": deps}


def diagnose_environment(python_exe, deep=False):
    """诊断环境问题, deep=True 启用深度诊断"""
    issues = []

    # 1. pip check
    rc, out, _ = run_cmd([python_exe, "-m", "pip", "check"], timeout=30)
    if out:
        for line in out.splitlines():
            line = line.strip()
            if not line or "No broken requirements" in line:
                continue
            if "is not installed" in line:
                m = re.match(r"(.+?)\s+[\d.]+\s+requires\s+(.+?),", line)
                pkg = m.group(1) if m else "?"
                dep = m.group(2).split()[0] if m else "?"
                issues.append({
                    "type": "依赖缺失", "level": "高",
                    "description": line,
                    "impact": f"{pkg} 可能无法正常导入或运行",
                    "fix": f"安装缺失依赖: {dep}",
                    "fix_cmd": f"install {dep}", "pkg": dep,
                    "explanation": "某个已安装包声明需要此依赖，但当前环境中未找到。缺失依赖会导致 ImportError 或运行时崩溃。",
                })
            elif "but you have" in line or "has requirement" in line:
                m = re.match(r"(.+?)\s+[\d.]+\s+(?:requires|has requirement)\s+(.+?),", line)
                target = m.group(2) if m else ""
                issues.append({
                    "type": "版本冲突", "level": "中",
                    "description": line,
                    "impact": "相关包可能无法正常工作",
                    "fix": f"安装兼容版本: {target}",
                    "fix_cmd": f"install {target}",
                    "pkg": target.split("<")[0].split(">")[0].split("=")[0].split("~")[0].strip(),
                    "explanation": "已安装包的版本不在其依赖声明的允许范围内，可能导致 API 不兼容或运行时错误。",
                })

    # 2. pip 版本
    pip_ver = get_pip_version(python_exe)
    if pip_ver != "未知":
        try:
            if version_tuple(pip_ver) < (21, 0, 0):
                issues.append({
                    "type": "环境异常", "level": "中",
                    "description": f"pip 版本过低 ({pip_ver}), 建议升级到 21.0+",
                    "impact": "可能导致包解析异常、缺少安全补丁",
                    "fix": "升级 pip 到最新稳定版",
                    "fix_cmd": "install --upgrade pip", "pkg": "pip",
                    "explanation": "旧版 pip 存在已知的依赖解析缺陷和安全漏洞，新版 pip 具备更可靠的解析器。",
                })
        except (ValueError, IndexError):
            pass

    # 3. 孤儿包
    rc, out, _ = run_cmd([python_exe, "-m", "pip", "list", "--not-required", "--format=freeze"], timeout=30)
    if rc == 0 and out:
        base_pkgs = {"pip", "setuptools", "wheel", "distribute"}
        orphans = []
        for line in out.splitlines():
            if "==" in line:
                name = line.split("==")[0]
                if name.lower() not in base_pkgs:
                    orphans.append(name)
        if orphans:
            issues.append({
                "type": "冗余/孤儿包", "level": "低",
                "description": f"发现 {len(orphans)} 个未被其他包依赖的闲置包: {', '.join(orphans[:10])}{'...' if len(orphans) > 10 else ''}",
                "impact": "占用磁盘空间, 不影响运行",
                "fix": "可选择性卸载闲置包",
                "fix_cmd": "uninstall_orphans",
                "pkg": ",".join(orphans), "orphans": orphans,
                "explanation": "这些包没有被任何其他已安装包依赖，可能是手动安装后遗忘的，或被其他包卸载后遗留的。",
            })

    # 4. 残留文件
    site = get_site_packages(python_exe)
    if site and os.path.isdir(site):
        residuals = []
        try:
            for item in os.listdir(site):
                if item.startswith("~") or item.endswith("~") or item.endswith(".bak") or item.endswith(".old"):
                    residuals.append(item)
        except PermissionError:
            pass
        if residuals:
            issues.append({
                "type": "残留文件", "level": "低",
                "description": f"site-packages 中存在疑似残留: {', '.join(residuals[:5])}",
                "impact": "可能导致包导入异常",
                "fix": "删除残留目录",
                "fix_cmd": "remove_residuals",
                "pkg": ",".join(residuals), "residuals": residuals, "site": site,
                "explanation": "这些文件通常是 pip 安装/卸载中断或手动修改后留下的临时文件。",
            })

    # 5. 重复包检测 (dist-info 多版本)
    if site and os.path.isdir(site):
        dist_infos = {}
        try:
            for item in os.listdir(site):
                if item.endswith(".dist-info") or item.endswith(".egg-info"):
                    pkg_name = re.split(r"-\d", item)[0].lower().replace("_", "-")
                    dist_infos.setdefault(pkg_name, []).append(item)
            dupes = {k: v for k, v in dist_infos.items() if len(v) > 1}
            if dupes:
                desc_parts = [f"{k} ({len(v)}个)" for k, v in list(dupes.items())[:5]]
                issues.append({
                    "type": "重复安装", "level": "中",
                    "description": f"发现 {len(dupes)} 个包存在多个版本元数据: {', '.join(desc_parts)}",
                    "impact": "可能导致 pip 混淆和导入错误版本",
                    "fix": "强制重新安装相关包",
                    "fix_cmd": "install --force-reinstall " + " ".join(list(dupes.keys())[:5]),
                    "pkg": ",".join(list(dupes.keys())[:5]),
                    "explanation": "同一包存在多个 .dist-info 目录通常是因为安装中断或手动删除不彻底。",
                })
        except PermissionError:
            pass

    # ===== 深度诊断 =====
    if deep:
        # 6. 循环依赖检测
        all_pkgs = list_packages(python_exe)
        dep_graph = {}
        for p in all_pkgs:
            info = package_details(python_exe, p["name"])
            if info and info.get("Requires"):
                reqs = [re.split(r"[<>=!~;\[\(]", d.strip())[0].strip().lower() for d in info["Requires"].split(",") if d.strip()]
                dep_graph[p["name"].lower()] = [r for r in reqs if r]

        def find_cycles(graph):
            cycles = []
            visited = set()
            def dfs(node, path):
                if node in path:
                    idx = path.index(node)
                    cycle = path[idx:] + [node]
                    cycles.append(cycle)
                    return
                if node in visited:
                    return
                visited.add(node)
                for dep in graph.get(node, []):
                    dfs(dep, path + [node])
            for n in graph:
                dfs(n, [])
            return cycles

        cycles = find_cycles(dep_graph)
        if cycles:
            unique_cycles = []
            seen_cycles = set()
            for c in cycles:
                key = tuple(sorted(set(c)))
                if key not in seen_cycles:
                    seen_cycles.add(key)
                    unique_cycles.append(c)
            for c in unique_cycles[:3]:
                issues.append({
                    "type": "循环依赖", "level": "中",
                    "description": f"检测到循环依赖链: {' → '.join(c)}",
                    "impact": "可能导致导入死锁或初始化异常",
                    "fix": "检查相关包版本兼容性, 考虑升级或降级",
                    "fix_cmd": "check", "pkg": c[0],
                    "explanation": "循环依赖指包 A 依赖 B，B 又直接或间接依赖 A，可能在导入时造成问题。",
                })

        # 7. 过时废弃包检测 (版本超过2年未更新视为过时)
        try:
            import urllib.request
            outdated_pkgs = []
            for p in all_pkgs[:30]:  # 限制检查数量
                try:
                    req = urllib.request.Request(
                        f"https://pypi.org/pypi/{p['name']}/json",
                        headers={"User-Agent": "Avenger/2.0"},
                    )
                    with urllib.request.urlopen(req, timeout=5) as resp:
                        data = json.loads(resp.read().decode("utf-8"))
                        latest_ver = data.get("info", {}).get("version", "")
                        if latest_ver and latest_ver != p["version"]:
                            # 检查最新版发布时间
                            urls = data.get("urls", [])
                            if urls:
                                upload_time = urls[0].get("upload_time_iso_8601", "")
                                if upload_time:
                                    upload_year = int(upload_time[:4])
                                    if datetime.now().year - upload_year >= 3:
                                        outdated_pkgs.append(f"{p['name']} (最新版发布于{upload_year}年)")
                except Exception:
                    pass
            if outdated_pkgs:
                issues.append({
                    "type": "过时包", "level": "低",
                    "description": f"发现 {len(outdated_pkgs)} 个长期未更新的包: {', '.join(outdated_pkgs[:5])}",
                    "impact": "可能存在未修复的安全漏洞或兼容性问题",
                    "fix": "评估是否仍需要这些包, 考虑寻找替代方案",
                    "fix_cmd": "", "pkg": "",
                    "explanation": "这些包的最新版本已超过3年未发布，可能不再维护。",
                })
        except Exception:
            pass

    return issues


def get_cache_info(python_exe):
    cache_dir = get_pip_cache_dir(python_exe)
    if not cache_dir or not os.path.isdir(cache_dir):
        return {"dir": cache_dir or "未知", "total": 0, "total_human": "0 B", "categories": [], "files": []}

    categories = []
    total = 0
    all_files = []

    for cat_name, subdir in [("HTTP 下载缓存", "http"), ("Wheels 缓存", "wheels")]:
        cat_dir = os.path.join(cache_dir, subdir)
        if os.path.isdir(cat_dir):
            size = get_dir_size(cat_dir)
            count = 0
            for dirpath, _, filenames in os.walk(cat_dir):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    count += 1
                    try:
                        st = os.stat(fp)
                        all_files.append({
                            "name": fn,
                            "path": fp,
                            "size": st.st_size,
                            "size_human": format_size(st.st_size),
                            "modified": datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M"),
                            "category": cat_name,
                        })
                    except OSError:
                        pass
            categories.append({"name": cat_name, "size": size, "size_human": format_size(size), "count": count})
            total += size

    other_size = get_dir_size(cache_dir) - total
    if other_size > 0:
        categories.append({"name": "其他缓存文件", "size": other_size, "size_human": format_size(other_size), "count": 0})
        total += other_size

    # 按大小排序文件
    all_files.sort(key=lambda x: x["size"], reverse=True)

    return {
        "dir": cache_dir,
        "total": total,
        "total_human": format_size(total),
        "categories": categories,
        "files": all_files[:100],  # 最多返回100个文件
    }


def get_all_cache_info():
    """获取所有环境的缓存总览"""
    result = []
    total = 0
    seen = set()
    with _env_lock:
        envs = list(_env_cache)
    for env in envs:
        if env["pip_version"] == "未知":
            continue
        cache_dir = get_pip_cache_dir(env["path"])
        if cache_dir and cache_dir not in seen and os.path.isdir(cache_dir):
            seen.add(cache_dir)
            size = get_dir_size(cache_dir)
            total += size
            result.append({
                "env_id": env["id"],
                "env_type": env["type"],
                "env_version": env["version"],
                "cache_dir": cache_dir,
                "size": size,
                "size_human": format_size(size),
            })
    return {"envs": result, "total": total, "total_human": format_size(total)}


# ============================================================
#  PATH 操作
# ============================================================

def get_user_path():
    if not winreg:
        return ""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ) as k:
            val, _ = winreg.QueryValueEx(k, "PATH")
            return val
    except OSError:
        return ""


def set_user_path(new_path):
    if not winreg:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as k:
            winreg.SetValueEx(k, "PATH", 0, winreg.REG_EXPAND_SZ, new_path)
        import ctypes
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST, WM_SETTINGCHANGE, 0, "Environment", SMTO_ABORTIFHUNG, 5000, None
        )
        return True
    except OSError:
        return False


# ============================================================
#  V3.0 硬件监控 / 端口 / 多语言检测
# ============================================================

def _ps(cmd):
    """运行 PowerShell，UTF-8 优先，失败再按 GBK 解码（修中文 Windows 豆腐块）"""
    script = (
        "[Console]::OutputEncoding=[System.Text.Encoding]::UTF8; "
        "$OutputEncoding=[Console]::OutputEncoding; "
        + cmd
    )
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        raw = r.stdout or b""
        for enc in ("utf-8", "gbk", "cp936"):
            try:
                return raw.decode(enc).strip()
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", "replace").strip()
    except Exception:
        return ""


def parse_host_header(host):
    if not host:
        return "", None
    host = host.strip()
    if host.startswith("["):
        end = host.find("]")
        name = host[1:end].lower() if end > 0 else ""
        port = host[end + 2:] if end > 0 and end + 1 < len(host) and host[end + 1] == ":" else None
        return name, port
    if host.count(":") == 1:
        name, port = host.rsplit(":", 1)
        return name.lower(), port
    return host.lower(), None


def is_loopback_host(host_header):
    name, hport = parse_host_header(host_header)
    if name not in ("127.0.0.1", "localhost", "::1"):
        return False
    if hport and str(hport) != str(PORT):
        return False
    return True


def origin_is_local(origin):
    if not origin:
        return True
    try:
        u = urlparse(origin)
    except Exception:
        return False
    if u.scheme not in ("http", "https"):
        return False
    name = (u.hostname or "").lower()
    if name not in ("127.0.0.1", "localhost", "::1"):
        return False
    if u.port and int(u.port) != int(PORT):
        return False
    return True


def is_probe_host_allowed(host):
    h = (host or "").strip().lower()
    if h in ("127.0.0.1", "localhost", "::1"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return bool(ip.is_loopback or ip.is_private)
    except ValueError:
        return False


def path_is_blocked(p):
    n = os.path.normcase(os.path.normpath(p or ""))
    blocked = ("\\windows\\system32", "/windows/system32", "\\windows\\syswow64", "\\$recycle.bin")
    return any(b in n for b in blocked)


def parse_gpu_name(raw):
    s = raw or ""
    m = re.search(r"(GeForce RTX [^(/,]+|GeForce GTX [^(/,]+|Radeon [^(/,]+|Intel[^(/,]*)", s, re.I)
    if m:
        return m.group(1).strip()
    m = re.search(r"NVIDIA,\s*(NVIDIA\s+)?([^(/]+)", s)
    if m:
        return m.group(2).strip()
    return s[:80] if s else "未检测到"


def nvidia_smi_info():
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    rc, out, _ = run_cmd(
        [exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
        timeout=6,
    )
    if rc != 0 or not out:
        return None
    line = out.splitlines()[0]
    parts = [p.strip() for p in line.split(",")]
    if len(parts) < 4:
        return None
    try:
        return {
            "name": parts[0],
            "mem_used_mb": float(parts[1]),
            "mem_total_mb": float(parts[2]),
            "util": float(parts[3]),
        }
    except ValueError:
        return None


def _persist_caches():
    try:
        CACHE_META.write_text(json.dumps({
            "pip": {"t": _overview_cache["t"], "total": _overview_cache["total"], "human": _overview_cache["human"]},
            "hw": _hw_cache.get("data"),
            "lang": _lang_cache.get("data"),
        }, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def _load_persisted_caches():
    try:
        d = json.loads(CACHE_META.read_text(encoding="utf-8"))
        pip = d.get("pip") or {}
        if pip.get("human"):
            _overview_cache["t"] = float(pip.get("t") or 0)
            _overview_cache["total"] = int(pip.get("total") or 0)
            _overview_cache["human"] = pip.get("human") or "—"
        if d.get("hw"):
            _hw_cache["data"] = d["hw"]
            _hw_cache["t"] = 0
        if d.get("lang"):
            _lang_cache["data"] = d["lang"]
            _lang_cache["t"] = 0
    except Exception:
        pass


def _compute_pip_cache():
    seen = set()
    total = 0
    with _env_lock:
        envs = list(_env_cache)
    for env in envs:
        if env.get("pip_version") == "未知":
            continue
        cache_dir = get_pip_cache_dir(env["path"])
        if not cache_dir or cache_dir in seen:
            continue
        seen.add(cache_dir)
        if os.path.isdir(cache_dir):
            total += get_dir_size(cache_dir)
    _overview_cache["t"] = time.time()
    _overview_cache["total"] = total
    _overview_cache["human"] = format_size(total)
    _persist_caches()
    return total, _overview_cache["human"]


def _kick_pip_refresh():
    global _pip_refreshing
    with _lock:
        if _pip_refreshing:
            return
        _pip_refreshing = True

    def work():
        global _pip_refreshing
        try:
            _compute_pip_cache()
        except Exception:
            pass
        finally:
            _pip_refreshing = False

    threading.Thread(target=work, daemon=True, name="pip-cache").start()


def unique_pip_cache_total():
    """从不阻塞请求线程。冷启动返回上次快照或“计算中”。"""
    now = time.time()
    if _overview_cache["t"] and now - _overview_cache["t"] < 60:
        return _overview_cache["total"], _overview_cache["human"]
    _kick_pip_refresh()
    return _overview_cache["total"], _overview_cache["human"] or "计算中"


_DISK_SKIP = {
    "node_modules", "__pycache__", ".git", "windows", "system volume information",
    "$recycle.bin", "appdata", "program files", "program files (x86)", "programdata",
}


def list_windows_drives():
    drives = []
    for code in range(65, 91):
        root = chr(code) + ":\\"
        if not os.path.isdir(root):
            continue
        try:
            u = shutil.disk_usage(root)
            drives.append({
                "letter": chr(code),
                "path": root,
                "total": u.total,
                "free": u.free,
                "used": u.used,
                "total_human": format_size(u.total),
                "free_human": format_size(u.free),
                "percent": round(100.0 * u.used / u.total, 1) if u.total else 0,
            })
        except OSError:
            continue
    return drives


def dir_size_budgeted(path, budget_files=3500, deadline=1.6):
    total = 0
    n = 0
    t0 = time.time()
    truncated = False
    try:
        for dirpath, dirnames, filenames in os.walk(path):
            dirnames[:] = [d for d in dirnames if d.lower() not in _DISK_SKIP and not d.startswith(".")]
            for fn in filenames:
                fp = os.path.join(dirpath, fn)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
                n += 1
                if n >= budget_files or (time.time() - t0) > deadline:
                    truncated = True
                    return total, truncated
    except (OSError, PermissionError):
        pass
    return total, truncated


_allowed_roots_cache = {"t": 0, "roots": []}


def allowed_scan_roots():
    now = time.time()
    if _allowed_roots_cache["roots"] and now - _allowed_roots_cache["t"] < 60:
        return _allowed_roots_cache["roots"]
    roots = [str(BASE_DIR), os.path.expanduser("~")]
    home = os.path.expanduser("~")
    for sub in ("Desktop", "Documents", "Projects", "Code", "source", "workspace", "dev", "Downloads"):
        roots.append(os.path.join(home, sub))
    with _env_lock:
        envs = list(_env_cache)
    for env in envs:
        if env.get("dir"):
            roots.append(env["dir"])
        cache_dir = get_pip_cache_dir(env["path"]) if env.get("path") else ""
        if cache_dir:
            roots.append(cache_dir)
    local_app = os.environ.get("LOCALAPPDATA") or ""
    if local_app:
        roots.append(os.path.join(local_app, "pip"))
        roots.append(os.path.join(local_app, "pip", "Cache"))
    uniq = []
    seen = set()
    for r in roots:
        if not r or not os.path.isdir(r):
            continue
        n = os.path.normcase(os.path.abspath(r))
        if n in seen:
            continue
        seen.add(n)
        uniq.append(os.path.abspath(r))
    _allowed_roots_cache["t"] = now
    _allowed_roots_cache["roots"] = uniq
    return uniq


def is_scan_path_allowed(path):
    if not path or path_is_blocked(path):
        return False
    n = os.path.normcase(os.path.abspath(path))
    for root in allowed_scan_roots():
        r = os.path.normcase(os.path.abspath(root))
        if n == r or n.startswith(r + os.sep):
            return True
    return False


_disk_overview_cache = {"t": 0, "data": None}


def disk_overview():
    now = time.time()
    if _disk_overview_cache["data"] and now - _disk_overview_cache["t"] < 45:
        return _disk_overview_cache["data"]
    paths = allowed_scan_roots()[:10]

    def one(p):
        size, trunc = dir_size_budgeted(p, 1800, 0.7)
        return {
            "name": os.path.basename(p.rstrip("\\/")) or p,
            "path": p,
            "size": size,
            "size_human": format_size(size) + ("+" if trunc else ""),
            "truncated": trunc,
        }

    with ThreadPoolExecutor(max_workers=4) as ex:
        roots = list(ex.map(one, paths))
    roots.sort(key=lambda x: x["size"], reverse=True)
    data = {"ok": True, "drives": list_windows_drives(), "roots": roots}
    _disk_overview_cache["t"] = now
    _disk_overview_cache["data"] = data
    return data


def disk_tree(path):
    if not path:
        return {"ok": False, "error": "缺少路径"}
    if not is_scan_path_allowed(path):
        return {"ok": False, "error": "路径不在可扫描白名单（项目/环境/缓存/用户文档）"}
    if not os.path.isdir(path):
        return {"ok": False, "error": "不是目录"}
    children = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.name.startswith(".") and entry.name not in (".venv", ".git"):
                    continue
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    trunc = False
                    if is_dir:
                        size, trunc = dir_size_budgeted(entry.path)
                    else:
                        size = entry.stat().st_size
                    children.append({
                        "name": entry.name,
                        "path": entry.path,
                        "dir": is_dir,
                        "size": size,
                        "size_human": format_size(size) + ("+" if trunc else ""),
                        "truncated": trunc,
                    })
                except OSError:
                    continue
    except (OSError, PermissionError) as e:
        return {"ok": False, "error": str(e)}
    children.sort(key=lambda x: x["size"], reverse=True)
    return {
        "ok": True,
        "path": os.path.abspath(path),
        "children": children[:48],
        "more": max(0, len(children) - 48),
    }


def flatten_dep_graph(tree):
    nodes = {}
    edges = []

    def walk(n, parent=None):
        key = (n.get("name") or "?").lower()
        if key not in nodes:
            nodes[key] = {
                "id": key,
                "name": n.get("name"),
                "version": n.get("version"),
                "missing": (n.get("version") == "未安装"),
            }
        if parent:
            edges.append({"source": parent, "target": key})
        for c in n.get("deps") or []:
            walk(c, key)

    if tree:
        walk(tree)
    return {"nodes": list(nodes.values()), "edges": edges}


def load_undo_stack():
    global _undo_stack
    if _undo_stack:
        return
    try:
        if UNDO_FILE.exists():
            _undo_stack = json.loads(UNDO_FILE.read_text(encoding="utf-8"))
            if not isinstance(_undo_stack, list):
                _undo_stack = []
    except Exception:
        _undo_stack = []


def save_undo_stack():
    try:
        UNDO_FILE.write_text(json.dumps(_undo_stack[:20], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def push_undo(entry):
    load_undo_stack()
    entry["id"] = str(uuid.uuid4())[:8]
    entry["ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    _undo_stack.insert(0, entry)
    del _undo_stack[20:]
    save_undo_stack()
    return entry


def apply_undo(undo_id):
    load_undo_stack()
    item = None
    for i, e in enumerate(_undo_stack):
        if e.get("id") == undo_id:
            item = _undo_stack.pop(i)
            break
    if not item:
        return {"ok": False, "error": "没有这条可撤销记录"}
    save_undo_stack()
    kind = item.get("type")
    if kind == "uninstall":
        env = get_env_by_id(item.get("env_id") or "")
        spec = item.get("spec") or item.get("package")
        if not env or not spec:
            return {"ok": False, "error": "撤销数据不完整"}
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": f"撤销卸载，重装 {spec}\n", "returncode": None}
        threading.Thread(
            target=run_cmd_streaming,
            args=([env["path"], "-m", "pip", "install", spec], job_id),
            daemon=True,
        ).start()
        log_op(f"撤销卸载: {spec}")
        return {"ok": True, "job_id": job_id, "message": f"正在重装 {spec}"}
    if kind == "path_reorder":
        prev = item.get("previous") or ""
        if not prev or not set_user_path(prev):
            return {"ok": False, "error": "无法恢复 PATH"}
        log_op("撤销 PATH 重排")
        return {"ok": True, "message": "PATH 已恢复"}
    if kind in ("install_version", "upgrade"):
        env = get_env_by_id(item.get("env_id") or "")
        specs = item.get("specs") or []
        if item.get("spec"):
            specs = [item["spec"]]
        if not env or not specs:
            return {"ok": False, "error": "撤销数据不完整"}
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": "正在还原包版本...\n", "returncode": None}
        threading.Thread(
            target=run_cmd_streaming,
            args=([env["path"], "-m", "pip", "install"] + specs, job_id),
            daemon=True,
        ).start()
        log_op(f"撤销包变更: {', '.join(specs)}")
        return {"ok": True, "job_id": job_id, "message": "正在还原版本"}
    return {"ok": False, "error": "不支持撤销该类型"}


PLUGIN_MANIFEST = {
    "disk": {
        "name": "磁盘占用分析",
        "desc": "扫描项目/环境/pip 缓存目录，矩形树图下钻",
        "actions": ["overview", "tree"],
    },
    "git": {
        "name": "Git 可视化",
        "desc": "仓库扫描与提交摘要",
        "actions": ["repos"],
    },
    "docker": {
        "name": "Docker 状态",
        "desc": "仅检测本机 docker 是否在 PATH（不执行任意容器命令）",
        "actions": ["status"],
    },
    "database": {
        "name": "数据库",
        "desc": "端口探测与 SQLite 只读",
        "actions": ["status"],
    },
}


def plugin_dispatch(plugin_id, action, qs):
    spec = PLUGIN_MANIFEST.get(plugin_id)
    if not spec:
        return {"ok": False, "error": "未知插件"}, 404
    if action not in spec["actions"]:
        return {"ok": False, "error": "未声明的插件动作"}, 404
    if plugin_id == "disk" and action == "overview":
        return disk_overview(), 200
    if plugin_id == "disk" and action == "tree":
        return disk_tree((qs.get("path") or [""])[0]), 200
    if plugin_id == "git" and action == "repos":
        return {"ok": True, "repos": scan_git_repos()}, 200
    if plugin_id == "docker" and action == "status":
        exe = shutil.which("docker")
        ver = ""
        if exe:
            _, out, err = run_cmd([exe, "--version"], timeout=5)
            ver = (out or err or "").strip().splitlines()[0] if (out or err) else ""
        return {"ok": True, "installed": bool(exe), "path": exe or "", "version": ver}, 200
    if plugin_id == "database" and action == "status":
        return {"ok": True, "sqlite": True, "drivers": "stdlib-only"}, 200
    return {"ok": False, "error": "未实现"}, 404


_PKG_SPEC_RE = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._\-]*(\[[A-Za-z0-9,_]+\])?(===?|>=|<=|~=|!=)?[A-Za-z0-9._\-]*$"
)

_PKG_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]*$")
_PKG_VER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+!\-]*$")


def safe_pkg_name(name):
    """严格包名校验：只允许字母数字 . _ -，防止 pip 参数注入。"""
    n = str(name or "").strip()
    if not n or len(n) > 120:
        return None
    return n if _PKG_NAME_RE.match(n) else None


def safe_pkg_spec(spec):
    """允许 name、name==ver 等完整规格。"""
    s = str(spec or "").strip().replace(" ", "")
    if not s or len(s) > 160 or any(c in s for c in ";&|`$'\"\n\r"):
        return None
    return s if _PKG_SPEC_RE.match(s) else None


def pypi_package_info(name):
    name = re.sub(r"[^A-Za-z0-9._-]", "", name or "")[:80]
    if not name:
        return {"ok": False, "error": "包名无效"}
    try:
        req = Request(
            "https://pypi.org/pypi/%s/json" % name,
            headers={"User-Agent": "Avenger-Local/4.0"},
        )
        with urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8", "replace"))
        info = data.get("info") or {}
        vers = sorted((data.get("releases") or {}).keys(), key=version_tuple, reverse=True)[:16]
        return {
            "ok": True,
            "name": info.get("name") or name,
            "summary": (info.get("summary") or "")[:400],
            "version": info.get("version") or "",
            "home": info.get("home_page") or info.get("project_url") or "",
            "requires_python": info.get("requires_python") or "",
            "license": (info.get("license") or "")[:80],
            "versions": vers,
        }
    except Exception as e:
        return {"ok": False, "error": "PyPI 查询失败（离线或包名不存在）: %s" % e}


def sanitize_requirement_lines(text):
    out = []
    for line in (text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("-") or "://" in line:
            continue
        token = line.split(";")[0].strip()
        if _PKG_SPEC_RE.match(token.replace(" ", "")) or re.match(
            r"^[A-Za-z0-9][A-Za-z0-9._\-]*", token
        ):
            out.append(token[:160])
        if len(out) >= 400:
            break
    return out


def osv_querybatch(pkg_pairs):
    queries = []
    for name, ver in pkg_pairs[:180]:
        if not name or not ver:
            continue
        queries.append({"package": {"name": name, "ecosystem": "PyPI"}, "version": ver})
    if not queries:
        return []
    body = json.dumps({"queries": queries}).encode("utf-8")
    req = Request(
        "https://api.osv.dev/v1/querybatch",
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "Avenger-Local/4.0"},
        method="POST",
    )
    with urlopen(req, timeout=25) as resp:
        data = json.loads(resp.read().decode("utf-8", "replace"))
    return data.get("results") or []


_hw_cache = {"t": 0, "data": None}
_lang_cache = {"t": 0, "data": None}


class _FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def _filetime_int(ft):
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


def _win_perf_ctypes():
    kernel32 = ctypes.windll.kernel32
    kernel32.GetSystemTimes.argtypes = [
        ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME)
    ]
    kernel32.GetSystemTimes.restype = wintypes.BOOL
    kernel32.GlobalMemoryStatusEx.argtypes = [ctypes.POINTER(_MEMORYSTATUSEX)]
    kernel32.GlobalMemoryStatusEx.restype = wintypes.BOOL
    idle, kernel, user = _FILETIME(), _FILETIME(), _FILETIME()
    if not kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
        raise OSError("GetSystemTimes")
    idle_i, kern_i, user_i = _filetime_int(idle), _filetime_int(kernel), _filetime_int(user)
    pct = _cpu_sample["pct"]
    if _cpu_sample["t"]:
        didle = idle_i - _cpu_sample["idle"]
        dkern = kern_i - _cpu_sample["kernel"]
        duser = user_i - _cpu_sample["user"]
        total = dkern + duser
        if total > 0:
            pct = max(0.0, min(100.0, (1.0 - didle / float(total)) * 100.0))
    _cpu_sample.update(t=time.time(), idle=idle_i, kernel=kern_i, user=user_i, pct=pct)
    mem = _MEMORYSTATUSEX()
    mem.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
    if not kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
        raise OSError("GlobalMemoryStatusEx")
    total_b = int(mem.ullTotalPhys)
    avail_b = int(mem.ullAvailPhys)
    used_b = max(0, total_b - avail_b)
    return {
        "cpu_percent": round(pct, 1),
        "memory_percent": round(100.0 * used_b / max(total_b, 1), 1),
        "memory_used_gb": round(used_b / (1024 ** 3), 2),
        "memory_total_gb": round(total_b / (1024 ** 3), 2),
        "memory_total": total_b,
        "memory_available": avail_b,
        "python_processes": 0,
    }


def _hw_skeleton():
    perf = {}
    try:
        perf = _win_perf_ctypes()
    except Exception:
        pass
    usage = None
    try:
        usage = shutil.disk_usage(os.environ.get("SystemDrive", "C:\\"))
    except Exception:
        pass
    cores = os.cpu_count() or 0
    return {
        "cpu_model": platform.processor() or "CPU",
        "cpu_cores": cores,
        "cpu_threads": cores,
        "memory_total": perf.get("memory_total") or 0,
        "memory_available": perf.get("memory_available") or 0,
        "disk": {
            "total": usage.total if usage else 0,
            "free": usage.free if usage else 0,
            "used": usage.used if usage else 0,
            "total_human": format_size(usage.total) if usage else "—",
            "free_human": format_size(usage.free) if usage else "—",
        } if usage else {"total": 0, "free": 0, "used": 0, "total_human": "—", "free_human": "—"},
        "gpu": "检测中…",
        "gpu_raw": "",
        "os": platform.platform(),
        "arch": platform.machine(),
        "hostname": os.environ.get("COMPUTERNAME", "unknown"),
        "username": os.environ.get("USERNAME", "unknown"),
        "battery": None,
        "disks": [],
        "pending": True,
    }


def _compute_hardware():
    info = _hw_skeleton()
    info["pending"] = False
    ps_script = (
        "$cpu=Get-CimInstance Win32_Processor; "
        "$cs=Get-CimInstance Win32_ComputerSystem; "
        "$os=Get-CimInstance Win32_OperatingSystem; "
        "$gpu=Get-CimInstance Win32_VideoController; "
        "$bat=Get-CimInstance Win32_Battery; "
        "Write-Output ('CPU:'+$cpu.Name); "
        "Write-Output ('CORES:'+$cpu.NumberOfCores); "
        "Write-Output ('THREADS:'+$cpu.NumberOfLogicalProcessors); "
        "Write-Output ('MEMTOTAL:'+$cs.TotalPhysicalMemory); "
        "Write-Output ('MEMFREE:'+($os.FreePhysicalMemory*1KB)); "
        "Write-Output ('GPU:'+($gpu.Name -join '; ')); "
        "Write-Output ('OS:'+$os.Caption); "
        "Write-Output ('ARCH:'+$os.OSArchitecture); "
        "if($bat){Write-Output ('BAT:'+$bat.EstimatedChargeRemaining+'|'+$bat.BatteryStatus)}"
    )
    out = _ps(ps_script)
    data = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            data[k.strip()] = v.strip()

    if data.get("CPU"):
        info["cpu_model"] = data.get("CPU")
    if data.get("CORES", "").isdigit():
        info["cpu_cores"] = int(data["CORES"])
    if data.get("THREADS", "").isdigit():
        info["cpu_threads"] = int(data["THREADS"])
    try:
        if data.get("MEMTOTAL"):
            info["memory_total"] = int(float(data.get("MEMTOTAL", 0)))
        if data.get("MEMFREE"):
            info["memory_available"] = int(float(data.get("MEMFREE", 0)))
    except (ValueError, TypeError):
        pass
    info["gpu"] = parse_gpu_name(data.get("GPU", "") or "未检测到")
    info["gpu_raw"] = data.get("GPU", "") or ""
    info["os"] = data.get("OS", info["os"])
    info["arch"] = data.get("ARCH", info["arch"])
    bat_str = data.get("BAT", "")
    if bat_str and "|" in bat_str:
        parts = bat_str.split("|")
        info["battery"] = {
            "percent": int(parts[0]) if parts[0].isdigit() else 0,
            "charging": parts[1] != "1" if len(parts) > 1 else False,
        }
    smi = nvidia_smi_info()
    if smi:
        info["gpu"] = smi["name"] or info["gpu"]
        info["gpu_mem"] = smi
    info["disks"] = list_windows_drives()
    _hw_cache["t"] = time.time()
    _hw_cache["data"] = info
    _persist_caches()
    return info


def _kick_hw_refresh():
    global _hw_refreshing
    with _lock:
        if _hw_refreshing:
            return
        _hw_refreshing = True

    def work():
        global _hw_refreshing
        try:
            _compute_hardware()
        except Exception:
            pass
        finally:
            _hw_refreshing = False

    threading.Thread(target=work, daemon=True, name="hw-refresh").start()


def get_hardware_info(force=False):
    """立即返回快照，PowerShell/CIM 在后台刷新。"""
    now = time.time()
    if _hw_cache["data"] is None:
        _hw_cache["data"] = _hw_skeleton()
        _hw_cache["t"] = 0
        _kick_hw_refresh()
        return _hw_cache["data"]
    if force:
        return _compute_hardware()
    if now - _hw_cache["t"] >= 20:
        _kick_hw_refresh()
    return _hw_cache["data"]


def get_system_stats():
    """用 Windows API 取 CPU/内存，避免每次 CIM 卡住驾驶舱图表。"""
    try:
        stats = _win_perf_ctypes()
        return {
            "cpu_percent": stats["cpu_percent"],
            "memory_percent": stats["memory_percent"],
            "memory_used_gb": stats["memory_used_gb"],
            "memory_total_gb": stats["memory_total_gb"],
            "python_processes": stats.get("python_processes") or 0,
        }
    except Exception:
        pass
    return {"cpu_percent": 0, "memory_percent": 0, "memory_used_gb": 0, "memory_total_gb": 0, "python_processes": 0}


def get_listening_ports():
    """监听端口 — 一次 netstat + 一次 tasklist"""
    ports = []
    try:
        r = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True, text=True, timeout=10, encoding="gbk", errors="replace",
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
        pid_map = {}
        try:
            pr = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10, encoding="gbk", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
            for line in pr.stdout.splitlines():
                cols = [c.strip('"') for c in line.split('","')]
                if len(cols) >= 2:
                    pid_map[cols[1]] = cols[0]
        except Exception:
            pass
        seen = set()
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 5 and parts[0] == "TCP" and parts[3].upper() == "LISTENING":
                local = parts[1]
                pid = parts[-1]
                port = local.rsplit(":", 1)[-1]
                if port in seen:
                    continue
                seen.add(port)
                try:
                    ports.append({
                        "port": int(port), "pid": int(pid),
                        "name": pid_map.get(pid, ""), "protocol": "TCP",
                        "state": "LISTENING", "address": local,
                    })
                except ValueError:
                    continue
        ports.sort(key=lambda x: x["port"])
    except Exception:
        pass
    return ports


def _compute_languages():
    checks = [
        ("Node.js", "node", ["--version"]),
        ("Go", "go", ["version"]),
        ("Java", "java", ["-version"]),
        ("Rust", "rustc", ["--version"]),
        ("PHP", "php", ["--version"]),
        ("Ruby", "ruby", ["--version"]),
        (".NET", "dotnet", ["--version"]),
        ("Docker", "docker", ["--version"]),
        ("Git", "git", ["--version"]),
    ]

    def check(item):
        name, cmd, args = item
        exe = shutil.which(cmd)
        if not exe:
            return {"name": name, "version": "未安装", "path": "", "installed": False}
        rc, out, err = run_cmd([exe] + args, timeout=5)
        text = (out or err or "").strip().split("\n")[0]
        ver = text
        for prefix in [f"{name} version ", f"{cmd} version ", "openjdk version ", "PHP ", "go version ", "git version "]:
            if prefix.lower() in ver.lower():
                idx = ver.lower().find(prefix.lower())
                ver = ver[idx + len(prefix):]
                break
        if ver.startswith("v"):
            ver = ver[1:]
        ver = ver.strip('"').split()[0] if ver else "已安装"
        return {"name": name, "version": ver, "path": exe, "installed": True}

    with ThreadPoolExecutor(max_workers=6) as ex:
        langs = list(ex.map(check, checks))
    _lang_cache["t"] = time.time()
    _lang_cache["data"] = langs
    _persist_caches()
    return langs


def _kick_lang_refresh():
    global _lang_refreshing
    with _lock:
        if _lang_refreshing:
            return
        _lang_refreshing = True

    def work():
        global _lang_refreshing
        try:
            _compute_languages()
        except Exception:
            pass
        finally:
            _lang_refreshing = False

    threading.Thread(target=work, daemon=True, name="lang-refresh").start()


def detect_languages(force=False):
    """并行检测运行时。默认立即返回缓存，后台刷新。"""
    now = time.time()
    if force:
        return _compute_languages()
    if _lang_cache["data"] is not None:
        if now - _lang_cache["t"] >= 30:
            _kick_lang_refresh()
        return _lang_cache["data"]
    _lang_cache["data"] = []
    _kick_lang_refresh()
    return []


def scan_git_repos(max_depth=3):
    """只扫描常见开发目录，禁止扫整个盘符"""
    repos = []
    home = os.path.expanduser("~")
    search_roots = [
        str(BASE_DIR),
        os.path.join(home, "Desktop"),
        os.path.join(home, "Documents"),
        os.path.join(home, "Projects"),
        os.path.join(home, "Code"),
        os.path.join(home, "source"),
        os.path.join(home, "workspace"),
        os.path.join(home, "dev"),
        "D:\\Projects",
        "D:\\Code",
        "D:\\workspace",
        "D:\\src",
        "D:\\Avenger",
    ]
    skip = {
        "node_modules", "__pycache__", "venv", ".venv", "env", "dist", "build",
        "site-packages", "appdata", "windows", "program files", "program files (x86)",
        "programdata", "$recycle.bin", "system volume information",
    }
    seen = set()
    for root in search_roots:
        if not os.path.isdir(root):
            continue
        try:
            for dirpath, dirnames, filenames in os.walk(root):
                depth = dirpath[len(root):].count(os.sep)
                if depth > max_depth:
                    dirnames[:] = []
                    continue
                dirnames[:] = [d for d in dirnames if not d.startswith(".") and d.lower() not in skip]
                if ".git" in dirnames or os.path.isdir(os.path.join(dirpath, ".git")):
                    rp = os.path.abspath(dirpath)
                    if rp in seen:
                        continue
                    seen.add(rp)
                    info = {"name": os.path.basename(rp), "path": rp, "branch": "?", "commits": 0}
                    try:
                        r = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=rp,
                                           capture_output=True, text=True, timeout=5,
                                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                        if r.returncode == 0:
                            info["branch"] = r.stdout.strip()
                        r2 = subprocess.run(["git", "rev-list", "--count", "HEAD"], cwd=rp,
                                            capture_output=True, text=True, timeout=5,
                                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
                        if r2.returncode == 0:
                            info["commits"] = int(r2.stdout.strip() or 0)
                    except Exception:
                        pass
                    repos.append(info)
                    if ".git" in dirnames:
                        dirnames.remove(".git")
                    dirnames[:] = []
        except (PermissionError, OSError):
            continue
        if len(repos) >= 40:
            break
    return repos[:40]


def git_repo_detail(path):
    if not os.path.isdir(os.path.join(path, ".git")):
        return {"ok": False, "error": "不是 Git 仓库"}
    flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        st = subprocess.run(["git", "status", "-sb"], cwd=path, capture_output=True, text=True, timeout=8, creationflags=flags)
        lg = subprocess.run(["git", "log", "-8", "--pretty=format:%h  %ad  %s", "--date=short"],
                            cwd=path, capture_output=True, text=True, timeout=8, creationflags=flags)
        status = (st.stdout or "").strip() or "clean"
        log_lines = [ln for ln in (lg.stdout or "").splitlines() if ln.strip()]
        return {"ok": True, "status": status, "log": log_lines}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def detect_project_runtime(path):
    if not os.path.isdir(path):
        return {"ok": False, "error": "目录不存在"}
    mapping = [
        (".nvmrc", "Node.js"),
        (".node-version", "Node.js"),
        ("package.json", "Node.js"),
        (".python-version", "Python"),
        ("Pipfile", "Python"),
        ("pyproject.toml", "Python"),
        ("requirements.txt", "Python"),
        (".go-version", "Go"),
        ("go.mod", "Go"),
        (".java-version", "Java"),
        ("pom.xml", "Java"),
        ("build.gradle", "Java"),
        ("rust-toolchain", "Rust"),
        ("Cargo.toml", "Rust"),
        (".php-version", "PHP"),
        ("composer.json", "PHP"),
        (".ruby-version", "Ruby"),
        ("Gemfile", "Ruby"),
    ]
    files = []
    for name, runtime in mapping:
        fp = os.path.join(path, name)
        if os.path.isfile(fp):
            value = ""
            try:
                with open(fp, "r", encoding="utf-8", errors="replace") as f:
                    value = f.read(200).strip().splitlines()[0] if name.startswith(".") or name in ("rust-toolchain",) else name
            except Exception:
                value = name
            files.append({"file": name, "runtime": runtime, "value": value[:80]})
    return {"ok": True, "files": files}


def probe_db_port(host, port, db_type):
    if not is_probe_host_allowed(host):
        return {"ok": False, "error": "仅允许探测本机或私有网段，禁止公网地址"}
    try:
        port = int(port)
    except (TypeError, ValueError):
        return {"ok": False, "error": "端口无效"}
    if port < 1 or port > 65535:
        return {"ok": False, "error": "端口无效"}
    try:
        s = socket.create_connection((host, int(port)), timeout=2)
        banner = ""
        if db_type == "Redis":
            try:
                s.sendall(b"PING\r\n")
                banner = s.recv(64).decode("utf-8", "replace").strip()
            except Exception:
                pass
        s.close()
        return {"ok": True, "message": "端口开放", "banner": banner}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def sqlite_tables(db_path):
    if path_is_blocked(db_path):
        log_op(f"拒绝敏感路径 SQLite: {db_path}")
        return {"ok": False, "error": "拒绝访问系统敏感目录"}
    if not os.path.isfile(db_path):
        return {"ok": False, "error": "文件不存在"}
    try:
        uri = "file:{}?mode=ro".format(db_path.replace("\\", "/"))
        con = sqlite3.connect(uri, uri=True, timeout=3)
        cur = con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [r[0] for r in cur.fetchall()]
        con.close()
        return {"ok": True, "tables": tables}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def sqlite_preview(db_path, table):
    if path_is_blocked(db_path):
        return {"ok": False, "error": "拒绝访问系统敏感目录"}
    if not os.path.isfile(db_path):
        return {"ok": False, "error": "文件不存在"}
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", table or ""):
        return {"ok": False, "error": "非法表名"}
    try:
        uri = "file:{}?mode=ro".format(db_path.replace("\\", "/"))
        con = sqlite3.connect(uri, uri=True, timeout=3)
        con.row_factory = sqlite3.Row
        cur = con.execute(f'SELECT * FROM "{table}" LIMIT 50')
        rows = [dict(r) for r in cur.fetchall()]
        columns = list(rows[0].keys()) if rows else [d[0] for d in cur.description or []]
        con.close()
        return {"ok": True, "columns": columns, "rows": rows}
    except Exception as e:
        return {"ok": False, "error": str(e)}


KNOWN_RISKY = {
    "pillow": ("10.0.0", "历史版本存在图像解析相关漏洞，建议升级"),
    "requests": ("2.31.0", "旧版本 TLS/证书处理存在已知问题"),
    "urllib3": ("2.0.0", "建议使用较新主版本"),
    "setuptools": ("65.5.1", "旧版本存在包安装相关风险"),
    "jinja2": ("3.1.3", "模板引擎建议保持较新"),
    "cryptography": ("41.0.0", "加密库应保持更新"),
}


def security_scan_env(env):
    pkgs = list_packages(env["path"], outdated=False)
    findings = []
    seen = set()
    for p in pkgs:
        name = (p.get("name") or "").lower()
        ver = p.get("version") or ""
        if name in KNOWN_RISKY:
            min_v, reason = KNOWN_RISKY[name]
            if version_tuple(ver) < version_tuple(min_v):
                findings.append({
                    "name": p["name"], "version": ver, "suggest": f">={min_v}",
                    "level": "高", "reason": reason, "source": "local",
                })
                seen.add((name, ver))
    osv_ok = False
    osv_error = ""
    try:
        pairs = [(p.get("name"), p.get("version")) for p in pkgs]
        results = osv_querybatch(pairs)
        osv_ok = True
        for i, result in enumerate(results):
            vulns = result.get("vulns") or []
            if not vulns or i >= len(pkgs):
                continue
            p = pkgs[i]
            ids = [v.get("id") for v in vulns if v.get("id")][:8]
            if not ids:
                continue
            findings.append({
                "name": p.get("name"), "version": p.get("version"),
                "suggest": "查阅 OSV / 升级到修复版本",
                "level": "高" if len(ids) >= 2 else "中",
                "reason": "OSV: " + ", ".join(ids),
                "cves": ids, "source": "osv",
            })
    except Exception as e:
        osv_error = str(e)
        log_op(f"OSV 扫描降级: {e}")
    return {
        "ok": True,
        "findings": findings[:250],
        "outdated": sum(1 for f in findings if f.get("source") == "osv"),
        "osv": osv_ok,
        "osv_error": osv_error,
    }


def create_env_snapshot(env, full=False):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_name = re.sub(r"[^\w.-]+", "_", env.get("type", "env") + "_" + env.get("version", ""))
    req_path = BACKUP_DIR / f"snapshot_{safe_name}_{stamp}.txt"
    rc, out, err = run_cmd([env["path"], "-m", "pip", "freeze"], timeout=120)
    req_path.write_text(out or err or "", encoding="utf-8")
    meta = {
        "env": {k: env.get(k) for k in ("id", "type", "version", "path", "dir", "pip_version")},
        "created": stamp,
        "requirements": str(req_path),
    }
    meta_path = BACKUP_DIR / f"snapshot_{safe_name}_{stamp}.json"
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    zip_path = BACKUP_DIR / f"snapshot_{safe_name}_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(req_path, req_path.name)
        zf.write(meta_path, meta_path.name)
        if full and env.get("type") == "venv" and env.get("dir") and os.path.isdir(env["dir"]):
            root = env["dir"]
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d.lower() not in ("__pycache__", ".git")]
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    try:
                        zf.write(fp, os.path.relpath(fp, os.path.dirname(root)))
                    except OSError:
                        pass
    return str(zip_path)



class AvengerHandler(http.server.BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def _security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "font-src 'self' data:; "
            "frame-ancestors 'none'; "
            "base-uri 'none'; "
            "form-action 'self'",
        )

    def _guard(self, mutating=False):
        if not is_loopback_host(self.headers.get("Host", "")):
            self._send_json({"error": "拒绝非本机 Host（防 DNS rebinding）"}, 403)
            return False
        site = (self.headers.get("Sec-Fetch-Site") or "").lower()
        if site == "cross-site":
            self._send_json({"error": "拒绝跨站请求"}, 403)
            return False
        if mutating:
            origin = self.headers.get("Origin")
            if origin and not origin_is_local(origin):
                self._send_json({"error": "拒绝跨源 Origin"}, 403)
                return False
            token = self.headers.get("X-Avenger-Token") or ""
            if token != SESSION_TOKEN:
                self._send_json({"error": "缺少或无效的会话令牌"}, 403)
                return False
        return True

    def _send_json(self, data, code=200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            return {}
        if length <= 0:
            return {}
        if length > MAX_BODY:
            self._send_json({"error": "请求体超过 10MB 上限"}, 413)
            return None
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            log_op("收到无法解析的请求体（已忽略）")
            return {}

    def _serve_html(self):
        filepath = BASE_DIR / "avenger.html"
        try:
            content = filepath.read_text(encoding="utf-8")
        except FileNotFoundError:
            self._send_json({"error": "文件不存在"}, 404)
            return
        meta = f'<meta name="avenger-token" content="{SESSION_TOKEN}">'
        if "%%AVENGER_TOKEN%%" in content:
            content = content.replace("%%AVENGER_TOKEN%%", SESSION_TOKEN)
        elif 'name="avenger-token"' in content:
            content = re.sub(
                r'<meta name="avenger-token" content="[^"]*">',
                meta,
                content,
                count=1,
            )
        else:
            content = content.replace("<head>", "<head>\n" + meta, 1)
        data = content.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self._security_headers()
        self.end_headers()
        self.wfile.write(data)

    def _serve_file(self, filepath, content_type):
        try:
            with open(filepath, "rb") as f:
                content = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            self._security_headers()
            self.end_headers()
            self.wfile.write(content)
        except FileNotFoundError:
            self._send_json({"error": "文件不存在"}, 404)

    def do_OPTIONS(self):
        self.send_response(403)
        self._security_headers()
        self.end_headers()

    # ---------- GET ----------
    def do_GET(self):
        try:
            self._do_get_impl()
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            pass
        except Exception as e:
            log_op("GET 异常 %s: %s" % (getattr(self, 'path', '?'), e))
            try:
                self._send_json({"error": "服务器内部错误: %s" % e}, 500)
            except Exception:
                pass

    def _do_get_impl(self):
        global _last_heartbeat
        if not self._guard(mutating=False):
            return
        parsed = urlparse(self.path)
        path = parsed.path
        qs = parse_qs(parsed.query)

        if path in ("/", "/index.html"):
            self._serve_html()
            return

        if path == "/api/heartbeat":
            _last_heartbeat = time.time()
            self._send_json({"ok": True})
            return

        if path == "/api/overview":
            self._send_json(self._api_overview())
            return

        if path == "/api/notes":
            if not studio:
                self._send_json({"notes": []})
                return
            self._send_json({"notes": studio.notes_list(BASE_DIR)})
            return

        if path == "/api/ai/config":
            if not studio:
                self._send_json({"error": "studio 模块缺失"}, 500)
                return
            self._send_json(studio.ai_public_config(BASE_DIR))
            return

        if path == "/api/kata":
            if not studio:
                self._send_json({"katas": []})
                return
            self._send_json({"katas": studio.kata_list()})
            return

        if path == "/api/learn":
            if not studio:
                self._send_json({"sheets": []})
                return
            self._send_json({"sheets": studio.CHEATSHEETS})
            return

        if path == "/api/ui-prefs":
            self._send_json(load_ui_prefs())
            return

        if path == "/api/environments":
            self._send_json({"environments": list(_env_cache), "scan_status": dict(_scan_status)})
            return

        if path == "/api/scan-status":
            self._send_json(dict(_scan_status))
            return

        if path == "/api/packages":
            env_id = qs.get("env_id", [""])[0]
            env = get_env_by_id(env_id)
            if not env:
                self._send_json({"error": "环境不存在"}, 404)
                return
            outdated = qs.get("outdated", ["0"])[0] == "1"
            pkgs = list_packages(env["path"], outdated=outdated)
            self._send_json({"packages": pkgs, "env": env})
            return

        if path == "/api/package":
            env_id = qs.get("env_id", [""])[0]
            name = qs.get("name", [""])[0]
            env = get_env_by_id(env_id)
            if not env:
                self._send_json({"error": "环境不存在"}, 404)
                return
            detail = package_details(env["path"], name)
            if not detail:
                self._send_json({"error": "包不存在"}, 404)
                return
            self._send_json({"detail": detail})
            return

        if path == "/api/package/versions":
            env_id = qs.get("env_id", [""])[0]
            name = qs.get("name", [""])[0]
            env = get_env_by_id(env_id)
            if not env:
                self._send_json({"error": "环境不存在"}, 404)
                return
            versions = get_package_versions(env["path"], name)
            self._send_json({"versions": versions})
            return

        if path == "/api/package/deps-tree":
            env_id = qs.get("env_id", [""])[0]
            name = qs.get("name", [""])[0]
            env = get_env_by_id(env_id)
            if not env:
                self._send_json({"error": "环境不存在"}, 404)
                return
            tree = get_package_deps_tree(env["path"], name)
            self._send_json({"tree": tree, "graph": flatten_dep_graph(tree)})
            return

        if path == "/api/cache":
            env_id = qs.get("env_id", [""])[0]
            env = get_env_by_id(env_id)
            if not env:
                self._send_json({"error": "环境不存在"}, 404)
                return
            self._send_json(get_cache_info(env["path"]))
            return

        if path == "/api/cache/all":
            self._send_json(get_all_cache_info())
            return

        if path == "/api/logs":
            logs = []
            if LOG_FILE.exists():
                with open(LOG_FILE, "r", encoding="utf-8") as f:
                    logs = f.readlines()[-200:]
            self._send_json({"logs": logs})
            return

        if path == "/api/backups":
            backups = []
            if BACKUP_DIR.exists():
                for f in sorted(BACKUP_DIR.glob("backup_*.txt"), reverse=True)[:20]:
                    backups.append({
                        "name": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "size_human": format_size(f.stat().st_size),
                        "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "kind": "backup",
                    })
                for f in sorted(BACKUP_DIR.glob("snapshot_*.txt"), reverse=True)[:20]:
                    backups.append({
                        "name": f.name,
                        "path": str(f),
                        "size": f.stat().st_size,
                        "size_human": format_size(f.stat().st_size),
                        "time": datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "kind": "snapshot",
                    })
            self._send_json({"backups": backups})
            return

        if path == "/api/job":
            job_id = qs.get("id", [""])[0]
            with _lock:
                job = _jobs.get(job_id)
            if not job:
                self._send_json({"error": "任务不存在"}, 404)
                return
            self._send_json(job)
            return

        if path == "/api/search":
            q = qs.get("q", [""])[0].strip()
            if not q:
                self._send_json({"results": []})
                return
            self._send_json({"results": self._cross_search(q)})
            return

        if path == "/api/diagnose/export":
            env_id = qs.get("env_id", [""])[0]
            deep = qs.get("deep", ["0"])[0] == "1"
            env = get_env_by_id(env_id)
            if not env:
                self._send_json({"error": "环境不存在"}, 404)
                return
            issues = diagnose_environment(env["path"], deep=deep)
            self._send_json({"report": self._build_report(env, issues), "issues": issues})
            return

        # ============================================================
        #  V3.0 新增 API
        # ============================================================
        if path == "/api/hardware":
            force = qs.get("wait", ["0"])[0] == "1"
            self._send_json(get_hardware_info(force=force))
            return

        if path == "/api/system/stats":
            self._send_json(get_system_stats())
            return

        if path == "/api/ports":
            self._send_json({"ports": get_listening_ports()})
            return

        if path == "/api/languages":
            force = qs.get("wait", ["0"])[0] == "1"
            self._send_json({"languages": detect_languages(force=force), "pending": _lang_refreshing})
            return

        if path == "/api/git/repos":
            self._send_json({"repos": scan_git_repos()})
            return

        if path == "/api/git/detail":
            gp = qs.get("path", [""])[0]
            self._send_json(git_repo_detail(gp))
            return

        if path == "/api/project/detect":
            self._send_json(detect_project_runtime(qs.get("path", [""])[0]))
            return

        if path == "/api/sqlite/tables":
            self._send_json(sqlite_tables(qs.get("path", [""])[0]))
            return

        if path == "/api/security/scan":
            env = get_env_by_id(qs.get("env_id", [""])[0])
            if not env:
                self._send_json({"error": "环境不存在"}, 404)
                return
            self._send_json(security_scan_env(env))
            return

        if path == "/api/pypi/info":
            self._send_json(pypi_package_info((qs.get("name") or [""])[0]))
            return

        if path == "/api/devtools/json" and qs.get("q"):
            import json as _json
            try:
                parsed = _json.loads(qs["q"][0])
                self._send_json({"ok": True, "result": _json.dumps(parsed, indent=2, ensure_ascii=False)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)})
            return

        if path == "/api/disk/overview":
            self._send_json(disk_overview())
            return

        if path == "/api/disk/tree":
            self._send_json(disk_tree((qs.get("path") or [""])[0]))
            return

        if path == "/api/undo":
            load_undo_stack()
            self._send_json({"items": _undo_stack[:12]})
            return

        if path == "/api/plugins":
            items = [{"id": k, **v} for k, v in PLUGIN_MANIFEST.items()]
            self._send_json({"plugins": items})
            return

        if path.startswith("/api/plugin/"):
            parts = [p for p in path.split("/") if p]
            if len(parts) == 3:
                pid = parts[2]
                spec = PLUGIN_MANIFEST.get(pid)
                if not spec:
                    self._send_json({"error": "未知插件"}, 404)
                    return
                self._send_json({"ok": True, "id": pid, **spec})
                return
            if len(parts) >= 4:
                data, code = plugin_dispatch(parts[2], parts[3], qs)
                self._send_json(data, code)
                return

        self._send_json({"error": "未知接口"}, 404)

    # ---------- POST ----------
    def do_POST(self):
        if not self._guard(mutating=True):
            return
        parsed = urlparse(self.path)
        path = parsed.path
        body = self._read_body()
        if body is None:
            return

        routes = {
            "/api/shutdown": self._handle_shutdown,
            "/api/rescan": self._handle_rescan,
            "/api/diagnose": self._handle_diagnose,
            "/api/fix": self._handle_fix,
            "/api/export": self._handle_export,
            "/api/cache/purge": self._handle_cache_purge,
            "/api/cache/purge-files": self._handle_cache_purge_files,
            "/api/venv/create": self._handle_create_venv,
            "/api/venv/clone": self._handle_clone_venv,
            "/api/venv/delete": self._handle_delete_venv,
            "/api/package/upgrade": self._handle_upgrade,
            "/api/package/uninstall": self._handle_uninstall,
            "/api/package/install-version": self._handle_install_version,
            "/api/compare": self._handle_compare,
            "/api/backup": self._handle_backup,
            "/api/rollback": self._handle_rollback,
            "/api/set-default": self._handle_set_default,
            "/api/path/reorder": self._handle_path_reorder,
            "/api/open-dir": self._handle_open_dir,
            "/api/launch-bat": self._handle_launch_bat,
            "/api/process/kill": self._handle_kill_process,
            "/api/db/probe": self._handle_db_probe,
            "/api/sqlite/query": self._handle_sqlite_query,
            "/api/snapshot": self._handle_snapshot,
            "/api/undo": self._handle_undo,
            "/api/snapshot/compare": self._handle_snapshot_compare,
            "/api/package/install": self._handle_install,
            "/api/requirements/import": self._handle_req_import,
            "/api/http/probe": self._handle_http_probe,
            "/api/notes/save": self._handle_note_save,
            "/api/notes/delete": self._handle_note_delete,
            "/api/ai/config": self._handle_ai_config,
            "/api/ai/chat": self._handle_ai_chat,
            "/api/ai/chat-stream": self._handle_ai_chat_stream,
            "/api/ai/test": self._handle_ai_test,
            "/api/kata/run": self._handle_kata_run,
            "/api/ui-prefs": self._handle_ui_prefs,
        }
        handler = routes.get(path)
        if handler:
            try:
                handler(body)
            except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                pass
            except Exception as e:
                log_op("接口异常 %s: %s" % (path, e))
                try:
                    self._send_json({"error": "服务器内部错误: %s" % e}, 500)
                except Exception:
                    pass
        else:
            self._send_json({"error": "未知接口"}, 404)

    # ---------- API 实现 ----------
    def _api_overview(self):
        with _env_lock:
            envs = list(_env_cache)
        total_envs = len(envs)
        venv_count = sum(1 for e in envs if e["type"] in ("venv", "Conda"))
        total_pkgs = sum(e.get("package_count", 0) for e in envs)
        cache_total, cache_human = unique_pip_cache_total()
        avg_health = round(sum(e.get("health", {}).get("score", 0) for e in envs) / max(total_envs, 1))
        return {
            "total_environments": total_envs,
            "virtual_environments": venv_count,
            "cache_size": cache_total,
            "cache_size_human": cache_human,
            "total_packages": total_pkgs,
            "avg_health": avg_health,
            "scan_time": datetime.now().strftime("%H:%M:%S"),
            "scanning": bool(_scan_status.get("scanning")),
            "scan_message": _scan_status.get("message") or "",
            "scan_progress": int(_scan_status.get("progress") or 0),
            "cache_pending": _pip_refreshing,
        }

    def _cross_search(self, q):
        results = []
        q_lower = q.lower()
        with _env_lock:
            envs = list(_env_cache)
        for env in envs:
            pkgs = list_packages(env["path"])
            for p in pkgs:
                if q_lower in p["name"].lower():
                    results.append({
                        "env": env["id"], "env_type": env["type"],
                        "env_path": env["path"], "env_version": env["version"],
                        "package": p["name"], "version": p["version"],
                    })
        return results

    def _handle_rescan(self, body):
        def do_scan():
            global _env_cache
            with _pkg_cache_lock:
                _pkg_cache.clear()
            envs = scan_environments()
            with _env_lock:
                _env_cache = envs
            log_op(f"重新扫描完成, 发现 {len(envs)} 个环境")
        threading.Thread(target=do_scan, daemon=True).start()
        self._send_json({"ok": True, "message": "扫描已启动"})

    def _handle_diagnose(self, body):
        env_id = body.get("env_id", "")
        deep = body.get("deep", False)
        env = get_env_by_id(env_id)
        if not env:
            self._send_json({"error": "环境不存在"}, 404)
            return
        issues = diagnose_environment(env["path"], deep=deep)
        log_op(f"诊断环境: {env['path']} ({'深度' if deep else '快速'}), 发现 {len(issues)} 个问题")
        self._send_json({"issues": issues})

    def _build_report(self, env, issues):
        """生成 Markdown 诊断报告"""
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        lines = [
            f"# Python 环境诊断报告",
            f"",
            f"**生成时间**: {ts}",
            f"**环境类型**: {env['type']}",
            f"**Python 版本**: {env['version']}",
            f"**pip 版本**: {env['pip_version']}",
            f"**安装路径**: `{env['path']}`",
            f"**包数量**: {env['package_count']}",
            f"**健康度**: {env.get('health', {}).get('score', '?')}/100 ({env.get('health', {}).get('level', '?')})",
            f"",
            f"---",
            f"",
        ]
        if not issues:
            lines.append("## ✅ 未发现问题\n\n当前环境状态良好。\n")
        else:
            high = [i for i in issues if i["level"] == "高"]
            mid = [i for i in issues if i["level"] == "中"]
            low = [i for i in issues if i["level"] == "低"]
            lines.append(f"## 概览\n\n- 🔴 高风险: {len(high)}\n- 🟡 中风险: {len(mid)}\n- 🔵 低风险: {len(low)}\n")
            for level_name, group in [("高风险", high), ("中风险", mid), ("低风险", low)]:
                if group:
                    lines.append(f"## {level_name}问题\n")
                    for i, iss in enumerate(group, 1):
                        lines.append(f"### {i}. {iss['type']}\n")
                        lines.append(f"- **描述**: {iss['description']}")
                        lines.append(f"- **影响**: {iss['impact']}")
                        lines.append(f"- **建议**: {iss['fix']}")
                        if iss.get("explanation"):
                            lines.append(f"- **原理**: {iss['explanation']}")
                        lines.append("")
        lines.append("---\n*报告由 Avenger V4.0 全景工作台自动生成*\n")
        return "\n".join(lines)

    def _handle_fix(self, body):
        env_id = body.get("env_id", "")
        fix_cmd = body.get("fix_cmd", "")
        env = get_env_by_id(env_id)
        if not env:
            self._send_json({"error": "环境不存在"}, 404)
            return

        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": "", "returncode": None}

        if fix_cmd == "uninstall_orphans":
            orphans = [safe_pkg_name(o) for o in body.get("orphans", [])]
            orphans = [o for o in orphans if o]
            if not orphans:
                self._send_json({"error": "未指定要卸载的包或包名不合法"}, 400)
                return
            args = [env["path"], "-m", "pip", "uninstall", "-y"] + orphans
        elif fix_cmd == "remove_residuals":
            residuals = body.get("residuals", [])
            site = body.get("site", "")
            if not site or not os.path.isdir(site):
                self._send_json({"error": "site-packages 目录无效"}, 400)
                return
            results = []
            for r in residuals:
                if not re.match(r"^[^\\/:*?\"<>|]{1,120}$", str(r)):
                    results.append({"item": r, "success": False, "error": "名称不合法"})
                    continue
                rp = os.path.join(site, str(r))
                if not os.path.abspath(rp).startswith(os.path.abspath(site) + os.sep):
                    results.append({"item": r, "success": False, "error": "路径越界"})
                    continue
                try:
                    if os.path.isdir(rp):
                        shutil.rmtree(rp)
                    elif os.path.isfile(rp):
                        os.remove(rp)
                    results.append({"item": r, "success": True})
                    log_op(f"删除残留: {rp}")
                except OSError as e:
                    results.append({"item": r, "success": False, "error": str(e)})
            self._send_json({"results": results})
            return
        else:
            # fix_cmd 形如 "install <pkg>" / "install --upgrade pip"，逐 token 校验
            toks = str(fix_cmd or "").replace('"', "").replace("'", "").split()
            if not toks or toks[0] not in ("install", "check") or len(toks) > 12:
                self._send_json({"error": "不支持的修复命令"}, 400)
                return
            for t in toks[1:]:
                if not re.match(r"^(--[A-Za-z0-9\-]+|[A-Za-z0-9][A-Za-z0-9._=<>!~+\[\],\-]*)$", t):
                    self._send_json({"error": "修复命令参数不合法"}, 400)
                    return
            args = [env["path"], "-m", "pip"] + toks

        log_op(f"执行修复: {' '.join(args)}")
        threading.Thread(target=run_cmd_streaming, args=(args, job_id), daemon=True).start()
        self._send_json({"job_id": job_id})

    def _handle_export(self, body):
        env_id = body.get("env_id", "")
        env = get_env_by_id(env_id)
        if not env:
            self._send_json({"error": "环境不存在"}, 404)
            return
        desktop = os.path.join(os.path.expanduser("~"), "Desktop")
        if not os.path.isdir(desktop):
            desktop = os.path.expanduser("~")
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        outfile = os.path.join(desktop, f"requirements_{env['type']}_{ts}.txt")
        rc, out, err = run_cmd([env["path"], "-m", "pip", "freeze"], timeout=30)
        if rc == 0:
            with open(outfile, "w", encoding="utf-8") as f:
                f.write(out)
            log_op(f"导出 requirements: {outfile}")
            self._send_json({"ok": True, "path": outfile, "count": len(out.splitlines())})
        else:
            self._send_json({"error": f"导出失败: {err}"}, 500)

    def _handle_cache_purge(self, body):
        env_id = body.get("env_id", "")
        env = get_env_by_id(env_id)
        if not env:
            self._send_json({"error": "环境不存在"}, 404)
            return
        rc, out, err = run_cmd([env["path"], "-m", "pip", "cache", "purge"], timeout=30)
        log_op(f"清理pip缓存: {out or err}")
        self._send_json({"ok": rc == 0, "output": out or err})

    def _handle_cache_purge_files(self, body):
        """选择性清理缓存文件（仅允许白名单目录内的路径）"""
        files = body.get("files", [])
        results = []
        freed = 0
        for fp in files:
            fp = str(fp or "")
            if not is_scan_path_allowed(fp) or path_is_blocked(fp):
                results.append({"file": fp, "success": False, "error": "路径不在可清理白名单内"})
                continue
            try:
                size = os.path.getsize(fp) if os.path.isfile(fp) else 0
                if os.path.isfile(fp):
                    os.remove(fp)
                    freed += size
                    results.append({"file": fp, "success": True})
                elif os.path.isdir(fp):
                    shutil.rmtree(fp)
                    freed += size
                    results.append({"file": fp, "success": True})
            except OSError as e:
                results.append({"file": fp, "success": False, "error": str(e)})
        log_op(f"选择性清理缓存: 释放 {format_size(freed)}")
        self._send_json({"ok": True, "results": results, "freed": freed, "freed_human": format_size(freed)})

    def _handle_create_venv(self, body):
        base_python = body.get("python_path", "")
        target_dir = body.get("target_dir", "")
        name = body.get("name", "")
        system_site = body.get("system_site", False)
        presets = body.get("presets", [])
        if not all([base_python, target_dir, name]):
            self._send_json({"error": "参数不完整"}, 400)
            return
        venv_path = os.path.join(target_dir, name)
        if os.path.exists(venv_path):
            self._send_json({"error": "目标目录已存在"}, 400)
            return
        args = [base_python, "-m", "venv"]
        if system_site:
            args.append("--system-site-packages")
        args.append(venv_path)
        rc, out, err = run_cmd(args, timeout=60)
        if rc == 0 and os.path.isfile(os.path.join(venv_path, "Scripts", "python.exe")):
            # 安装预设包
            venv_python = os.path.join(venv_path, "Scripts", "python.exe")
            if presets:
                run_cmd([venv_python, "-m", "pip", "install"] + presets, timeout=120)
            log_op(f"创建venv: {venv_path}" + (f" (含预设: {', '.join(presets)})" if presets else ""))
            self._send_json({"ok": True, "path": venv_path})
        else:
            self._send_json({"error": f"创建失败: {err}"}, 500)

    def _handle_clone_venv(self, body):
        """克隆虚拟环境"""
        source_env_id = body.get("source_env_id", "")
        target_dir = body.get("target_dir", "")
        name = body.get("name", "")
        source_env = get_env_by_id(source_env_id)
        if not source_env or not target_dir or not name:
            self._send_json({"error": "参数不完整"}, 400)
            return
        target_path = os.path.join(target_dir, name)
        if os.path.exists(target_path):
            self._send_json({"error": "目标目录已存在"}, 400)
            return
        # 1. 导出源环境包列表
        rc, freeze_out, err = run_cmd([source_env["path"], "-m", "pip", "freeze"], timeout=60)
        if rc != 0:
            self._send_json({"error": f"导出源环境失败: {err}"}, 500)
            return
        # 2. 创建新 venv
        rc, _, err = run_cmd([source_env["path"], "-m", "venv", target_path], timeout=60)
        if rc != 0:
            self._send_json({"error": f"创建venv失败: {err}"}, 500)
            return
        # 3. 在新环境中安装包
        venv_python = os.path.join(target_path, "Scripts", "python.exe")
        req_file = os.path.join(target_path, "_clone_requirements.txt")
        with open(req_file, "w", encoding="utf-8") as f:
            f.write(freeze_out)
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": f"正在克隆 {source_env['type']} 环境到 {target_path}...\n"}
        args = [venv_python, "-m", "pip", "install", "-r", req_file]
        log_op(f"克隆环境: {source_env['path']} -> {target_path}")
        threading.Thread(target=run_cmd_streaming, args=(args, job_id), daemon=True).start()
        self._send_json({"ok": True, "job_id": job_id, "path": target_path})

    def _handle_delete_venv(self, body):
        env_id = body.get("env_id", "")
        env = get_env_by_id(env_id)
        if not env or env["type"] not in ("venv", "Conda"):
            self._send_json({"error": "只能删除虚拟环境"}, 400)
            return
        venv_dir = str(Path(env["path"]).parent.parent) if "Scripts" in env["path"] else str(Path(env["path"]).parent)
        try:
            shutil.rmtree(venv_dir)
            log_op(f"删除虚拟环境: {venv_dir}")
            self._send_json({"ok": True})
        except OSError as e:
            self._send_json({"error": str(e)}, 500)

    def _handle_upgrade(self, body):
        env_id = body.get("env_id", "")
        packages = [safe_pkg_name(p) for p in (body.get("packages") or [])]
        packages = [p for p in packages if p][:40]
        env = get_env_by_id(env_id)
        if not env or not packages:
            self._send_json({"error": "参数不完整或包名不合法"}, 400)
            return
        specs = []
        for name in packages:
            info = package_details(env["path"], name)
            ver = (info or {}).get("Version") or ""
            if ver:
                specs.append(f"{name}=={ver}")
        undo = push_undo({"type": "upgrade", "env_id": env_id, "specs": specs, "label": "升级 " + ", ".join(packages[:6])}) if specs else None
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": "", "returncode": None}
        args = [env["path"], "-m", "pip", "install", "--upgrade"] + packages
        log_op(f"批量升级: {', '.join(packages)}")
        threading.Thread(target=run_cmd_streaming, args=(args, job_id), daemon=True).start()
        self._send_json({"job_id": job_id, "undo": undo})

    def _handle_uninstall(self, body):
        env_id = body.get("env_id", "")
        package = safe_pkg_name(body.get("package"))
        env = get_env_by_id(env_id)
        if not env or not package:
            self._send_json({"error": "参数不完整或包名不合法"}, 400)
            return
        info = package_details(env["path"], package)
        ver = (info or {}).get("Version", "")
        spec = f"{package}=={ver}" if ver else package
        rc, out, err = run_cmd([env["path"], "-m", "pip", "uninstall", "-y", package], timeout=30)
        log_op(f"卸载包: {package} ({'成功' if rc == 0 else '失败'})")
        undo = None
        if rc == 0:
            undo = push_undo({"type": "uninstall", "env_id": env_id, "package": package, "spec": spec, "label": f"卸载 {spec}"})
        self._send_json({"ok": rc == 0, "output": out or err, "undo": undo})

    def _handle_install_version(self, body):
        """安装指定版本的包"""
        env_id = body.get("env_id", "")
        package = safe_pkg_name(body.get("package"))
        version = str(body.get("version") or "").strip()
        if version and not _PKG_VER_RE.match(version):
            version = ""
        env = get_env_by_id(env_id)
        if not env or not package or not version:
            self._send_json({"error": "参数不完整或包名不合法"}, 400)
            return
        info = package_details(env["path"], package)
        old = (info or {}).get("Version") or ""
        undo = None
        if old:
            undo = push_undo({"type": "install_version", "env_id": env_id, "spec": f"{package}=={old}", "label": f"版本 {package} {old}←{version}"})
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": f"正在安装 {package}=={version}...\n", "returncode": None}
        args = [env["path"], "-m", "pip", "install", f"{package}=={version}"]
        log_op(f"安装指定版本: {package}=={version}")
        threading.Thread(target=run_cmd_streaming, args=(args, job_id), daemon=True).start()
        self._send_json({"job_id": job_id, "undo": undo})

    def _handle_install(self, body):
        env_id = body.get("env_id", "")
        package = (body.get("package") or "").strip()
        env = get_env_by_id(env_id)
        if not env or not package:
            self._send_json({"error": "参数不完整"}, 400)
            return
        spec = package.replace(" ", "")
        if not safe_pkg_spec(spec):
            self._send_json({"error": "包名不合法（示例：requests 或 requests==2.32.3）"}, 400)
            return
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": "正在安装 %s...\n" % spec, "returncode": None}
        log_op("安装包: %s" % spec)
        threading.Thread(
            target=run_cmd_streaming,
            args=([env["path"], "-m", "pip", "install", spec], job_id),
            daemon=True,
        ).start()
        self._send_json({"job_id": job_id})

    def _handle_req_import(self, body):
        env_id = body.get("env_id", "")
        env = get_env_by_id(env_id)
        lines = sanitize_requirement_lines(body.get("text") or "")
        if not env or not lines:
            self._send_json({"error": "没有可导入的包行（已忽略 URL 与 pip 选项）"}, 400)
            return
        req_path = BACKUP_DIR / ("import_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        req_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": "从 requirements 安装 %d 行...\n" % len(lines), "returncode": None}
        log_op("导入 requirements: %s (%d)" % (req_path, len(lines)))
        threading.Thread(
            target=run_cmd_streaming,
            args=([env["path"], "-m", "pip", "install", "-r", str(req_path)], job_id),
            daemon=True,
        ).start()
        self._send_json({"job_id": job_id, "count": len(lines), "path": str(req_path)})

    def _handle_http_probe(self, body):
        raw_url = (body or {}).get("url") or ""
        method = ((body or {}).get("method") or "GET").upper()
        if method not in ("GET", "HEAD"):
            self._send_json({"ok": False, "error": "仅允许 GET / HEAD"}, 400)
            return
        parsed = urlparse(raw_url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or host not in ("127.0.0.1", "localhost", "::1"):
            self._send_json({"ok": False, "error": "仅允许探测本机 127.0.0.1 / localhost"}, 400)
            return
        if parsed.port and parsed.port == 0:
            self._send_json({"ok": False, "error": "端口无效"}, 400)
            return
        try:
            req = Request(raw_url, method=method, headers={"User-Agent": "Avenger-Local/4.0"})
            with urlopen(req, timeout=8) as resp:
                status = getattr(resp, "status", 200)
                headers = {k: v for k, v in list(resp.headers.items())[:24]}
                raw = resp.read(200000) if method == "GET" else b""
            text = raw.decode("utf-8", "replace")
            self._send_json({
                "ok": True,
                "status": status,
                "headers": headers,
                "body": text[:8000],
                "truncated": len(text) >= 8000,
                "bytes": len(raw),
            })
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)})

    def _handle_note_save(self, body):
        if not studio:
            self._send_json({"ok": False, "error": "studio 模块缺失"}, 500)
            return
        self._send_json(studio.notes_save(BASE_DIR, body or {}))

    def _handle_note_delete(self, body):
        if not studio:
            self._send_json({"ok": False, "error": "studio 模块缺失"}, 500)
            return
        nid = (body or {}).get("id") or ""
        if not nid:
            self._send_json({"ok": False, "error": "缺少 id"}, 400)
            return
        self._send_json(studio.notes_delete(BASE_DIR, nid))

    def _handle_ai_config(self, body):
        if not studio:
            self._send_json({"ok": False, "error": "studio 模块缺失"}, 500)
            return
        self._send_json(studio.ai_save_config(BASE_DIR, body or {}))

    def _handle_ai_chat(self, body):
        if not studio:
            self._send_json({"ok": False, "error": "studio 模块缺失"}, 500)
            return
        self._send_json(studio.ai_chat(BASE_DIR, body or {}, log_op=log_op))

    def _handle_ai_chat_stream(self, body):
        """流式 AI 对话：不设 Content-Length，写完即关连接，前端用 ReadableStream 读取。"""
        if not studio:
            self._send_json({"ok": False, "error": "studio 模块缺失"}, 500)
            return
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-cache, no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            try:
                for chunk in studio.ai_chat_stream(BASE_DIR, body or {}, log_op=log_op):
                    try:
                        self.wfile.write(chunk.encode("utf-8"))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
                        return
            except ValueError as e:
                try:
                    self.wfile.write(("\n[错误] %s" % e).encode("utf-8"))
                except OSError:
                    pass
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return
        except Exception as e:
            try:
                self._send_json({"ok": False, "error": str(e)[:300]}, 500)
            except Exception:
                pass

    def _handle_ai_test(self, body):
        if not studio:
            self._send_json({"ok": False, "error": "studio 模块缺失"}, 500)
            return
        self._send_json(studio.ai_test(BASE_DIR, body or {}))

    def _handle_kata_run(self, body):
        if not studio:
            self._send_json({"ok": False, "error": "studio 模块缺失"}, 500)
            return
        env_id = (body or {}).get("env_id") or ""
        env = get_env_by_id(env_id) if env_id else None
        exe = (env or {}).get("path") or sys.executable
        kid = (body or {}).get("id") or ""
        code = (body or {}).get("code") or ""
        result = studio.kata_run(exe, kid, code)
        if result.get("passed"):
            log_op("练习通过 · " + kid)
        self._send_json(result)

    def _handle_ui_prefs(self, body):
        data = load_ui_prefs()
        body = body or {}
        if "pet" in body:
            data["pet"] = str(body.get("pet") or "ember")[:24]
        if "skin" in body:
            data["skin"] = str(body.get("skin") or "ember")[:24]
        if "skinAccent" in body:
            data["skinAccent"] = str(body.get("skinAccent") or "")[:16]
        save_ui_prefs(data)
        self._send_json({"ok": True, "prefs": data})

    def _handle_compare(self, body):
        """多环境对比 (支持2-3个)"""
        env_ids = body.get("envs", [])
        if len(env_ids) < 2:
            # 兼容旧格式
            env_ids = [body.get("env1", ""), body.get("env2", "")]
        envs = [get_env_by_id(eid) for eid in env_ids if eid]
        if len(envs) < 2:
            self._send_json({"error": "至少需要2个有效环境"}, 400)
            return
        pkg_maps = []
        for env in envs:
            pkgs = list_packages(env["path"])
            pkg_maps.append({p["name"].lower(): {"name": p["name"], "version": p["version"]} for p in pkgs})

        all_names = set()
        for pm in pkg_maps:
            all_names.update(pm.keys())

        comparison = []
        for name in sorted(all_names):
            row = {"package": name}
            versions = []
            for i, pm in enumerate(pkg_maps):
                if name in pm:
                    row[f"v{i}"] = pm[name]["version"]
                    versions.append(pm[name]["version"])
                else:
                    row[f"v{i}"] = None
            unique_versions = set(v for v in versions if v)
            row["status"] = "identical" if len(unique_versions) <= 1 else "diff"
            row["missing_in"] = [i for i in range(len(pkg_maps)) if row[f"v{i}"] is None]
            comparison.append(row)

        diff_count = sum(1 for r in comparison if r["status"] == "diff")
        self._send_json({
            "envs": [{"id": e["id"], "type": e["type"], "version": e["version"]} for e in envs],
            "comparison": comparison,
            "diff_count": diff_count,
        })

    def _handle_backup(self, body):
        env_id = body.get("env_id", "")
        env = get_env_by_id(env_id)
        if not env:
            self._send_json({"error": "环境不存在"}, 404)
            return
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = BACKUP_DIR / f"backup_{env['type']}_{ts}.txt"
        rc, out, err = run_cmd([env["path"], "-m", "pip", "freeze"], timeout=30)
        if rc == 0:
            with open(backup_file, "w", encoding="utf-8") as f:
                f.write(out)
            self._send_json({"ok": True, "path": str(backup_file), "count": len(out.splitlines())})
        else:
            self._send_json({"error": err}, 500)

    def _handle_rollback(self, body):
        """从备份文件回滚"""
        env_id = body.get("env_id", "")
        backup_path = body.get("backup_path", "")
        env = get_env_by_id(env_id)
        if not env or not backup_path or not os.path.isfile(backup_path):
            self._send_json({"error": "参数无效"}, 400)
            return
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": f"正在从备份回滚: {backup_path}\n", "returncode": None}
        args = [env["path"], "-m", "pip", "install", "-r", backup_path]
        log_op(f"回滚环境: {env['path']} <- {backup_path}")
        threading.Thread(target=run_cmd_streaming, args=(args, job_id), daemon=True).start()
        self._send_json({"job_id": job_id})

    def _handle_set_default(self, body):
        env_id = body.get("env_id", "")
        env = get_env_by_id(env_id)
        if not env:
            self._send_json({"error": "环境不存在"}, 404)
            return
        target_dir = env["dir"]
        current = get_user_path()
        parts = [p for p in current.split(os.pathsep) if p]
        parts = [p for p in parts if os.path.normcase(os.path.normpath(p)) != os.path.normcase(os.path.normpath(target_dir))]
        parts.insert(0, target_dir)
        new_path = os.pathsep.join(parts)
        if set_user_path(new_path):
            log_op(f"设置默认Python: {target_dir}")
            self._send_json({"ok": True})
        else:
            self._send_json({"error": "修改PATH失败"}, 500)

    def _handle_path_reorder(self, body):
        """拖拽重排 PATH 中的 Python 目录顺序"""
        ordered_dirs = body.get("order", [])
        if not ordered_dirs:
            self._send_json({"error": "未提供顺序"}, 400)
            return
        current = get_user_path()
        current_parts = [p for p in current.split(os.pathsep) if p]
        # 分离 Python 相关目录和其他目录
        python_dirs_norm = set(os.path.normcase(os.path.normpath(d)) for d in ordered_dirs)
        other_parts = [p for p in current_parts if os.path.normcase(os.path.normpath(p)) not in python_dirs_norm]
        # 按新顺序排列 Python 目录, 其他目录保持在后面
        new_parts = ordered_dirs + other_parts
        new_path = os.pathsep.join(new_parts)
        if set_user_path(new_path):
            undo = push_undo({"type": "path_reorder", "previous": current, "label": "PATH 重排"})
            log_op(f"重排PATH优先级: {', '.join(ordered_dirs)}")
            self._send_json({"ok": True, "undo": undo})
        else:
            self._send_json({"error": "修改PATH失败"}, 500)

    def _handle_shutdown(self, body=None):
        log_op("收到关闭请求")
        self._send_json({"ok": True})
        threading.Thread(target=self._delayed_shutdown, daemon=True).start()

    def _handle_open_dir(self, body):
        target = body.get("path", "")
        if path_is_blocked(target):
            log_op(f"拒绝打开敏感目录: {target}")
            self._send_json({"ok": False, "error": "拒绝打开系统敏感目录"})
            return
        if not target or not os.path.isdir(target):
            self._send_json({"ok": False, "error": "目录不存在"})
            return
        try:
            os.startfile(target)
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)})

    def _handle_launch_bat(self, body=None):
        bat_path = os.path.join(BASE_DIR, "PythonEnvManager.bat")
        if not os.path.isfile(bat_path):
            self._send_json({"ok": False, "error": "未找到 PythonEnvManager.bat"})
            return
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "cmd", "/k", bat_path],
                cwd=BASE_DIR,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)})

    def _handle_kill_process(self, body):
        """V3: 终止指定进程"""
        pid = body.get("pid")
        if not pid:
            self._send_json({"ok": False, "error": "缺少 PID"}, 400)
            return
        try:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=10,
                           creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
            log_op(f"终止进程 PID={pid}")
            self._send_json({"ok": True})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)})

    def _handle_db_probe(self, body):
        self._send_json(probe_db_port(body.get("host") or "127.0.0.1", body.get("port") or 0, body.get("type") or ""))

    def _handle_sqlite_query(self, body):
        self._send_json(sqlite_preview(body.get("path") or "", body.get("table") or ""))

    def _handle_snapshot(self, body):
        env = get_env_by_id(body.get("env_id", ""))
        if not env:
            self._send_json({"ok": False, "error": "环境不存在"}, 404)
            return
        full = bool(body.get("full"))
        job_id = str(uuid.uuid4())[:8]
        with _lock:
            _jobs[job_id] = {"status": "pending", "output": "", "returncode": None}
        def work():
            try:
                with _lock:
                    _jobs[job_id]["status"] = "running"
                    _jobs[job_id]["output"] += "正在导出 requirements...\n"
                path = create_env_snapshot(env, full=full)
                with _lock:
                    _jobs[job_id]["output"] += f"快照已写入\n{path}\n"
                    _jobs[job_id]["status"] = "success"
                    _jobs[job_id]["returncode"] = 0
                log_op(f"环境快照 {env.get('path')} -> {path}")
            except Exception as e:
                with _lock:
                    _jobs[job_id]["status"] = "failed"
                    _jobs[job_id]["output"] += f"\n[错误] {e}"
                    _jobs[job_id]["returncode"] = 1
        threading.Thread(target=work, daemon=True).start()
        self._send_json({"ok": True, "job_id": job_id})

    def _handle_undo(self, body):
        uid = (body or {}).get("id") or ""
        result = apply_undo(uid)
        code = 200 if result.get("ok") else 400
        self._send_json(result, code)

    def _handle_snapshot_compare(self, body):
        a = (body or {}).get("path_a") or ""
        b = (body or {}).get("path_b") or ""
        if path_is_blocked(a) or path_is_blocked(b):
            self._send_json({"ok": False, "error": "拒绝敏感路径"}, 400)
            return
        if not os.path.isfile(a) or not os.path.isfile(b):
            self._send_json({"ok": False, "error": "文件不存在"}, 400)
            return
        bak = os.path.normcase(str(BACKUP_DIR.resolve()))
        if os.path.normcase(str(Path(a).resolve().parent)) != bak or os.path.normcase(str(Path(b).resolve().parent)) != bak:
            self._send_json({"ok": False, "error": "仅允许对比 backups 目录内文件"}, 400)
            return

        def parse_req(p):
            pkgs = {}
            try:
                text = Path(p).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return pkgs
            for line in text.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "==" in line:
                    n, v = line.split("==", 1)
                    pkgs[n.strip().lower()] = v.strip()
                else:
                    pkgs[line.lower()] = ""
            return pkgs

        pa, pb = parse_req(a), parse_req(b)
        names = sorted(set(pa) | set(pb))
        rows = []
        for n in names:
            va, vb = pa.get(n), pb.get(n)
            if va == vb:
                st = "same"
            elif va is None:
                st = "only_b"
            elif vb is None:
                st = "only_a"
            else:
                st = "diff"
            rows.append({"name": n, "a": va, "b": vb, "status": st})
        self._send_json({"ok": True, "rows": rows, "diff": sum(1 for r in rows if r["status"] != "same")})

    def _delayed_shutdown(self):
        time.sleep(0.5)
        os._exit(0)


# ============================================================
#  启动
# ============================================================

def find_free_port(preferred=PORT):
    for p in range(preferred, preferred + 20):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind((HOST, p))
                return p
        except OSError:
            continue
    return preferred


def start_watchdog(server):
    def loop():
        while True:
            time.sleep(15)
            idle = time.time() - _last_heartbeat
            if idle > WATCHDOG_SEC:
                log_op(f"心跳超时 {int(idle)}s，自动关闭服务")
                try:
                    server.shutdown()
                except Exception:
                    pass
                os._exit(0)
    threading.Thread(target=loop, daemon=True, name="avenger-watchdog").start()


def _boot_scan():
    global _env_cache
    envs = scan_environments()
    with _env_lock:
        _env_cache = envs
    log_op("启动扫描完成, 发现 %d 个环境" % len(envs))
    _kick_pip_refresh()
    _kick_hw_refresh()
    _kick_lang_refresh()


def main():
    global PORT, _http_server, _last_heartbeat
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--no-hud", action="store_true")
    args, _unknown = parser.parse_known_args()

    _load_persisted_caches()
    PORT = find_free_port()
    _last_heartbeat = time.time()
    try:
        TOKEN_FILE.write_text(SESSION_TOKEN, encoding="utf-8")
    except Exception:
        pass

    port_file = os.path.join(BASE_DIR, "avenger_port.txt")
    try:
        with open(port_file, "w") as f:
            f.write(str(PORT))
    except Exception:
        pass

    _scan_status["scanning"] = True
    _scan_status["message"] = "启动扫描..."
    _scan_status["progress"] = 1
    print("=" * 56)
    print("   Avenger V4.0 - 全栈开发者全景工作台")
    print("   服务地址: http://%s:%s" % (HOST, PORT))
    print("   启动时间: %s" % datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("   关掉浏览器后由托管小窗保活；关掉小窗即停止服务")
    print("=" * 56)

    server = http.server.ThreadingHTTPServer((HOST, PORT), AvengerHandler)
    server.daemon_threads = True
    _http_server = server
    start_watchdog(server)
    threading.Thread(target=_jobs_gc_loop, daemon=True, name="jobs-gc").start()
    threading.Thread(target=_boot_scan, daemon=True, name="boot-scan").start()
    threading.Thread(target=server.serve_forever, daemon=True, name="http").start()

    if not args.no_browser:
        try:
            import webbrowser
            threading.Timer(0.35, lambda: webbrowser.open("http://%s:%s/" % (HOST, PORT))).start()
        except Exception:
            pass

    def cleanup():
        try:
            if os.path.isfile(port_file):
                os.remove(port_file)
            if TOKEN_FILE.exists():
                TOKEN_FILE.unlink()
        except Exception:
            pass

    if not args.no_hud:
        try:
            from avenger_hud import run_hud
            os.environ["AVENGER_PET"] = (load_ui_prefs().get("pet") or "ember")
            run_hud(HOST, PORT, SESSION_TOKEN, on_quit=lambda: os._exit(0))
            cleanup()
            try:
                server.shutdown()
            except Exception:
                pass
            os._exit(0)
        except Exception as e:
            log_op("托管小窗未能启动: %s" % e)
            print("[!] 托管小窗未能启动，服务仍在运行。关闭浏览器约 90 秒后会退出。")
            print("    原因: %s" % e)

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n[*] 正在停止服务...")
        try:
            server.shutdown()
        except Exception:
            pass
    finally:
        cleanup()


if __name__ == "__main__":
    main()
