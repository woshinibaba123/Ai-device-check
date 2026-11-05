#!/bin/zsh
cd "${0:A:h}/.."
if [[ ! -x .runtime/desktop-venv/bin/python ]]; then
  print "请先用 Python 3.12 创建 .runtime/desktop-venv，并安装 desktop/requirements.txt。"
  exit 1
fi
exec .runtime/desktop-venv/bin/python desktop_main.py
