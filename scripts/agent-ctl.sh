#!/bin/bash
# agent-ctl - full Atrophy system management CLI
#
# Designed for both desktop use and headless GPU deployment.
# All operations work without the Electron GUI.
#
# AGENTS
#   agent-ctl status                       - all agents: state, last tool, uptime
#   agent-ctl stop <name>                  - interrupt current inference (Ctrl+C)
#   agent-ctl restart <name> [--fresh]     - restart agent (--fresh = new session)
#   agent-ctl send <name> <message>        - send a message
#   agent-ctl logs <name> [N]              - tail recent activity (default 30 lines)
#   agent-ctl peek <name>                  - show terminal content
#   agent-ctl kill <name>                  - kill tmux window
#   agent-ctl list                         - list all agent directories
#
# SYSTEM
#   agent-ctl boot                         - start tmux session + all primary agents
#   agent-ctl shutdown                     - stop all agents and kill tmux session
#   agent-ctl health                       - HTTP API health check
#   agent-ctl cron                         - show cron job status (recent runs)
#   agent-ctl errors [N]                   - show recent errors from app.log
#
# INFERENCE
#   agent-ctl chat <name> <message>        - send via HTTP API, stream response
#   agent-ctl switch <name>                - switch active agent via HTTP API
#
# DATABASE
#   agent-ctl turns <name> [N]             - show recent conversation turns
#   agent-ctl sessions <name> [N]          - show recent sessions
#   agent-ctl threads <name> [N]           - show active memory threads
#
# TMUX
#   agent-ctl attach [name]                - attach to tmux session or agent window
#   agent-ctl windows                      - list all tmux windows

set -uo pipefail

SESSION="atrophy"
ATROPHY_DIR="$HOME/.atrophy"
CLAUDE_PROJECTS="$HOME/.claude/projects"
LOG="$ATROPHY_DIR/logs/app.log"
TOKEN_FILE="$ATROPHY_DIR/server_token"
API_PORT=3847

red()   { printf '\033[31m%s\033[0m' "$1"; }
green() { printf '\033[32m%s\033[0m' "$1"; }
yellow(){ printf '\033[33m%s\033[0m' "$1"; }
dim()   { printf '\033[2m%s\033[0m' "$1"; }
bold()  { printf '\033[1m%s\033[0m' "$1"; }

get_token() {
  cat "$TOKEN_FILE" 2>/dev/null || echo ""
}

api() {
  local method="$1" endpoint="$2" body="${3:-}"
  local token
  token=$(get_token)
  if [ -z "$token" ]; then echo "No server token"; return 1; fi

  if [ "$method" = "GET" ]; then
    curl -s -H "Authorization: Bearer $token" "http://127.0.0.1:$API_PORT$endpoint" 2>/dev/null
  else
    curl -s -X "$method" -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
      -d "$body" "http://127.0.0.1:$API_PORT$endpoint" 2>/dev/null
  fi
}

# Resolve an agent's directory, checking both flat (~/.atrophy/agents/<name>/)
# and org-nested (~/.atrophy/agents/<org>/<name>/) layouts.
agent_dir() {
  local name="$1"
  # Flat layout
  if [ -d "$ATROPHY_DIR/agents/$name/data" ]; then
    echo "$ATROPHY_DIR/agents/$name"
    return 0
  fi
  # Org-nested layout
  for entry in "$ATROPHY_DIR"/agents/*/; do
    local nested="${entry}$name/data"
    if [ -d "$nested" ]; then
      echo "${entry}$name"
      return 0
    fi
  done
  return 1
}

# Iterate over every agent directory (flat + nested), one path per line.
all_agent_dirs() {
  for top in "$ATROPHY_DIR"/agents/*/; do
    if [ -d "${top}data" ]; then
      echo "${top%/}"
    else
      for sub in "${top}"*/; do
        if [ -d "${sub}data" ]; then
          echo "${sub%/}"
        fi
      done
    fi
  done
}

# ─────────────────────────────────────────────────────────────────────────────
# AGENT COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

cmd_status() {
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "No tmux session '$SESSION' running."
    echo "Run: agent-ctl boot"
    exit 1
  fi

  printf "\n"
  printf "  %-22s %-10s %-12s %-20s\n" "AGENT" "STATUS" "UPTIME" "LAST TOOL"
  printf "  %-22s %-10s %-12s %-20s\n" "-----" "------" "------" "---------"

  while read -r name; do
    [ "$name" = "zsh" ] || [ "$name" = "bash" ] && continue
    activity=""

    # Check if window has a running claude process
    pane_pid=$(tmux list-panes -t "$SESSION:$name" -F '#{pane_pid}' 2>/dev/null | head -1)
    has_claude=$(pgrep -P "$pane_pid" 2>/dev/null | head -1)

    if [ -n "$has_claude" ]; then
      # Check last 3 lines of terminal for activity indicators
      pane_tail=$(tmux capture-pane -t "$SESSION:$name" -p 2>/dev/null | tail -3)
      if echo "$pane_tail" | grep -qE 'Thinking|thinking|tool_use|Running'; then
        status=$(yellow "busy")
      else
        status=$(green "idle")
      fi
    else
      status=$(red "down")
    fi

    # Uptime from window activity timestamp
    uptime="-"
    if [ -n "$activity" ] && [ "$activity" != "0" ]; then
      now=$(date +%s)
      diff=$((now - activity))
      if [ "$diff" -lt 60 ]; then
        uptime="${diff}s"
      elif [ "$diff" -lt 3600 ]; then
        uptime="$((diff / 60))m"
      else
        uptime="$((diff / 3600))h$((diff % 3600 / 60))m"
      fi
    fi

    # Last tool from logs
    last_tool=$(grep "$name.*tool ->" "$LOG" 2>/dev/null | tail -1 | sed 's/.*tool -> //' | head -c 20)
    [ -z "$last_tool" ] && last_tool="-"

    printf "  %-22s %-20s %-12s %-20s\n" "$name" "$status" "$uptime" "$last_tool"
  done < <(tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null)
  printf "\n"
}

cmd_stop() {
  local name="$1"
  [ -z "$name" ] && echo "Usage: agent-ctl stop <name>" && exit 1
  tmux send-keys -t "$SESSION:$name" C-c 2>/dev/null && echo "Stopped $name" || echo "Window $name not found"
}

cmd_restart() {
  local name="$1"
  local flag="${2:-}"
  [ -z "$name" ] && echo "Usage: agent-ctl restart <name> [--fresh]" && exit 1

  local mcp_config="$ATROPHY_DIR/mcp/$name.config.json"
  [ ! -f "$mcp_config" ] && echo "No MCP config at $mcp_config" && exit 1

  local dir
  dir=$(agent_dir "$name")
  if [ -z "$dir" ]; then
    echo "Agent '$name' not found in $ATROPHY_DIR/agents/ (flat or nested)"
    exit 1
  fi

  local session_id
  if [ "$flag" = "--fresh" ]; then
    session_id=$(python3 -c "import uuid; print(uuid.uuid4())")
    echo "Fresh session: $session_id"
  else
    session_id=$(sqlite3 "$dir/data/memory.db" \
      "SELECT cli_session_id FROM sessions WHERE cli_session_id IS NOT NULL ORDER BY started_at DESC LIMIT 1;" 2>/dev/null)
    [ -z "$session_id" ] && session_id=$(python3 -c "import uuid; print(uuid.uuid4())")
    echo "Session: $session_id"
  fi

  # Stop existing
  tmux send-keys -t "$SESSION:$name" C-c 2>/dev/null; sleep 1
  tmux kill-window -t "$SESSION:$name" 2>/dev/null; sleep 1

  # Start new
  tmux new-window -t "$SESSION" -n "$name" -c "$dir"
  sleep 1

  local cmd="claude"
  [ "$flag" = "--fresh" ] && cmd="$cmd --session-id $session_id" || cmd="$cmd --resume $session_id"
  cmd="$cmd --dangerously-skip-permissions --mcp-config $mcp_config"

  tmux send-keys -t "$SESSION:$name" "$cmd" Enter
  echo "Started $name"
}

cmd_send() {
  local name="$1"; shift
  local message="$*"
  [ -z "$name" ] || [ -z "$message" ] && echo "Usage: agent-ctl send <name> <message>" && exit 1

  tmux send-keys -t "$SESSION:$name" "$message" ""
  sleep 0.5
  tmux send-keys -t "$SESSION:$name" Enter
  echo "Sent to $name"
}

cmd_logs() {
  local name="$1"
  local count="${2:-30}"
  [ -z "$name" ] && echo "Usage: agent-ctl logs <name> [N]" && exit 1
  grep "$name" "$LOG" 2>/dev/null | tail -"$count"
}

cmd_peek() {
  local name="$1"
  [ -z "$name" ] && echo "Usage: agent-ctl peek <name>" && exit 1
  echo "--- $name terminal ---"
  tmux capture-pane -t "$SESSION:$name" -p 2>/dev/null | tail -30
  echo "--- end ---"
}

cmd_kill() {
  local name="$1"
  [ -z "$name" ] && echo "Usage: agent-ctl kill <name>" && exit 1
  tmux send-keys -t "$SESSION:$name" C-c 2>/dev/null; sleep 1
  tmux kill-window -t "$SESSION:$name" 2>/dev/null
  echo "Killed $name"
}

cmd_list() {
  echo ""
  echo "  Agents in $ATROPHY_DIR/agents/ (flat + org-nested):"
  echo ""
  printf "  %-25s %-20s %-12s %s\n" "NAME" "DISPLAY" "CHANNELS" "LOCATION"
  printf "  %-25s %-20s %-12s %s\n" "----" "-------" "--------" "--------"
  while read -r dir; do
    local name display desktop telegram channels rel
    name=$(basename "$dir")
    local manifest="$dir/data/agent.json"
    if [ -f "$manifest" ]; then
      display=$(python3 -c "import json; d=json.load(open('$manifest')); print(d.get('display_name','$name'))" 2>/dev/null)
      desktop=$(python3 -c "import json; d=json.load(open('$manifest')); print('1' if d.get('channels',{}).get('desktop',{}).get('enabled') else '0')" 2>/dev/null)
      telegram=$(python3 -c "import json; d=json.load(open('$manifest')); print('1' if d.get('channels',{}).get('telegram',{}).get('enabled') else '0')" 2>/dev/null)
      channels=""
      [ "$desktop" = "1" ] && channels="${channels}d"
      [ "$telegram" = "1" ] && channels="${channels}t"
      [ -z "$channels" ] && channels="-"
      rel="${dir#$ATROPHY_DIR/agents/}"
      printf "  %-25s %-20s %-12s %s\n" "$name" "$display" "$channels" "$rel"
    fi
  done < <(all_agent_dirs)
  echo ""
  echo "  Channels: d=desktop, t=telegram"
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

cmd_boot() {
  if tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "Session '$SESSION' already exists. Use: agent-ctl shutdown first"
    exit 1
  fi

  tmux new-session -d -s "$SESSION" -x 200 -y 50
  echo "Created tmux session: $SESSION"

  # Boot primary agents (desktop or telegram enabled), walking flat + nested
  while read -r dir; do
    local name manifest is_primary mcp_config session_id
    name=$(basename "$dir")
    manifest="$dir/data/agent.json"
    [ ! -f "$manifest" ] && continue

    is_primary=$(python3 -c "
import json
d=json.load(open('$manifest'))
desktop = d.get('channels',{}).get('desktop',{}).get('enabled', False)
telegram = d.get('channels',{}).get('telegram',{}).get('enabled', False)
print('yes' if desktop or telegram else 'no')
" 2>/dev/null)

    [ "$is_primary" != "yes" ] && continue

    mcp_config="$ATROPHY_DIR/mcp/$name.config.json"
    [ ! -f "$mcp_config" ] && continue

    session_id=$(sqlite3 "$dir/data/memory.db" \
      "SELECT cli_session_id FROM sessions WHERE cli_session_id IS NOT NULL ORDER BY started_at DESC LIMIT 1;" 2>/dev/null)
    [ -z "$session_id" ] && session_id=$(python3 -c "import uuid; print(uuid.uuid4())")

    tmux new-window -t "$SESSION" -n "$name" -c "$dir"
    sleep 0.5
    tmux send-keys -t "$SESSION:$name" "claude --resume $session_id --dangerously-skip-permissions --mcp-config $mcp_config" Enter
    echo "  Started $name ($session_id)"
    sleep 1
  done < <(all_agent_dirs)

  echo ""
  echo "All primary agents booted. Run: agent-ctl status"
}

cmd_shutdown() {
  echo "Stopping all agents..."
  tmux list-windows -t "$SESSION" -F '#{window_name}' 2>/dev/null | while read -r name; do
    [ "$name" = "zsh" ] || [ "$name" = "bash" ] && continue
    tmux send-keys -t "$SESSION:$name" C-c 2>/dev/null
    echo "  Stopped $name"
  done
  sleep 2
  tmux kill-session -t "$SESSION" 2>/dev/null
  echo "Session killed."
}

cmd_health() {
  local result
  result=$(api GET /health 2>/dev/null)
  if [ -z "$result" ]; then
    echo "API server not responding at port $API_PORT"
    exit 1
  fi
  echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d, indent=2))" 2>/dev/null || echo "$result"
}

cmd_cron() {
  local count="${1:-20}"
  echo ""
  echo "  Recent cron activity:"
  echo ""
  grep -E "cron-scheduler.*Executing|cron-runner.*finished" "$LOG" 2>/dev/null | tail -"$count"
  echo ""
}

cmd_cron_state() {
  local state_file="$ATROPHY_DIR/cron-state.json"
  if [ ! -f "$state_file" ]; then
    echo "No cron state file at $state_file"
    return
  fi
  echo ""
  echo "  Cron state ($state_file):"
  echo ""
  python3 -c "
import json
try:
    with open('$state_file') as f:
        d = json.load(f)
    if not d:
        print('  (empty - no jobs in failure state)')
    else:
        for k, v in sorted(d.items()):
            disabled = 'DISABLED' if v.get('disabled') else 'ok'
            fails = v.get('consecutiveFailures', 0)
            since = v.get('disabledAt', '')
            print(f'  {k:50s} {disabled:10s} fails={fails}{\" since \" + since if since else \"\"}')
except Exception as e:
    print(f'  error reading state: {e}')
"
  echo ""
}

cmd_cron_reset() {
  local state_file="$ATROPHY_DIR/cron-state.json"
  local target="${1:-}"
  if [ -z "$target" ] || [ "$target" = "all" ]; then
    echo "[]" > /dev/null # noop
    echo "{}" > "$state_file"
    echo "Reset all cron job circuit breakers (state file emptied)"
    echo "Restart the app to re-enable disabled jobs."
  else
    python3 -c "
import json
try:
    with open('$state_file') as f:
        d = json.load(f)
    if '$target' in d:
        del d['$target']
        with open('$state_file', 'w') as f:
            json.dump(d, f, indent=2)
        print('Reset $target')
    else:
        print('$target not in state file (already enabled)')
except Exception as e:
    print(f'error: {e}')
"
    echo "Restart the app to re-enable the job."
  fi
}

cmd_errors() {
  local count="${1:-20}"
  echo ""
  echo "  Recent errors:"
  echo ""
  grep -iE "ERROR|CRASH|error.*code|SIGTERM" "$LOG" 2>/dev/null | tail -"$count"
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# INFERENCE COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

cmd_chat() {
  local name="$1"; shift
  local message="$*"
  [ -z "$name" ] || [ -z "$message" ] && echo "Usage: agent-ctl chat <name> <message>" && exit 1

  # Switch to agent first
  api POST /agent/switch "{\"agent\":\"$name\"}" >/dev/null 2>&1

  # Stream response
  local token
  token=$(get_token)
  curl -sN -H "Authorization: Bearer $token" -H "Content-Type: application/json" \
    -d "{\"message\":\"$message\"}" "http://127.0.0.1:$API_PORT/chat/stream" 2>/dev/null | while IFS= read -r line; do
    if [[ "$line" == data:* ]]; then
      local data="${line#data: }"
      local type
      type=$(echo "$data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('type',''))" 2>/dev/null)
      case "$type" in
        text)
          echo "$data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('content',''), end='')" 2>/dev/null
          ;;
        tool)
          local tname
          tname=$(echo "$data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('name',''))" 2>/dev/null)
          echo ""
          echo "  [tool: $tname]"
          ;;
        done)
          echo ""
          ;;
        error)
          local msg
          msg=$(echo "$data" | python3 -c "import json,sys; print(json.load(sys.stdin).get('message',''))" 2>/dev/null)
          echo "  [error: $msg]"
          ;;
      esac
    fi
  done
}

cmd_switch() {
  local name="$1"
  [ -z "$name" ] && echo "Usage: agent-ctl switch <name>" && exit 1
  local result
  result=$(api POST /agent/switch "{\"agent\":\"$name\"}" 2>/dev/null)
  echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Switched to {d.get(\"agent\",\"?\")}')" 2>/dev/null || echo "$result"
}

# ─────────────────────────────────────────────────────────────────────────────
# DATABASE COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

cmd_turns() {
  local name="$1"
  local count="${2:-10}"
  [ -z "$name" ] && echo "Usage: agent-ctl turns <name> [N]" && exit 1

  local dir
  dir=$(agent_dir "$name")
  [ -z "$dir" ] && echo "Agent '$name' not found" && exit 1
  local db="$dir/data/memory.db"
  [ ! -f "$db" ] && echo "No database at $db" && exit 1

  echo ""
  sqlite3 -column -header "$db" \
    "SELECT timestamp, role, substr(content, 1, 120) as content FROM turns ORDER BY timestamp DESC LIMIT $count;" 2>/dev/null
  echo ""
}

cmd_sessions() {
  local name="$1"
  local count="${2:-5}"
  [ -z "$name" ] && echo "Usage: agent-ctl sessions <name> [N]" && exit 1

  local dir
  dir=$(agent_dir "$name")
  [ -z "$dir" ] && echo "Agent '$name' not found" && exit 1
  local db="$dir/data/memory.db"
  [ ! -f "$db" ] && echo "No database at $db" && exit 1

  echo ""
  sqlite3 -column -header "$db" \
    "SELECT id, started_at, ended_at, total_turns, mood, cli_session_id FROM sessions ORDER BY started_at DESC LIMIT $count;" 2>/dev/null
  echo ""
}

cmd_threads() {
  local name="$1"
  local count="${2:-10}"
  [ -z "$name" ] && echo "Usage: agent-ctl threads <name> [N]" && exit 1

  local dir
  dir=$(agent_dir "$name")
  [ -z "$dir" ] && echo "Agent '$name' not found" && exit 1
  local db="$dir/data/memory.db"
  [ ! -f "$db" ] && echo "No database at $db" && exit 1

  echo ""
  sqlite3 -column -header "$db" \
    "SELECT id, title, status, substr(summary, 1, 80) as summary, updated_at FROM threads WHERE status='active' ORDER BY updated_at DESC LIMIT $count;" 2>/dev/null
  echo ""
}

# ─────────────────────────────────────────────────────────────────────────────
# TMUX COMMANDS
# ─────────────────────────────────────────────────────────────────────────────

cmd_attach() {
  local name="${1:-}"
  if [ -n "$name" ]; then
    tmux select-window -t "$SESSION:$name" 2>/dev/null
  fi
  tmux attach -t "$SESSION" 2>/dev/null || echo "No session '$SESSION'"
}

cmd_windows() {
  tmux list-windows -t "$SESSION" 2>/dev/null || echo "No session '$SESSION'"
}

# ─────────────────────────────────────────────────────────────────────────────
# ROUTER
# ─────────────────────────────────────────────────────────────────────────────

case "${1:-}" in
  # Agent
  status)   cmd_status ;;
  stop)     cmd_stop "${2:-}" ;;
  restart)  cmd_restart "${2:-}" "${3:-}" ;;
  send)     shift; cmd_send "$@" ;;
  logs)     cmd_logs "${2:-}" "${3:-}" ;;
  peek)     cmd_peek "${2:-}" ;;
  kill)     cmd_kill "${2:-}" ;;
  list)     cmd_list ;;

  # System
  boot)         cmd_boot ;;
  shutdown)     cmd_shutdown ;;
  health)       cmd_health ;;
  cron)         cmd_cron "${2:-}" ;;
  cron-state)   cmd_cron_state ;;
  cron-reset)   cmd_cron_reset "${2:-}" ;;
  errors)       cmd_errors "${2:-}" ;;

  # Inference
  chat)     shift; cmd_chat "$@" ;;
  switch)   cmd_switch "${2:-}" ;;

  # Database
  turns)    cmd_turns "${2:-}" "${3:-}" ;;
  sessions) cmd_sessions "${2:-}" "${3:-}" ;;
  threads)  cmd_threads "${2:-}" "${3:-}" ;;

  # Tmux
  attach)   cmd_attach "${2:-}" ;;
  windows)  cmd_windows ;;

  *)
    cat << 'HELP'
agent-ctl - Atrophy system management

AGENTS
  status                       All agents: state, uptime, last tool
  stop <name>                  Interrupt inference (Ctrl+C)
  restart <name> [--fresh]     Restart agent (--fresh = new session)
  send <name> <message>        Send a message via tmux
  logs <name> [N]              Tail recent log lines (default 30)
  peek <name>                  Show terminal content
  kill <name>                  Kill tmux window
  list                         List all agent directories

SYSTEM
  boot                         Start tmux session + all primary agents
  shutdown                     Stop everything
  health                       HTTP API health check
  cron [N]                     Recent cron activity
  cron-state                   Show circuit breaker state for all jobs
  cron-reset [job|all]         Reset circuit breaker (re-enable disabled jobs)
  errors [N]                   Recent errors

INFERENCE
  chat <name> <message>        Send via HTTP API, stream response
  switch <name>                Switch active agent

DATABASE
  turns <name> [N]             Recent conversation turns
  sessions <name> [N]          Recent sessions
  threads <name> [N]           Active memory threads

TMUX
  attach [name]                Attach to tmux (optionally select window)
  windows                      List tmux windows
HELP
    ;;
esac
