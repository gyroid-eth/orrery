#!/usr/bin/env bash
# Offline tests for scripts/get.sh and scripts/setup.sh (the one-line install).
# They use throwaway HOMEs and local file:// repositories only: no network,
# no services, nothing outside a temporary folder.
#
#   tools/test_one_command_install.sh
#
# The full install (services, doctor, selftest, cockpit) is tested by hand in
# a separate HOME with separate ports; see docs/install.md.
set -u

ROOT="$(cd -- "$(dirname -- "$0")/.." && pwd)"
WORK="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/orrery-install-test.XXXXXX")" && pwd -P)"
# Every cockpit a test starts lives in this test-only tmux server.
TEST_SOCK="orrery-cockpit-test-$$"
cleanup() {
  env -u TMUX tmux -L "$TEST_SOCK" kill-server 2>/dev/null; env -u TMUX tmux -L "${TEST_SOCK}-bg" kill-server 2>/dev/null
  pkill -f "$WORK" 2>/dev/null
  rm -rf "$WORK"
}
trap cleanup EXIT
failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() {
  printf 'FAIL  %s\n' "$1"; failures=$((failures + 1))
  # ORRERY_TEST_VERBOSE=1: the end of the last setup output, to see why.
  if [ "${ORRERY_TEST_VERBOSE:-0}" = 1 ]; then printf '%s\n' "${out:-}" | tail -n 25 | sed 's/^/      | /'; fi
}
check() { # $1 = name; rest = command that must succeed
  name="$1"; shift
  if "$@"; then pass "$name"; else fail "$name"; fi
}

# A repository of this checkout's committed state to clone from (file:// so
# partial clone and sparse checkout behave as with GitHub).
BRANCH="$(git -C "$ROOT" rev-parse --abbrev-ref HEAD)"
git clone --quiet --bare "$ROOT" "$WORK/orrery.git"
COCKPIT_URL="file://$WORK/orrery.git"

fresh_home() { # $1 = name; prints the new HOME
  h="$WORK/$1"
  mkdir -p "$h/tmp"
  printf '%s' "$h"
}
run_in() { # $1 = HOME; rest = command (a clean environment)
  h="$1"; shift
  env -i PATH="$PATH" HOME="$h" TMPDIR="$h/tmp" TERM=dumb LANG=C ORRERY_RETRY_SLEEP=0 \
    ORRERY_NO_OPEN=1 PORT=18999 AGENTSTACK_PORT=18998 ORRERY_COCKPIT_TMUX_SOCKET="$TEST_SOCK" "$@"
}

# ---------------------------------------------------------------- remote match
block() { sed -n '/# >>> remote-match/,/# <<< remote-match/p' "$1" | sed 's/^ *//'; }
check "get.sh and setup.sh share the same remote check" \
  test "$(block "$ROOT/scripts/get.sh")" = "$(block "$ROOT/scripts/setup.sh")"
eval "$(block "$ROOT/scripts/setup.sh")"
for url in https://github.com/gyroid-eth/orrery https://github.com/gyroid-eth/orrery.git \
  git@github.com:gyroid-eth/orrery.git ssh://git@github.com/gyroid-eth/orrery.git; do
  check "official: $url" official_remote "$url" orrery ""
done
for url in https://example.invalid/gyroid-eth/orrery.git https://github.com.evil/gyroid-eth/orrery.git \
  https://github.com/someone/gyroid-eth/orrery.git git@example.invalid:gyroid-eth/orrery.git \
  https://github.com/gyroid-eth/orrery-telemetry.git https://github.com/other/orrery.git; do
  if official_remote "$url" orrery ""; then fail "not official: $url"; else pass "not official: $url"; fi
done
check "override: only the exact URL" official_remote "file:///x/orrery.git" orrery "file:///x/orrery.git"
if official_remote https://github.com/gyroid-eth/orrery.git orrery file:///x/orrery.git; then
  fail "override: the official URL is not taken while overriding"
else
  pass "override: the official URL is not taken while overriding"
fi

# ---------------------------------------------------------------- foreign origin
H="$(fresh_home foreign)"
git clone --quiet "$COCKPIT_URL" "$H/orrery"
git -C "$H/orrery" remote set-url origin https://example.invalid/gyroid-eth/orrery.git
rm -f "$H/orrery/scripts/setup.sh"
out="$(run_in "$H" bash "$ROOT/scripts/get.sh" --help 2>&1)"; status=$?
check "foreign origin: get.sh stops" test "$status" -ne 0
check "foreign origin: says why" sh -c 'printf "%s" "$1" | grep -q "not the official repository"' _ "$out"
check "foreign origin: nothing fetched" test ! -e "$H/orrery/.git/FETCH_HEAD"

# ---------------------------------------------------------------- read-only entry
H="$(fresh_home readonly)"
before="$(cd "$H" && find . | sort)"
out="$(run_in "$H" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" bash "$ROOT/scripts/get.sh" --check 2>&1)"; status=$?
after="$(cd "$H" && find . | sort)"
check "--check through get.sh: exits 0" test "$status" -eq 0
check "--check through get.sh: HOME unchanged (no checkout, no state)" test "$before" = "$after"
check "--check through get.sh: shows the plan" sh -c 'printf "%s" "$1" | grep -q "change these 4 things"' _ "$out"
check "--check through get.sh: says where it would download" sh -c 'printf "%s" "$1" | grep -q "would be downloaded to"' _ "$out"

# ---------------------------------------------------------------- old checkout -> remote setup
H="$(fresh_home oldsetup)"
git clone --quiet --branch "$BRANCH" "$COCKPIT_URL" "$H/orrery"
git -C "$H/orrery" -c user.name=t -c user.email=t@t rm --quiet scripts/setup.sh
git -C "$H/orrery" -c user.name=t -c user.email=t@t commit --quiet -m "older: no setup.sh"
git -C "$H/orrery" reset --quiet --hard HEAD   # a checkout without setup.sh
out="$(run_in "$H" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" bash "$ROOT/scripts/get.sh" --help 2>&1)"; status=$?
check "no setup.sh: runs the remote's setup" sh -c 'printf "%s" "$1" | grep -q "setup: from"' _ "$out"
check "no setup.sh: the remote's setup ran (--help)" sh -c 'printf "%s" "$1" | grep -q "Usage: scripts/setup.sh"' _ "$out"
check "no setup.sh: checkout files unchanged" test ! -e "$H/orrery/scripts/setup.sh"

H="$(fresh_home oldcontract)"
git clone --quiet --branch "$BRANCH" "$COCKPIT_URL" "$H/orrery"
sed -i.bak 's/^ORRERY_SETUP_CONTRACT=.*/# no contract line/' "$H/orrery/scripts/setup.sh" && rm -f "$H/orrery/scripts/setup.sh.bak"
out="$(run_in "$H" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" bash "$ROOT/scripts/get.sh" --help 2>&1)"
check "old contract: runs the remote's setup" sh -c 'printf "%s" "$1" | grep -q "setup: from"' _ "$out"

# ---------------------------------------------------------------- failures keep the first record
H="$(fresh_home baseline)"
git clone --quiet --branch "$BRANCH" "$COCKPIT_URL" "$H/orrery"
setup_fail() {
  run_in "$H" ORRERY_DIR="$H/orrery" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" \
    ORRERY_TELEMETRY_URL="file://$WORK/does-not-exist.git" AGENTSTACK_PYTHON="$(command -v python3)" \
    bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1
}
out1="$(setup_fail)"; s1=$?
first="$(cat "$H/.orrery-install/baseline" 2>/dev/null)"
sleep 1
out2="$(setup_fail)"; s2=$?
check "failed download: stops (1st)" test "$s1" -ne 0
check "failed download: stops (2nd)" test "$s2" -ne 0
check "failed download: first record written" test -n "$first"
check "failed download: retry keeps the first record" test "$first" = "$(cat "$H/.orrery-install/baseline" 2>/dev/null)"
check "failed download: one folder per run" test "$(ls "$H/.orrery-install/runs" | wc -l | tr -d ' ')" -eq 2
check "failed download: shows what changed" sh -c 'printf "%s" "$1" | grep -q "What changed since the first attempt"' _ "$out2"
check "failed download: lock released" test ! -e "$H/.orrery-install/lock"
check "failed download: no half checkout left" test ! -e "$H/orrery-telemetry"

# ---------------------------------------------------------------- lock
H="$(fresh_home lock)"
git clone --quiet --branch "$BRANCH" "$COCKPIT_URL" "$H/orrery"
mkdir -p "$H/.orrery-install/lock" && printf '%s\n' "$$" >"$H/.orrery-install/lock/pid"
out="$(run_in "$H" ORRERY_DIR="$H/orrery" ORRERY_REPO_URL="$COCKPIT_URL" bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1)"; status=$?
check "lock: a second setup stops" test "$status" -ne 0
check "lock: says another is running" sh -c 'printf "%s" "$1" | grep -q "Another ORRERY setup is running"' _ "$out"

# ---------------------------------------------------------------- --mail update without support
H="$(fresh_home mail)"
git init --quiet "$WORK/fake-telemetry"
mkdir -p "$WORK/fake-telemetry/scripts" && printf '#!/bin/sh\nexit 0\n' >"$WORK/fake-telemetry/scripts/install.sh"
chmod +x "$WORK/fake-telemetry/scripts/install.sh"
git -C "$WORK/fake-telemetry" add -A && git -C "$WORK/fake-telemetry" -c user.name=t -c user.email=t@t commit --quiet -m t
git clone --quiet "file://$WORK/fake-telemetry" "$H/orrery-telemetry"
mkdir -p "$H/.agentstack"
printf '{\n  "repo_root": "%s",\n  "tool": "x"\n}\n' "$H/orrery-telemetry" >"$H/.agentstack/install-state.json"
# A cockpit whose update.sh is older and has no --mail.
git clone --quiet --branch "$BRANCH" "$COCKPIT_URL" "$H/orrery"
printf '#!/bin/sh\necho "Usage: update.sh [--dry-run]"\n' >"$H/orrery/scripts/update.sh"
git -C "$H/orrery" -c user.name=t -c user.email=t@t commit --quiet -am "an update.sh without --mail"
out="$(run_in "$H" ORRERY_DIR="$H/orrery" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_TELEMETRY_URL="file://$WORK/fake-telemetry" \
  bash "$H/orrery/scripts/setup.sh" --yes --no-start --mail update 2>&1)"; status=$?
check "--mail update unsupported: stops" test "$status" -ne 0
check "--mail update unsupported: before any change (no run folder)" test ! -e "$H/.orrery-install/runs"
check "--mail update unsupported: says so" sh -c 'printf "%s" "$1" | grep -q "cannot take --mail yet"' _ "$out"

# ================================================================ end-to-end with stubs
# The real setup.sh, with orrery-telemetry, doctor, selftest, update.sh and
# start-cockpit.sh replaced by small stubs (driven by STUB_* variables).

# A stub orrery-telemetry whose install.sh lays out what setup.sh reads.
STUBTEL="$WORK/stub-telemetry"
mkdir -p "$STUBTEL/scripts"
cat >"$STUBTEL/scripts/install.sh" <<'EOF'
#!/usr/bin/env bash
set -eu
dir="${AGENTSTACK_HOME:-$HOME/.agentstack}"
if [ "${1:-}" = "--help" ]; then
  echo "Usage: install.sh"
  if [ -n "${STUB_MAIL_HELP:-}" ]; then
    echo "  --mail auto|update|keep"
    echo "  --print-mail-update-advice"
  fi
  exit 0
fi
if [ "${1:-}" = "--print-mail-update-advice" ]; then
  if [ -n "${STUB_MAIL_ADVICE:-}" ]; then
    echo "ORRERY Mail is out of date (running aaaaaaa, this checkout bbbbbbb)."
    echo "  Risk: STUB-RISK-LINE"
    echo "  If one shows orrery-mail as failed afterwards, in that session: /mcp, choose orrery-mail (shown as failed), then Reconnect (not Authenticate)."
  fi
  exit 0
fi
if [ "${1:-}" = "--dry-run" ] || [ "${2:-}" = "--dry-run" ]; then
  # As the real installer probes Codex: an explicit AGENTSTACK_CODEX_BIN,
  # else the one saved in env.sh, else codex on PATH.
  saved="$(sed -n 's/^export AGENTSTACK_CODEX_BIN=//p' "$dir/env.sh" 2>/dev/null | head -n 1)"
  "${AGENTSTACK_CODEX_BIN:-${saved:-codex}}" --version >/dev/null 2>&1 || true
  echo "Tier1 settings safe-merge dry-run: (stub)"
  exit "${STUB_PREVIEW_EXIT:-0}"
fi
# Like the real installer: settings it reads back from env.sh itself, and a
# Codex path in its environment counts as chosen; a chosen one that does not
# run is refused (exit 2).
resolve_setting() { :; }
resolve_setting CODEX_BIN_SETTING AGENTSTACK_CODEX_BIN "" found
if [ -n "${AGENTSTACK_CODEX_BIN:-}" ] && ! "$AGENTSTACK_CODEX_BIN" --version >/dev/null 2>&1; then
  echo "error: --codex-bin / AGENTSTACK_CODEX_BIN cannot be used: $AGENTSTACK_CODEX_BIN" >&2; exit 2
fi
if [ -n "${STUB_INSTALL_ERROR:-}" ]; then echo "error: ${STUB_INSTALL_ERROR}" >&2; exit 1; fi
printf 'args=%s env=%s\n' "$*" "${AGENTSTACK_MAIL_UPDATE-unset}" >"$HOME/install-args"
if [ -n "${STUB_WARN:-}" ]; then
  echo "warning: Claude skill 'delegate' already exists; leaving it untouched: $HOME/.claude/skills/delegate" >&2
  echo "warning: optional dependency 'fswatch' not found; mail watcher will use polling" >&2
fi
mkdir -p "$dir/bin"
printf '2026.10.01.1\n' >"$dir/VERSION"
printf 'export AGENTSTACK_PROJECT_KEY=%s\n' "$HOME/orrery-work" >"$dir/env.sh"
printf '{\n  "repo_root": "%s",\n  "tool": "stub"\n}\n' "$(pwd)" >"$dir/install-state.json"
cat >"$dir/bin/agentstack-doctor" <<'DOC'
#!/bin/sh
case "${STUB_DOCTOR:-ok}" in
  ok) echo "ok: everything"; exit 0 ;;
  missing) echo "ok: env"; echo "missing: hooks under $HOME/.agentstack/hooks" >&2; exit 1 ;;
  warn) echo "warn: dashboard does not answer"; exit 1 ;;
  unknown) echo "something odd happened"; exit 3 ;;
  mailnewer)
    echo "ok: everything else"
    echo "warn: ORRERY Mail (running ccccccc) lacks register_agent.existing_agent_id, which this install relies on: STUB-NEEDED-FOR" >&2
    echo "      Update ORRERY Mail from an orrery-telemetry checkout at least as new as the running build (docs/agentstack-mail-update.md)." >&2
    echo "mail-features: status=missing missing=register_agent.existing_agent_id running=ccccccc"
    exit 0 ;;
  mailmissing)
    echo "ok: everything else"
    echo "warn: ORRERY Mail (running aaaaaaa) lacks register_agent.existing_agent_id, which this install relies on: STUB-NEEDED-FOR" >&2
    echo "      To update: ./scripts/install.sh --mail update" >&2
    echo "mail-features: status=missing missing=register_agent.existing_agent_id running=aaaaaaa"
    exit 0 ;;
esac
DOC
printf '#!/bin/sh\necho "self-test passed"\n' >"$dir/bin/agentstack-selftest"
chmod +x "$dir/bin/agentstack-doctor" "$dir/bin/agentstack-selftest"
echo "installer will provision ORRERY Mail at stub"
echo "assume-yes: registered orrery-mail in $HOME/.claude.json"
echo "assume-yes: applied Tier1 settings merge to $HOME/.claude/settings.json"
echo "assume-yes: applied Codex AGENTS.md managed setup"
echo "assume-yes: applied Claude CLAUDE.md managed setup"
if [ "${STUB_MAIL_RESULT:-}" = switched ]; then
  echo "ORRERY Mail was unavailable for 3s."
  echo "  in each running Claude Code session: STUB-RECONNECT-LINE"
fi
if [ -n "${STUB_MAIL_RESULT:-}" ]; then
  echo "mail-result: ${STUB_MAIL_RESULT} mode=keep from=aaaaaaa to=bbbbbbb running=aaaaaaa outage_s=0 reason=keep_requested"
fi
EOF
chmod +x "$STUBTEL/scripts/install.sh"
git -C "$STUBTEL" init --quiet
git -C "$STUBTEL" add -A && git -C "$STUBTEL" -c user.name=t -c user.email=t@t commit --quiet -m stub
STUBTEL_URL="file://$STUBTEL"

# A cockpit checkout whose update.sh and start-cockpit.sh are stubs.
stub_cockpit() { # $1 = HOME
  git clone --quiet --branch "$BRANCH" "$COCKPIT_URL" "$1/orrery"
  cat >"$1/orrery/scripts/start-cockpit.sh" <<'EOF'
#!/bin/sh
# Stub: --check succeeds; a start serves /telemetry/health like the real
# backend (root and commit fixed at start) until it is stopped.
case "${1:-}" in --check) echo "stub start-cockpit --check"; exit 0 ;; esac
root="$(cd "$(dirname "$0")/.." && pwd -P)"
commit="$(git -C "$root" rev-parse HEAD)"
exec python3 - "$PORT" "$root" "$commit" <<'PY'
import http.server, json, sys
port, root, commit = int(sys.argv[1]), sys.argv[2], sys.argv[3]
class H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps({"backend": "ok", "root": root, "commit": commit}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
http.server.HTTPServer(("127.0.0.1", port), H).serve_forever()
PY
EOF
  cat >"$1/orrery/scripts/update.sh" <<'EOF'
#!/bin/sh
case "${1:-}" in --help) echo "Usage: update.sh"; exit 0 ;; esac
echo "Updating orrery-telemetry ..."
(cd "$HOME/orrery-telemetry" && ./scripts/install.sh --assume-yes) || exit 1
exit "${STUB_UPDATE_EXIT:-0}"
EOF
  git -C "$1/orrery" -c user.name=t -c user.email=t@t commit --quiet -am "test stubs"
}
setup_in() { # $1 = HOME; rest = env assignments and setup options
  h="$1"; shift
  run_in "$h" ORRERY_DIR="$h/orrery" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" \
    ORRERY_TELEMETRY_URL="$STUBTEL_URL" AGENTSTACK_PYTHON="$(command -v python3)" "$@"
}

for case_ in ok missing warn unknown; do
  H="$(fresh_home "doctor-$case_")"
  stub_cockpit "$H"
  out="$(setup_in "$H" STUB_DOCTOR="$case_" bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1)"
  if [ "$case_" = ok ]; then
    check "doctor ok: ready" sh -c 'printf "%s" "$1" | grep -q "ORRERY is ready\|base is ready"' _ "$out"
    check "doctor ok: first record closed" test ! -e "$H/.orrery-install/baseline"
  else
    check "doctor ${case_} (exit != 0): not ready" sh -c '! printf "%s" "$1" | grep -q "is ready"' _ "$out"
    check "doctor ${case_} (exit != 0): says the doctor found problems" sh -c 'printf "%s" "$1" | grep -q "doctor: exited"' _ "$out"
    check "doctor ${case_} (exit != 0): first record kept" test -s "$H/.orrery-install/baseline"
  fi
done
H="$(fresh_home doctor-missing-line)"
stub_cockpit "$H"
out="$(setup_in "$H" STUB_DOCTOR=missing bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1)"
check "doctor missing: the missing line is on the screen" sh -c 'printf "%s" "$1" | grep -q "missing: hooks under"' _ "$out"

# Update failed, then "start with what you have": never ready, record kept.
H="$(fresh_home update-failed)"
stub_cockpit "$H"
setup_in "$H" bash "$H/orrery/scripts/setup.sh" --yes --no-start >/dev/null 2>&1   # a first, good install
check "update-failed: the good install closed its record" test ! -e "$H/.orrery-install/baseline"
pty_run() { # rest = command; answers yes twice through a pseudo-terminal
  if script --version >/dev/null 2>&1; then   # util-linux
    (sleep 3; printf 'yes\n'; sleep 3; printf 'yes\n'; sleep 3) | script -qec "$*" /dev/null
  else                                         # BSD / macOS
    (sleep 3; printf 'yes\n'; sleep 3; printf 'yes\n'; sleep 3) | script -q /dev/null sh -c "$*"
  fi
}
out="$(pty_run env -i PATH="$PATH" HOME="$H" TMPDIR="$H/tmp" TERM=dumb ORRERY_RETRY_SLEEP=0 ORRERY_NO_OPEN=1 PORT=18999 AGENTSTACK_PORT=18998 ORRERY_COCKPIT_TMUX_SOCKET="$TEST_SOCK" \
  ORRERY_DIR="$H/orrery" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" STUB_UPDATE_EXIT=1 bash "$H/orrery/scripts/setup.sh" 2>&1 | tr -d '\r')"
env -u TMUX tmux -L "$TEST_SOCK" kill-server 2>/dev/null
check "update-failed: offered to start what is there" sh -c 'printf "%s" "$1" | grep -q "Start the cockpit with the versions you have now"' _ "$out"
check "update-failed: not ready" sh -c '! printf "%s" "$1" | grep -q "is ready"' _ "$out"
check "update-failed: says the update did not finish" sh -c 'printf "%s" "$1" | grep -q "update did not finish"' _ "$out"
check "update-failed: first record kept" test -s "$H/.orrery-install/baseline"

# A fresh interactive run asks one thing only: yes to the plan. The project
# folder is the default unless --project-key / ORRERY_PROJECT_KEY says otherwise.
H="$(fresh_home one-question)"
stub_cockpit "$H"
pty_yes_once() {
  if script --version >/dev/null 2>&1; then
    (sleep 3; printf 'yes\n'; sleep 4) | script -qec "$*" /dev/null
  else
    (sleep 3; printf 'yes\n'; sleep 4) | script -q /dev/null sh -c "$*"
  fi
}
out="$(pty_yes_once env -i PATH="$PATH" HOME="$H" TMPDIR="$H/tmp" TERM=dumb ORRERY_RETRY_SLEEP=0 ORRERY_NO_OPEN=1 PORT=18999 AGENTSTACK_PORT=18998 ORRERY_COCKPIT_TMUX_SOCKET="$TEST_SOCK" \
  ORRERY_DIR="$H/orrery" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" bash "$H/orrery/scripts/setup.sh" --no-start 2>&1 | tr -d '\r')"
env -u TMUX tmux -L "$TEST_SOCK" kill-server 2>/dev/null
check "one question: no folder question" sh -c '! printf "%s" "$1" | grep -q "Folder the agents will work in"' _ "$out"
check "one question: the default folder is used" test -d "$H/orrery-work"
check "one question: the plan says how to choose another folder" sh -c 'printf "%s" "$1" | grep -q -- "--project-key"' _ "$out"
check "one question: ready after a single yes" sh -c 'printf "%s" "$1" | grep -q "is ready"' _ "$out"
H="$(fresh_home project-key-option)"
stub_cockpit "$H"
setup_in "$H" bash "$H/orrery/scripts/setup.sh" --yes --no-start --project-key "~/elsewhere" >/dev/null 2>&1
check "--project-key: that folder is used" test -d "$H/elsewhere"

# The cockpit starts in the background (its own tmux server) and the window
# comes back; a later update restarts the cockpit setup started itself.
SOCK="${TEST_SOCK}-bg"
H="$(fresh_home background)"
stub_cockpit "$H"
default_before="$(env -u TMUX tmux list-sessions -F '#{session_name}' 2>/dev/null | sort)"
start_ts=$(date +%s)
out="$(setup_in "$H" PORT=18997 ORRERY_COCKPIT_TMUX_SOCKET="$SOCK" bash "$H/orrery/scripts/setup.sh" --yes 2>&1)"; status=$?
check "background: setup returns (exit 0)" test "$status" -eq 0
check "background: returns promptly" test $(( $(date +%s) - start_ts )) -lt 60
check "background: the cockpit answers after setup returned" sh -c 'curl -fsS --max-time 2 http://127.0.0.1:18997/telemetry/health >/dev/null'
check "background: in its own tmux server" tmux -L "$SOCK" has-session
check "background: the default tmux server (the agents') is untouched" \
  test "$default_before" = "$(env -u TMUX tmux list-sessions -F '#{session_name}' 2>/dev/null | sort)"
check "background: says how to stop it" sh -c 'printf "%s" "$1" | grep -q "kill-server"' _ "$out"
check "background: says the window is free" sh -c 'printf "%s" "$1" | grep -q "this window is free"' _ "$out"
git -C "$H/orrery" -c user.name=t -c user.email=t@t commit --quiet --allow-empty -m "newer"
out="$(setup_in "$H" PORT=18997 ORRERY_COCKPIT_TMUX_SOCKET="$SOCK" bash "$H/orrery/scripts/setup.sh" --yes 2>&1)"
check "background: an older cockpit it started is restarted" sh -c 'printf "%s" "$1" | grep -q "restarted the cockpit"' _ "$out"
check "background: now runs the new commit" sh -c 'curl -fsS --max-time 2 http://127.0.0.1:18997/telemetry/health | grep -q "$1"' _ "$(git -C "$H/orrery" rev-parse HEAD)"
tmux -L "$SOCK" kill-server 2>/dev/null
# A cockpit it did not start (not in its tmux server) is never stopped.
H2="$(fresh_home foreign-cockpit)"
stub_cockpit "$H2"
(cd "$H2" && env PORT=18996 "$H/orrery/scripts/start-cockpit.sh" >/dev/null 2>&1 &) ; sleep 2
out="$(setup_in "$H2" PORT=18996 ORRERY_COCKPIT_TMUX_SOCKET="$SOCK" bash "$H2/orrery/scripts/setup.sh" --yes 2>&1)"
check "foreign cockpit: not stopped" sh -c 'curl -fsS --max-time 2 http://127.0.0.1:18996/telemetry/health >/dev/null'
check "foreign cockpit: says a restart is needed" sh -c 'printf "%s" "$1" | grep -q "not this version"' _ "$out"
pkill -f "$H2" 2>/dev/null

# A Codex path saved in env.sh that no longer runs is not handed to the
# installer as chosen (it looks for codex again instead of refusing).
H="$(fresh_home saved-broken-codex)"
stub_cockpit "$H"
mkdir -p "$H/.agentstack"
printf "export AGENTSTACK_CODEX_BIN='/broken/codex'\nexport AGENTSTACK_PROJECT_KEY='%s'\n" "$H/orrery-work" >"$H/.agentstack/env.sh"
out="$(setup_in "$H" bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1)"; status=$?
check "saved broken codex: the install goes on" test "$status" -eq 0
check "saved broken codex: not refused as chosen" sh -c '! printf "%s" "$1" | grep -q "cannot be used"' _ "$out"
# ... also when the login shell already exported env.sh (~/.zshenv on the Air).
H="$(fresh_home saved-broken-codex-echoed)"
stub_cockpit "$H"
mkdir -p "$H/.agentstack"
printf "export AGENTSTACK_CODEX_BIN='/broken/codex'\nexport AGENTSTACK_PROJECT_KEY='%s'\n" "$H/orrery-work" >"$H/.agentstack/env.sh"
out="$(setup_in "$H" AGENTSTACK_CODEX_BIN=/broken/codex AGENTSTACK_PROJECT_KEY="$H/orrery-work" bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1)"; status=$?
check "saved broken codex, echoed by the shell: the install goes on" test "$status" -eq 0
check "saved broken codex, echoed by the shell: not refused as chosen" sh -c '! printf "%s" "$1" | grep -q "cannot be used"' _ "$out"

# An existing cockpit checkout that is behind: the newest setup.sh AND the
# newest update.sh run on it (a fix to update.sh takes effect on this run,
# not the next one). MacBook Air, 2026-10-02.
REMOTE_B="$WORK/behind.git"
git clone --quiet --bare "$WORK/orrery.git" "$REMOTE_B"
SEED_B="$WORK/behind-seed"
git clone --quiet --branch "$BRANCH" "file://$REMOTE_B" "$SEED_B"
cat >"$SEED_B/scripts/start-cockpit.sh" <<'EOF'
#!/bin/sh
case "${1:-}" in --check) exit 0 ;; esac
exit 0
EOF
git -C "$SEED_B" -c user.name=t -c user.email=t@t commit --quiet -am "stub start-cockpit"
git -C "$SEED_B" push --quiet origin "HEAD:$BRANCH"
H="$(fresh_home behind)"
git clone --quiet --branch "$BRANCH" "file://$REMOTE_B" "$H/orrery"
setup_in "$H" ORRERY_REPO_URL="file://$REMOTE_B" bash "$H/orrery/scripts/setup.sh" --yes --no-start >/dev/null 2>&1   # a first install
# A newer update.sh appears on the remote; the checkout is now one behind.
sed -i.bak 's/^set -eu$/set -eu\necho "NEWEST-UPDATE-SH ran"/' "$SEED_B/scripts/update.sh" && rm -f "$SEED_B/scripts/update.sh.bak"
git -C "$SEED_B" -c user.name=t -c user.email=t@t commit --quiet -am "a newer update.sh"
git -C "$SEED_B" push --quiet origin "HEAD:$BRANCH"
out="$(run_in "$H" ORRERY_REPO_URL="file://$REMOTE_B" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" bash "$ROOT/scripts/get.sh" --yes --no-start 2>&1)"; status=$?
log="$(ls -d "$H"/.orrery-install/runs/*/ | tail -n 1)log"
check "behind: the run succeeds" test "$status" -eq 0
check "behind: the newest update.sh ran (not the checkout's old one)" grep -q "NEWEST-UPDATE-SH ran" "$log"
check "behind: the checkout is at the newest commit afterwards" \
  test "$(git -C "$H/orrery" rev-parse HEAD)" = "$(git -C "$SEED_B" rev-parse HEAD)"
check "behind: says it uses the newest setup" sh -c 'printf "%s" "$1" | grep -q "setup: from"' _ "$out"
check "behind: the log says which setup and update.sh ran" sh -c 'grep -q "setup: .*(the newest, taken from the remote by get.sh)" "$1" && grep -q "^update.sh: .*(on $2)" "$1"' _ "$log" "$H/orrery"
# A cached, older get.sh hands over to the newer get.sh of the fetched commit.
sed -i.bak 's/^  get_version=[0-9]*/  get_version=99\n  echo "NEWEST-GET-SH ran with: $*"/' "$SEED_B/scripts/get.sh" && rm -f "$SEED_B/scripts/get.sh.bak"
git -C "$SEED_B" -c user.name=t -c user.email=t@t commit --quiet -am "a newer get.sh"
git -C "$SEED_B" push --quiet origin "HEAD:$BRANCH"
out="$(run_in "$H" ORRERY_REPO_URL="file://$REMOTE_B" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" bash "$ROOT/scripts/get.sh" --check 2>&1)"
check "older get.sh: runs the newer one, with the same options" sh -c 'printf "%s" "$1" | grep -q "NEWEST-GET-SH ran with: --check"' _ "$out"
# Uncommitted changes in that checkout: the newest update.sh stops, nothing moves.
git -C "$SEED_B" -c user.name=t -c user.email=t@t commit --quiet --allow-empty -m "newer again"
git -C "$SEED_B" push --quiet origin "HEAD:$BRANCH"
echo "# local edit" >>"$H/orrery/README.md"
before="$(git -C "$H/orrery" rev-parse HEAD)"
out="$(run_in "$H" ORRERY_REPO_URL="file://$REMOTE_B" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" bash "$ROOT/scripts/get.sh" --yes --no-start 2>&1)"; status=$?
check "behind + uncommitted: stops" test "$status" -ne 0
check "behind + uncommitted: the checkout did not move" test "$(git -C "$H/orrery" rev-parse HEAD)" = "$before"
check "behind + uncommitted: the local edit is still there" grep -q "# local edit" "$H/orrery/README.md"

# ORRERY Mail at the end: what the installer and doctor say is relayed as is
# (their wording is the one source); setup adds only its own update line.
mail_run() { # $1 = name; rest = env assignments
  name="$1"; shift
  H="$(fresh_home "mail-$name")"
  stub_cockpit "$H"
  setup_in "$H" "$@" bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1
}
out="$(mail_run advice STUB_MAIL_HELP=1 STUB_MAIL_RESULT=kept STUB_MAIL_ADVICE=1)"
check "mail advice: the installer's notice is shown" sh -c 'printf "%s" "$1" | grep -q "ORRERY Mail is out of date (running aaaaaaa"' _ "$out"
check "mail advice: risk and reconnect lines as the installer wrote them" sh -c 'printf "%s" "$1" | grep -q "STUB-RISK-LINE" && printf "%s" "$1" | grep -q "Reconnect (not Authenticate)"' _ "$out"
check "mail advice: setup's own update line" sh -c 'printf "%s" "$1" | grep -q -- "bash -s -- --mail update"' _ "$out"
check "mail advice: the result line is read" sh -c 'printf "%s" "$1" | grep -q "Mail: kept"' _ "$out"
check "mail advice: still ready (an older Mail is a note, not a failure)" sh -c 'printf "%s" "$1" | grep -q "is ready"' _ "$out"
out="$(mail_run current STUB_MAIL_HELP=1 STUB_MAIL_RESULT=unchanged)"
check "mail current: no update notice" sh -c '! printf "%s" "$1" | grep -q -- "--mail update"' _ "$out"
out="$(mail_run noline STUB_MAIL_HELP=1)"
check "mail result missing from a new installer: not ready" sh -c '! printf "%s" "$1" | grep -q "is ready"' _ "$out"
check "mail result missing from a new installer: says so" sh -c 'printf "%s" "$1" | grep -q "did not report what it did with ORRERY Mail"' _ "$out"
out="$(mail_run old)"
check "mail result from an older installer: no line needed" sh -c 'printf "%s" "$1" | grep -q "is ready"' _ "$out"
out="$(mail_run switched STUB_MAIL_HELP=1 STUB_MAIL_RESULT=switched)"
check "mail switched: the reconnect check is shown as the installer wrote it" sh -c 'printf "%s" "$1" | grep -q "ORRERY Mail was unavailable for 3s" && printf "%s" "$1" | grep -q STUB-RECONNECT-LINE' _ "$out"
out="$(mail_run doctor STUB_DOCTOR=mailmissing)"
check "mail missing (doctor): the doctor's block is shown" sh -c 'printf "%s" "$1" | grep -q "lacks register_agent.existing_agent_id" && printf "%s" "$1" | grep -q "To update: ./scripts/install.sh --mail update"' _ "$out"
check "mail missing (doctor): setup's own update line" sh -c 'printf "%s" "$1" | grep -q -- "bash -s -- --mail update"' _ "$out"
check "mail missing (doctor): still ready" sh -c 'printf "%s" "$1" | grep -q "is ready"' _ "$out"
out="$(mail_run newer STUB_DOCTOR=mailnewer)"
check "mail missing but not older: the doctor's block is shown" sh -c 'printf "%s" "$1" | grep -q "at least as new as the running build"' _ "$out"
check "mail missing but not older: no --mail update from setup" sh -c '! printf "%s" "$1" | grep -q -- "--mail update"' _ "$out"
# On update, the choice reaches the installer explicitly (keep by default),
# even through an update.sh without --mail.
H="$(fresh_home mail-keep-explicit)"
stub_cockpit "$H"
setup_in "$H" bash "$H/orrery/scripts/setup.sh" --yes --no-start >/dev/null 2>&1
setup_in "$H" bash "$H/orrery/scripts/setup.sh" --yes --no-start >/dev/null 2>&1
check "mail on update: keep reaches the installer explicitly" grep -q "env=keep" "$H/install-args"

# Installer warnings a first user meets get a plain explanation.
out="$(mail_run warnings STUB_WARN=1)"
check "skill kept: explained" sh -c 'printf "%s" "$1" | grep -q "is kept and used instead of ORRERY"' _ "$out"
check "fswatch: a harmless note, not a WARN" sh -c 'printf "%s" "$1" | grep -q "note  install: fswatch" && ! printf "%s" "$1" | grep -q "WARN  install: optional dependency"' _ "$out"
check "warnings: still ready" sh -c 'printf "%s" "$1" | grep -q "is ready"' _ "$out"

# An unfinished Mail copy: never a command that deletes anything.
H="$(fresh_home mail-incomplete)"
stub_cockpit "$H"
out="$(setup_in "$H" STUB_INSTALL_ERROR="ORRERY Mail candidate venv exists but is incomplete: $H/.agentstack/mail-service/candidates/abc/venv" \
  bash "$H/orrery/scripts/setup.sh" --yes --no-start 2>&1)"; status=$?
check "mail incomplete: stops" test "$status" -ne 0
check "mail incomplete: no rm in the advice" sh -c '! printf "%s" "$1" | grep -q "rm -rf"' _ "$out"
check "mail incomplete: does not claim nothing runs from it" sh -c '! printf "%s" "$1" | grep -qi "nothing runs from it"' _ "$out"
check "mail incomplete: explains it" sh -c 'printf "%s" "$1" | grep -q "unfinished copy of ORRERY Mail"' _ "$out"

# --dry-run changes nothing, also through the installer's own Codex probe.
H="$(fresh_home dryrun)"
stub_cockpit "$H"
mkdir -p "$WORK/stubbin"
printf '#!/bin/sh\nmkdir -p "${CODEX_HOME:-$HOME/.codex}/tmp"\necho "codex-cli 0.0.0"\n' >"$WORK/stubbin/codex"
chmod +x "$WORK/stubbin/codex"
before="$(cd "$H" && find . -not -path './orrery/*' -not -path './tmp*' | sort)"
out="$(PATH="$WORK/stubbin:$PATH" setup_in "$H" bash "$H/orrery/scripts/setup.sh" --dry-run 2>&1)"; status=$?
after="$(cd "$H" && find . -not -path './orrery/*' -not -path './tmp*' | sort)"
check "dry-run: exits 0" test "$status" -eq 0
check "dry-run: HOME unchanged (installer's Codex probe isolated)" test "$before" = "$after"
check "dry-run: shows the installer's preview" sh -c 'printf "%s" "$1" | grep -q "safe-merge dry-run"' _ "$out"
out="$(PATH="$WORK/stubbin:$PATH" setup_in "$H" STUB_PREVIEW_EXIT=1 bash "$H/orrery/scripts/setup.sh" --dry-run 2>&1)"; status=$?
check "dry-run: a failed preview fails" test "$status" -ne 0
check "dry-run: says the preview failed" sh -c 'printf "%s" "$1" | grep -q "preview failed"' _ "$out"

# ... also when the Codex binary is given by absolute path, explicitly or as
# saved in env.sh (the installer probes that path directly, not PATH).
mkdir -p "$WORK/abscodex"
cp "$WORK/stubbin/codex" "$WORK/abscodex/codex-abs"
H="$(fresh_home dryrun-explicit)"
stub_cockpit "$H"
before="$(cd "$H" && find . -not -path './orrery/*' -not -path './tmp*' | sort)"
out="$(setup_in "$H" AGENTSTACK_CODEX_BIN="$WORK/abscodex/codex-abs" bash "$H/orrery/scripts/setup.sh" --dry-run 2>&1)"; status=$?
after="$(cd "$H" && find . -not -path './orrery/*' -not -path './tmp*' | sort)"
check "dry-run, explicit AGENTSTACK_CODEX_BIN: exits 0" test "$status" -eq 0
check "dry-run, explicit AGENTSTACK_CODEX_BIN: HOME unchanged" test "$before" = "$after"
H="$(fresh_home dryrun-saved)"
stub_cockpit "$H"
mkdir -p "$H/.agentstack"
printf 'export AGENTSTACK_CODEX_BIN=%s\nexport AGENTSTACK_PROJECT_KEY=%s\n' "$WORK/abscodex/codex-abs" "$H/orrery-work" >"$H/.agentstack/env.sh"
before="$(cd "$H" && find . -not -path './orrery/*' -not -path './tmp*' | sort)"
out="$(setup_in "$H" bash "$H/orrery/scripts/setup.sh" --dry-run 2>&1)"; status=$?
after="$(cd "$H" && find . -not -path './orrery/*' -not -path './tmp*' | sort)"
check "dry-run, AGENTSTACK_CODEX_BIN saved in env.sh: exits 0" test "$status" -eq 0
check "dry-run, AGENTSTACK_CODEX_BIN saved in env.sh: HOME unchanged" test "$before" = "$after"

# What get.sh already did is reported when the setup then stops before yes.
H="$(fresh_home bootstrap-note)"
out="$(run_in "$H" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" bash "$ROOT/scripts/get.sh" </dev/null 2>&1)"; status=$?
check "bootstrap: stops without a terminal" test "$status" -ne 0
check "bootstrap: says what get.sh left" sh -c 'printf "%s" "$1" | grep -q "get.sh downloaded the cockpit to"' _ "$out"
check "bootstrap: and that it stays" test -d "$H/orrery"

printf '\n%s\n' "$([ "$failures" -eq 0 ] && echo "all passed" || echo "${failures} failed")"
[ "$failures" -eq 0 ]
