#!/usr/bin/env bash
# Start the ORRERY cockpit backend in this terminal window.
#
# One run does: check prerequisites, create/update the Python venv, carry over
# the orrery-telemetry settings (project key, Mail DB, dashboard port), start
# the backend in the foreground, and print the URL to open in a browser.
# Closing the window or pressing Ctrl-C stops the backend.
#
# Works on macOS (including /bin/bash 3.2) and on Linux inside WSL2.
# It never edits ~/.agentstack or ~/.orrery; the only thing it writes is the
# venv (default: bridge/.venv in this checkout), which also keeps a one-day
# cache of the latest orrery-telemetry release.
set -eu

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
BRIDGE_DIR="${REPO_ROOT}/bridge"
REQUIREMENTS="${BRIDGE_DIR}/requirements.txt"

PORT="${PORT:-8791}"
VENV_DIR="${ORRERY_VENV:-${BRIDGE_DIR}/.venv}"
AGENTSTACK_ENV_FILE="${AGENTSTACK_HOME:-${HOME}/.agentstack}/env.sh"
MIN_PY_MAJOR=3
MIN_PY_MINOR=10
# The orrery-telemetry API generation this cockpit needs: the "api" number in
# its /api/version, which orrery-telemetry raises only when it adds or changes
# something the cockpit relies on. An older one only gets a warning at startup
# (see telemetry_version_check below); release dates are never hard-coded here.
# orrery-telemetry manages "api" this way from 2 on; every release before that
# reports 1, whatever it can do, so 1 always means "update".
MIN_TELEMETRY_API=2
# Where the newest release is announced. Set ORRERY_NO_UPDATE_CHECK=1 to skip
# the check; the answer is kept for a day in the venv folder.
TELEMETRY_RELEASES_URL="${ORRERY_UPDATE_CHECK_URL:-https://api.github.com/repos/gyroid-eth/orrery-telemetry/releases/latest}"

check_only=false

usage() {
  cat <<'EOF'
Usage: scripts/start-cockpit.sh [--check] [-h|--help]

Check prerequisites, prepare the Python venv, and start the ORRERY cockpit
backend in this window. Open the printed URL in your browser.
Ctrl-C (or closing the window) stops the backend.

Options:
  --check    Only check prerequisites and the venv; do not start the backend.
  -h, --help Show this help text.

Environment (all optional):
  PORT                 backend port (default 8791)
  ORRERY_PYTHON        Python 3.10+ used to create the venv
  ORRERY_VENV          venv directory (default: bridge/.venv)
  ORRERY_PROJECT_KEY   project key (default: taken from orrery-telemetry)
  ORRERY_DASHBOARD_URL orrery-telemetry dashboard (default: from its port)
  ORRERY_NO_UPDATE_CHECK=1  do not ask GitHub whether a newer orrery-telemetry exists
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --check) check_only=true ;;
    -h | --help) usage; exit 0 ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
ok() { printf '  ok    %s\n' "$*"; }
note() { printf '  note  %s\n' "$*"; }
# A warning does not stop the start; each argument is one line.
warn() {
  printf '\n  WARN  %s\n' "$1"
  shift
  for line in "$@"; do
    printf '        %s\n' "$line"
  done
}

# Collect every missing prerequisite before stopping, so one run shows them all.
problems=0
problem() {
  problems=$((problems + 1))
  printf '\n  NG    %s\n' "$1"
  shift
  for line in "$@"; do
    printf '        %s\n' "$line"
  done
}

# ---------------------------------------------------------------- platform
os_name="$(uname -s)"
is_wsl=false
case "$os_name" in
  Darwin) platform="macOS" ;;
  Linux)
    platform="Linux"
    if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then
      is_wsl=true
      platform="WSL2 (${WSL_DISTRO_NAME:-unknown distro})"
    fi
    ;;
  *)
    say "ORRERY cockpit: unsupported OS '$os_name'."
    say "On Windows, run this inside WSL2 Ubuntu (not PowerShell / Git Bash)."
    exit 1
    ;;
esac

say "ORRERY cockpit — prerequisite check (${platform})"

# ---------------------------------------------------------------- python
py_version_ok() {
  "$1" -c "import sys; sys.exit(0 if sys.version_info >= (${MIN_PY_MAJOR}, ${MIN_PY_MINOR}) else 1)" 2>/dev/null
}

# orrery-telemetry's env.sh is generated with `export KEY=<shell-quoted>` and
# no secrets. Read single values in a subshell so nothing else leaks into this
# script's environment.
telemetry_value() {
  [ -r "$AGENTSTACK_ENV_FILE" ] || return 0
  (
    # shellcheck disable=SC1090
    . "$AGENTSTACK_ENV_FILE" >/dev/null 2>&1 || true
    eval "printf '%s' \"\${$1:-}\""
  )
}

python_bin=""
tried_pythons=""
try_python() {
  [ -z "$python_bin" ] && [ -n "$1" ] || return 0
  resolved="$(command -v "$1" 2>/dev/null || true)"
  [ -n "$resolved" ] || return 0
  if py_version_ok "$resolved"; then
    python_bin="$resolved"
  else
    tried_pythons="${tried_pythons} ${resolved}($("$resolved" -c 'import platform; print(platform.python_version())' 2>/dev/null || echo '?'))"
  fi
}
if [ -n "${ORRERY_PYTHON:-}" ]; then
  # An explicit choice is used as-is, never replaced by a fallback.
  try_python "$ORRERY_PYTHON"
else
  try_python python3
  try_python "$(telemetry_value AGENTSTACK_PYTHON)"
  for candidate in python3.14 python3.13 python3.12 python3.11 python3.10 \
    /opt/homebrew/bin/python3 /usr/local/bin/python3; do
    try_python "$candidate"
  done
fi

if [ -n "$python_bin" ]; then
  ok "python: $python_bin ($("$python_bin" -c 'import platform; print(platform.python_version())'))"
elif [ -x "${VENV_DIR}/bin/python" ] && py_version_ok "${VENV_DIR}/bin/python"; then
  # An existing venv is enough; a system Python is only needed to create one.
  ok "python: existing venv ${VENV_DIR}"
else
  if [ "$os_name" = Darwin ]; then
    fix="Fix: install Python 3.11+ (e.g. 'brew install python@3.13'), or set ORRERY_PYTHON=/path/to/python3."
  else
    fix="Fix: 'sudo apt install python3' (Ubuntu 24.04 ships 3.12), or set ORRERY_PYTHON=/path/to/python3."
  fi
  if [ -n "$tried_pythons" ]; then
    found="Found only:${tried_pythons}"
  else
    found="No python3 on PATH."
  fi
  problem "Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR} or newer is required." "$found" "$fix"
fi

# ---------------------------------------------------------------- tmux
if tmux_path="$(command -v "${TMUX_BIN:-tmux}" 2>/dev/null)"; then
  ok "tmux: $tmux_path ($("$tmux_path" -V 2>/dev/null || echo 'version unknown'))"
else
  if [ "$os_name" = Darwin ]; then
    problem "tmux is not installed." "Fix: brew install tmux"
  else
    problem "tmux is not installed." "Fix: sudo apt install tmux"
  fi
fi

# ---------------------------------------------------------------- orrery-telemetry
telemetry_installed=false
if [ -r "$AGENTSTACK_ENV_FILE" ]; then
  telemetry_installed=true
  ok "orrery-telemetry settings: $AGENTSTACK_ENV_FILE"
else
  problem "orrery-telemetry is not installed (no $AGENTSTACK_ENV_FILE)." \
    "ORRERY cockpit reads agents, spawn and Mail from orrery-telemetry. Install it first:" \
    "  git clone https://github.com/gyroid-eth/orrery-telemetry.git" \
    "  cd orrery-telemetry && ./scripts/install.sh --project-key /absolute/path/to/your-project" \
    "See docs/install.md in orrery-telemetry (it has a WSL2 section)."
fi

# Project key: explicit ORRERY_* > AGENTSTACK_* in this shell > orrery-telemetry
# env.sh > ~/.orrery/config.json (the backend reads the last one by itself).
project_key="${ORRERY_PROJECT_KEY:-${AGENTSTACK_PROJECT_KEY:-}}"
project_key_source="environment"
if [ -z "$project_key" ]; then
  project_key="$(telemetry_value AGENTSTACK_PROJECT_KEY)"
  project_key_source="$AGENTSTACK_ENV_FILE"
fi
if [ -z "$project_key" ] && [ -r "${HOME}/.orrery/config.json" ] && [ -n "$python_bin" ]; then
  project_key="$("$python_bin" -c '
import json, sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8")).get("project_key", "")
except Exception:
    value = ""
print(value.strip() if isinstance(value, str) else "")
' "${HOME}/.orrery/config.json")"
  project_key_source="${HOME}/.orrery/config.json"
fi
if [ -n "$project_key" ]; then
  ok "project key: $project_key (from $project_key_source)"
  if [ ! -d "$project_key" ]; then
    note "the project key is not an existing directory here; Mail shows only messages filed under exactly this path."
  fi
elif [ "$telemetry_installed" = true ]; then
  problem "No project key is configured." \
    "orrery-telemetry's env.sh has no AGENTSTACK_PROJECT_KEY. Re-run its installer with the key:" \
    "  ./scripts/install.sh --project-key /absolute/path/to/your-project" \
    "or start this script with ORRERY_PROJECT_KEY=/absolute/path/to/your-project."
fi

# Mail DB: explicit ORRERY_MAIL_DB > AGENTSTACK_MAIL_DB > env.sh > backend default.
mail_db="${ORRERY_MAIL_DB:-${AGENTSTACK_MAIL_DB:-}}"
[ -n "$mail_db" ] || mail_db="$(telemetry_value AGENTSTACK_MAIL_DB)"
if [ -n "$mail_db" ]; then
  if [ -f "$mail_db" ]; then
    ok "Mail DB: $mail_db"
  else
    note "Mail DB not found at $mail_db; the Mail pane stays empty until ORRERY Mail creates it."
  fi
fi

# Dashboard: explicit ORRERY_DASHBOARD_URL > port from env.sh > 8770.
dashboard_port="$(telemetry_value AGENTSTACK_PORT)"
dashboard_url="${ORRERY_DASHBOARD_URL:-http://127.0.0.1:${dashboard_port:-8770}}"
dashboard_url="${dashboard_url%/}"

# Probe with the Python we already require, so curl is not a prerequisite.
# A 200 alone is not enough: another program on the port would pass. The body
# must have the service's own JSON shape.
#   exit 0: the expected service; 1: no answer; 2: something else answered.
#   $2 = cockpit: /telemetry/health with backend == "ok" and a boot id
#   $2 = dashboard: /api/agents with an "agents" list
#   $2 = version: /api/version of orrery-telemetry; prints "<version> <api>"
#        (either may be empty)
probe() {
  "${probe_python}" - "$1" "$2" <<'PY' 2>/dev/null
import json, sys, urllib.error, urllib.request
url, kind = sys.argv[1], sys.argv[2]
try:
    with urllib.request.urlopen(url, timeout=3) as response:
        body = response.read(1 << 20)
except urllib.error.HTTPError:
    sys.exit(2)
except Exception:
    sys.exit(1)
try:
    data = json.loads(body)
except ValueError:
    sys.exit(2)
if not isinstance(data, dict):
    sys.exit(2)
if kind == "cockpit":
    good = data.get("backend") == "ok" and isinstance(data.get("boot"), str)
elif kind == "version":
    good = data.get("name") == "orrery-telemetry"
    if good:
        version, api = data.get("version"), data.get("api")
        print("%s %s" % (version if isinstance(version, str) and " " not in version else "",
                         api if isinstance(api, int) and not isinstance(api, bool) else ""))
else:
    good = isinstance(data.get("agents"), list)
sys.exit(0 if good else 2)
PY
}
# Release versions are a date and an optional count: 2026.09.30 < 2026.09.30.1
# < 2026.10.01. Compare the dot-separated numbers in order, a missing one
# counting as 0; "10#" keeps "09" from being read as octal. Plain string
# walking keeps it working in macOS bash 3.2.
#   exit 0: $1 is older than $2; 1: not older; 2: $1 is not a version.
version_older() {
  case "$1" in
    '' | .* | *. | *..* | *[!0-9.]*) return 2 ;;
  esac
  a="$1." b="$2."
  while [ -n "$a" ] || [ -n "$b" ]; do
    x="${a%%.*}" y="${b%%.*}"
    a="${a#*.}" b="${b#*.}"
    [ -n "$x" ] || x=0
    [ -n "$y" ] || y=0
    if [ $((10#$x)) -lt $((10#$y)) ]; then return 0; fi
    if [ $((10#$x)) -gt $((10#$y)) ]; then return 1; fi
  done
  return 1
}

# The newest orrery-telemetry release on GitHub, from a cache younger than a
# day when there is one. Prints nothing on any failure (no network, slow,
# rate limited): this check must never hold up or stop the start.
latest_telemetry_release() {
  cache=""
  [ -d "$VENV_DIR" ] && cache="${VENV_DIR}/.orrery-telemetry-latest.json"
  "${probe_python}" - "$TELEMETRY_RELEASES_URL" "$cache" <<'PY' 2>/dev/null
import json, os, re, sys, threading, time, urllib.request
url, cache = sys.argv[1], sys.argv[2]
DAY = 24 * 60 * 60

def version(tag):
    if isinstance(tag, str) and re.fullmatch(r"v?\d+(\.\d+)*", tag):
        return tag.lstrip("v")
    return None

if cache:
    try:
        with open(cache, encoding="utf-8") as f:
            kept = json.load(f)
        if kept.get("url") == url and 0 <= time.time() - kept["checked"] < DAY and version(kept.get("tag")):
            print(version(kept["tag"]))
            sys.exit(0)
    except Exception:
        pass
answer = {}

def ask():
    try:
        request = urllib.request.Request(url, headers={
            "Accept": "application/vnd.github+json", "User-Agent": "orrery-cockpit-start"})
        with urllib.request.urlopen(request, timeout=3) as response:
            answer["tag"] = json.loads(response.read(1 << 20)).get("tag_name")
    except Exception:
        pass

# urllib's timeout is per read, so a server that trickles its answer could
# hold the start much longer; the whole lookup gets 3 seconds.
worker = threading.Thread(target=ask, daemon=True)
worker.start()
worker.join(3)
tag = answer.get("tag")
if not version(tag):
    sys.exit(1)
if cache:
    try:
        with open(cache + ".tmp", "w", encoding="utf-8") as f:
            json.dump({"url": url, "checked": time.time(), "tag": tag}, f)
        os.replace(cache + ".tmp", cache)
    except OSError:
        pass
print(version(tag))
PY
}

# scripts/update.sh updates orrery-telemetry (pull + install.sh), then this
# checkout. The line is only the command, quoted for the shell, so it can be
# pasted as shown.
update_hint="  $(printf '%q' "${SCRIPT_DIR}/update.sh")"

telemetry_update_check() {
  case "${ORRERY_NO_UPDATE_CHECK:-}" in
    '' | 0) ;;
    *) return 0 ;;
  esac
  latest="$(latest_telemetry_release)" || return 0
  [ -n "$latest" ] || return 0
  if version_older "$1" "$latest"; then
    # After a WARN the update steps are already on screen.
    if [ "$api_warned" = true ]; then
      note "a newer orrery-telemetry is available: ${latest} (this one is ${1})."
    else
      note "a newer orrery-telemetry is available: ${latest} (this one is ${1})."
      note "Update it, then this cockpit, with:"
      note "$update_hint"
    fi
  fi
}

# Warn, never stop: an older orrery-telemetry still runs most of the cockpit.
telemetry_version_check() {
  api_warned=false
  version_status=0
  answer="$(probe "${dashboard_url}/api/version" version)" || version_status=$?
  telemetry_version="${answer%% *}"
  telemetry_api="${answer#* }"
  case "$telemetry_api" in
    '' | *[!0-9]*) telemetry_api="" ;;
  esac
  if [ "$version_status" -ne 0 ] || [ -z "$telemetry_api" ] || [ "$telemetry_api" -lt "$MIN_TELEMETRY_API" ]; then
    if [ "$version_status" -ne 0 ]; then
      found="could not read its API generation at ${dashboard_url}/api/version"
    elif [ -z "$telemetry_api" ]; then
      found="orrery-telemetry ${telemetry_version:-(unknown version)} does not report an API generation"
    else
      found="orrery-telemetry ${telemetry_version:-(unknown version)} has API ${telemetry_api}"
    fi
    warn "This cockpit needs orrery-telemetry API ${MIN_TELEMETRY_API} or later; ${found}." \
      "Some parts may not work, e.g. resuming a Codex agent that has exited." \
      "Update it, then this cockpit, with this command (the cockpit starts anyway):" \
      "$update_hint" \
      "then run this script again."
    api_warned=true
  else
    ok "orrery-telemetry version: ${telemetry_version:-unknown} (API ${telemetry_api})"
  fi
  # Only a version in the usual form can be compared with the newest release.
  form=0
  version_older "$telemetry_version" 0 || form=$?
  if [ "$form" -ne 2 ]; then
    telemetry_update_check "$telemetry_version"
  fi
}

# Any Python 3 can probe, even one too old to run the backend.
probe_python="${python_bin:-$(command -v python3 2>/dev/null || printf '%s' "${VENV_DIR}/bin/python")}"

if [ -x "$probe_python" ] || command -v "$probe_python" >/dev/null 2>&1; then
  dashboard_status=0
  probe "${dashboard_url}/api/agents" dashboard || dashboard_status=$?
  if [ "$dashboard_status" -eq 0 ]; then
    ok "orrery-telemetry dashboard: ${dashboard_url}"
    telemetry_version_check
  elif [ "$dashboard_status" -eq 2 ]; then
    problem "Something answers at ${dashboard_url}, but it is not the orrery-telemetry dashboard." \
      "Another program may be using the dashboard port, or ORRERY_DASHBOARD_URL points to the wrong place." \
      "Check it:  ~/.agentstack/bin/agentstack-doctor"
  elif [ "$telemetry_installed" = true ]; then
    problem "The orrery-telemetry dashboard does not answer at ${dashboard_url}." \
      "Check it:  ~/.agentstack/bin/agentstack-doctor" \
      "Start it:  ~/.agentstack/dashboard/agentctl.sh start" \
      "           ~/.agentstack/bin/agentstack-mailctl start   (ORRERY Mail, if doctor says it is down)" \
      "(On WSL2 both stop when every Ubuntu window is closed; start them again as above.)"
  fi
fi

# ---------------------------------------------------------------- agent CLIs
agent_cli=""
command -v claude >/dev/null 2>&1 && agent_cli="${agent_cli} claude"
{ command -v codex >/dev/null 2>&1 || [ -n "$(telemetry_value AGENTSTACK_CODEX_BIN)" ]; } \
  && agent_cli="${agent_cli} codex"
if [ -n "$agent_cli" ]; then
  ok "agent CLI:${agent_cli} (log in once with 'claude' → /login, or 'codex login')"
else
  note "neither 'claude' nor 'codex' is on PATH; NEW AGENT cannot start agents until one is installed and logged in."
fi

# ---------------------------------------------------------------- WSL helpers
if [ "$is_wsl" = true ]; then
  # Used by the cockpit to open windows / URLs / folders on the Windows side.
  if command -v wt.exe >/dev/null 2>&1; then
    ok "Windows Terminal: wt.exe"
  else
    note "wt.exe not on PATH; the cockpit's open-window button needs Windows Terminal (Microsoft Store)."
  fi
  if ! command -v wslview >/dev/null 2>&1 && ! command -v explorer.exe >/dev/null 2>&1; then
    note "neither wslview nor explorer.exe is on PATH; links and folders cannot be opened in Windows."
  fi
fi

# ---------------------------------------------------------------- port
backend_url="http://127.0.0.1:${PORT}"
port_in_use() {
  "${probe_python}" - "$PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(1)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}
if [ -x "$probe_python" ] || command -v "$probe_python" >/dev/null 2>&1; then
  backend_status=0
  probe "${backend_url}/telemetry/health" cockpit || backend_status=$?
  if [ "$backend_status" -eq 0 ]; then
    say ""
    say "The ORRERY cockpit backend is already running on port ${PORT}."
    say "Open:  ${backend_url}/cockpit.html"
    say "(To run a second one, start this script with another port, e.g. PORT=8796.)"
    exit 0
  elif [ "$backend_status" -eq 2 ] || port_in_use; then
    problem "Port ${PORT} is used by another program." \
      "Start on another port instead, e.g.:  PORT=8796 $0"
  fi
fi

if [ "$problems" -gt 0 ]; then
  say ""
  say "Stopped: ${problems} prerequisite(s) missing (marked NG above). Nothing was started."
  exit 1
fi

# ---------------------------------------------------------------- venv
venv_python="${VENV_DIR}/bin/python"
# uv's installer puts it in ~/.local/bin, which a fresh shell may not have on PATH yet.
uv_bin="$(command -v uv 2>/dev/null || true)"
[ -n "$uv_bin" ] || { [ -x "${HOME}/.local/bin/uv" ] && uv_bin="${HOME}/.local/bin/uv"; } || true
stamp="${VENV_DIR}/.orrery-requirements"

create_venv() {
  say ""
  say "Creating the Python environment in ${VENV_DIR} ..."
  if "$python_bin" -c 'import ensurepip, venv' >/dev/null 2>&1; then
    "$python_bin" -m venv "$VENV_DIR"
  elif [ -n "$uv_bin" ]; then
    # Ubuntu's python3 ships without ensurepip unless python3-venv is
    # installed; uv (an orrery-telemetry prerequisite) does not need it.
    "$uv_bin" venv --python "$python_bin" "$VENV_DIR"
  else
    py_mm="$("$python_bin" -c 'import sys; print("%d.%d" % sys.version_info[:2])')"
    say ""
    say "  NG    ${python_bin} cannot create a venv (ensurepip is missing)."
    say "        Fix: sudo apt install python${py_mm}-venv   (or install uv: https://docs.astral.sh/uv/)"
    exit 1
  fi
}

install_requirements() {
  say "Installing Python packages from bridge/requirements.txt ..."
  if "$venv_python" -m pip --version >/dev/null 2>&1; then
    "$venv_python" -m pip install --disable-pip-version-check --quiet -r "$REQUIREMENTS"
  else
    "$uv_bin" pip install --python "$venv_python" --quiet -r "$REQUIREMENTS"
  fi
}

if [ ! -x "$venv_python" ] || ! py_version_ok "$venv_python"; then
  if [ -e "$VENV_DIR" ]; then
    say ""
    say "  NG    ${VENV_DIR} exists but is not a usable Python ${MIN_PY_MAJOR}.${MIN_PY_MINOR}+ venv."
    say "        Fix: remove it (rm -rf \"${VENV_DIR}\") and run this script again."
    exit 1
  fi
  create_venv
fi

if ! cmp -s "$REQUIREMENTS" "$stamp" \
  || ! "$venv_python" -c 'import aiohttp, websockets, PIL, pyte' >/dev/null 2>&1; then
  if ! install_requirements; then
    say ""
    say "  NG    Installing the Python packages failed (see the pip output above)."
    say "        Check the network connection and run this script again."
    exit 1
  fi
  cp "$REQUIREMENTS" "$stamp"
fi
ok "venv: ${VENV_DIR}"

if [ "$check_only" = true ]; then
  say ""
  say "All prerequisites are in place. Run without --check to start the cockpit."
  exit 0
fi

# ---------------------------------------------------------------- start
export PORT
export ORRERY_DASHBOARD_URL="$dashboard_url"
[ -n "$project_key" ] && export ORRERY_PROJECT_KEY="$project_key"
[ -n "$mail_db" ] && export ORRERY_MAIL_DB="$mail_db"

say ""
say "Starting the ORRERY cockpit backend on port ${PORT} ..."
cd "$BRIDGE_DIR"
"$venv_python" orrery_backend.py --port "$PORT" &
backend_pid=$!

# Stop the backend if it is still running; the caller decides the exit status.
kill_backend() {
  trap - INT TERM HUP
  if kill -0 "$backend_pid" 2>/dev/null; then
    kill -TERM "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi
}
stop_backend() {
  kill_backend
  say ""
  say "ORRERY cockpit backend stopped."
  exit 0
}
# A background job of a non-interactive shell ignores SIGINT, so forward
# Ctrl-C / window close as SIGTERM (aiohttp shuts down cleanly on it).
trap stop_backend INT TERM HUP

STARTUP_TIMEOUT=30
deadline=$((SECONDS + STARTUP_TIMEOUT))
until probe "${backend_url}/telemetry/health" cockpit; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" 2>/dev/null || status=$?
    say ""
    say "  NG    The backend exited during startup (exit ${status:-0}); see its output above."
    exit 1
  fi
  if [ "$SECONDS" -ge "$deadline" ]; then
    say ""
    say "  NG    The backend did not answer within ${STARTUP_TIMEOUT} seconds; stopping it."
    kill_backend
    exit 1
  fi
  sleep 0.5
done

say ""
say "=============================================================="
say "  ORRERY cockpit is running. Open this URL in your browser:"
say ""
say "    ${backend_url}/cockpit.html"
say ""
if [ "$is_wsl" = true ]; then
  say "  Keep this window open: closing it stops the cockpit."
  say "  Agents, the dashboard, and Mail keep running after you close"
  say "  the Ubuntu windows. To stop WSL2 and give its memory back to"
  say "  Windows, run wsl --shutdown in PowerShell (stops every distro)."
else
  say "  Keep this window open: closing it stops the cockpit."
fi
say "  Press Ctrl-C to stop."
say "=============================================================="

wait "$backend_pid" || status=$?
trap - INT TERM HUP
if [ "${status:-0}" -ne 0 ]; then
  say ""
  say "ORRERY cockpit backend exited (status ${status})."
  exit "$status"
fi
