@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0.."
if not exist ".runtime\desktop-venv\Scripts\python.exe" (
  py -3.12 -m venv .runtime\desktop-venv
  if errorlevel 1 exit /b 1
)
.runtime\desktop-venv\Scripts\python.exe -m pip install -r desktop\requirements.txt
if errorlevel 1 exit /b 1
.runtime\desktop-venv\Scripts\python.exe desktop\build.py
if errorlevel 1 exit /b 1
set "DEVICECHECK_ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not exist "%DEVICECHECK_ISCC%" (
  echo 已生成 dist\desktop\DeviceCheck\DeviceCheck.exe。生成安装程序还需要安装 Inno Setup 6。
  pause
  exit /b 0
)
"%DEVICECHECK_ISCC%" desktop\DeviceCheck.iss
if errorlevel 1 exit /b 1
echo 安装程序已生成到 dist\installers。
pause
