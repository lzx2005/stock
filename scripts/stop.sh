#!/bin/bash
# 一键停止盯盘系统（只停通过 start.sh 启动的进程，按 pid 文件）
set -u
cd "$(dirname "$0")/.." || exit 1

stop_one() {  # $1=pidfile $2=名字
  if [ ! -f "$1" ]; then
    echo "$2：无 pid 记录（可能不是 start.sh 启动的，手动 ps 查）"
    return
  fi
  pid=$(cat "$1")
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" && echo "$2 已停止 (pid $pid)"
  else
    echo "$2 本就不在运行 (pid $pid 已退出)"
  fi
  rm -f "$1"
}

stop_one data/logs/monitor.pid "盯盘守护进程"
stop_one data/logs/webui.pid "Web API"
