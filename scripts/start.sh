#!/bin/bash
# 一键启动盯盘系统：盯盘守护进程 + Web API 服务（serve.py 纯 /api，无内置前端；前端在独立工程，proxy 到 8666）
# 后台运行，日志/pid 在 data/logs/
set -u
cd "$(dirname "$0")/.." || exit 1
# 拿 TICKFLOW_API_KEY：已在环境里就直接用；否则开一个交互 zsh 读 ~/.zshrc
# （直接 source ~/.zshrc 会把 zsh 专有语法喂给 sh 导致脚本中断，不能那么干）
if [ -z "${TICKFLOW_API_KEY:-}" ]; then
  TICKFLOW_API_KEY="$(zsh -ic 'echo -n $TICKFLOW_API_KEY' 2>/dev/null | tail -c 64)"
  export TICKFLOW_API_KEY
fi
[ -n "${TICKFLOW_API_KEY:-}" ] && echo "TICKFLOW_API_KEY 已加载" || echo "警告：未取到 TICKFLOW_API_KEY，盯盘取数会失败"

mkdir -p data/logs

is_running() { [ -f "$1" ] && kill -0 "$(cat "$1")" 2>/dev/null; }

if is_running data/logs/monitor.pid; then
  echo "盯盘守护进程已在运行 (pid $(cat data/logs/monitor.pid))"
else
  nohup .venv/bin/python -u scripts/monitor_daemon.py > data/logs/monitor.log 2>&1 &
  echo $! > data/logs/monitor.pid
  echo "盯盘守护进程已启动 (pid $!)，日志 data/logs/monitor.log"
fi

if is_running data/logs/webui.pid; then
  echo "Web API 已在运行 (pid $(cat data/logs/webui.pid))"
elif lsof -nP -iTCP:8666 -sTCP:LISTEN >/dev/null 2>&1; then
  holder=$(lsof -nP -iTCP:8666 -sTCP:LISTEN | tail -1 | awk '{print $1" pid="$2}')
  echo "警告：8666 已被占用（${holder}，非 start.sh 启动），Web API 未启动。确认后可 kill 再重跑 start.sh"
else
  nohup .venv/bin/python -u scripts/serve.py > data/logs/webui.log 2>&1 &
  echo $! > data/logs/webui.pid
  echo "Web API 已启动 (pid $!)，接口 http://127.0.0.1:8666/api ，日志 data/logs/webui.log"
fi
