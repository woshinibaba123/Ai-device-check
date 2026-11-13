#!/bin/bash
# scheduler_tick.sh —— codex 总调度器（launchd 每 2 小时触发一次）
#
# 每次触发依次执行：
#   1. codex_auto_resume.sh watchdog —— 续跑 2 小时内未完成的 codex 任务
#   2. case_import_task.sh tick      —— 运行项目自动化测试 + 驱动 codex
#      导入/解析 xlsx 用例直到全部成功（额度用尽则等下次触发）
#
# 用法：
#   ./scheduler_tick.sh tick        # launchd 触发入口
#   ./scheduler_tick.sh install     # 安装 launchd 定时任务（每 2 小时触发，安装后 2 小时首次触发）
#   ./scheduler_tick.sh uninstall   # 卸载定时任务
#   ./scheduler_tick.sh status      # 查看两个子任务状态

set -u

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.user.codex-scheduler"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"
TICK_LOG="$BASE_DIR/scheduler.log"
INTERVAL="${CODEX_SCHEDULE_INTERVAL:-7200}"   # 2 小时

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] [scheduler] $*" >> "$TICK_LOG"; }

cmd_tick() {
  log "----- 定时触发开始 -----"
  # 1. 续跑之前未完成的 codex 任务（原 auto-resume 逻辑）
  "$BASE_DIR/codex_auto_resume.sh" watchdog
  # 2. 用例导入/解析任务
  "$BASE_DIR/case_import_task.sh" tick
  log "----- 定时触发结束 -----"
}

cmd_install() {
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${BASE_DIR}/scheduler_tick.sh</string>
        <string>tick</string>
    </array>
    <key>StartInterval</key>
    <integer>${INTERVAL}</integer>
    <key>RunAtLoad</key>
    <false/>
    <key>StandardOutPath</key>
    <string>${TICK_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${TICK_LOG}</string>
</dict>
</plist>
EOF
  launchctl unload "$PLIST" 2>/dev/null
  launchctl load "$PLIST"
  echo "已安装 LaunchAgent: $PLIST"
  echo "调度规则: 每 ${INTERVAL}s（2 小时）触发一次，首次触发在安装完成 2 小时后"
  echo "每次触发: 1) 续跑未完成的 codex 任务  2) 跑项目自动化测试 + 驱动 codex 解析用例"
}

cmd_uninstall() {
  if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null
    rm -f "$PLIST"
    echo "已卸载 LaunchAgent"
  else
    echo "未找到已安装的 LaunchAgent"
  fi
}

cmd_status() {
  echo "== 用例导入任务 =="
  "$BASE_DIR/case_import_task.sh" status
  echo
  echo "== codex 续跑任务 =="
  "$BASE_DIR/codex_auto_resume.sh" status
}

case "${1:-tick}" in
  tick)      cmd_tick ;;
  install)   cmd_install ;;
  uninstall) cmd_uninstall ;;
  status)    cmd_status ;;
  *)         sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
