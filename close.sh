#!/usr/bin/env bash
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$APP_DIR/service.pid"

if [[ ! -f "$PID_FILE" ]]; then
  echo "服务未运行: 找不到 $PID_FILE"
  exit 0
fi

PID="$(cat "$PID_FILE")"
if [[ -z "$PID" ]] || ! kill -0 "$PID" 2>/dev/null; then
  echo "服务未运行: pid=$PID"
  rm -f "$PID_FILE"
  exit 0
fi

echo "正在停止服务: pid=$PID"
kill "$PID"

for _ in {1..10}; do
  if ! kill -0 "$PID" 2>/dev/null; then
    rm -f "$PID_FILE"
    echo "服务已停止"
    exit 0
  fi
  sleep 1
done

echo "服务未在 10 秒内退出，强制停止: pid=$PID"
kill -9 "$PID" 2>/dev/null || true
rm -f "$PID_FILE"
echo "服务已强制停止"
