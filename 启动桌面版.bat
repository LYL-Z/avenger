@echo off
chcp 65001 >nul 2>&1
title Avenger Desktop
cd /d "%~dp0"
where pythonw >nul 2>&1 && set "PY=pythonw"
if not defined PY set "PY=python"
%PY% -c "import webview" >nul 2>&1
if not %errorlevel%==0 (
    echo [Avenger Desktop] 正在安装桌面组件 pywebview（仅一次）...
    %PY% -m pip install --quiet pywebview
)
echo [Avenger Desktop] 启动中...
start "" %PY% avenger_app.py
exit /b 0
