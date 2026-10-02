#!/usr/bin/env bash
# Install or update orrery-telemetry and this ORRERY cockpit, check that they
# work, then start the cockpit. scripts/get.sh (the one-line install) ends
# here; it can also be run directly from a checkout.
#
# It decides what to call and calls the existing tools:
#   nothing installed     -> clone orrery-telemetry, run its install.sh
#   orrery-telemetry in   -> scripts/update.sh (updates both checkouts)
#   then                  -> agentstack-doctor, agentstack-selftest,
#                            scripts/start-cockpit.sh (venv, start, URL)
# Before anything is changed it shows one plan and asks once (type yes).
#
# What it promises when something fails:
#   - a check that fails before the plan is approved changes nothing;
#   - after that, nothing is rolled back. It shows what changed since the
#     first attempt (kept in ~/.orrery-install/baseline until a run passes
#     every check) and the one line that carries on.
#
# Works on macOS (including /bin/bash 3.2) and on Linux inside WSL2.
set -eu

# Raised when get.sh needs something new from this file (see get.sh).
ORRERY_SETUP_CONTRACT=1

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
AGENTSTACK_DIR="${AGENTSTACK_HOME:-${HOME}/.agentstack}"
INSTALL_STATE="${AGENTSTACK_DIR}/install-state.json"
ENV_FILE="${AGENTSTACK_DIR}/env.sh"
COCKPIT_OVERRIDE="${ORRERY_REPO_URL:-}"
TEL_OVERRIDE="${ORRERY_TELEMETRY_URL:-}"
TEL_URL="${TEL_OVERRIDE:-https://github.com/gyroid-eth/orrery-telemetry.git}"
TEL_REF="${ORRERY_TELEMETRY_REF:-master}"
TEL_DEFAULT="${ORRERY_TELEMETRY_DIR:-${HOME}/orrery-telemetry}"
COCKPIT_REF="${ORRERY_REF:-master}"
DEFAULT_PROJECT="${HOME}/orrery-work"
COCKPIT_PORT="${PORT:-8791}"
STATE_DIR="${ORRERY_INSTALL_STATE_DIR:-${HOME}/.orrery-install}"
BASELINE="${STATE_DIR}/baseline"

# The cockpit checkout: the one get.sh chose, else the one this file is in.
# With --check / --dry-run from get.sh there may be none yet (PLANNED).
COCKPIT_PLANNED=""
if [ -n "${ORRERY_DIR:-}" ]; then
  COCKPIT_ROOT="$(cd -- "$ORRERY_DIR" && pwd)"
elif [ -n "${ORRERY_PLANNED_DIR:-}" ]; then
  COCKPIT_ROOT=""
  COCKPIT_PLANNED="$ORRERY_PLANNED_DIR"
else
  COCKPIT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
fi

assume_yes=false
ask_each=false
check_only=false
dry_run=false
no_start=false
mail_mode=""
project_key_arg=""

usage() {
  cat <<'EOF'
Usage: scripts/setup.sh [options]

Install or update orrery-telemetry and the ORRERY cockpit, check that they
work, then start the cockpit and print its URL. Shows the plan and asks once
(type yes) before changing anything.

Options:
  --project-key PATH  folder the agents work in (first install; default
                      ~/orrery-work, created if missing)
  -y, --yes           do not ask; accept the plan (you have read it here)
  --ask-each          also show orrery-telemetry's installer previews and let
                      it ask before each of its four changes
  --mail keep|update  ORRERY Mail on update, passed on to scripts/update.sh
                      (stops before changing anything if update.sh cannot take it)
  --check             only check and show the plan; changes nothing
  --dry-run           also show the installer's own previews; changes nothing
  --no-start          do everything but start the cockpit
  -h, --help          show this help

Environment (optional): ORRERY_DIR, ORRERY_TELEMETRY_DIR (default
~/orrery-telemetry), PORT (cockpit, default 8791), ORRERY_NO_OPEN=1 (do not
open the browser). AGENTSTACK_* values are passed on to orrery-telemetry.
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -y | --yes) assume_yes=true ;;
    --ask-each) ask_each=true ;;
    --check) check_only=true ;;
    --dry-run) dry_run=true ;;
    --no-start) no_start=true ;;
    --project-key)
      [ $# -ge 2 ] || { printf 'Missing value for --project-key\n' >&2; exit 2; }
      project_key_arg="$2"; shift ;;
    --project-key=*) project_key_arg="${1#*=}" ;;
    --mail)
      [ $# -ge 2 ] || { printf 'Missing value for --mail\n' >&2; exit 2; }
      mail_mode="$2"; shift ;;
    --mail=*) mail_mode="${1#*=}" ;;
    -h | --help) usage; exit 0 ;;
    *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
case "$mail_mode" in
  "" | keep | update) ;;
  *) printf 'Unknown --mail value: %s (keep or update)\n' "$mail_mode" >&2; exit 2 ;;
esac
read_only=false
if [ "$check_only" = true ] || [ "$dry_run" = true ]; then read_only=true; fi
if [ -z "$COCKPIT_ROOT" ] && [ "$read_only" != true ]; then
  printf 'No cockpit checkout (ORRERY_PLANNED_DIR is only for --check / --dry-run).\n' >&2
  exit 2
fi

say() { printf '%s\n' "$*"; }
ok() { printf '  ok    %s\n' "$*"; }
note() { printf '  note  %s\n' "$*"; }
warn_line() { printf '  WARN  %s\n' "$*"; }
problems=0
problem() {
  problems=$((problems + 1))
  printf '\n  NG    %s\n' "$1"
  shift
  for line in "$@"; do printf '        %s\n' "$line"; done
}
changes_started=false
stop() {
  printf '\n  NG    %s\n' "$1"
  shift
  for line in "$@"; do printf '        %s\n' "$line"; done
  if [ "$changes_started" = true ]; then after_failure; fi
  exit 1
}
TAB="$(printf '\t')"
step_no=0
step() {
  step_no=$((step_no + 1))
  printf '\n[%d/7] %s\n' "$step_no" "$1"
  if [ -n "${RUN_DIR:-}" ]; then printf '%s start %s\n' "$(date +%H:%M:%S)" "$1" >>"${RUN_DIR}/steps"; fi
}
step_done() {
  if [ -n "${RUN_DIR:-}" ]; then printf '%s done  %s\n' "$(date +%H:%M:%S)" "$1" >>"${RUN_DIR}/steps"; fi
}

# >>> remote-match (tools/test_one_command_install.sh reads this block)
# Exact match only: the official GitHub repository in its HTTPS / SSH forms,
# or the exact URL given in the test override.
official_remote() { # $1 = URL, $2 = repository name, $3 = override URL (may be empty)
  if [ -n "$3" ]; then
    [ "$1" = "$3" ]
    return
  fi
  case "$1" in
    "https://github.com/gyroid-eth/$2" | "https://github.com/gyroid-eth/$2.git" | \
      "git@github.com:gyroid-eth/$2" | "git@github.com:gyroid-eth/$2.git" | \
      "ssh://git@github.com/gyroid-eth/$2" | "ssh://git@github.com/gyroid-eth/$2.git") return 0 ;;
  esac
  return 1
}
# <<< remote-match

# ---------------------------------------------------------------- helpers
env_value() { # $1 = name in orrery-telemetry's env.sh
  [ -r "$ENV_FILE" ] || return 0
  ( . "$ENV_FILE" >/dev/null 2>&1 || true; eval "printf '%s' \"\${$1:-}\"" )
}
origin_of() { git -C "$1" remote get-url origin 2>/dev/null || true; }
is_checkout_root() { # $1 = folder
  top="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null || true)"
  [ -n "$top" ] && [ "$(cd "$top" && pwd -P)" = "$(cd "$1" && pwd -P)" ]
}
py_ok() { "$1" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; }
expand_path() { # ~ and relative paths -> absolute
  case "$1" in
    "~") printf '%s' "$HOME" ;;
    "~/"*) printf '%s/%s' "$HOME" "${1#\~/}" ;;
    /*) printf '%s' "$1" ;;
    *) printf '%s/%s' "$(pwd)" "$1" ;;
  esac
}
on_windows_drive() { case "$1" in /mnt/[a-z] | /mnt/[a-z]/*) return 0 ;; esac; return 1; }
have_tty() { [ -t 0 ]; }
http_get() { curl -fsS --max-time 2 "$1" 2>/dev/null || true; }
json_str() { # $1 = key; reads one JSON object on stdin; prints the string value
  sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" | head -n 1
}
short() { printf '%s' "$1" | cut -c1-7; }
head_of() { git -C "$1" rev-parse --short HEAD 2>/dev/null || printf -- '-'; }
branch_of() { git -C "$1" symbolic-ref -q --short HEAD 2>/dev/null || printf 'detached'; }

# ---------------------------------------------------------------- run state
RUN_DIR=""
LOG=""
open_run() {
  [ -z "$RUN_DIR" ] || return 0
  RUN_DIR="${STATE_DIR}/runs/$(date +%Y%m%d-%H%M%S)-$$"
  mkdir -p "$RUN_DIR"
  LOG="${RUN_DIR}/log"
  : >"$LOG"
  : >"${RUN_DIR}/steps"
}
backend_state() { # running backend on the cockpit port: none | root@commit | unknown (older backend)
  health="$(http_get "http://127.0.0.1:${COCKPIT_PORT}/telemetry/health")"
  if [ -z "$health" ]; then printf 'none'; return; fi
  b_root="$(printf '%s' "$health" | json_str root)"
  b_commit="$(printf '%s' "$health" | json_str commit)"
  if [ -n "$b_root" ] && [ -n "$b_commit" ]; then
    printf '%s@%s' "$b_root" "$b_commit"
  else
    printf 'unknown (started before it reported its version)'
  fi
}
# One line per item: "name<TAB>value". Recorded before anything changes.
snapshot() {
  if [ -n "${tel_root:-}" ] && [ -e "${tel_root}/.git" ]; then
    printf 'telemetry checkout\t%s (%s)\n' "$(head_of "$tel_root")" "$(branch_of "$tel_root")"
  else
    printf 'telemetry checkout\t-\n'
  fi
  printf 'installed version\t%s\n' "$(cat "${AGENTSTACK_DIR}/VERSION" 2>/dev/null || printf -- '-')"
  from="$(sed -n 's/^ *"repo_root": *"\(.*\)",*$/\1/p' "$INSTALL_STATE" 2>/dev/null | head -n 1 || true)"
  printf 'installed from\t%s\n' "${from:--}"
  mail_build="$(sed -n 's/.*"candidate_venv": *"[^"]*candidates\/\([0-9a-f]\{7\}\)[0-9a-f]*\/venv".*/\1/p' "$INSTALL_STATE" 2>/dev/null | head -n 1 || true)"
  printf 'Mail build\t%s\n' "${mail_build:--}"
  dash="$(http_get "http://127.0.0.1:${dash_port:-8770}/api/version" | json_str version)"
  printf 'dashboard answers\t%s\n' "${dash:-no}"
  if [ -n "$COCKPIT_ROOT" ]; then
    printf 'cockpit checkout\t%s (%s)\n' "$(head_of "$COCKPIT_ROOT")" "$(branch_of "$COCKPIT_ROOT")"
    if [ -f "${COCKPIT_ROOT}/bridge/.venv/.orrery-requirements" ]; then
      printf 'cockpit venv\tready\n'
    elif [ -e "${COCKPIT_ROOT}/bridge/.venv" ]; then
      printf 'cockpit venv\tincomplete\n'
    else
      printf 'cockpit venv\tnone\n'
    fi
  fi
  printf 'cockpit backend\t%s\n' "$(backend_state)"
}
after_failure() {
  [ -n "$RUN_DIR" ] || return 0
  snapshot >"${RUN_DIR}/now" 2>/dev/null || true
  since="$(sed -n "s/^started${TAB}//p" "$BASELINE" 2>/dev/null)"
  say ""
  say "  What changed since the first attempt (${since:-unknown}):"
  printf '    %-19s %-40s %s\n' "" "then" "now"
  while IFS="$TAB" read -r name value; do
    case "$name" in started | "") continue ;; esac
    now="$(sed -n "s/^${name}${TAB}//p" "${RUN_DIR}/now" | head -n 1)"
    mark=""
    [ "$value" = "$now" ] || mark="   <- changed"
    printf '    %-19s %-40s %s%s\n' "$name" "$value" "$now" "$mark"
  done <"$BASELINE"
  say ""
  say "  Nothing is rolled back. What stays changed until a later run fixes it: the"
  say "  4 settings (their backups are kept), the Mail database, uv and Python."
  say "  To carry on: fix what is reported above, then run the same command again."
  say "  It continues from what is already there; the 'then' column stays the first"
  say "  attempt's until a run passes every check."
  say "  Steps: ${RUN_DIR}/steps    Log: ${LOG}"
}

# What get.sh did before handing over (a new cockpit checkout, or git data
# fetched into an old one). It stays when the setup stops, so say so.
BOOTSTRAP_DID="${ORRERY_BOOTSTRAP_DID:-}"
LOCK=""
on_exit() {
  status=$?
  if [ -n "$LOCK" ] && [ -f "${LOCK}/pid" ] && [ "$(cat "${LOCK}/pid" 2>/dev/null)" = "$$" ]; then rm -rf "$LOCK"; fi
  if [ "$status" -ne 0 ] && [ "$changes_started" != true ] && [ -n "$BOOTSTRAP_DID" ]; then
    printf '\n  note  The setup changed nothing, but before it get.sh %s;\n' "$BOOTSTRAP_DID"
    printf '        that stays (the same command uses it next time).\n'
  fi
}
trap on_exit EXIT

# ---------------------------------------------------------------- questions
ask_yes() { # $1 = question; continues only on "yes"
  if [ "$assume_yes" = true ]; then return 0; fi
  have_tty || stop "No terminal to ask in." \
    "Run this in a terminal, or add --yes after reading the plan above."
  printf '%s ' "$1"
  reply=""
  read -r reply || reply=""
  case "$reply" in
    yes | YES | Yes) return 0 ;;
  esac
  say "Stopped: you did not type yes. Nothing more was changed."
  exit 1
}

# ---------------------------------------------------------------- run a tool
# Output goes to the log (and to the screen with --ask-each, where the
# installer's previews and questions must be seen). Returns its status.
logged() {
  printf '\n$ %s\n' "$*" >>"$LOG"
  if [ "$ask_each" = true ]; then
    set +e
    "$@" 2>&1 | tee -a "$LOG"
    status=${PIPESTATUS[0]}
    set -e
    return "$status"
  fi
  "$@" >>"$LOG" 2>&1
}
show_log_tail() {
  if [ -z "$LOG" ] || [ ! -r "$LOG" ]; then return 0; fi
  say ""
  say "  --- last lines of ${LOG} ---"
  tail -n 20 "$LOG" | sed 's/^/  | /'
  say "  ---"
}

# ================================================================ 1. prerequisites
if [ "$check_only" = true ]; then
  say "ORRERY setup (check only: nothing will be changed)"
elif [ "$dry_run" = true ]; then
  say "ORRERY setup (dry run: nothing will be changed)"
else
  say "ORRERY setup"
fi
step "Prerequisites"

case "$(uname -s)" in
  Darwin) os=mac; platform=macOS ;;
  Linux)
    os=linux; platform=Linux
    if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then
      os=wsl; platform="WSL2 (${WSL_DISTRO_NAME:-unknown distro})"
    fi
    ;;
  *) stop "Unsupported OS: $(uname -s). On Windows, run this inside WSL2 Ubuntu." ;;
esac
[ "$(id -u)" != 0 ] || stop "Do not run this as root or with sudo."
ok "platform: ${platform} ($(uname -m))"

missing_pkgs=""
for cmd in git tmux curl; do
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$cmd"
  else
    missing_pkgs="${missing_pkgs} ${cmd}"
  fi
done
if [ -n "$missing_pkgs" ]; then
  if [ "$os" = mac ]; then
    problem "Missing:${missing_pkgs}" \
      "Fix (Homebrew, https://brew.sh):  brew install${missing_pkgs}"
  else
    problem "Missing:${missing_pkgs}" \
      "Fix:  sudo apt update && sudo apt install -y${missing_pkgs}"
  fi
fi

# uv: orrery-telemetry builds ORRERY Mail's Python environment with it. It
# installs without sudo, so it goes into the plan when missing.
export PATH="${HOME}/.local/bin:${PATH}"
need_uv=false
if uv --version >/dev/null 2>&1; then
  ok "uv: $(command -v uv) ($(uv --version 2>/dev/null | awk '{print $2}'))"
else
  need_uv=true
  if command -v uv >/dev/null 2>&1; then
    note "$(command -v uv) does not run here; a working uv will be installed into ~/.local/bin"
  else
    note "uv is not installed; it will be installed into ~/.local/bin (no sudo)"
  fi
fi

# Python 3.11+, judged by running it. Without one, uv installs one (no sudo).
python_bin=""
for candidate in "${AGENTSTACK_PYTHON:-}" "$(env_value AGENTSTACK_PYTHON)" python3 python3.14 python3.13 python3.12 python3.11 \
  /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  [ -n "$candidate" ] || continue
  resolved="$(command -v "$candidate" 2>/dev/null || true)"
  [ -n "$resolved" ] || continue
  if py_ok "$resolved"; then python_bin="$resolved"; break; fi
done
need_python=false
if [ -n "$python_bin" ]; then
  ok "Python: ${python_bin} ($("$python_bin" -c 'import platform; print(platform.python_version())'))"
else
  need_python=true
  sys_py="$(command -v python3 2>/dev/null || true)"
  if [ -n "$sys_py" ]; then
    note "${sys_py} is $("$sys_py" -c 'import platform; print(platform.python_version())' 2>/dev/null || printf '?'); 3.11 or newer is needed"
  fi
  note "uv will install Python 3.12 (no sudo) and both parts will use it"
fi

# Does each agent CLI run? (codex --version writes into CODEX_HOME, so it is
# asked with a throwaway one; a check must not change anything.)
agent_cli=""
if command -v claude >/dev/null 2>&1 && claude --version >/dev/null 2>&1; then
  agent_cli="claude"
fi
if command -v codex >/dev/null 2>&1; then
  probe_home="$(mktemp -d "${TMPDIR:-/tmp}/orrery-codex-probe.XXXXXX")"
  if CODEX_HOME="$probe_home" codex --version >/dev/null 2>&1; then
    agent_cli="${agent_cli}${agent_cli:+ }codex"
  fi
  rm -rf "$probe_home"
fi
if [ -n "$agent_cli" ]; then
  ok "agent CLI: ${agent_cli}"
else
  note "neither 'claude' nor 'codex' runs here. The install works without them;"
  note "      agents need one of them, installed and logged in (see the end)."
fi

if [ "$problems" -gt 0 ]; then
  say ""
  say "Stopped: ${problems} problem(s) above. Nothing was changed."
  exit 1
fi
step_done "Prerequisites"

# ================================================================ 2. what is here
step "What is installed"

# Only one setup at a time for this user.
if [ "$read_only" != true ]; then
  LOCK="${STATE_DIR}/lock"
  mkdir -p "$STATE_DIR"
  if ! mkdir "$LOCK" 2>/dev/null; then
    other="$(cat "${LOCK}/pid" 2>/dev/null || true)"
    if [ -n "$other" ] && kill -0 "$other" 2>/dev/null; then
      stop "Another ORRERY setup is running (pid ${other}); nothing was changed." \
        "Wait for it to finish, then run this again."
    fi
    rm -rf "$LOCK"
    mkdir "$LOCK" || stop "Could not take the setup lock ${LOCK}."
  fi
  printf '%s\n' "$$" >"${LOCK}/pid"
fi

if [ -n "$COCKPIT_ROOT" ]; then
  is_checkout_root "$COCKPIT_ROOT" || stop "${COCKPIT_ROOT} is not a git checkout of ORRERY."
  origin="$(origin_of "$COCKPIT_ROOT")"
  official_remote "$origin" orrery "$COCKPIT_OVERRIDE" \
    || stop "The cockpit checkout ${COCKPIT_ROOT} has origin '${origin:-none}'." \
      "That is not https://github.com/gyroid-eth/orrery, so this setup does not change it." \
      "Use another folder for the official one:  ORRERY_DIR=/path/to/new/folder"
  ok "cockpit: ${COCKPIT_ROOT} ($(head_of "$COCKPIT_ROOT"), ${origin})"
else
  ok "cockpit: not here yet; would be downloaded to ${COCKPIT_PLANNED}"
fi
[ -z "$COCKPIT_OVERRIDE" ] || note "test override: ORRERY_REPO_URL=${COCKPIT_OVERRIDE}"

# orrery-telemetry: env.sh, the install record and the checkout are looked at
# separately; any of them may be left from an install that stopped halfway.
tel_root=""
recorded_root=""
state_readable=false
if [ -r "$INSTALL_STATE" ]; then
  recorded_root="$(sed -n 's/^ *"repo_root": *"\(.*\)",*$/\1/p' "$INSTALL_STATE" | head -n 1)"
  if [ -n "$recorded_root" ]; then state_readable=true; fi
fi
mode=""
tel_clone=false
if [ "$state_readable" = true ] && [ -d "$recorded_root" ] && is_checkout_root "$recorded_root" \
  && [ -x "${recorded_root}/scripts/install.sh" ]; then
  tel_root="$recorded_root"
  origin="$(origin_of "$tel_root")"
  official_remote "$origin" orrery-telemetry "$TEL_OVERRIDE" \
    || stop "orrery-telemetry was installed from ${tel_root}, whose origin is '${origin:-none}'." \
      "That is not https://github.com/gyroid-eth/orrery-telemetry, so this setup does not change it." \
      "Update it yourself: docs/install.md, step 5."
  mode=update
  ok "orrery-telemetry: installed from ${tel_root} ($(head_of "$tel_root")) -> update"
else
  if [ -r "$INSTALL_STATE" ] || [ -r "$ENV_FILE" ] || [ -d "${AGENTSTACK_DIR}/bin" ]; then
    mode=reinstall
    if [ "$state_readable" = true ]; then
      note "orrery-telemetry was installed from ${recorded_root}, which is no longer a checkout"
    else
      note "an orrery-telemetry install in ${AGENTSTACK_DIR} stopped halfway (no readable install record)"
    fi
    note "      -> its installer runs again (it keeps the settings in env.sh)"
  else
    mode=fresh
    ok "orrery-telemetry: not installed -> new install"
  fi
  tel_root="$TEL_DEFAULT"
  if [ -e "$tel_root" ]; then
    origin="$(origin_of "$tel_root")"
    if ! is_checkout_root "$tel_root" || [ ! -x "${tel_root}/scripts/install.sh" ]; then
      stop "${tel_root} exists but is not an orrery-telemetry checkout; nothing was changed." \
        "Move it away, or choose another folder: ORRERY_TELEMETRY_DIR=/path/to/new/folder"
    fi
    official_remote "$origin" orrery-telemetry "$TEL_OVERRIDE" \
      || stop "${tel_root} has origin '${origin:-none}', not https://github.com/gyroid-eth/orrery-telemetry; nothing was changed." \
        "Choose another folder: ORRERY_TELEMETRY_DIR=/path/to/new/folder"
    ok "orrery-telemetry checkout: ${tel_root} ($(head_of "$tel_root"), already here)"
  else
    tel_clone=true
    ok "orrery-telemetry: would be downloaded from ${TEL_URL} to ${tel_root}"
  fi
fi
[ -z "$TEL_OVERRIDE" ] || note "test override: ORRERY_TELEMETRY_URL=${TEL_OVERRIDE}"

# Project key: the folder the agents work in. Only collected here and passed
# on to the installer, which owns what it means.
project_key=""
saved_key="$(env_value AGENTSTACK_PROJECT_KEY)"
if [ -n "$project_key_arg" ]; then
  project_key="$(expand_path "$project_key_arg")"
elif [ -n "${ORRERY_PROJECT_KEY:-}" ]; then
  project_key="$(expand_path "$ORRERY_PROJECT_KEY")"
elif [ -n "${AGENTSTACK_PROJECT_KEY:-}" ]; then
  project_key="$AGENTSTACK_PROJECT_KEY"
elif [ -n "$saved_key" ]; then
  project_key="$saved_key"
fi
if [ -z "$project_key" ]; then
  if [ "$assume_yes" = true ] || ! have_tty || [ "$read_only" = true ]; then
    project_key="$DEFAULT_PROJECT"
  else
    printf '\n  Folder the agents will work in [%s]: ' "$DEFAULT_PROJECT"
    answer=""
    read -r answer || answer=""
    project_key="$(expand_path "${answer:-$DEFAULT_PROJECT}")"
  fi
fi
ok "project folder: ${project_key}"

# Everything this writes must be on the Linux side in WSL.
if [ "$os" = wsl ]; then
  for path in "$HOME" "${COCKPIT_ROOT:-$COCKPIT_PLANNED}" "$tel_root" "$project_key" "${ORRERY_VENV:-}"; do
    [ -n "$path" ] || continue
    if on_windows_drive "$path"; then
      stop "${path} is on the Windows drive (/mnt/...); nothing was changed." \
        "ORRERY's folders must be in the Ubuntu home (e.g. ~/orrery-work)."
    fi
  done
fi

# A checkout on a detached HEAD cannot be pulled. It goes back to its branch
# only when nothing can be lost; both checkouts are checked before either is
# switched (after the plan is approved).
detached_fix=""
check_detached() { # $1 = label, $2 = checkout, $3 = branch
  if git -C "$2" symbolic-ref -q HEAD >/dev/null 2>&1; then return 0; fi
  head="$(git -C "$2" rev-parse HEAD)"
  if [ "$read_only" = true ]; then
    note "$1 is on a detached HEAD ($(short "$head")); a real run checks whether it can go back to $3"
    return 0
  fi
  [ -z "$(git -C "$2" status --porcelain --untracked-files=no)" ] \
    || stop "$1 (${2}) is on a detached HEAD and has uncommitted changes; nothing was changed." \
      "Commit them on a branch (git -C \"$2\" switch -c my-work), then run this again."
  tag="$(git -C "$2" tag --points-at HEAD 2>/dev/null | head -n 1)"
  [ -z "$tag" ] || stop "$1 (${2}) is on tag ${tag}; it is left there on purpose. Nothing was changed." \
    "To follow the newest version instead: git -C \"$2\" switch $3, then run this again."
  git -C "$2" fetch --quiet origin "$3" 2>/dev/null \
    || stop "could not reach the remote of $1 (${2}); nothing was changed." "Check the network connection, then run this again."
  remote_head="$(git -C "$2" rev-parse FETCH_HEAD)"
  if ! git -C "$2" merge-base --is-ancestor HEAD "$remote_head" 2>/dev/null; then
    if [ -f "$(git -C "$2" rev-parse --git-dir)/shallow" ]; then
      git -C "$2" fetch --quiet --deepen=50 origin "$3" 2>/dev/null || true
      remote_head="$(git -C "$2" rev-parse FETCH_HEAD)"
    fi
    if ! git -C "$2" merge-base --is-ancestor HEAD "$remote_head" 2>/dev/null; then
      if git -C "$2" merge-base HEAD "$remote_head" >/dev/null 2>&1; then
        stop "$1 (${2}) is on a detached HEAD with commits that are not on origin/$3; nothing was changed." \
          "Look at them with: git -C \"$2\" log $(short "$remote_head")..HEAD" \
          "Keep them on a branch (git -C \"$2\" switch -c my-work), then: git -C \"$2\" switch $3"
      fi
      stop "$1 (${2}) is on a detached HEAD, and this shallow checkout cannot show whether it is on origin/$3; nothing was changed." \
        "Switch it yourself after checking: git -C \"$2\" switch $3"
    fi
  fi
  if git -C "$2" show-ref --verify --quiet "refs/heads/$3"; then
    git -C "$2" merge-base --is-ancestor "refs/heads/$3" "$remote_head" 2>/dev/null \
      || stop "$1 (${2}): your local branch $3 has commits that are not on origin/$3; nothing was changed." \
        "Look at them with: git -C \"$2\" log origin/$3..$3"
  fi
  detached_fix="${detached_fix}${2}|${3}|${head}
"
  note "$1 is on a detached HEAD that is already on origin/$3; it will go back to $3"
}
if [ -n "$COCKPIT_ROOT" ]; then check_detached cockpit "$COCKPIT_ROOT" "$COCKPIT_REF"; fi
if [ "$mode" = update ]; then check_detached orrery-telemetry "$tel_root" "$TEL_REF"; fi

# ORRERY Mail: this setup does not touch it. --mail is passed on to update.sh
# only when that update.sh says it takes --mail.
if [ "$mode" = update ]; then
  mail_line="keep the running ORRERY Mail (the installer reports a newer build; it does not switch)"
else
  mail_line="set up ORRERY Mail (or keep one that is already running and healthy)"
fi
pass_mail=""
if [ -n "$mail_mode" ]; then
  if [ "$mode" != update ]; then
    note "--mail ${mail_mode}: a new install sets up ORRERY Mail anyway; the option is not needed"
  elif "${COCKPIT_ROOT}/scripts/update.sh" --help 2>/dev/null | grep -q -- '--mail'; then
    pass_mail="--mail=${mail_mode}"
    mail_line="ORRERY Mail: --mail ${mail_mode}, as scripts/update.sh does it"
  elif [ "$mail_mode" = keep ]; then
    note "this update.sh has no --mail option; keeping the running ORRERY Mail is what it does anyway"
  else
    stop "--mail update was asked for, but this cockpit's update.sh cannot take --mail yet; nothing was changed." \
      "To switch ORRERY Mail now, follow orrery-telemetry's docs/agentstack-mail-update.md" \
      "(install.sh --update-mail), or run this without --mail."
  fi
fi

dash_port="${AGENTSTACK_PORT:-$(env_value AGENTSTACK_PORT)}"
mail_url="${AGENTSTACK_MCP_URL:-$(env_value AGENTSTACK_MCP_URL)}"
step_done "What is installed"

# Before anything changes: what is here now. The first attempt's record is
# kept until a run passes every check, so a retry never overwrites it.
if [ "$read_only" != true ]; then
  open_run
  snapshot >"${RUN_DIR}/start"
  if [ -n "$BOOTSTRAP_DID" ]; then printf 'before the setup\tget.sh %s\n' "$BOOTSTRAP_DID" >>"${RUN_DIR}/start"; fi
  if [ ! -s "$BASELINE" ]; then
    { printf 'started\t%s\n' "$(date '+%Y-%m-%d %H:%M:%S')"; cat "${RUN_DIR}/start"; } >"$BASELINE"
  fi
fi

# ================================================================ 3. plan + confirm
step "Plan"
backup_dir="${AGENTSTACK_DIR}/backups"
say "  This will:"
if [ "$need_uv" = true ]; then say "    - install uv into ~/.local/bin (your shell profile is not changed)"; fi
if [ "$need_python" = true ]; then say "    - install Python 3.12 with uv (into uv's own folder)"; fi
if [ -n "$detached_fix" ]; then
  while IFS='|' read -r path branch head; do
    [ -z "$path" ] || say "    - switch ${path} from $(short "$head") back to ${branch}"
  done <<EOF
$detached_fix
EOF
fi
if [ ! -d "$project_key" ]; then say "    - create the project folder ${project_key}"; fi
if [ -z "$COCKPIT_ROOT" ]; then say "    - download the cockpit to ${COCKPIT_PLANNED}"; fi
case "$mode" in
  fresh | reinstall)
    if [ "$tel_clone" = true ]; then say "    - download orrery-telemetry (${TEL_REF}) to ${tel_root}"; fi
    say "    - install orrery-telemetry into ${AGENTSTACK_DIR}"
    ;;
  update)
    say "    - update orrery-telemetry (${tel_root}) and the cockpit (${COCKPIT_ROOT})"
    say "      with scripts/update.sh: git pull --ff-only, then the installer again"
    ;;
esac
say "    - change these 4 things (each is backed up first):"
say "        1. ~/.claude.json            all your Claude Code sessions: MCP server 'orrery-mail'"
say "                                     -> ${mail_url:-http://127.0.0.1:18765/mcp}"
say "                                     backup: ${backup_dir}/claude-mcp.<time>"
say "        2. ~/.claude/settings.json   all your Claude Code sessions: ORRERY hooks (file"
say "                                     reservations, Mail) and permissions are added;"
say "                                     your own entries are kept.  backup: ${backup_dir}/<time>/"
say "        3. ~/.codex/AGENTS.md        ALL your Codex work (global): ORRERY's marked block only"
say "                                     backup: next to it, AGENTS.md.bak.<time>"
say "        4. ${project_key}/CLAUDE.md"
say "                                     Claude Code in that folder: ORRERY's marked block only"
say "                                     backup: next to it, CLAUDE.md.bak.<time>"
say "    - run 2 background services: dashboard (port ${dash_port:-8770}) and ORRERY Mail"
say "    - ${mail_line}"
say "    - check: agentstack-doctor, and agentstack-selftest (a Mail round trip with 2 test"
say "      agents, which it removes again)"
if [ "$no_start" != true ]; then say "    - start the cockpit in this window: http://127.0.0.1:${COCKPIT_PORT}/cockpit.html"; fi
say "  If something fails after you type yes, nothing is rolled back; you get a list of"
say "  what changed and the line that carries on."
if [ "$ask_each" = true ]; then say "  (--ask-each: the installer also shows each change and asks before it.)"; fi

if [ "$check_only" = true ]; then
  say ""
  say "Check finished: nothing was changed. Run without --check to do the above."
  exit 0
fi

if [ "$dry_run" = true ]; then
  say ""
  say "Dry run: the installer's own preview of the 4 changes"
  preview_root="$tel_root"
  preview_tmp=""
  if [ "$tel_clone" = true ]; then
    preview_tmp="$(mktemp -d "${TMPDIR:-/tmp}/orrery-preview.XXXXXX")"
    git clone --quiet --depth 1 --branch "$TEL_REF" "$TEL_URL" "${preview_tmp}/t" \
      || { rm -rf "$preview_tmp"; stop "Could not download orrery-telemetry for the preview."; }
    preview_root="${preview_tmp}/t"
  fi
  if [ "$mode" = update ]; then say "(this is the version you have now; the update may change it)"; fi
  # The installer asks codex for its version, and codex writes into its
  # CODEX_HOME when it starts. It probes an explicit AGENTSTACK_CODEX_BIN, else
  # the one saved in env.sh (if it runs), else the first codex that runs in
  # PATH and a few usual folders. Pick the same binary here (probing it with a
  # throwaway CODEX_HOME) and hand the installer a wrapper as an explicit
  # AGENTSTACK_CODEX_BIN, so every probe it makes goes to the throwaway home.
  # Everything else (e.g. ~/.codex/AGENTS.md for the preview) is untouched.
  probe_dir="$(mktemp -d "${TMPDIR:-/tmp}/orrery-probe.XXXXXX")"
  mkdir -p "${probe_dir}/bin" "${probe_dir}/codex-home"
  codex_runs() { [ -f "$1" ] || [ -L "$1" ] || return 1; CODEX_HOME="${probe_dir}/codex-home" "$1" --version >/dev/null 2>&1; }
  preview_codex=""
  if [ -n "${AGENTSTACK_CODEX_BIN:-}" ]; then
    preview_codex="$AGENTSTACK_CODEX_BIN"   # explicit: used as given, even if it fails
  else
    saved_codex="$(env_value AGENTSTACK_CODEX_BIN)"
    if [ -n "$saved_codex" ] && codex_runs "$saved_codex"; then
      preview_codex="$saved_codex"
    else
      old_ifs="$IFS"; IFS=:
      for dir in $PATH "$HOME/.local/bin" "$HOME/.npm-global/bin" "$HOME/.nodebrew/current/bin" /opt/homebrew/bin /usr/local/bin; do
        if [ -n "$dir" ] && codex_runs "$dir/codex"; then preview_codex="$dir/codex"; break; fi
      done
      IFS="$old_ifs"
    fi
  fi
  rm -rf "${probe_dir}/codex-home" && mkdir -p "${probe_dir}/codex-home"
  preview_env=""
  if [ -n "$preview_codex" ]; then
    printf '#!/bin/sh\nCODEX_HOME=%s exec %s "$@"\n' "'${probe_dir}/codex-home'" "'${preview_codex}'" >"${probe_dir}/bin/codex"
    chmod +x "${probe_dir}/bin/codex"
    preview_env="AGENTSTACK_CODEX_BIN=${probe_dir}/bin/codex"
    note "the preview asks ${preview_codex} for its version with a throwaway CODEX_HOME"
  fi
  preview_status=0
  (cd "$preview_root" && env PATH="${probe_dir}/bin:${PATH}" $preview_env ./scripts/install.sh --dry-run --project-key "$project_key") \
    || preview_status=$?
  rm -rf "$probe_dir"
  if [ -n "$preview_tmp" ]; then rm -rf "$preview_tmp"; fi
  if [ "$preview_status" -ne 0 ]; then
    stop "The installer's preview failed (exit ${preview_status}, see above). Nothing was changed."
  fi
  if [ "$mode" = update ]; then
    say ""
    say "Dry run: what the update would fetch"
    "${COCKPIT_ROOT}/scripts/update.sh" --dry-run \
      || stop "The update's preview failed (see above). Nothing was changed."
  fi
  say ""
  say "Dry run finished: nothing was changed."
  exit 0
fi

say ""
ask_yes "Type yes and press Enter to go ahead (anything else stops):"
step_done "Plan"

# ================================================================ 4. orrery-telemetry
step "orrery-telemetry"
say "  log: ${LOG}"
changes_started=true

if [ "$need_uv" = true ]; then
  say "  installing uv ..."
  logged env UV_NO_MODIFY_PATH=1 sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh' \
    || { show_log_tail; stop "Installing uv failed (see above)."; }
  uv --version >/dev/null 2>&1 || stop "uv was installed but does not run (looked in ~/.local/bin)."
  ok "uv: $(command -v uv) ($(uv --version | awk '{print $2}'))"
fi
if [ "$need_python" = true ]; then
  say "  installing Python 3.12 with uv ..."
  logged uv python install 3.12 || { show_log_tail; stop "Installing Python with uv failed (see above)."; }
  python_bin="$(uv python find 3.12 2>/dev/null || true)"
  if [ -z "$python_bin" ] || ! py_ok "$python_bin"; then stop "uv installed Python 3.12 but it cannot be run."; fi
  ok "Python: ${python_bin} ($("$python_bin" -c 'import platform; print(platform.python_version())'))"
fi
# Both parts use the same interpreter.
export AGENTSTACK_PYTHON="${AGENTSTACK_PYTHON:-$python_bin}"
export ORRERY_PYTHON="${ORRERY_PYTHON:-$python_bin}"

if [ -n "$detached_fix" ]; then
  while IFS='|' read -r path branch head; do
    [ -n "$path" ] || continue
    printf '%s was detached at %s\n' "$path" "$head" >>"${RUN_DIR}/steps"
    if git -C "$path" show-ref --verify --quiet "refs/heads/${branch}"; then
      logged git -C "$path" switch "$branch" || { show_log_tail; stop "Could not switch ${path} back to ${branch}."; }
    else
      logged git -C "$path" switch -c "$branch" --track "origin/${branch}" \
        || { show_log_tail; stop "Could not switch ${path} back to ${branch}."; }
    fi
    ok "switched ${path} to ${branch} (it was at $(short "$head"); back: git -C \"${path}\" switch --detach ${head})"
  done <<EOF
$detached_fix
EOF
fi

mkdir -p "$project_key"
assume_flag=""
if [ "$ask_each" != true ]; then assume_flag="--assume-yes"; fi

# install.sh reads some saved settings from env.sh by itself and others only
# from the environment, so load env.sh first; values set in this shell win.
# (The same rule as scripts/update.sh.)
run_installer() {
  (
    cd "$tel_root"
    if [ -r "$ENV_FILE" ]; then
      explicit=""
      for name in $(compgen -e); do
        case "$name" in
          AGENTSTACK_*) explicit="${explicit} ${name}"; eval "saved_${name}=\"\${${name}}\"" ;;
        esac
      done
      . "$ENV_FILE"
      for name in $explicit; do
        eval "export ${name}=\"\${saved_${name}}\""
      done
    fi
    exec ./scripts/install.sh $assume_flag --project-key "$project_key"
  )
}

# The installer's own failure. One known case gets its own explanation; this
# setup never offers to delete anything of ORRERY Mail.
installer_failed_hint() {
  bad_venv="$(sed -n 's/^error: ORRERY Mail candidate venv exists but is incomplete: //p' "$LOG" | tail -n 1)"
  if [ -n "$bad_venv" ]; then
    stop "orrery-telemetry's installer stopped: it found an unfinished copy of ORRERY Mail" \
      "(${bad_venv})," \
      "probably from a download that was cut off, and it does not continue past it." \
      "This setup does not remove it: it cannot tell for sure that nothing uses it." \
      "Ask for help with this log: ${LOG}"
  fi
  stop "orrery-telemetry's installer stopped (see above)." \
    "Fix what it reports, then run the same command again."
}

update_failed=false
case "$mode" in
  fresh | reinstall)
    if [ "$tel_clone" = true ]; then
      say "  downloading orrery-telemetry (about 55 MB) ..."
      parent="$(dirname "$tel_root")"
      mkdir -p "$parent"
      tmp="$(mktemp -d "${parent}/.orrery-telemetry-get.XXXXXX")"
      tries=0
      until logged git clone --depth 1 --branch "$TEL_REF" "$TEL_URL" "${tmp}/t"; do
        rm -rf "${tmp}/t"
        tries=$((tries + 1))
        if [ "$tries" -ge 3 ]; then
          rm -rf "$tmp"
          show_log_tail
          stop "Could not download orrery-telemetry from ${TEL_URL} (3 tries)." \
            "Check the network connection, then run the same command again."
        fi
        note "download failed; trying again in $((tries * ${ORRERY_RETRY_SLEEP:-5})) seconds (${tries}/3)"
        sleep $((tries * ${ORRERY_RETRY_SLEEP:-5}))
      done
      if [ -e "$tel_root" ]; then rm -rf "$tmp"; stop "${tel_root} appeared while downloading (another install?)."; fi
      mv "${tmp}/t" "$tel_root"
      rm -rf "$tmp"
      ok "downloaded: ${tel_root} ($(head_of "$tel_root"))"
    fi
    say "  installing (about a minute) ..."
    if ! logged run_installer; then
      show_log_tail
      installer_failed_hint
    fi
    ok "orrery-telemetry installed ($(cat "${AGENTSTACK_DIR}/VERSION" 2>/dev/null || printf '?'))"
    ;;
  update)
    if [ -n "$project_key_arg" ]; then export AGENTSTACK_PROJECT_KEY="$project_key"; fi
    if [ "$ask_each" != true ]; then export AGENTSTACK_ASSUME_YES=1; fi
    say "  updating orrery-telemetry and the cockpit ..."
    if logged "${COCKPIT_ROOT}/scripts/update.sh" $pass_mail; then
      ok "orrery-telemetry: $(head_of "$tel_root") ($(cat "${AGENTSTACK_DIR}/VERSION" 2>/dev/null || printf '?')), cockpit: $(head_of "$COCKPIT_ROOT")"
    else
      update_failed=true
      show_log_tail
      say ""
      say "  NG    The update stopped (see above)."
      start_tel="$(sed -n "s/^telemetry checkout${TAB}\([^ ]*\).*/\1/p" "${RUN_DIR}/start")"
      start_cockpit="$(sed -n "s/^cockpit checkout${TAB}\([^ ]*\).*/\1/p" "${RUN_DIR}/start")"
      if [ "$(head_of "$tel_root")" = "$start_tel" ] && [ "$(head_of "$COCKPIT_ROOT")" = "$start_cockpit" ] \
        && ! grep -q '^\$ .*install.sh\|Updating orrery-telemetry' "$LOG"; then
        say "        It stopped in its checks: neither checkout moved."
        say "        Fix what it reports and run the same command again."
      else
        after_failure
      fi
    fi
    unset AGENTSTACK_ASSUME_YES
    ;;
esac

if [ "$update_failed" = true ]; then
  if [ ! -r "$ENV_FILE" ] || [ "$no_start" = true ] || [ "$assume_yes" = true ] || ! have_tty; then exit 1; fi
  say ""
  ask_yes "Start the cockpit with the versions you have now? Type yes to start:"
fi
step_done "orrery-telemetry"

# ================================================================ 5. cockpit environment
step "Cockpit environment"
say "  preparing the Python environment (the first time takes a minute) ..."
default_venv="${COCKPIT_ROOT}/bridge/.venv"
if ! logged env ORRERY_NO_UPDATE_CHECK=1 "${COCKPIT_ROOT}/scripts/start-cockpit.sh" --check; then
  # A venv left half-made (no completion stamp) is rebuilt, but only the
  # default one, and only while no cockpit is running from it.
  if [ -z "${ORRERY_VENV:-}" ] && [ -d "$default_venv" ] && [ ! -f "${default_venv}/.orrery-requirements" ] \
    && [ "$(backend_state)" = none ]; then
    note "the Python environment ${default_venv} was left unfinished; making it again"
    rm -rf "$default_venv"
    logged env ORRERY_NO_UPDATE_CHECK=1 "${COCKPIT_ROOT}/scripts/start-cockpit.sh" --check \
      || { show_log_tail; stop "The cockpit check stopped (see above). Fix what it reports, then run the same command again."; }
  else
    show_log_tail
    stop "The cockpit check stopped (see above). Fix what it reports, then run the same command again."
  fi
fi
ok "cockpit environment ready"
step_done "Cockpit environment"

# ================================================================ 6. checks
step "Checks"
checks_ok=true
bin_dir="${AGENTSTACK_DIR}/bin"

# The 4 changes, from the installer's own lines in this run's log.
item_result() { # $1 = "applied" pattern, $2 = "already" pattern (may be empty), $3 = "skipped" pattern
  if grep -q -- "$3" "$LOG"; then printf 'SKIPPED'
  elif [ -n "$2" ] && grep -q -- "$2" "$LOG"; then printf 'already the same'
  elif grep -q -- "$1" "$LOG"; then printf 'applied'
  else printf 'not reported by the installer'
  fi
}
show_item() { # $1 = label, $2 = result
  case "$2" in
    applied | "already the same") ok "$1: $2" ;;
    *) warn_line "$1: $2"; checks_ok=false ;;
  esac
}
if [ "$ask_each" = true ]; then
  applied_mcp="Claude MCP user-config safe-merge dry-run"
  applied_settings="Tier1 settings safe-merge dry-run"
  applied_codex="Codex AGENTS.md managed setup dry-run"
  applied_claude="Claude CLAUDE.md managed setup dry-run"
else
  applied_mcp="assume-yes: registered orrery-mail"
  applied_settings="assume-yes: applied Tier1 settings merge"
  applied_codex="assume-yes: applied Codex AGENTS.md managed setup"
  applied_claude="assume-yes: applied Claude CLAUDE.md managed setup"
fi
show_item "1. ~/.claude.json (MCP)" "$(item_result "$applied_mcp" "Claude MCP already registered" "Skipped Claude MCP\|skipping Claude MCP")"
show_item "2. ~/.claude/settings.json" "$(item_result "$applied_settings" "" "Skipped Tier1\|skipping Tier1")"
show_item "3. ~/.codex/AGENTS.md" "$(item_result "$applied_codex" "" "Skipped Codex AGENTS.md\|skipping Codex AGENTS.md")"
show_item "4. ${project_key}/CLAUDE.md" "$(item_result "$applied_claude" "" "Skipped Claude CLAUDE.md\|skipping Claude CLAUDE.md")"

# What the installer did with ORRERY Mail, in one line.
if grep -q 'installer will provision ORRERY Mail' "$LOG"; then
  ok "Mail: set up (new)"
elif grep -q 'adopted the running ORRERY Mail deployment' "$LOG"; then
  ok "Mail: kept the running one (not switched)"
else
  mail_report="$(grep 'ORRERY Mail update\|ORRERY Mail .*rolled back\|switched ORRERY Mail' "$LOG" | tail -n 1 || true)"
  ok "Mail: ${mail_report:-${mail_line}}"
fi

# Warnings the installer printed even though it finished. Known harmless
# ones are only counted.
harmless="AGENTSTACK_WORKTREE_ROOT: directory does not exist yet"
install_warnings="$(grep '^warning:' "$LOG" | grep -v -- "$harmless" | sort -u || true)"
harmless_count="$(grep -c -- "$harmless" "$LOG" || true)"
if [ -n "$install_warnings" ]; then
  printf '%s\n' "$install_warnings" | while IFS= read -r line; do warn_line "install: ${line#warning: }"; done
fi
if [ "${harmless_count:-0}" -gt 0 ]; then note "install: ${harmless_count} known harmless warning(s) (folders made on first use)"; fi

# doctor: read-only. Its exit status decides; the lines only explain. It
# reports problems as "missing:" (and some as "warn:") with exit 1, and any
# other non-zero exit counts as a problem too.
if [ -x "${bin_dir}/agentstack-doctor" ]; then
  doctor_status=0
  doctor_out="$("${bin_dir}/agentstack-doctor" 2>&1)" || doctor_status=$?
  printf '\n$ agentstack-doctor   (exit %s)\n%s\n' "$doctor_status" "$doctor_out" >>"$LOG"
  doctor_lines="$(printf '%s\n' "$doctor_out" | grep -v '^ok:' | grep -v '^ *$' || true)"
  if [ "$doctor_status" -ne 0 ]; then
    checks_ok=false
    warn_line "doctor: exited ${doctor_status}; what it reported (all of it: ${bin_dir}/agentstack-doctor):"
    if [ -n "$doctor_lines" ]; then
      printf '%s\n' "$doctor_lines" | head -n 20 | sed 's/^/          /'
    else
      printf '          (no explanation printed; see %s)\n' "$LOG"
    fi
  else
    ok "doctor: no problems"
    if [ -n "$doctor_lines" ]; then
      note "doctor: notes (it still exited 0):"
      printf '%s\n' "$doctor_lines" | head -n 8 | sed 's/^/          /'
    fi
  fi
else
  checks_ok=false
  warn_line "doctor: ${bin_dir}/agentstack-doctor is missing"
fi

# selftest: registers 2 test agents, sends a message both ways, reserves a
# file, checks the dashboard reads the same database, and removes the agents.
if [ -x "${bin_dir}/agentstack-selftest" ]; then
  say "  running agentstack-selftest (a Mail round trip with 2 test agents) ..."
  if logged "${bin_dir}/agentstack-selftest"; then
    ok "selftest: Mail round trip, file reservation and dashboard all work"
  else
    checks_ok=false
    warn_line "selftest failed; its output is in ${LOG}"
    tail -n 8 "$LOG" | sed 's/^/          /'
  fi
else
  checks_ok=false
  warn_line "selftest: ${bin_dir}/agentstack-selftest is missing"
fi

if [ -n "$agent_cli" ]; then
  ok "agent CLI: ${agent_cli}"
else
  note "agent CLI: none -> the base is ready, agents are not yet"
fi
step_done "Checks"

# A run that passes every check closes the first attempt's record. A run
# whose update failed never does, even when what is there works.
if [ "$update_failed" = true ]; then checks_ok=false; fi
if [ "$checks_ok" = true ]; then
  mv "$BASELINE" "${RUN_DIR}/baseline" 2>/dev/null || true
fi

# ================================================================ 7. start
step "Start"
url="http://127.0.0.1:${COCKPIT_PORT}/cockpit.html"
cockpit_head_full="$(git -C "$COCKPIT_ROOT" rev-parse HEAD)"
running="$(backend_state)"
restart_needed=false
case "$running" in
  none) ;;
  "$(cd "$COCKPIT_ROOT" && pwd -P)@${cockpit_head_full}" | "${COCKPIT_ROOT}@${cockpit_head_full}") ;;
  *) restart_needed=true ;;
esac

say ""
say "=============================================================="
if [ "$update_failed" = true ]; then
  say "  The update did not finish (see NG above). What runs now is the version"
  say "  you had. Fix what the update reported, then run the same command again."
elif [ "$checks_ok" = true ]; then
  if [ -n "$agent_cli" ]; then
    say "  ORRERY is ready."
  else
    say "  ORRERY's base is ready. To run agents, install Claude Code or Codex CLI"
    say "  and log in (claude, then /login  |  codex login), then follow step 2 below."
  fi
else
  say "  Installed, but not every check passed (WARN above). If you need help,"
  say "  send this file: ${LOG}"
fi
say ""
say "  See it work:"
say "    1. In the browser, the cockpit shows your project: $(basename "$project_key")"
say "    2. NEW AGENT starts a small agent (or in a new window:"
say "       ~/.agentstack/bin/agent-start ${project_key})"
say "    3. The agent appears in the list and its reply shows up"
say "  After closing this window or restarting the computer:"
say "    ~/.agentstack/bin/agentstack-doctor"
say "    (if stopped) ~/.agentstack/dashboard/agentctl.sh start; ~/.agentstack/bin/agentstack-mailctl start"
say "    ${COCKPIT_ROOT}/scripts/start-cockpit.sh"
if [ "$mode" = fresh ]; then
  say "  To remove this new install: ${tel_root}/scripts/uninstall.sh"
  say "  (it keeps the Mail database unless --purge-data; the 2 checkouts, uv and Python stay)"
fi
say "  Log: ${LOG}"
say "=============================================================="

if [ "$restart_needed" = true ]; then
  say ""
  say "  A cockpit is already running on port ${COCKPIT_PORT}, but not this version"
  say "  (running: ${running})."
  say "  It was not stopped. In its window press Ctrl-C, then run:"
  say "    ${COCKPIT_ROOT}/scripts/start-cockpit.sh"
  say "  Until then the browser shows the old cockpit."
  exit 0
fi
if [ "$running" != none ]; then
  say ""
  say "  The cockpit is already running this version: ${url}"
  exit 0
fi
if [ "$no_start" = true ]; then
  say ""
  say "Start the cockpit when you want with:"
  say "  ${COCKPIT_ROOT}/scripts/start-cockpit.sh"
  exit 0
fi

# Open the browser once the cockpit answers (never blocks the start).
if [ "${ORRERY_NO_OPEN:-0}" != 1 ]; then
  (
    i=0
    while [ "$i" -lt 60 ]; do
      i=$((i + 1))
      sleep 1
      if curl -fsS -o /dev/null --max-time 1 "http://127.0.0.1:${COCKPIT_PORT}/telemetry/health" 2>/dev/null; then
        case "$os" in
          mac) open "$url" ;;
          wsl) if command -v wslview >/dev/null 2>&1; then wslview "$url"; else explorer.exe "$url"; fi ;;
          *) if command -v xdg-open >/dev/null 2>&1; then xdg-open "$url"; fi ;;
        esac
        exit 0
      fi
    done
  ) </dev/null >/dev/null 2>&1 &
fi
say ""
say "Starting the cockpit in this window. It keeps running here: leave the window"
say "open; Ctrl-C (or closing the window) stops it. If it reports NG, follow its Fix."
if [ "$os" = wsl ]; then
  say "If the Windows browser shows nothing: in PowerShell run"
  say "  curl http://127.0.0.1:${COCKPIT_PORT}/telemetry/health   (localhost forwarding)"
  say "and in Ubuntu run  explorer.exe .   (opening Windows apps from Ubuntu)."
fi
if [ -n "$LOCK" ]; then rm -rf "$LOCK"; fi
trap - EXIT
export ORRERY_NO_UPDATE_CHECK=1
exec "${COCKPIT_ROOT}/scripts/start-cockpit.sh"
