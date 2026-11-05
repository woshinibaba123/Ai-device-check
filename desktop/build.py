"""Build native desktop payload; invoke with the dedicated desktop venv."""
import subprocess
import os
import sys
from pathlib import Path

root=Path(__file__).resolve().parents[1]
if sys.platform not in ('darwin','win32'):raise SystemExit('仅支持在 macOS / Windows 原生构建')
os.environ.setdefault('PYINSTALLER_CONFIG_DIR',str(root/'.runtime/pyinstaller-cache'))
subprocess.run([sys.executable,'-m','PyInstaller','--noconfirm','--clean','--distpath',str(root/'dist/desktop'),'--workpath',str(root/'.runtime/desktop-build'),str(root/'desktop/DeviceCheck.spec')],cwd=root,check=True)
print('桌面程序已构建：'+str(root/'dist/desktop'))
