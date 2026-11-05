#!/bin/zsh
set -e
cd "${0:A:h}"
export ANDROID_HOME="${ANDROID_HOME:-$HOME/Library/Android/sdk}"
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME="${JAVA_HOME:-$(/usr/libexec/java_home 2>/dev/null)}"
export APPIUM_HOME="$PWD/.appium"
if [[ -f "$PWD/.runtime/node-path" ]]; then
  export PATH="$(cat "$PWD/.runtime/node-path"):$PATH"
fi
command -v node >/dev/null || { print '请先安装 Node.js 20.19 或更新的受支持版本'; exit 1; }
mkdir -p .runtime
node -e 'process.stdout.write(require("path").dirname(process.execPath))' > .runtime/node-path
npm install --prefix .runtime appium@3.8.0 --registry=https://registry.npmjs.org
export npm_config_registry=https://registry.npmjs.org
for driver in uiautomator2 xcuitest; do
  if ! .runtime/node_modules/.bin/appium driver list --installed --json | /usr/bin/python3 -c 'import json,sys;sys.exit(0 if sys.argv[1] in json.load(sys.stdin) else 1)' "$driver"; then
    .runtime/node_modules/.bin/appium driver install "$driver"
  fi
done
/usr/bin/python3 wda_compat.py
sdkmanager="$ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager"
[[ -x "$sdkmanager" ]] || { print '请先通过 Android Studio 安装 SDK Command-line Tools'; exit 1; }
proxy_args=()
if /usr/bin/python3 -c 'import socket;s=socket.socket();s.settimeout(.3);exit(s.connect_ex(("127.0.0.1",7890)))'; then
  print '使用本机已有的 7890 代理下载 Android 镜像'
  proxy_args=(--proxy=http --proxy_host=127.0.0.1 --proxy_port=7890)
fi
arch=arm64-v8a
[[ "$(uname -m)" == x86_64 ]] && arch=x86_64
"$sdkmanager" "${proxy_args[@]}" "system-images;android-29;google_apis;$arch" "system-images;android-33;google_apis;$arch" "system-images;android-34;google_apis;$arch" "system-images;android-35;google_apis;$arch" "system-images;android-36;google_apis;$arch"
print '依赖安装完成。双击 启动工具.command 即可使用。'
