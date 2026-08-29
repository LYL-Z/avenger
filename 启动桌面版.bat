@echo off
chcp 65001 >nul 2>&1
title Avenger Desktop
cd /d "%~dp0"

echo ============================================
echo   Avenger Desktop 启动器
echo ============================================

set "PY="
where python >nul 2>&1 && set "PY=python"
if not defined PY where py >nul 2>&1 && set "PY=py"
if not defined PY (
    echo [错误] 未检测到 Python，请先安装: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/3] 检测桌面组件 pywebview ...
%PY% -c "import webview" >nul 2>&1
if errorlevel 1 (
    echo       未安装，正在安装（仅一次，约 10-30 秒）...
    %PY% -m pip install --quiet pywebview
    %PY% -c "import webview" >nul 2>&1
    if errorlevel 1 (
        echo [!] pywebview 安装失败（网络原因？）。将使用浏览器模式启动。
    ) else (
        echo       pywebview 安装成功。
    )
) else (
    echo       pywebview 已就绪。
)

echo [2/3] 启动 Avenger 服务与窗口 ...
%PY% avenger_app.py
if errorlevel 1 (
    echo [!] 启动异常，请截图本窗口内容反馈。
    pause
)
echo [3/3] Avenger 已退出。
pause
