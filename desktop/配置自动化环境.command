#!/bin/zsh
cd "${0:A:h}/.."
exec .runtime/desktop-venv/bin/python desktop_main.py --setup-runtime
