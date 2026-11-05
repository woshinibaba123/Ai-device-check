@echo off
chcp 65001 >nul
cd /d "%~dp0.."
if not exist ".runtime\desktop-venv\Scripts\python.exe" (
  echo 请先安装 Python 3.12，然后按 desktop\README.md 创建桌面环境。
  pause
  exit /b 1
)
".runtime\desktop-venv\Scripts\python.exe" desktop_main.py
