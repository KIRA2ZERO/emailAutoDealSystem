#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$APP_DIR/service.pid"
LOG_DIR="$APP_DIR/logs"
SERVICE_LOG="$LOG_DIR/service.log"

mkdir -p "$LOG_DIR"
cd "$APP_DIR"

if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE")"
  if [[ -n "$OLD_PID" ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "服务已在运行: pid=$OLD_PID"
    echo "日志文件: $SERVICE_LOG"
    exit 0
  fi
  rm -f "$PID_FILE"
fi

setsid nohup python3 autoDownload.py >> "$SERVICE_LOG" 2>&1 &
PID="$!"
echo "$PID" > "$PID_FILE"

echo "服务已启动: pid=$PID"
echo "日志文件: $SERVICE_LOG"
