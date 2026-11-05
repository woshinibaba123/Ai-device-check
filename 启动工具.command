#!/bin/zsh
cd "${0:A:h}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${JAVA_HOME:-$(/usr/libexec/java_home 2>/dev/null)}"
if [[ -f "$PWD/.runtime/node-path" ]]; then
  export PATH="$(cat "$PWD/.runtime/node-path"):$PATH"
fi
export PATH="$PWD/.runtime/node_modules/.bin:$ANDROID_HOME/platform-tools:$ANDROID_HOME/emulator:$ANDROID_HOME/cmdline-tools/latest/bin:$PATH"
if ! /usr/bin/curl --noproxy '*' -sf http://127.0.0.1:4723/status >/dev/null; then
  if [[ -x "$PWD/.runtime/node_modules/.bin/appium" ]]; then
    nohup ./启动自动操作服务.command > "$PWD/appium-console.log" 2>&1 &
  fi
fi
for attempt in {1..20}; do
  /usr/bin/curl --noproxy '*' -sf http://127.0.0.1:4723/status >/dev/null && break
  sleep 1
done
if /usr/bin/curl --noproxy '*' -sf http://127.0.0.1:8765/api/jobs >/dev/null; then
  open http://127.0.0.1:8765
  exit 0
fi
(sleep 1; open http://127.0.0.1:8765) &
/usr/bin/python3 app.py
