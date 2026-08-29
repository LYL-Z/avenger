@echo off
chcp 65001 >nul 2>&1
title Avenger V3.3 启动器
setlocal enabledelayedexpansion

:: 启动后立即退出控制台。服务由「Avenger 托管」小窗保活。
:: 关掉浏览器不会停服务；关掉托管小窗才会停止。

cd /d "%~dp0"

echo.
echo  Avenger V3.3 正在启动...
echo.

set "PYTHON_CMD="
set "PYTHONW="
for %%P in (pythonw python py) do (
    if not defined PYTHON_CMD (
        where %%P >nul 2>&1 && set "PYTHON_CMD=%%P"
    )
)
where pythonw >nul 2>&1 && set "PYTHONW=pythonw"

if not defined PYTHON_CMD (
    echo  [错误] 未检测到 Python 3.8+
    echo  下载: https://www.python.org/downloads/
    pause
    exit /b 1
)

if exist "avenger_port.txt" del /q "avenger_port.txt" >nul 2>&1

if defined PYTHONW (
    start "Avenger-HUD" /min %PYTHONW% avenger_server.py
) else (
    start "Avenger-HUD" /min %PYTHON_CMD% avenger_server.py
)

set "PORT=8765"
set "TRIES=0"
:wait_loop
set /a TRIES+=1
if !TRIES! GTR 40 (
    echo  [错误] 服务启动超时。请检查 Python 是否带 tkinter。
    pause
    exit /b 1
)
if exist "avenger_port.txt" (
    set /p PORT=<avenger_port.txt
    goto :ready
)
timeout /t 1 /nobreak >nul
goto :wait_loop

:ready
echo  [√] 工作台: http://127.0.0.1:!PORT!/
echo  [√] 右下角「Avenger 托管」小窗负责后台保活
echo  [√] 关掉浏览器没关系；关掉小窗才停止服务
echo.
timeout /t 2 /nobreak >nul
endlocal
exit /b 0
