#!/bin/zsh
app_binary="/Applications/巡测.app/Contents/MacOS/DeviceCheck"
if [[ ! -x "$app_binary" ]]; then
  app_binary="${0:A:h}/巡测.app/Contents/MacOS/DeviceCheck"
fi
if [[ ! -x "$app_binary" ]]; then
  print "请先把巡测.app 拖入 Applications。"
  exit 1
fi
exec "$app_binary" --setup-runtime
