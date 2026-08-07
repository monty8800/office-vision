#!/bin/zsh
# Office Vision AI 服务管理脚本
# 三个服务跑在 tmux 会话中，终端断开/系统休眠唤醒后依然存活。
#
# 用法：
#   scripts/service.sh start          启动全部服务（自动清理占用端口的旧进程）
#   scripts/service.sh stop           停止全部服务
#   scripts/service.sh restart        重启全部服务
#   scripts/service.sh status         查看端口与 tmux 会话状态
#   scripts/service.sh logs <名称>    查看最近日志（名称：server | agent | dashboard）
#   scripts/service.sh attach         进入 tmux 会话实时查看（Ctrl-b d 退出）

SESSION="office-vision"
SCRIPT="$0"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STOP_FLAG="$ROOT/.service_stopped"  # 存在时服务循环不再自动拉起

# tmux 是非登录 shell，显式补全 PATH（uv 在 ~/.local/bin，npm 在 homebrew）
export PATH="$HOME/.local/bin:/opt/homebrew/bin:$PATH"

UV="$(command -v uv)"
NPM="$(command -v npm)"
TMUX_BIN="$(command -v tmux)"

PORTS=(8000 8100 3000)

_die() { echo "错误：$1" >&2; exit 1; }

_session_exists() { $TMUX_BIN has-session -t "$SESSION" 2>/dev/null; }

_free_ports() {
  for port in $PORTS; do
    local pids
    pids="$(lsof -ti:"$port" 2>/dev/null)"
    if [[ -n "$pids" ]]; then
      echo "清理端口 $port 上的旧进程（PID $(echo "$pids" | tr '\n' ' ')）"
      echo "$pids" | xargs kill 2>/dev/null
    fi
  done
  sleep 2
}

cmd_start() {
  [[ -x "$TMUX_BIN" ]] || _die "tmux 未安装（brew install tmux）"
  [[ -x "$UV" ]] || _die "找不到 uv"
  [[ -x "$NPM" ]] || _die "找不到 npm"
  rm -f "$STOP_FLAG"

  if _session_exists; then
    echo "tmux 会话 $SESSION 已存在，先执行 stop"
    cmd_stop
  fi
  _free_ports

  # 服务包在循环里：崩溃后 3 秒自动拉起，窗口不会随进程退出而消失；stop 标记存在时循环退出
  $TMUX_BIN new-session -d -s "$SESSION" -n server \
    "while [ ! -f $STOP_FLAG ]; do cd $ROOT/office-vision-server && $UV run uvicorn server.main:app --host 0.0.0.0 --port 8000; echo \"[server] 进程退出，3 秒后自动重启\"; sleep 3; done"
  $TMUX_BIN new-window -t "$SESSION" -n agent \
    "while [ ! -f $STOP_FLAG ]; do cd $ROOT/office-vision-agent && $UV run python -m agent.main; echo \"[agent] 进程退出，3 秒后自动重启\"; sleep 3; done"
  $TMUX_BIN new-window -t "$SESSION" -n dashboard \
    "while [ ! -f $STOP_FLAG ]; do cd $ROOT/office-vision-dashboard && $NPM run dev; echo \"[dashboard] 进程退出，3 秒后自动重启\"; sleep 3; done"

  echo "已在 tmux 会话 $SESSION 中启动三个服务"
  sleep 8
  cmd_status
}

cmd_stop() {
  touch "$STOP_FLAG"  # 让服务循环退出，避免 kill 后被自动拉起
  sleep 1
  if _session_exists; then
    $TMUX_BIN kill-session -t "$SESSION"
    echo "tmux 会话 $SESSION 已终止"
  fi
  _free_ports
  echo "全部服务已停止"
}

cmd_status() {
  local names=(Server Agent Dashboard)
  local i=1
  for port in $PORTS; do
    if lsof -ti:"$port" >/dev/null 2>&1; then
      echo ":$port $names[$i]  ✅ 运行中"
    else
      echo ":$port $names[$i]  ❌ 已停止"
    fi
    i=$((i + 1))
  done
  if _session_exists; then
    echo "tmux 会话：$SESSION 存在（$SCRIPT logs <名称> 查看日志）"
  else
    echo "tmux 会话：不存在"
  fi
}

cmd_logs() {
  local name="${1:-}"
  [[ -n "$name" ]] || _die "用法：$SCRIPT logs <server|agent|dashboard>"
  _session_exists || _die "tmux 会话不存在，请先 start"
  $TMUX_BIN capture-pane -pt "$SESSION:$name" -S -50
}

cmd_attach() {
  _session_exists || _die "tmux 会话不存在，请先 start"
  exec $TMUX_BIN attach -t "$SESSION"
}

case "${1:-}" in
  start) cmd_start ;;
  stop) cmd_stop ;;
  restart) cmd_stop; cmd_start ;;
  status) cmd_status ;;
  logs) cmd_logs "${2:-}" ;;
  attach) cmd_attach ;;
  *)
    echo "用法：$SCRIPT <start|stop|restart|status|logs|attach>"
    exit 1
    ;;
esac
