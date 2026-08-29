@echo off
chcp 65001 >nul 2>&1
setlocal enabledelayedexpansion

:: ============================================================
::  Python 环境全生命周期管理脚本 v1.0
::  适用系统: Windows 10 / 11 (x64)
::  兼容版本: Python 3.8 及以上 / Anaconda3 / Miniconda3
::  编写方式: 纯原生 BAT + Windows 内置命令, 零第三方依赖
::
::  功能概览:
::    1. 全景扫描  - 全局/conda/venv 环境无遗漏扫描
::    2. 包管理    - 已装包清单/依赖查询/requirements 导出
::    3. 智能诊断  - 版本冲突/冗余包/环境异常/依赖缺失
::    4. 交互修复  - 逐项确认后执行, 全程可取消
::    5. 附加工具  - venv 创建/批量升级/操作日志
::
::  免责声明:
::    本脚本所有修改类操作均需用户手动确认, 但作者不对
::    因使用本脚本造成的任何直接或间接损失承担责任。
::    建议在执行修复前备份重要环境。
:: ============================================================

title Python 环境全生命周期管理工具 v1.0

:: ---- 切换到脚本所在目录 ----
cd /d "%~dp0"

:: ---- 管理员权限检查与提权 ----
if "%~1"=="_ELEVATED_" (
    set "ELEVATED=1"
) else (
    net session >nul 2>&1
    if !errorlevel! neq 0 (
        echo 正在请求管理员权限...
        powershell -NoProfile -Command "Start-Process -FilePath cmd.exe -ArgumentList '/c \"\"%~f0\" _ELEVATED_\"' -Verb RunAs" <nul 2>nul
        if !errorlevel! neq 0 (
            echo 管理员权限获取失败, 部分系统级操作可能受限。
            pause
        )
        exit /b
    )
)

:: ---- 启用 ANSI 虚拟终端支持 (Windows 10 1511+) ----
set "VTPS=%TEMP%\_vt_enable_%RANDOM%.ps1"
> "%VTPS%" echo $code = @'
>> "%VTPS%" echo using System;
>> "%VTPS%" echo using System.Runtime.InteropServices;
>> "%VTPS%" echo public class VT {
>> "%VTPS%" echo   [DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int n);
>> "%VTPS%" echo   [DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr h, out uint m);
>> "%VTPS%" echo   [DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr h, uint m);
>> "%VTPS%" echo }
>> "%VTPS%" echo '@
>> "%VTPS%" echo Add-Type -TypeDefinition $code
>> "%VTPS%" echo try {
>> "%VTPS%" echo   $h = [VT]::GetStdHandle(-11);
>> "%VTPS%" echo   $m = 0;
>> "%VTPS%" echo   [void][VT]::GetConsoleMode($h, [ref]$m);
>> "%VTPS%" echo   [void][VT]::SetConsoleMode($h, $m -bor 4 -bor 8);
>> "%VTPS%" echo } catch {}
powershell -NoProfile -ExecutionPolicy Bypass -File "%VTPS%" <nul 2>nul
del "%VTPS%" >nul 2>&1

:: ---- 颜色定义 ----
:: 用 PowerShell 获取 ESC 字符 (避免子 cmd 进程消耗标准输入)
for /f "delims=" %%a in ('powershell -NoProfile -Command "[char]27" ^<nul 2^>nul') do set "ESC=%%a"
set "C_RED=%ESC%[91m"
set "C_GREEN=%ESC%[92m"
set "C_YELLOW=%ESC%[93m"
set "C_BLUE=%ESC%[94m"
set "C_MAGENTA=%ESC%[95m"
set "C_CYAN=%ESC%[96m"
set "C_WHITE=%ESC%[97m"
set "C_GRAY=%ESC%[90m"
set "C_BOLD=%ESC%[1m"
set "C_RESET=%ESC%[0m"

:: ---- 全局变量 ----
set "SCRIPT_DIR=%~dp0"
set "SCRIPT_DIR=!SCRIPT_DIR:~0,-1!"
set "LOG_FILE=!SCRIPT_DIR!\python_env_manager.log"
set "ENV_TEMP=%TEMP%\_pyenvs_%RANDOM%.tmp"
set "DIAG_TEMP=%TEMP%\_pydiag_%RANDOM%.tmp"
set "PKG_TEMP=%TEMP%\_pkglist_%RANDOM%.tmp"
set "OUTDATED_TEMP=%TEMP%\_pipout_%RANDOM%.tmp"
set "SELECTED_ENV_NUM="
set "SELECTED_PYTHON="
set "SELECTED_PYTHON_DIR="
set "SELECTED_ENV_TYPE="
set "ENV_COUNT=0"
set "ISSUE_COUNT=0"
set "PKG_COUNT=0"
set "PAGE_SIZE=15"

:: ---- 初始化日志 ----
call :InitLog

:: ============================================================
::  主菜单
:: ============================================================
:MainMenu
cls
call :PrintHeader "Python 环境全生命周期管理工具 v1.0"
echo.
echo   %C_CYAN%[1]%C_RESET%  扫描并选择 Python 环境
echo   %C_CYAN%[2]%C_RESET%  创建虚拟环境 (venv)
echo   %C_CYAN%[3]%C_RESET%  查看操作日志
echo   %C_CYAN%[4]%C_RESET%  帮助与说明
echo   %C_CYAN%[0]%C_RESET%  退出脚本
echo.
call :PrintSeparator
set "CHOICE="
set /p "CHOICE=  请选择操作: "
if "%CHOICE%"=="1" call :ScanEnvironments
if "%CHOICE%"=="2" call :CreateVenvMenu
if "%CHOICE%"=="3" call :ViewLog
if "%CHOICE%"=="4" call :ShowHelp
if "%CHOICE%"=="0" goto ExitScript
goto MainMenu

:: ============================================================
::  退出脚本
:: ============================================================
:ExitScript
cls
echo.
echo   %C_GREEN%感谢使用 Python 环境管理工具, 再见!%C_RESET%
echo.
echo   日志文件: %C_GRAY%%LOG_FILE%%C_RESET%
echo.
:: 清理临时文件
del "%ENV_TEMP%" >nul 2>&1
del "%DIAG_TEMP%" >nul 2>&1
del "%PKG_TEMP%" >nul 2>&1
del "%OUTDATED_TEMP%" >nul 2>&1
if defined ELEVATED (
    pause
    exit
)
exit /b

:: ============================================================
::  模块一: 环境全景扫描
:: ============================================================
:ScanEnvironments
cls
call :PrintHeader "扫描 Python 环境"
echo.
echo   %C_GRAY%正在扫描系统中的 Python 环境, 请稍候...%C_RESET%
echo.

:: 重置环境列表
set "ENV_COUNT=0"
if exist "%ENV_TEMP%" del "%ENV_TEMP%" >nul 2>&1
echo. > "%ENV_TEMP%"

:: 1. 扫描 PATH 中的 python (where 命令)
echo   %C_CYAN%[*]%C_RESET% 扫描系统 PATH 中的 Python...
for /f "usebackq delims=" %%p in (`where python 2^>nul`) do (
    call :AddEnvironment "全局" "%%p"
)

:: 2. 扫描注册表 (HKCU/HKLM, 含 WOW6432Node)
echo   %C_CYAN%[*]%C_RESET% 扫描注册表中的 Python 安装记录...
for %%R in (
    "HKCU\SOFTWARE\Python\PythonCore"
    "HKLM\SOFTWARE\Python\PythonCore"
    "HKCU\SOFTWARE\WOW6432Node\Python\PythonCore"
    "HKLM\SOFTWARE\WOW6432Node\Python\PythonCore"
) do (
    for /f "usebackq tokens=*" %%k in (`reg query %%R 2^>nul`) do (
        for /f "usebackq tokens=2,*" %%a in (`reg query "%%k\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"`) do (
            set "INSTPATH=%%b"
            if defined INSTPATH if "!INSTPATH:~-1!"=="\" set "INSTPATH=!INSTPATH:~0,-1!"
            if exist "!INSTPATH!\python.exe" call :AddEnvironment "全局" "!INSTPATH!\python.exe"
        )
    )
)

:: 3. 扫描常见安装目录
echo   %C_CYAN%[*]%C_RESET% 扫描常见安装目录...
for %%D in (
    "%LOCALAPPDATA%\Programs\Python"
    "%ProgramFiles%\Python39" "%ProgramFiles%\Python310" "%ProgramFiles%\Python311"
    "%ProgramFiles%\Python312" "%ProgramFiles%\Python313"
    "%ProgramFiles(x86)%\Python39" "%ProgramFiles(x86)%\Python310"
    "%ProgramFiles(x86)%\Python311" "%ProgramFiles(x86)%\Python312"
    "C:\Python39" "C:\Python310" "C:\Python311" "C:\Python312" "C:\Python313"
) do (
    if exist "%%~D\python.exe" call :AddEnvironment "全局" "%%~D\python.exe"
)

:: 4. 扫描 Anaconda / Miniconda
echo   %C_CYAN%[*]%C_RESET% 扫描 Anaconda / Miniconda 环境...
for %%D in (
    "%USERPROFILE%\anaconda3" "%USERPROFILE%\miniconda3"
    "%ProgramData%\anaconda3" "%ProgramData%\miniconda3"
    "%LOCALAPPDATA%\anaconda3" "%LOCALAPPDATA%\miniconda3"
    "C:\Anaconda3" "C:\Miniconda3" "C:\ProgramData\Anaconda3" "C:\ProgramData\Miniconda3"
) do (
    if exist "%%~D\python.exe" call :AddEnvironment "Conda(base)" "%%~D\python.exe"
    if exist "%%~D\envs" (
        for /d %%E in ("%%~D\envs\*") do (
            if exist "%%E\python.exe" call :AddEnvironment "Conda" "%%E\python.exe"
        )
    )
)

:: 5. 通过 conda env list 补充扫描
where conda >nul 2>&1
if !errorlevel! equ 0 (
    echo   %C_CYAN%[*]%C_RESET% 通过 conda env list 补充扫描...
    for /f "usebackq tokens=*" %%L in (`conda env list 2^>nul`) do (
        set "CLINE=%%L"
        if not "!CLINE:~0,1!"=="#" if not "!CLINE!"=="" (
            set "LASTTOK="
            for %%T in (!CLINE!) do set "LASTTOK=%%T"
            if defined LASTTOK if exist "!LASTTOK!\python.exe" call :AddEnvironment "Conda" "!LASTTOK!\python.exe"
        )
    )
)

:: 6. 扫描 venv (桌面/文档/当前目录及一级子目录)
echo   %C_CYAN%[*]%C_RESET% 扫描项目级 venv 虚拟环境...
for %%D in ("%USERPROFILE%\Desktop" "%USERPROFILE%\Documents" "%CD%") do (
    if exist "%%~D\pyvenv.cfg" (
        for %%P in ("%%~D\Scripts\python.exe" "%%~D\bin\python.exe") do (
            if exist "%%P" call :AddEnvironment "venv" "%%P"
        )
    )
    for /d %%S in ("%%~D\*") do (
        if exist "%%S\pyvenv.cfg" (
            for %%P in ("%%S\Scripts\python.exe" "%%S\bin\python.exe") do (
                if exist "%%P" call :AddEnvironment "venv" "%%P"
            )
        )
    )
)

:: 7. 扫描 Windows Store 版 Python
if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
    call :AddEnvironment "WinStore" "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
)

:: ---- 显示扫描结果 ----
echo.
call :PrintSeparator
echo.
if %ENV_COUNT% equ 0 (
    echo   %C_RED%[!] 未扫描到任何 Python 环境!%C_RESET%
    echo.
    echo   请确认系统已安装 Python 3.8+ 且可正常访问。
    echo.
    pause
    goto MainMenu
)

echo   %C_GREEN%[√] 共扫描到 %ENV_COUNT% 个 Python 环境:%C_RESET%
echo.
echo   %C_BOLD%  %C_WHITE%编号  类型          Python版本    pip版本     环境变量  路径%C_RESET%
echo   %C_GRAY%──────────────────────────────────────────────────────────────────────────────%C_RESET%

:: 计算 PATH 优先级并显示
for /l %%I in (1,1,%ENV_COUNT%) do (
    set "EP=!ENV_%%I_PATH!"
    for %%J in ("!EP!") do set "ED=%%~dpJ"
    set "ED=!ED:~0,-1!"
    set "ENV_%%I_DIR=!ED!"
    set "ENV_%%I_INPATH=否"
    set "ENV_%%I_PRIORITY=-"

    :: 在 PATH 中查找优先级
    set "TEMPP=%PATH%;"
    set "PPOS=0"
    call :CalcPathPriority
)

:: 显示环境列表
for /l %%I in (1,1,%ENV_COUNT%) do (
    set "ETYPE=!ENV_%%I_TYPE!"
    set "EVER=!ENV_%%I_VERSION!"
    set "EPVR=!ENV_%%I_PIPVER!"
    set "EINP=!ENV_%%I_INPATH!"
    set "EPRI=!ENV_%%I_PRIORITY!"
    set "EPATH=!ENV_%%I_PATH!"

    :: 类型着色
    set "TYPE_COLOR=%C_CYAN%"
    if "!ETYPE!"=="Conda" set "TYPE_COLOR=%C_GREEN%"
    if "!ETYPE!"=="Conda(base)" set "TYPE_COLOR=%C_GREEN%"
    if "!ETYPE!"=="venv" set "TYPE_COLOR=%C_MAGENTA%"
    if "!ETYPE!"=="WinStore" set "TYPE_COLOR=%C_YELLOW%"

    :: 环境变量状态着色
    set "PATH_COLOR=%C_GREEN%"
    if "!EINP!"=="否" set "PATH_COLOR=%C_GRAY%"
    if "!EINP!"=="是" if not "!EPRI!"=="1" set "PATH_COLOR=%C_YELLOW%"

    set "PRI_DISPLAY="
    if "!EINP!"=="是" set "PRI_DISPLAY=(!EPRI!)"

    echo   %C_CYAN%%%I%C_RESET%     !TYPE_COLOR!!ETYPE!%C_RESET%  %C_WHITE%!EVER!%C_RESET%    !EPVR!    !PATH_COLOR!!EINP!!PRI_DISPLAY!%C_RESET%     !EPATH!
)

echo.
call :PrintSeparator
echo.
echo   %C_GRAY%环境变量列: "是(N)" 表示在 PATH 中且优先级为 N; "否" 表示未加入 PATH%C_RESET%
echo.
set "SEL="
set /p "SEL=  请输入要管理的环境编号 (0 返回主菜单): "
if "%SEL%"=="0" goto MainMenu
if "%SEL%"=="" goto MainMenu

:: 验证输入
set "VALID=0"
for /l %%I in (1,1,%ENV_COUNT%) do if "%SEL%"=="%%I" set "VALID=1"
if "%VALID%"=="0" (
    echo   %C_RED%无效编号!%C_RESET%
    pause
    goto ScanEnvironments
)

set "SELECTED_ENV_NUM=%SEL%"
set "SELECTED_PYTHON=!ENV_%SEL%_PATH!"
set "SELECTED_PYTHON_DIR=!ENV_%SEL%_DIR!"
set "SELECTED_ENV_TYPE=!ENV_%SEL%_TYPE!"
call :EnvMenu
goto MainMenu

:: ---- 计算 PATH 优先级 ----
:CalcPathPriority
set "PPOS=0"
:CPP_Loop
for /f "tokens=1* delims=;" %%a in ("!TEMPP!") do (
    set /a PPOS+=1
    set "PENTRY=%%~a"
    if defined PENTRY if "!PENTRY:~-1!"=="\" set "PENTRY=!PENTRY:~0,-1!"
    if /i "!PENTRY!"=="!ED!" (
        set "ENV_%%I_INPATH=是"
        set "ENV_%%I_PRIORITY=!PPOS!"
    )
    set "TEMPP=%%b"
)
if defined TEMPP if not "!TEMPP!"=="" goto CPP_Loop
exit /b

:: ---- 添加环境到列表 ----
:AddEnvironment
set "EPATH=%~2"
for %%I in ("%EPATH%") do set "EPATH=%%~fI"
:: 去重
findstr /i /x /c:"%EPATH%" "%ENV_TEMP%" >nul 2>&1
if %errorlevel% equ 0 exit /b
echo %EPATH%>> "%ENV_TEMP%"

:: 获取 Python 版本
set "PYVER=未知"
for /f "usebackq tokens=2" %%v in (`"%EPATH%" --version 2^>nul`) do set "PYVER=%%v"
if "!PYVER!"=="未知" exit /b

:: 获取 pip 版本
set "PIPVER=未知"
for /f "usebackq tokens=2" %%v in (`"%EPATH%" -m pip --version 2^>nul`) do set "PIPVER=%%v"

:: 自动识别 venv (检查上级目录是否有 pyvenv.cfg)
set "ETYPE=%~1"
if /i not "!ETYPE!"=="venv" (
    for %%I in ("%EPATH%") do set "EPARENT=%%~dpI"
    set "EPARENT=!EPARENT:~0,-1!"
    for %%I in ("!EPARENT!") do set "EGRAND=%%~dpI"
    set "EGRAND=!EGRAND:~0,-1!"
    if exist "!EGRAND!\pyvenv.cfg" set "ETYPE=venv"
)

set /a ENV_COUNT+=1
set "ENV_!ENV_COUNT!_TYPE=!ETYPE!"
set "ENV_!ENV_COUNT!_PATH=%EPATH%"
set "ENV_!ENV_COUNT!_VERSION=!PYVER!"
set "ENV_!ENV_COUNT!_PIPVER=!PIPVER!"
exit /b

:: ============================================================
::  模块二: 环境管理子菜单
:: ============================================================
:EnvMenu
cls
call :PrintHeader "环境管理 - !SELECTED_ENV_TYPE! [!SELECTED_PYTHON!]"
echo.
echo   %C_CYAN%[1]%C_RESET%  已安装包全量清单
echo   %C_CYAN%[2]%C_RESET%  查询包依赖关系
echo   %C_CYAN%[3]%C_RESET%  导出 requirements.txt 到桌面
echo   %C_CYAN%[4]%C_RESET%  智能冲突诊断
echo   %C_CYAN%[5]%C_RESET%  修复问题 (基于诊断报告)
echo   %C_CYAN%[6]%C_RESET%  批量升级可升级包
echo   %C_CYAN%[7]%C_RESET%  清理 pip 缓存
echo   %C_CYAN%[B]%C_RESET%  返回主菜单
echo.
call :PrintSeparator
set "ECHOICE="
set /p "ECHOICE=  请选择操作: "
if /i "%ECHOICE%"=="1" call :ListPackages
if /i "%ECHOICE%"=="2" call :QueryDependency
if /i "%ECHOICE%"=="3" call :ExportRequirements
if /i "%ECHOICE%"=="4" call :Diagnose
if /i "%ECHOICE%"=="5" call :FixMenu
if /i "%ECHOICE%"=="6" call :BatchUpgrade
if /i "%ECHOICE%"=="7" call :CleanCache
if /i "%ECHOICE%"=="B" goto :eof
goto EnvMenu

:: ---- 已安装包全量清单 ----
:ListPackages
cls
call :PrintHeader "已安装包清单"
echo.
echo   %C_GRAY%正在获取已安装包列表...%C_RESET%

set "PKG_COUNT=0"
if exist "%PKG_TEMP%" del "%PKG_TEMP%" >nul 2>&1

:: 获取包列表 (freeze 格式: package==version)
for /f "usebackq tokens=1,* delims==" %%a in (`""!SELECTED_PYTHON!" -m pip list --format=freeze 2^>nul"`) do (
    set "PKGNAME=%%a"
    set "PKGVER=%%b"
    :: 过滤非标准行
    if defined PKGNAME if defined PKGVER (
        echo !PKGNAME!==!PKGVER!>> "%PKG_TEMP%"
        set /a PKG_COUNT+=1
        set "PKG_!PKG_COUNT!_NAME=!PKGNAME!"
        set "PKG_!PKG_COUNT!_VER=!PKGVER!"
        set "PKG_!PKG_COUNT!_LATEST=-"
        set "PKG_!PKG_COUNT!_STATUS=正常"
    )
)

if %PKG_COUNT% equ 0 (
    echo   %C_RED%[!] 无法获取包列表或环境中没有安装包%C_RESET%
    pause
    goto :eof
)

:ListPackagesShow
cls
call :PrintHeader "已安装包清单 (共 %PKG_COUNT% 个)"
echo.
echo   %C_CYAN%[U]%C_RESET% 检查可升级包  %C_CYAN%[D]%C_RESET% 查看包详情  %C_CYAN%[R]%C_RESET% 刷新  %C_CYAN%[B]%C_RESET% 返回
echo.
echo   %C_BOLD%  %C_WHITE%序号  包名                              当前版本          最新版本          状态%C_RESET%
echo   %C_GRAY%──────────────────────────────────────────────────────────────────────────────────────%C_RESET%

set "LINE=0"
for /l %%I in (1,1,%PKG_COUNT%) do (
    set "PN=!PKG_%%I_NAME!"
    set "PV=!PKG_%%I_VER!"
    set "PL=!PKG_%%I_LATEST!"
    set "PS=!PKG_%%I_STATUS!"

    set "STATUS_COLOR=%C_GREEN%"
    if "!PS!"=="可升级" set "STATUS_COLOR=%C_YELLOW%"

    :: 截断过长的包名以对齐
    set "PN_DISP=!PN!"
    if "!PN:~30!" neq "" set "PN_DISP=!PN:~0,29!~"

    echo   %C_CYAN%%%I%C_RESET%   !PN_DISP!  !PV!  !PL!  !STATUS_COLOR!!PS!%C_RESET%

    set /a LINE+=1
    if !LINE! geq %PAGE_SIZE% (
        set "LINE=0"
        echo.
        echo   %C_GRAY%--- 按任意键继续, Q 返回 ---%C_RESET%
        pause >nul
        cls
        call :PrintHeader "已安装包清单 (共 %PKG_COUNT% 个)"
        echo.
        echo   %C_CYAN%[U]%C_RESET% 检查可升级包  %C_CYAN%[D]%C_RESET% 查看包详情  %C_CYAN%[R]%C_RESET% 刷新  %C_CYAN%[B]%C_RESET% 返回
        echo.
        echo   %C_BOLD%  %C_WHITE%序号  包名                              当前版本          最新版本          状态%C_RESET%
        echo   %C_GRAY%──────────────────────────────────────────────────────────────────────────────────────%C_RESET%
    )
)

echo.
call :PrintSeparator
echo.
set "PKGINPUT="
set /p "PKGINPUT=  请输入操作 (U/D/编号/R/B): "
if /i "%PKGINPUT%"=="U" goto PkgCheckOutdated
if /i "%PKGINPUT%"=="R" goto ListPackages
if /i "%PKGINPUT%"=="B" goto :eof
if /i "%PKGINPUT%"=="D" (
    set /p "PKGDETAILNUM=  请输入包编号查看详情: "
    call :ShowPackageDetail !PKGDETAILNUM!
    goto ListPackagesShow
)
:: 数字输入 - 查看详情
set "ISNUM=0"
for /l %%I in (1,1,%PKG_COUNT%) do if "%PKGINPUT%"=="%%I" set "ISNUM=1"
if "%ISNUM%"=="1" (
    call :ShowPackageDetail %PKGINPUT%
    goto ListPackagesShow
)
goto ListPackagesShow

:PkgCheckOutdated
cls
echo.
echo   %C_GRAY%正在查询 PyPI 获取最新版本信息, 请稍候 (可能需要数十秒)...%C_RESET%
echo.

:: 获取可升级包列表
if exist "%OUTDATED_TEMP%" del "%OUTDATED_TEMP%" >nul 2>&1
"!SELECTED_PYTHON!" -m pip list --outdated --format=freeze 2>nul > "%OUTDATED_TEMP%"

set "OUTCOUNT=0"
for /f "usebackq tokens=1,2,3 delims==" %%a in ("%OUTDATED_TEMP%") do (
    set "UPNAME=%%a"
    set "UPCUR=%%b"
    set "UPLAT=%%c"
    if defined UPNAME if defined UPLAT (
        set /a OUTCOUNT+=1
        :: 在包列表中找到对应包并更新
        for /l %%I in (1,1,%PKG_COUNT%) do (
            if /i "!PKG_%%I_NAME!"=="!UPNAME!" (
                set "PKG_%%I_LATEST=!UPLAT!"
                set "PKG_%%I_STATUS=可升级"
            )
        )
    )
)

echo   %C_GREEN%[√] 检查完成, 共发现 %OUTCOUNT% 个可升级包%C_RESET%
pause
goto ListPackagesShow

:: ---- 查看包详情 ----
:ShowPackageDetail
set "PDN=%~1"
if "%PDN%"=="" exit /b
set "PDN_VALID=0"
for /l %%I in (1,1,%PKG_COUNT%) do if "%PDN%"=="%%I" set "PDN_VALID=1"
if "%PDN_VALID%"=="0" exit /b

cls
call :PrintHeader "包详情 - !PKG_%PDN%_NAME!"
echo.
echo   %C_CYAN%包名:%C_RESET%     !PKG_%PDN%_NAME!
echo   %C_CYAN%当前版本:%C_RESET% !PKG_%PDN%_VER!
echo   %C_CYAN%最新版本:%C_RESET% !PKG_%PDN%_LATEST!
echo.

:: 获取 pip show 详细信息
set "SHOW_LOC="
set "SHOW_REQ="
set "SHOW_REQBY="
set "SHOW_SUMMARY="
set "SHOW_HOMEPAGE="
for /f "usebackq tokens=1,* delims=:" %%a in (`""!SELECTED_PYTHON!" -m pip show "!PKG_%PDN%_NAME!" 2^>nul"`) do (
    set "SKEY=%%a"
    set "SVAL=%%b"
    if defined SVAL set "SVAL=!SVAL:~1!"
    if "!SKEY!"=="Location" set "SHOW_LOC=!SVAL!"
    if "!SKEY!"=="Requires" set "SHOW_REQ=!SVAL!"
    if "!SKEY!"=="Required-by" set "SHOW_REQBY=!SVAL!"
    if "!SKEY!"=="Summary" set "SHOW_SUMMARY=!SVAL!"
    if "!SKEY!"=="Home-page" set "SHOW_HOMEPAGE=!SVAL!"
)

echo   %C_CYAN%描述:%C_RESET%     !SHOW_SUMMARY!
echo   %C_CYAN%安装路径:%C_RESET% !SHOW_LOC!
echo   %C_CYAN%主页:%C_RESET%     !SHOW_HOMEPAGE!
echo.

:: 计算包大小
if defined SHOW_LOC (
    set "PKGDIR=!SHOW_LOC!\!PKG_%PDN%_NAME!"
    set "PKGDIR2=!SHOW_LOC!\!PKG_%PDN%_NAME:-=_!"
    set "PKGSIZE=0"
    set "SIZEDIR="
    if exist "!PKGDIR!" set "SIZEDIR=!PKGDIR!"
    if not defined SIZEDIR if exist "!PKGDIR2!" set "SIZEDIR=!PKGDIR2!"
    if defined SIZEDIR (
        for /f "usebackq tokens=3" %%s in (`dir /s /a /-c "!SIZEDIR!" 2^>nul ^| findstr /i /c:"File(s)" /c:"个文件"`) do (
            set "PKGSIZE=%%s"
        )
        if !PKGSIZE! gtr 0 (
            :: 转换为 KB/MB
            set /a "SIZEMB=!PKGSIZE!/1048576"
            set /a "SIZEMB_REM=(!PKGSIZE!%%1048576)/10486"
            if !SIZEMB! gtr 0 (
                echo   %C_CYAN%占用空间:%C_RESET% !SIZEMB!.!SIZEMB_REM! MB ^(!PKGSIZE! 字节^)
            ) else (
                set /a "SIZEKB=!PKGSIZE!/1024"
                echo   %C_CYAN%占用空间:%C_RESET% !SIZEKB! KB ^(!PKGSIZE! 字节^)
            )
        )
    )
)

echo.
echo   %C_CYAN%依赖项 (Requires):%C_RESET%
if defined SHOW_REQ if not "!SHOW_REQ!"=="" (
    for %%d in (!SHOW_REQ!) do echo     %C_YELLOW%→%%d%C_RESET%
) else (
    echo     %C_GRAY%无依赖%C_RESET%
)
echo.
echo   %C_CYAN%被依赖 (Required-by):%C_RESET%
if defined SHOW_REQBY if not "!SHOW_REQBY!"=="" (
    for %%d in (!SHOW_REQBY!) do echo     %C_GREEN%←%%d%C_RESET%
) else (
    echo     %C_GRAY%无其他包依赖此包%C_RESET%
)
echo.
call :PrintSeparator
echo.
pause
exit /b

:: ---- 依赖关系查询 ----
:QueryDependency
cls
call :PrintHeader "包依赖关系查询"
echo.
set "QPKG="
set /p "QPKG=  请输入要查询的包名 (B 返回): "
if /i "%QPKG%"=="B" goto :eof
if "%QPKG%"=="" goto QueryDependency

echo.
echo   %C_GRAY%正在查询 !QPKG! 的依赖关系...%C_RESET%
echo.

set "QFOUND=0"
set "QNAME="
set "QVER="
set "QREQ="
set "QREQBY="
set "QLOC="
for /f "usebackq tokens=1,* delims=:" %%a in (`""!SELECTED_PYTHON!" -m pip show "!QPKG!" 2^>nul"`) do (
    set "QKEY=%%a"
    set "QVAL=%%b"
    if defined QVAL set "QVAL=!QVAL:~1!"
    if "!QKEY!"=="Name" set "QNAME=!QVAL!"
    if "!QKEY!"=="Version" set "QVER=!QVAL!"
    if "!QKEY!"=="Requires" set "QREQ=!QVAL!"
    if "!QKEY!"=="Required-by" set "QREQBY=!QVAL!"
    if "!QKEY!"=="Location" set "QLOC=!QVAL!"
)

if not defined QNAME (
    echo   %C_RED%[!] 未找到包 "!QPKG!"%C_RESET%
    pause
    goto :eof
)

echo   %C_BOLD%  %C_GREEN%包名:%C_RESET% !QNAME!  %C_GREEN%版本:%C_RESET% !QVER!%C_RESET%
echo   %C_GRAY%安装位置: !QLOC!%C_RESET%
echo.
echo   %C_CYAN%━━ 依赖链路 (向下依赖) ━━%C_RESET%
if defined QREQ if not "!QREQ!"=="" (
    for %%d in (!QREQ!) do (
        echo     %C_YELLOW%→ %%d%C_RESET%
        :: 查询二级依赖
        set "SUBREQ="
        for /f "usebackq tokens=1,* delims=:" %%x in (`""!SELECTED_PYTHON!" -m pip show %%d 2^>nul ^| findstr /i "Requires""`) do (
            set "SUBREQ=%%y"
        )
        if defined SUBREQ if not "!SUBREQ!"=="" (
            set "SUBREQ=!SUBREQ:~1!"
            for %%s in (!SUBREQ!) do echo       %C_GRAY%→ %%s%C_RESET%
        )
    )
) else (
    echo     %C_GRAY%无依赖项%C_RESET%
)
echo.
echo   %C_CYAN%━━ 被依赖链路 (向上追溯) ━━%C_RESET%
if defined QREQBY if not "!QREQBY!"=="" (
    for %%d in (!QREQBY!) do (
        echo     %C_GREEN%← %%d%C_RESET%
        set "SUBREQBY="
        for /f "usebackq tokens=1,* delims=:" %%x in (`""!SELECTED_PYTHON!" -m pip show %%d 2^>nul ^| findstr /i "Required-by""`) do (
            set "SUBREQBY=%%y"
        )
        if defined SUBREQBY if not "!SUBREQBY!"=="" (
            set "SUBREQBY=!SUBREQBY:~1!"
            for %%s in (!SUBREQBY!) do echo       %C_GRAY%← %%s%C_RESET%
        )
    )
) else (
    echo     %C_GRAY%没有其他包依赖此包 (可能为顶层安装包)%C_RESET%
)
echo.
call :PrintSeparator
echo.
pause
goto QueryDependency

:: ---- 导出 requirements.txt ----
:ExportRequirements
cls
call :PrintHeader "导出 requirements.txt"
echo.
set "DESKTOP=%USERPROFILE%\Desktop"
if not exist "%DESKTOP%" set "DESKTOP=%USERPROFILE%"

:: 生成带环境类型和时间戳的文件名
:: 用 PowerShell 生成与区域设置无关的时间戳
set "TIMESTAMP="
for /f "usebackq" %%t in (`powershell -NoProfile -Command "Get-Date -Format 'yyyyMMdd_HHmmss'" ^<nul`) do set "TIMESTAMP=%%t"
set "OUTFILE=!DESKTOP!\requirements_!SELECTED_ENV_TYPE!_!TIMESTAMP!.txt"

echo   %C_GRAY%正在导出包清单...%C_RESET%
"!SELECTED_PYTHON!" -m pip freeze > "!OUTFILE!" 2>nul

if exist "!OUTFILE!" (
    set "LINECOUNT=0"
    for /f "usebackq" %%l in ("!OUTFILE!") do set /a LINECOUNT+=1
    echo.
    echo   %C_GREEN%[√] 导出成功!%C_RESET%
    echo   共导出 !LINECOUNT! 个包
    echo   文件路径: !OUTFILE!
    call :Log "导出requirements.txt: !OUTFILE! (!LINECOUNT! 个包)"
) else (
    echo   %C_RED%[!] 导出失败!%C_RESET%
)
echo.
pause
goto :eof

:: ============================================================
::  模块三: 智能冲突诊断引擎
:: ============================================================
:Diagnose
cls
call :PrintHeader "智能冲突诊断"
echo.
echo   %C_GRAY%正在执行全面诊断, 请稍候...%C_RESET%
echo.

:: 重置诊断结果
set "ISSUE_COUNT=0"
if exist "%DIAG_TEMP%" del "%DIAG_TEMP%" >nul 2>&1

:: ---- 诊断 1: pip check (版本冲突 + 依赖缺失) ----
echo   %C_CYAN%[*]%C_RESET% 检查依赖冲突与缺失...
"!SELECTED_PYTHON!" -m pip check > "%DIAG_TEMP%" 2>&1
for /f "usebackq delims=" %%L in ("%DIAG_TEMP%") do (
    call :ParseCheckLine "%%L"
)

:: ---- 诊断 2: pip 版本检查 ----
echo   %C_CYAN%[*]%C_RESET% 检查 pip 版本...
set "PIPVER_NOW=!ENV_%SELECTED_ENV_NUM%_PIPVER!"
if "!PIPVER_NOW!"=="未知" (
    call :AddIssue "环境异常" "pip 无法正常调用" "高" "所有包管理功能将不可用" "重新安装pip: python -m ensurepip --upgrade" "python -m ensurepip --upgrade"
) else (
    :: 提取主版本号
    for /f "tokens=1 delims=." %%v in ("!PIPVER_NOW!") do set "PIPMAJOR=%%v"
    if !PIPMAJOR! lss 21 (
        call :AddIssue "环境异常" "pip 版本过低 (!PIPVER_NOW!), 建议升级到 21.0+" "中" "可能导致包解析异常、缺少安全补丁" "升级pip到最新版" "python -m pip install --upgrade pip"
    )
)

:: ---- 诊断 3: 孤儿包检测 ----
echo   %C_CYAN%[*]%C_RESET% 检查孤儿包/闲置包...
set "ORPHAN_TEMP=%TEMP%\_orphan_%RANDOM%.tmp"
"!SELECTED_PYTHON!" -m pip list --not-required --format=freeze 2>nul > "%ORPHAN_TEMP%"
set "ORPHAN_LIST="
for /f "usebackq tokens=1 delims==" %%a in ("%ORPHAN_TEMP%") do (
    set "OPKG=%%a"
    :: 排除基础工具包
    set "IS_BASE=0"
    for %%b in (pip setuptools wheel distribute distribute-windows) do (
        if /i "!OPKG!"=="%%b" set "IS_BASE=1"
    )
    if "!IS_BASE!"=="0" set "ORPHAN_LIST=!ORPHAN_LIST!!OPKG!,"
)
del "%ORPHAN_TEMP%" >nul 2>&1
if defined ORPHAN_LIST (
    set "ORPHAN_LIST=!ORPHAN_LIST:~0,-1!"
    call :AddIssue "冗余/孤儿包" "发现未被其他包依赖的闲置包: !ORPHAN_LIST!" "低" "占用磁盘空间, 不影响运行" "可选择性卸载闲置包 (在修复菜单中操作)" "orphan"
)

:: ---- 诊断 4: 残留文件检查 ----
echo   %C_CYAN%[*]%C_RESET% 检查残留/损坏文件...
set "SITEPKG="
for /f "usebackq tokens=1,* delims=:" %%a in (`""!SELECTED_PYTHON!" -m pip show pip 2^>nul ^| findstr /i "Location""`) do (
    set "SITEPKG=%%b"
)
if defined SITEPKG (
    set "SITEPKG=!SITEPKG:~1!"
    set "RESIDUAL="
    for /d %%D in ("!SITEPKG!\~*") do (
        if exist "%%D" set "RESIDUAL=!RESIDUAL!%%~nxD,"
    )
    for /d %%D in ("!SITEPKG!\*~") do (
        if exist "%%D" set "RESIDUAL=!RESIDUAL!%%~nxD,"
    )
    if defined RESIDUAL (
        set "RESIDUAL=!RESIDUAL:~0,-1!"
        call :AddIssue "残留文件" "site-packages 中存在疑似残留目录: !RESIDUAL!" "低" "可能导致包导入异常" "删除残留目录" "residual"
    )
)

:: ---- 诊断 5: PATH 优先级检查 ----
echo   %C_CYAN%[*]%C_RESET% 检查环境变量优先级...
set "INPATH_NOW=!ENV_%SELECTED_ENV_NUM%_INPATH!"
set "PRI_NOW=!ENV_%SELECTED_ENV_NUM%_PRIORITY!"
if "!INPATH_NOW!"=="否" (
    call :AddIssue "环境变量" "当前环境未加入系统 PATH, 直接输入 python 将调用其他环境" "低" "命令行中无法直接使用此环境的 python/pip" "将此环境加入用户 PATH (修复菜单操作)" "addpath"
) else if not "!PRI_NOW!"=="1" (
    call :AddIssue "环境变量" "当前环境在 PATH 中优先级为 !PRI_NOW!, 非首选 (存在多个 Python 路径冲突)" "中" "命令行 python/pip 可能调用到其他环境" "调整 PATH 优先级 (修复菜单操作)" "fixpath"
)

:: ---- 诊断 6: pip 缓存检查 ----
echo   %C_CYAN%[*]%C_RESET% 检查 pip 缓存...
set "CACHE_INFO="
for /f "usebackq tokens=*" %%L in (`""!SELECTED_PYTHON!" -m pip cache info 2^>nul"`) do (
    set "CACHE_INFO=!CACHE_INFO!%%L,"
)
echo !CACHE_INFO! | findstr /i "error unknown" >nul 2>&1
if !errorlevel! neq 0 (
    if defined CACHE_INFO (
        :: 检查缓存大小是否过大
        echo !CACHE_INFO! | findstr /r /c:"[0-9][0-9][0-9][0-9][0-9][0-9][0-9]" >nul 2>&1
        if !errorlevel! equ 0 (
            call :AddIssue "缓存异常" "pip 下载缓存较大, 建议清理" "低" "占用磁盘空间, 不影响功能" "清理 pip 缓存" "python -m pip cache purge"
        )
    )
)

:: ---- 输出诊断报告 ----
echo.
call :PrintSeparator
echo.
if %ISSUE_COUNT% equ 0 (
    echo   %C_GREEN%[√] 诊断完成! 未发现任何问题, 当前环境状态良好。%C_RESET%
    echo.
    pause
    goto :eof
)

echo   %C_BOLD%  %C_WHITE%诊断报告 - 共发现 %ISSUE_COUNT% 个问题:%C_RESET%
echo.
call :PrintSeparator

for /l %%I in (1,1,%ISSUE_COUNT%) do (
    set "ITYPE=!ISSUE_%%I_TYPE!"
    set "IDESC=!ISSUE_%%I_DESC!"
    set "ILEVEL=!ISSUE_%%I_LEVEL!"
    set "IIMPACT=!ISSUE_%%I_IMPACT!"
    set "IFIX=!ISSUE_%%I_FIX!"

    set "LVL_COLOR=%C_GREEN%"
    if "!ILEVEL!"=="高" set "LVL_COLOR=%C_RED%"
    if "!ILEVEL!"=="中" set "LVL_COLOR=%C_YELLOW%"
    if "!ILEVEL!"=="低" set "LVL_COLOR=%C_CYAN%"

    echo.
    echo   %C_BOLD%问题 #%%I%C_RESET%  !LVL_COLOR![!ILEVEL!风险]%C_RESET%  %C_GRAY%类型: !ITYPE!%C_RESET%
    echo   %C_WHITE%描述:%C_RESET% !IDESC!
    echo   %C_WHITE%影响:%C_RESET% !IIMPACT!
    echo   %C_GREEN%建议:%C_RESET% !IFIX!
)

echo.
call :PrintSeparator
echo.
echo   %C_GRAY%可在环境管理菜单中选择 [5] 修复问题, 输入问题编号进行修复%C_RESET%
echo.
pause
goto :eof

:: ---- 解析 pip check 输出行 ----
:ParseCheckLine
set "CLINE=%~1"
if "%CLINE%"=="" exit /b
if "!CLINE:~0,4!"=="pip " exit /b
:: 跳过"No broken requirements"行
echo !CLINE! | findstr /i "No broken requirements found" >nul 2>&1
if !errorlevel! equ 0 exit /b

:: 提取包名和版本
for /f "tokens=1,2" %%a in ("!CLINE!") do (
    set "CK_PKG=%%a"
    set "CK_VER=%%b"
)

:: 提取 requires/has requirement 后面的内容
set "AFTER_REQ=!CLINE:*requires =!"
if "!AFTER_REQ!"=="!CLINE!" set "AFTER_REQ=!CLINE:*has requirement =!"
if "!AFTER_REQ!"=="!CLINE!" exit /b

:: 提取版本要求 (逗号前)
for /f "tokens=1 delims=," %%p in ("!AFTER_REQ!") do set "FIX_TARGET=%%p"

:: 判断是缺失还是冲突
echo !CLINE! | findstr /i "is not installed" >nul 2>&1
if !errorlevel! equ 0 (
    :: 依赖缺失
    for /f "tokens=1" %%d in ("!FIX_TARGET!") do set "MISSING_DEP=%%d"
    call :AddIssue "依赖缺失" "!CK_PKG! !CK_VER! 缺少依赖: !MISSING_DEP!" "高" "!CK_PKG! 可能无法正常导入或运行" "安装缺失依赖: !MISSING_DEP!" "python -m pip install !MISSING_DEP!"
) else (
    :: 版本冲突 (修复命令含特殊字符 < > =, 通过全局变量传递以保留引号)
    set "NEW_ISSUE_FIXCMD=python -m pip install "!FIX_TARGET!""
    call :AddIssue "版本冲突" "!CLINE!" "中" "相关包可能无法正常工作" "安装兼容版本: !FIX_TARGET!" ""
)
exit /b

:: ---- 添加诊断问题 ----
:AddIssue
set /a ISSUE_COUNT+=1
set "ISSUE_!ISSUE_COUNT!_TYPE=%~1"
set "ISSUE_!ISSUE_COUNT!_DESC=%~2"
set "ISSUE_!ISSUE_COUNT!_LEVEL=%~3"
set "ISSUE_!ISSUE_COUNT!_IMPACT=%~4"
set "ISSUE_!ISSUE_COUNT!_FIX=%~5"
:: FIXCMD 优先从全局变量 NEW_ISSUE_FIXCMD 获取 (避免 call 参数中嵌套引号丢失)
if defined NEW_ISSUE_FIXCMD (
    set "ISSUE_!ISSUE_COUNT!_FIXCMD=!NEW_ISSUE_FIXCMD!"
    set "NEW_ISSUE_FIXCMD="
) else (
    set "ISSUE_!ISSUE_COUNT!_FIXCMD=%~6"
)
exit /b

:: ============================================================
::  模块四: 交互式精准修复系统
:: ============================================================
:FixMenu
if %ISSUE_COUNT% equ 0 (
    cls
    call :PrintHeader "修复问题"
    echo.
    echo   %C_YELLOW%[!] 当前没有诊断报告, 请先执行智能冲突诊断 [4]%C_RESET%
    echo.
    pause
    goto :eof
)

:FixMenuShow
cls
call :PrintHeader "交互式修复系统 (共 %ISSUE_COUNT% 个问题)"
echo.
echo   %C_RED%  所有修复操作均需二次确认, 可随时取消%C_RESET%
echo.
for /l %%I in (1,1,%ISSUE_COUNT%) do (
    set "ILEVEL=!ISSUE_%%I_LEVEL!"
    set "LVL_COLOR=%C_GREEN%"
    if "!ILEVEL!"=="高" set "LVL_COLOR=%C_RED%"
    if "!ILEVEL!"=="中" set "LVL_COLOR=%C_YELLOW%"
    if "!ILEVEL!"=="低" set "LVL_COLOR=%C_CYAN%"
    echo   %C_CYAN%[%%I]%C_RESET% !LVL_COLOR![!ILEVEL!]%C_RESET% !ISSUE_%%I_TYPE! - !ISSUE_%%I_DESC!
)
echo.
call :PrintSeparator
echo.
echo   %C_CYAN%[A]%C_RESET% 一键修复所有高风险问题  %C_CYAN%[B]%C_RESET% 返回
echo.
set "FIXINPUT="
set /p "FIXINPUT=  请输入要修复的问题编号: "
if /i "%FIXINPUT%"=="B" goto :eof
if /i "%FIXINPUT%"=="A" (
    call :ConfirmAction "将自动修复所有高风险问题, 是否继续?"
    if "!CONFIRMED!"=="YES" (
        for /l %%I in (1,1,%ISSUE_COUNT%) do (
            if "!ISSUE_%%I_LEVEL!"=="高" (
                call :ExecuteFix %%I
            )
        )
        echo.
        echo   %C_YELLOW%修复完成, 建议重新运行诊断以确认%C_RESET%
        pause
    )
    goto :eof
)

:: 验证编号
set "FIXVALID=0"
for /l %%I in (1,1,%ISSUE_COUNT%) do if "%FIXINPUT%"=="%%I" set "FIXVALID=1"
if "%FIXVALID%"=="0" (
    echo   %C_RED%无效编号!%C_RESET%
    pause
    goto FixMenuShow
)

call :ExecuteFix %FIXINPUT%
echo.
set "REDIAG="
set /p "REDIAG=  是否重新运行诊断? (Y/N): "
if /i "%REDIAG%"=="Y" call :Diagnose
goto FixMenuShow

:: ---- 执行修复 ----
:ExecuteFix
set "FIXN=%~1"
set "FTYPE=!ISSUE_%FIXN%_TYPE!"
set "FDESC=!ISSUE_%FIXN%_DESC!"
set "FFIX=!ISSUE_%FIXN%_FIX!"
set "FCMD=!ISSUE_%FIXN%_FIXCMD!"

cls
call :PrintHeader "修复确认 - 问题 #%FIXN%"
echo.
echo   %C_CYAN%问题类型:%C_RESET% !FTYPE!
echo   %C_CYAN%问题描述:%C_RESET% !FDESC!
echo   %C_CYAN%修复方案:%C_RESET% !FFIX!
echo.

:: 特殊处理: 孤儿包卸载
if "!FCMD!"=="orphan" (
    echo   %C_YELLOW%以下包未被其他包依赖, 可选择要卸载的包:%C_RESET%
    echo.
    set "ORPHAN_IDX=0"
    for %%p in (!ORPHAN_LIST!) do (
        set /a ORPHAN_IDX+=1
        echo     %C_CYAN%[!ORPHAN_IDX!]%C_RESET% %%p
    )
    echo.
    set "UNSEL="
    set /p "UNSEL=  输入要卸载的包编号 (多个用逗号分隔, 0 取消): "
    if "!UNSEL!"=="0" exit /b
    if "!UNSEL!"=="" exit /b
    set "ORPHAN_IDX=0"
    for %%p in (!ORPHAN_LIST!) do (
        set /a ORPHAN_IDX+=1
        for %%n in ("!UNSEL:,=" "!") do (
            if "%%~n"=="!ORPHAN_IDX!" (
                call :ConfirmAction "将卸载包: %%p, 此操作不可逆!"
                if "!CONFIRMED!"=="YES" (
                    echo   %C_GRAY%正在卸载 %%p ...%C_RESET%
                    "!SELECTED_PYTHON!" -m pip uninstall -y "%%p" 2>&1
                    if !errorlevel! equ 0 (
                        echo   %C_GREEN%[√] %%p 卸载成功%C_RESET%
                        call :Log "卸载包: %%p (环境: !SELECTED_PYTHON!)"
                    ) else (
                        echo   %C_RED%[×] %%p 卸载失败%C_RESET%
                    )
                )
            )
        )
    )
    exit /b
)

:: 特殊处理: 残留文件清理
if "!FCMD!"=="residual" (
    echo   %C_YELLOW%将删除以下残留目录:%C_RESET%
    echo   !RESIDUAL:,=, !
    echo.
    call :ConfirmAction "删除残留目录, 是否继续?"
    if "!CONFIRMED!"=="YES" (
        for %%d in ("!RESIDUAL:,=" "!") do (
            set "RDIR=!SITEPKG!\%%~d"
            if exist "!RDIR!" (
                rd /s /q "!RDIR!" 2>nul
                if exist "!RDIR!" (
                    echo   %C_RED%[×] 删除失败: %%~d%C_RESET%
                ) else (
                    echo   %C_GREEN%[√] 已删除: %%~d%C_RESET%
                    call :Log "删除残留目录: !RDIR!"
                )
            )
        )
    )
    exit /b
)

:: 特殊处理: 添加到 PATH
if "!FCMD!"=="addpath" (
    echo   %C_YELLOW%将执行以下操作:%C_RESET%
    echo   将 !SELECTED_PYTHON_DIR! 添加到用户 PATH 环境变量
    echo.
    call :ConfirmAction "修改用户环境变量 PATH, 是否继续?"
    if "!CONFIRMED!"=="YES" (
        call :AddToUserPath "!SELECTED_PYTHON_DIR!"
    )
    exit /b
)

:: 特殊处理: 调整 PATH 优先级
if "!FCMD!"=="fixpath" (
    echo   %C_YELLOW%当前 PATH 中的 Python 相关条目:%C_RESET%
    echo.
    set "PATHENTRIES="
    set "PATHIDX=0"
    set "TEMPP2=%PATH%;"
    :FixPathLoop
    for /f "tokens=1* delims=;" %%a in ("!TEMPP2!") do (
        echo %%a | findstr /i "python conda" >nul 2>&1
        if !errorlevel! equ 0 (
            set /a PATHIDX+=1
            echo   %C_CYAN%[!PATHIDX!]%C_RESET% %%a
            set "PATHENTRIES=!PATHENTRIES!%%a;"
        )
        set "TEMPP2=%%b"
    )
    if defined TEMPP2 if not "!TEMPP2!"=="" goto FixPathLoop
    echo.
    set "PATHSEL="
    set /p "PATHSEL=  输入要提升到最前的条目编号 (0 取消): "
    if "!PATHSEL!"=="0" exit /b
    set "PATHIDX=0"
    set "SELECTED_PATH_ENTRY="
    for %%e in ("!PATHENTRIES:;=" "!") do (
        set /a PATHIDX+=1
        if "!PATHIDX!"=="!PATHSEL!" set "SELECTED_PATH_ENTRY=%%~e"
    )
    if defined SELECTED_PATH_ENTRY (
        call :ConfirmAction "将 [!SELECTED_PATH_ENTRY!] 移到用户 PATH 最前面, 是否继续?"
        if "!CONFIRMED!"=="YES" (
            call :MovePathToFront "!SELECTED_PATH_ENTRY!"
        )
    )
    exit /b
)

:: 常规 pip 命令修复
echo   %C_YELLOW%将执行命令:%C_RESET%
echo   !FCMD!
echo.
echo   %C_RED%风险提示: 此操作将修改当前环境的包状态, 建议提前备份。%C_RESET%
echo   %C_GRAY%备份方法: 先使用 [3] 导出 requirements.txt%C_RESET%
echo.
call :ConfirmAction "确认执行此修复操作?"
if "!CONFIRMED!"=="YES" (
    echo.
    echo   %C_GRAY%正在执行...%C_RESET%
    echo.
    :: 执行修复命令 (通过全局变量传递, 避免引号丢失)
    set "RUN_CMD=!FCMD!"
    call :RunPipCommand
    if !errorlevel! equ 0 (
        echo.
        echo   %C_GREEN%[√] 修复操作执行成功%C_RESET%
        call :Log "执行修复: !FCMD! (成功)"
    ) else (
        echo.
        echo   %C_RED%[×] 修复操作执行失败, 请检查错误信息%C_RESET%
        call :Log "执行修复: !FCMD! (失败)"
    )
) else (
    echo.
    echo   %C_GRAY%已取消修复操作%C_RESET%
)
exit /b

:: ---- 执行 pip 命令 (通过全局变量 RUN_CMD 传递, 避免引号丢失) ----
:RunPipCommand
set "CMD=!RUN_CMD!"
:: 去掉开头的 "python " 前缀, 用选中的 python 路径执行
if "!CMD:~0,7!"=="python " set "CMD=!CMD:~7!"
"!SELECTED_PYTHON!" !CMD!
exit /b

:: ---- 添加到用户 PATH ----
:AddToUserPath
set "NEWDIR=%~1"
set "PSFILE=%TEMP%\_addpath_%RANDOM%.ps1"
> "%PSFILE%" echo $newDir = '%NEWDIR%'
>> "%PSFILE%" echo $current = [Environment]::GetEnvironmentVariable('PATH','User')
>> "%PSFILE%" echo if ($current -notlike "*$newDir*") {
>> "%PSFILE%" echo   $updated = "$newDir;$current"
>> "%PSFILE%" echo   [Environment]::SetEnvironmentVariable('PATH',$updated,'User')
>> "%PSFILE%" echo   Write-Host "SUCCESS"
>> "%PSFILE%" echo } else {
>> "%PSFILE%" echo   Write-Host "ALREADY_EXISTS"
>> "%PSFILE%" echo }
for /f "usebackq delims=" %%r in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%PSFILE%" ^<nul 2^>nul`) do set "PATHRESULT=%%r"
del "%PSFILE%" >nul 2>&1
if "!PATHRESULT!"=="SUCCESS" (
    echo   %C_GREEN%[√] 已添加到用户 PATH, 请重新打开终端生效%C_RESET%
    call :Log "添加PATH: !NEWDIR!"
) else if "!PATHRESULT!"=="ALREADY_EXISTS" (
    echo   %C_YELLOW%[!] 该路径已在 PATH 中%C_RESET%
) else (
    echo   %C_RED%[×] PATH 修改失败%C_RESET%
)
exit /b

:: ---- 移动 PATH 条目到最前 ----
:MovePathToFront
set "MOVEENTRY=%~1"
set "PSFILE=%TEMP%\_movepath_%RANDOM%.ps1"
> "%PSFILE%" echo $target = '%MOVEENTRY%'
>> "%PSFILE%" echo $current = [Environment]::GetEnvironmentVariable('PATH','User')
>> "%PSFILE%" echo $parts = $current -split ';' ^| Where-Object { $_ -ne '' }
>> "%PSFILE%" echo $others = $parts ^| Where-Object { $_ -ne $target }
>> "%PSFILE%" echo $new = @($target) + $others -join ';'
>> "%PSFILE%" echo [Environment]::SetEnvironmentVariable('PATH',$new,'User')
>> "%PSFILE%" echo Write-Host "SUCCESS"
for /f "usebackq delims=" %%r in (`powershell -NoProfile -ExecutionPolicy Bypass -File "%PSFILE%" ^<nul 2^>nul`) do set "PATHRESULT=%%r"
del "%PSFILE%" >nul 2>&1
if "!PATHRESULT!"=="SUCCESS" (
    echo   %C_GREEN%[√] PATH 优先级已调整, 请重新打开终端生效%C_RESET%
    call :Log "调整PATH优先级: !MOVEENTRY! 移至最前"
) else (
    echo   %C_RED%[×] PATH 修改失败%C_RESET%
)
exit /b

:: ============================================================
::  模块五: 附加实用工具
:: ============================================================

:: ---- 创建虚拟环境 ----
:CreateVenvMenu
cls
call :PrintHeader "创建虚拟环境 (venv)"
echo.
echo   %C_CYAN%[1]%C_RESET% 使用已扫描的 Python 环境创建
echo   %C_CYAN%[2]%C_RESET% 手动指定 Python 解释器路径
echo   %C_CYAN%[B]%C_RESET% 返回
echo.
set "VC="
set /p "VC=  请选择: "
if /i "%VC%"=="B" goto :eof
if "%VC%"=="1" (
    if %ENV_COUNT% equ 0 (
        echo   %C_YELLOW%请先扫描环境!%C_RESET%
        pause
        goto :eof
    )
    echo.
    for /l %%I in (1,1,%ENV_COUNT%) do (
        echo   %C_CYAN%[%%I]%C_RESET% !ENV_%%I_VERSION! - !ENV_%%I_PATH!
    )
    echo.
    set "VENVBASE="
    set /p "VENVBASE=  选择基础 Python 编号: "
    for %%v in (!VENVBASE!) do set "VENV_PY=!ENV_%%v_PATH!"
)
if "%VC%"=="2" (
    echo.
    set "VENV_PY="
    set /p "VENV_PY=  请输入 python.exe 完整路径: "
)
if not defined VENV_PY (
    echo   %C_RED%未指定 Python 解释器!%C_RESET%
    pause
    goto :eof
)
if not exist "!VENV_PY!" (
    echo   %C_RED%Python 解释器不存在: !VENV_PY!%C_RESET%
    pause
    goto :eof
)

echo.
set "VENV_DIR="
set /p "VENV_DIR=  请输入虚拟环境创建目录 (如 D:\projects): "
if not defined VENV_DIR goto :eof
set "VENV_NAME="
set /p "VENV_NAME=  请输入虚拟环境名称 (如 myenv): "
if not defined VENV_NAME goto :eof
set "VENV_FULL=!VENV_DIR!\!VENV_NAME!"

if exist "!VENV_FULL!" (
    echo   %C_RED%[!] 目标目录已存在: !VENV_FULL!%C_RESET%
    pause
    goto :eof
)

set "VENV_SITE="
set /p "VENV_SITE=  是否继承全局包? (y/N): "
set "VENV_FLAG="
if /i "!VENV_SITE!"=="y" set "VENV_FLAG=--system-site-packages"

echo.
echo   %C_YELLOW%将创建虚拟环境:%C_RESET%
echo   路径: !VENV_FULL!
echo   基础: !VENV_PY!
echo.
call :ConfirmAction "确认创建虚拟环境?"
if "!CONFIRMED!"=="YES" (
    echo   %C_GRAY%正在创建...%C_RESET%
    "!VENV_PY!" -m venv !VENV_FLAG! "!VENV_FULL!" 2>&1
    if exist "!VENV_FULL!\Scripts\python.exe" (
        echo   %C_GREEN%[√] 虚拟环境创建成功!%C_RESET%
        echo   激活命令: !VENV_FULL!\Scripts\activate
        call :Log "创建venv: !VENV_FULL! (基础: !VENV_PY!)"
    ) else (
        echo   %C_RED%[×] 创建失败, 请检查错误信息%C_RESET%
    )
)
echo.
pause
goto :eof

:: ---- 批量升级 ----
:BatchUpgrade
cls
call :PrintHeader "批量升级可升级包"
echo.

:: 先检查可升级包
set "OUTCOUNT=0"
if exist "%OUTDATED_TEMP%" del "%OUTDATED_TEMP%" >nul 2>&1
echo   %C_GRAY%正在检查可升级包, 请稍候...%C_RESET%
"!SELECTED_PYTHON!" -m pip list --outdated --format=freeze 2>nul > "%OUTDATED_TEMP%"

set "UPGRADE_LIST="
for /f "usebackq tokens=1,2,3 delims==" %%a in ("%OUTDATED_TEMP%") do (
    if not "%%c"=="" (
        set /a OUTCOUNT+=1
        set "UPG_!OUTCOUNT!_NAME=%%a"
        set "UPG_!OUTCOUNT!_CUR=%%b"
        set "UPG_!OUTCOUNT!_LAT=%%c"
    )
)

if %OUTCOUNT% equ 0 (
    echo   %C_GREEN%[√] 所有包均为最新版本, 无需升级%C_RESET%
    pause
    goto :eof
)

echo.
echo   %C_BOLD%  %C_WHITE%可升级包列表 (共 %OUTCOUNT% 个):%C_RESET%
echo.
for /l %%I in (1,1,%OUTCOUNT%) do (
    echo   %C_CYAN%[%%I]%C_RESET% !UPG_%%I_NAME! : !UPG_%%I_CUR! %C_YELLOW%→%C_RESET% !UPG_%%I_LAT!
)
echo.
echo   %C_CYAN%[A]%C_RESET% 全选  %C_CYAN%[B]%C_RESET% 返回
echo.
set "UPSEL="
set /p "UPSEL=  输入要升级的编号 (逗号分隔, 如 1,3,5): "
if /i "%UPSEL%"=="B" goto :eof
if /i "%UPSEL%"=="A" (
    set "UPSEL_ALL="
    for /l %%I in (1,1,%OUTCOUNT%) do set "UPSEL_ALL=!UPSEL_ALL!%%I,"
    set "UPSEL=!UPSEL_ALL:~0,-1!"
)

echo.
echo   %C_YELLOW%将升级以下包:%C_RESET%
set "TODO="
for /l %%I in (1,1,%OUTCOUNT%) do (
    set "ISSEL=0"
    for %%n in ("!UPSEL:,=" "!") do (
        if "%%~n"=="%%I" set "ISSEL=1"
    )
    if "!ISSEL!"=="1" (
        echo     - !UPG_%%I_NAME! !UPG_%%I_CUR! → !UPG_%%I_LAT!
        set "TODO=!TODO!!UPG_%%I_NAME!,"
    )
)
if not defined TODO (
    echo   %C_RED%未选择有效包!%C_RESET%
    pause
    goto :eof
)
echo.
call :ConfirmAction "确认批量升级以上包?"
if "!CONFIRMED!"=="YES" (
    set "TODO=!TODO:~0,-1!"
    echo.
    echo   %C_GRAY%正在执行批量升级...%C_RESET%
    echo.
    for %%p in ("!TODO:,=" "!") do (
        echo   %C_CYAN%[*]%C_RESET% 升级 %%~p ...
        "!SELECTED_PYTHON!" -m pip install --upgrade "%%~p" 2>&1
        if !errorlevel! equ 0 (
            echo   %C_GREEN%  [√] %%~p 升级成功%C_RESET%
            call :Log "批量升级: %%~p (环境: !SELECTED_PYTHON!)"
        ) else (
            echo   %C_RED%  [×] %%~p 升级失败%C_RESET%
        )
    )
    echo.
    echo   %C_GREEN%批量升级操作完成%C_RESET%
)
echo.
pause
goto :eof

:: ---- 清理 pip 缓存 ----
:CleanCache
cls
call :PrintHeader "清理 pip 缓存"
echo.
echo   %C_GRAY%当前缓存信息:%C_RESET%
"!SELECTED_PYTHON!" -m pip cache info 2>&1
echo.
call :ConfirmAction "确认清理所有 pip 下载缓存?"
if "!CONFIRMED!"=="YES" (
    echo.
    "!SELECTED_PYTHON!" -m pip cache purge 2>&1
    if !errorlevel! equ 0 (
        echo   %C_GREEN%[√] 缓存清理成功%C_RESET%
        call :Log "清理pip缓存 (环境: !SELECTED_PYTHON!)"
    ) else (
        echo   %C_RED%[×] 缓存清理失败或当前pip版本不支持%C_RESET%
    )
)
echo.
pause
goto :eof

:: ---- 查看操作日志 ----
:ViewLog
cls
call :PrintHeader "操作日志"
echo.
if exist "!LOG_FILE!" (
    echo   %C_GRAY%日志文件: !LOG_FILE!%C_RESET%
    echo   %C_GRAY%──────────────────────────────────────────────────────────────────────────────────────%C_RESET%
    echo.
    set "LOGLINE=0"
    for /f "usebackq delims=" %%L in ("!LOG_FILE!") do (
        echo   %%L
        set /a LOGLINE+=1
        if !LOGLINE! geq %PAGE_SIZE% (
            set "LOGLINE=0"
            echo.
            pause
            cls
            call :PrintHeader "操作日志 (续)"
            echo.
        )
    )
) else (
    echo   %C_GRAY%暂无操作日志%C_RESET%
)
echo.
call :PrintSeparator
echo.
pause
goto :eof

:: ---- 帮助与说明 ----
:ShowHelp
cls
call :PrintHeader "帮助与说明"
echo.
echo   %C_CYAN%【脚本简介】%C_RESET%
echo   本脚本用于 Windows 平台 Python 环境的全生命周期管理, 包括环境扫描、
echo   包管理、冲突诊断和交互式修复。纯原生 BAT 实现, 无需安装任何第三方工具。
echo.
echo   %C_CYAN%【适用环境】%C_RESET%
echo   - 操作系统: Windows 10 / Windows 11 (64位)
echo   - Python: 3.8 及以上
echo   - 支持: 官方 Python / Anaconda3 / Miniconda3 / venv 虚拟环境
echo.
echo   %C_CYAN%【安全机制】%C_RESET%
echo   - 所有修改/删除/升级操作均需手动输入 YES 确认
echo   - 所有操作记录到日志文件 (脚本同目录)
echo   - 修复前建议先导出 requirements.txt 备份
echo   - 可随时取消, 不会自动执行任何破坏性操作
echo.
echo   %C_CYAN%【常见问题】%C_RESET%
echo.
echo   %C_YELLOW%Q: 为什么有些 Python 环境没扫描到?%C_RESET%
echo   A: venv 环境仅扫描桌面、文档和当前目录的两级子目录。
echo      如未找到, 可通过主菜单 [2] 手动指定 Python 解释器。
echo.
echo   %C_YELLOW%Q: 颜色显示为乱码怎么办?%C_RESET%
echo   A: 请确保使用 Windows 10 1511 以上版本的 cmd.exe 或 Windows Terminal。
echo      颜色不显示不影响任何功能。
echo.
echo   %C_YELLOW%Q: 修复操作失败怎么办?%C_RESET%
echo   A: 请查看错误信息, 常见原因包括网络问题、权限不足、包名错误。
echo      可尝试手动执行提示的 pip 命令, 或升级 pip 后重试。
echo.
echo   %C_YELLOW%Q: 修改 PATH 后不生效?%C_RESET%
echo   A: PATH 修改针对用户级环境变量, 需要重新打开终端窗口才会生效。
echo      系统级 PATH 不会被修改, 以保证安全。
echo.
echo   %C_YELLOW%Q: 如何备份环境?%C_RESET%
echo   A: 在环境管理菜单选择 [3] 导出 requirements.txt 到桌面,
echo      恢复时使用: pip install -r requirements.txt
echo.
call :PrintSeparator
echo.
pause
goto :eof

:: ============================================================
::  工具函数
:: ============================================================

:: ---- 初始化日志 ----
:InitLog
echo ============================================================ >> "!LOG_FILE!"
echo Python 环境管理工具 - 操作日志 >> "!LOG_FILE!"
echo 启动时间: %date% %time% >> "!LOG_FILE!"
echo 脚本路径: %~f0 >> "!LOG_FILE!"
echo ============================================================ >> "!LOG_FILE!"
exit /b

:: ---- 记录日志 ----
:Log
echo [%date% %time%] %~1 >> "!LOG_FILE!"
exit /b

:: ---- 打印标题 ----
:PrintHeader
echo.
echo   %C_BOLD%  %C_CYAN%═══════════════════════════════════════════════════════════════%C_RESET%
echo   %C_BOLD%  %C_WHITE%  %~1%C_RESET%
echo   %C_BOLD%  %C_CYAN%═══════════════════════════════════════════════════════════════%C_RESET%
exit /b

:: ---- 打印分隔线 ----
:PrintSeparator
echo   %C_GRAY%──────────────────────────────────────────────────────────────────────────────────────%C_RESET%
exit /b

:: ---- 确认操作 ----
:ConfirmAction
set "CONFIRMED=NO"
echo.
echo   %C_YELLOW%  ⚠ 操作确认%C_RESET%
echo   %~1
echo.
set "CONFIRM_INPUT="
set /p "CONFIRM_INPUT=  输入 YES 确认执行, 其他任意键取消: "
if /i "!CONFIRM_INPUT!"=="YES" set "CONFIRMED=YES"
exit /b
