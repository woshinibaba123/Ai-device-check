#!/bin/zsh
cd "${0:A:h}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${JAVA_HOME:-$(/usr/libexec/java_home 2>/dev/null)}"
export APPIUM_HOME="$PWD/.appium"
if [[ -f "$PWD/.runtime/node-path" ]]; then
  export PATH="$(cat "$PWD/.runtime/node-path"):$PATH"
fi
export PATH="$PWD/.runtime/node_modules/.bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
if [[ ! -x "$PWD/.runtime/node_modules/.bin/appium" ]]; then
  print "缺少自动操作服务，请先配置 Appium。"
  exit 1
fi
exec "$PWD/.runtime/node_modules/.bin/appium" --address 127.0.0.1 --port 4723 --log "$PWD/appium.log" --log-no-colors --log-level warn
