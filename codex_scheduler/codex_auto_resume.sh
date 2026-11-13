#!/bin/bash
# codex_auto_resume.sh —— codex 任务定时续跑工具
#
# 功能：
#   1. 后台启动一个 codex 任务（codex exec）
#   2. 由 launchd 定时调用 watchdog：若任务开始/上次续跑超过 2 小时仍未完成，
#      自动执行 `codex exec resume --last` 让 codex 从中断处继续
#   3. 循环续跑直到任务完成（可用环境变量调整间隔与次数上限）
#
# 用法：
#   ./codex_auto_resume.sh start "你的任务描述"   # 启动任务
#   ./codex_auto_resume.sh status                 # 查看任务状态
#   ./codex_auto_resume.sh resume-now             # 立即续跑（不等 2 小时）
#   ./codex_auto_resume.sh logs                   # 查看 codex 输出日志
#   ./codex_auto_resume.sh stop                   # 停止任务并清除状态
#   ./codex_auto_resume.sh install                # 安装 launchd 定时任务（开机自启）
#   ./codex_auto_resume.sh uninstall              # 卸载 launchd 定时任务
#
# 可配置环境变量：
#   CODEX_RESUME_INTERVAL  续跑判定间隔，默认 7200 秒（2 小时）
#   CODEX_CHECK_INTERVAL   watchdog 检查频率，默认 1800 秒（30 分钟）
#   CODEX_MAX_RESUMES      最大自动续跑次数，默认 10
#   CODEX_RESUME_PROMPT    续跑时发给 codex 的指令

set -u

STATE_DIR="${HOME}/.codex_auto_resume"
STATE_FILE="${STATE_DIR}/task.state"
LOG_FILE="${STATE_DIR}/codex.log"
WATCHDOG_LOG="${STATE_DIR}/watchdog.log"
LOCK_DIR="${STATE_DIR}/lock"

RESUME_INTERVAL="${CODEX_RESUME_INTERVAL:-7200}"
CHECK_INTERVAL="${CODEX_CHECK_INTERVAL:-1800}"
MAX_RESUMES="${CODEX_MAX_RESUMES:-10}"
RESUME_PROMPT="${CODEX_RESUME_PROMPT:-继续执行之前未完成的任务。先回顾当前进度，从上次中断的地方接着做，直到任务全部完成后结束。}"

now() { date +%s; }

init_dirs() { mkdir -p "$STATE_DIR"; }

get() { # 读取状态文件中某个 key 的值
  [ -f "$STATE_FILE" ] || return 1
  awk -v k="$1" '$0 ~ "^"k"=" {print substr($0, length(k)+2); exit}' "$STATE_FILE"
}

set_kv() { # 写入/更新某个 key
  local key="$1" val="$2" tmp="${STATE_FILE}.tmp"
  touch "$STATE_FILE"
  if grep -q "^${key}=" "$STATE_FILE"; then
    awk -v k="$key" -v v="$val" '
      $0 ~ "^"k"=" {print k"="v; found=1; next}
      {print}
      END {if (!found) print k"="v}
    ' "$STATE_FILE" > "$tmp" && mv "$tmp" "$STATE_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$STATE_FILE"
  fi
}

pid_alive() {
  local pid="$1"
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

clear_state() { rm -f "$STATE_FILE"; }

# ---------- 子命令 ----------

cmd_start() { # start "<任务描述>"
  local prompt="${1:-}"
  if [ -z "$prompt" ]; then
    echo '用法: ./codex_auto_resume.sh start "你的任务描述"'
    exit 1
  fi
  init_dirs
  if [ "$(get status 2>/dev/null)" = "running" ] && pid_alive "$(get pid)"; then
    echo "已有任务在运行中 (pid=$(get pid))，先执行 ./codex_auto_resume.sh status 查看"
    exit 1
  fi
  : > "$LOG_FILE"
  clear_state
  set_kv prompt "$prompt"
  set_kv started_at "$(now)"
  set_kv last_resume_at "$(now)"
  set_kv resume_count "0"
  set_kv status "running"
  nohup "$0" _run "$prompt" >> "$LOG_FILE" 2>&1 &
  set_kv pid "$!"
  echo "任务已启动 (pid=$(get pid))"
  echo "日志: tail -f $LOG_FILE"
  echo "状态: ./codex_auto_resume.sh status"
}

cmd_run() { # 内部命令：前台运行 codex，结束后写回状态
  local prompt="$1"
  set_kv pid "$$"
  codex exec "$prompt"
  local rc=$?
  set_kv finished_at "$(now)"
  if [ "$rc" -eq 0 ]; then
    set_kv status "done"
    echo "[$(date)] 任务完成" >> "$WATCHDOG_LOG"
  else
    set_kv status "failed"
    set_kv last_exit "$rc"
    echo "[$(date)] 任务异常退出 (exit=$rc)，等待自动续跑" >> "$WATCHDOG_LOG"
  fi
}

cmd_watchdog() { # 由 launchd 定时调用
  init_dirs
  [ -f "$STATE_FILE" ] || exit 0

  local status; status="$(get status)"
  [ "$status" = "done" ] && exit 0

  # 防止多个 watchdog 并发
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then exit 0; fi
  trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

  # 任务进程还在运行 => 正在执行中，不需要续跑
  if pid_alive "$(get pid)"; then exit 0; fi

  local last_resume; last_resume="$(get last_resume_at)"; last_resume="${last_resume:-0}"
  local elapsed=$(( $(now) - last_resume ))
  if [ "$elapsed" -lt "$RESUME_INTERVAL" ]; then exit 0; fi

  local count; count="$(get resume_count)"; count="${count:-0}"
  if [ "$count" -ge "$MAX_RESUMES" ]; then
    echo "[$(date)] 已达最大续跑次数 ${MAX_RESUMES}，停止自动续跑，请人工检查" >> "$WATCHDOG_LOG"
    exit 0
  fi

  echo "[$(date)] 距上次活动 ${elapsed}s >= ${RESUME_INTERVAL}s，自动续跑未完成任务 (第 $((count+1)) 次)..." >> "$WATCHDOG_LOG"
  set_kv status "resuming"
  {
    echo ""
    echo "===== 自动续跑 $(date) ====="
  } >> "$LOG_FILE"
  codex exec resume --last "$RESUME_PROMPT" >> "$LOG_FILE" 2>&1
  local rc=$?
  set_kv last_resume_at "$(now)"
  set_kv resume_count "$((count + 1))"
  if [ "$rc" -eq 0 ]; then
    set_kv status "done"
    echo "[$(date)] 续跑完成，任务结束" >> "$WATCHDOG_LOG"
  else
    set_kv status "failed"
    set_kv last_exit "$rc"
    echo "[$(date)] 续跑异常退出 (exit=$rc)，2 小时后将再次尝试" >> "$WATCHDOG_LOG"
  fi
}

cmd_resume_now() {
  init_dirs
  [ -f "$STATE_FILE" ] || { echo "当前没有任务记录，先执行 start"; exit 1; }
  # 把 last_resume_at 拨回到 2 小时前，触发 watchdog 立即续跑
  set_kv last_resume_at "$(( $(now) - RESUME_INTERVAL - 1 ))"
  "$0" watchdog
}

cmd_status() {
  if [ ! -f "$STATE_FILE" ]; then
    echo "当前没有任务记录"
    exit 0
  fi
  local status pid started count
  status="$(get status)"; pid="$(get pid)"; started="$(get started_at)"; count="$(get resume_count)"
  echo "状态:     $status"
  echo "PID:      $pid $(pid_alive "$pid" && echo '(运行中)' || echo '(已停止)')"
  [ -n "$started" ] && echo "开始时间: $(date -r "$started" '+%Y-%m-%d %H:%M:%S')"
  echo "已续跑:   ${count:-0} 次"
  echo "日志:     $LOG_FILE"
  echo "watchdog: $WATCHDOG_LOG"
}

cmd_stop() {
  local pid; pid="$(get pid 2>/dev/null)"
  if pid_alive "$pid"; then
    kill "$pid" 2>/dev/null && echo "已停止进程 $pid"
  fi
  clear_state
  echo "已清除任务状态"
}

cmd_logs() {
  [ -f "$LOG_FILE" ] && tail -n 50 "$LOG_FILE" || echo "暂无日志"
}

cmd_install() { # 安装 launchd 定时任务
  local script_path
  script_path="$(cd "$(dirname "$0")" && pwd)/$(basename "$0")"
  local plist="$HOME/Library/LaunchAgents/com.user.codex-autoresume.plist"
  mkdir -p "$HOME/Library/LaunchAgents"
  cat > "$plist" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.user.codex-autoresume</string>
    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>${script_path}</string>
        <string>watchdog</string>
    </array>
    <key>StartInterval</key>
    <integer>${CHECK_INTERVAL}</integer>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>${WATCHDOG_LOG}</string>
    <key>StandardErrorPath</key>
    <string>${WATCHDOG_LOG}</string>
</dict>
</plist>
EOF
  launchctl unload "$plist" 2>/dev/null
  launchctl load "$plist"
  echo "已安装 LaunchAgent: $plist"
  echo "每 ${CHECK_INTERVAL}s 检查一次；任务开始/上次续跑 ${RESUME_INTERVAL}s（2 小时）后未完成则自动续跑"
}

cmd_uninstall() {
  local plist="$HOME/Library/LaunchAgents/com.user.codex-autoresume.plist"
  if [ -f "$plist" ]; then
    launchctl unload "$plist" 2>/dev/null
    rm -f "$plist"
    echo "已卸载 LaunchAgent"
  else
    echo "未找到已安装的 LaunchAgent"
  fi
}

# ---------- 入口 ----------

case "${1:-}" in
  start)      shift; cmd_start "${1:-}" ;;
  _run)       shift; cmd_run "${1:-}" ;;
  watchdog)   cmd_watchdog ;;
  resume-now) cmd_resume_now ;;
  status)     cmd_status ;;
  stop)       cmd_stop ;;
  logs)       cmd_logs ;;
  install)    cmd_install ;;
  uninstall)  cmd_uninstall ;;
  *)
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
