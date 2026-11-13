#!/bin/bash
# case_import_task.sh —— 用例导入/解析任务（由 scheduler_tick.sh 每 2 小时触发一次）
#
# 每次触发（tick）：
#   1. 已完成则直接退出
#   2. 运行 deviceCheck 项目自动化测试（unittest discover，带超时）
#   3. 本地检查 xlsx 解析情况（check_case_parse.py）
#      -> 全部解析成功：标记 done，结束
#   4. 否则调用 codex exec，让它修复直到所有用例解析成功
#      -> 检测到额度用尽：标记 waiting_quota，等下一次（2 小时后）触发再继续
#
# 用法：
#   ./case_import_task.sh tick        # 定时触发入口
#   ./case_import_task.sh run-now     # 立即执行一轮（不等 2 小时）
#   ./case_import_task.sh status      # 查看状态
#   ./case_import_task.sh reset       # 重置任务状态（重新开始）
#   ./case_import_task.sh logs        # 查看最近日志

set -u

BASE_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="/Users/apple/Documents/deviceCheck"
XLSX_PATH="/Users/apple/Downloads/App与H5全功能多语言测试用例.xlsx"

STATE_DIR="$HOME/.codex_case_import"
STATE_FILE="$STATE_DIR/state"
LOG_FILE="$STATE_DIR/task.log"
CODEX_LOG="$STATE_DIR/codex.log"
TESTS_LOG="$STATE_DIR/tests.log"
PROMPT_FILE="$STATE_DIR/prompt.txt"
LOCK_DIR="$STATE_DIR/lock"

TEST_TIMEOUT="${CASE_IMPORT_TEST_TIMEOUT:-900}"   # 单测最长跑 15 分钟
DONE_MARKER="ALL_CASES_PARSED"
QUOTA_MARKER="QUOTA_WAIT"
# codex 输出中判定"额度用尽"的关键词（不区分大小写）
QUOTA_PATTERNS="usage limit|rate limit|quota|credit|upgrade to|limit reached|try again later|429|额度|配额|用量已达到"

now() { date +%s; }
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG_FILE"; }
get_state() { [ -f "$STATE_FILE" ] && cat "$STATE_FILE" || echo "idle"; }
set_state() { init_dirs; printf '%s' "$1" > "$STATE_FILE"; }
init_dirs() { mkdir -p "$STATE_DIR"; }

run_with_timeout() { # run_with_timeout <秒数> <命令...>
  local limit="$1"; shift
  "$@" &
  local pid=$! waited=0
  while kill -0 "$pid" 2>/dev/null && [ "$waited" -lt "$limit" ]; do
    sleep 10; waited=$((waited + 10))
  done
  if kill -0 "$pid" 2>/dev/null; then
    kill -9 "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
    return 124
  fi
  wait "$pid"; return $?
}

run_tests() {
  log "开始运行项目自动化测试 (unittest discover，超时 ${TEST_TIMEOUT}s)..."
  cd "$PROJECT_DIR" || return 1
  run_with_timeout "$TEST_TIMEOUT" /usr/bin/python3 -m unittest discover -s "$PROJECT_DIR" -t "$PROJECT_DIR" \
    > "$TESTS_LOG" 2>&1
  local rc=$?
  if [ "$rc" -eq 0 ]; then
    log "自动化测试通过"
  elif [ "$rc" -eq 124 ]; then
    log "自动化测试超时(${TEST_TIMEOUT}s)被终止，详情见 $TESTS_LOG"
  else
    log "自动化测试存在失败 (exit=$rc)，详情见 $TESTS_LOG"
  fi
  return "$rc"
}

check_parse() { # 本地解析检查，报告写入 codex_scheduler/parse_report.json
  /usr/bin/python3 "$BASE_DIR/check_case_parse.py" >> "$LOG_FILE" 2>&1
}

build_prompt() {
  local tests_summary="本轮自动化测试已运行，结果见 $TESTS_LOG"
  if grep -qE "^(FAILED|ERROR)" "$TESTS_LOG" 2>/dev/null; then
    tests_summary="本轮自动化测试有失败项（见 $TESTS_LOG 末尾的 FAILED/ERROR 摘要），请先修复明显阻塞性问题"
  fi
  cat > "$PROMPT_FILE" <<EOF
项目目录：$PROJECT_DIR（请以此作为工作目录）
任务：导入并解析测试用例文件 $XLSX_PATH，反复修复，直到所有用例都能解析成功为止。

解析检查命令（判定"全部解析成功"的唯一标准，在项目目录运行）：
  /usr/bin/python3 $BASE_DIR/check_case_parse.py
  - 退出码 0 且报告 ok=true：全部解析成功，输出 $DONE_MARKER 并结束
  - 退出码 1：读取 $BASE_DIR/parse_report.json 中 failures 的用例 id/标题/reason，针对性修复

工作循环：
  1. 运行上面的检查命令，查看失败原因
  2. 修复问题（可能是 xlsx 用例内容问题、case_workbook/case_runner 解析逻辑问题、或缺少 AI 步骤计划；
     如需生成 AI 步骤计划，可参考 excel_ai.py / excel_plan_cache.py，或启动 python3 app.py 后调用
     POST http://127.0.0.1:8765/api/cases/preview）
  3. 再次运行检查命令，循环直到 ok=true

注意事项：
  - 不要直接修改 Downloads 下的原始 xlsx；如需改用例，先复制到项目目录（如 testdata/）再修改，
    并同步调整检查脚本中 XLSX_PATH 指向副本
  - 项目自动化测试：$tests_summary；修复解析相关改动后建议至少回归 test_case_workbook.py 和 test_excel_ai.py
  - 如果遇到平台额度/配额用尽（usage limit、rate limit 等），不要重试，立即输出 $QUOTA_MARKER 并正常结束本次运行
  - 只有当检查命令确认所有用例解析成功后，才输出 $DONE_MARKER
EOF
}

run_codex() {
  build_prompt
  : > "$CODEX_LOG"
  log "调用 codex 开始修复用例解析问题..."
  codex exec -C "$PROJECT_DIR" -s workspace-write --skip-git-repo-check - \
    < "$PROMPT_FILE" >> "$CODEX_LOG" 2>&1
  local rc=$?
  log "codex 退出 (exit=$rc)"
  echo "$rc"
}

cmd_tick() {
  init_dirs
  # 防止上一轮还没跑完就重复触发
  if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    log "上一轮任务仍在运行，本次触发跳过"
    exit 0
  fi
  trap 'rmdir "$LOCK_DIR" 2>/dev/null' EXIT

  local state; state="$(get_state)"
  if [ "$state" = "done" ]; then
    log "任务已完成，跳过本次触发"
    exit 0
  fi

  log "===== 触发用例导入任务（当前状态: ${state}）====="

  # 1. 项目自动化测试（无论是否失败都继续，测试报告会交给 codex）
  run_tests || true

  # 2. 本地解析检查
  if check_parse; then
    set_state "done"
    log "所有用例已解析成功，任务完成 ✔"
    exit 0
  fi
  log "解析检查未通过，转交 codex 处理"

  # 3. codex 修复
  local rc; rc="$(run_codex)"

  # 4. 判断额度用尽 / 完成
  if grep -qiE "$QUOTA_PATTERNS" "$CODEX_LOG" 2>/dev/null; then
    set_state "waiting_quota"
    log "检测到额度/配额可能用尽，等待下次触发（2 小时后）自动继续"
    exit 0
  fi

  # codex 完成后再验证一次
  if check_parse; then
    set_state "done"
    log "所有用例已解析成功，任务完成 ✔"
  else
    set_state "incomplete"
    log "本轮 codex 未解决全部解析问题，等待下次触发继续"
  fi
}

cmd_status() {
  local state; state="$(get_state)"
  echo "任务状态: $state"
  echo "状态目录: $STATE_DIR"
  [ -f "$LOG_FILE" ] && echo "--- 最近日志 ---" && tail -n 20 "$LOG_FILE"
}

cmd_reset() {
  init_dirs
  set_state "idle"
  echo "已重置任务状态"
}

cmd_logs() {
  [ -f "$LOG_FILE" ] && tail -n 50 "$LOG_FILE" || echo "暂无日志"
  [ -f "$CODEX_LOG" ] && echo "--- codex 输出(尾部) ---" && tail -n 30 "$CODEX_LOG"
}

case "${1:-tick}" in
  tick)    cmd_tick ;;
  run-now) cmd_tick ;;
  status)  cmd_status ;;
  reset)   cmd_reset ;;
  logs)    cmd_logs ;;
  *)       sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
