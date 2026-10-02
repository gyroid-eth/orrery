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
WORK="$(mktemp -d "${TMPDIR:-/tmp}/orrery-install-test.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
failures=0
pass() { printf 'ok    %s\n' "$1"; }
fail() { printf 'FAIL  %s\n' "$1"; failures=$((failures + 1)); }
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
    ORRERY_NO_OPEN=1 PORT=18999 AGENTSTACK_PORT=18998 "$@"
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
git clone --quiet --branch "$BRANCH" "$COCKPIT_URL" "$H/orrery"
git init --quiet "$WORK/fake-telemetry"
mkdir -p "$WORK/fake-telemetry/scripts" && printf '#!/bin/sh\nexit 0\n' >"$WORK/fake-telemetry/scripts/install.sh"
chmod +x "$WORK/fake-telemetry/scripts/install.sh"
git -C "$WORK/fake-telemetry" add -A && git -C "$WORK/fake-telemetry" -c user.name=t -c user.email=t@t commit --quiet -m t
git clone --quiet "file://$WORK/fake-telemetry" "$H/orrery-telemetry"
mkdir -p "$H/.agentstack"
printf '{\n  "repo_root": "%s",\n  "tool": "x"\n}\n' "$H/orrery-telemetry" >"$H/.agentstack/install-state.json"
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
if [ "${1:-}" = "--dry-run" ] || [ "${2:-}" = "--dry-run" ]; then
  codex --version >/dev/null 2>&1 || true   # as the real installer probes Codex
  echo "Tier1 settings safe-merge dry-run: (stub)"
  exit "${STUB_PREVIEW_EXIT:-0}"
fi
if [ -n "${STUB_INSTALL_ERROR:-}" ]; then echo "error: ${STUB_INSTALL_ERROR}" >&2; exit 1; fi
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
esac
DOC
printf '#!/bin/sh\necho "self-test passed"\n' >"$dir/bin/agentstack-selftest"
chmod +x "$dir/bin/agentstack-doctor" "$dir/bin/agentstack-selftest"
echo "installer will provision ORRERY Mail at stub"
echo "assume-yes: registered orrery-mail in $HOME/.claude.json"
echo "assume-yes: applied Tier1 settings merge to $HOME/.claude/settings.json"
echo "assume-yes: applied Codex AGENTS.md managed setup"
echo "assume-yes: applied Claude CLAUDE.md managed setup"
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
echo "stub start-cockpit $*"
exit 0
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
out="$(pty_run env -i PATH="$PATH" HOME="$H" TMPDIR="$H/tmp" TERM=dumb ORRERY_RETRY_SLEEP=0 ORRERY_NO_OPEN=1 PORT=18999 AGENTSTACK_PORT=18998 \
  ORRERY_DIR="$H/orrery" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" STUB_UPDATE_EXIT=1 bash "$H/orrery/scripts/setup.sh" 2>&1 | tr -d '\r')"
check "update-failed: offered to start what is there" sh -c 'printf "%s" "$1" | grep -q "Start the cockpit with the versions you have now"' _ "$out"
check "update-failed: not ready" sh -c '! printf "%s" "$1" | grep -q "is ready"' _ "$out"
check "update-failed: says the update did not finish" sh -c 'printf "%s" "$1" | grep -q "update did not finish"' _ "$out"
check "update-failed: first record kept" test -s "$H/.orrery-install/baseline"

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

# What get.sh already did is reported when the setup then stops before yes.
H="$(fresh_home bootstrap-note)"
out="$(run_in "$H" ORRERY_REPO_URL="$COCKPIT_URL" ORRERY_REF="$BRANCH" ORRERY_TELEMETRY_URL="$STUBTEL_URL" \
  AGENTSTACK_PYTHON="$(command -v python3)" bash "$ROOT/scripts/get.sh" </dev/null 2>&1)"; status=$?
check "bootstrap: stops without a terminal" test "$status" -ne 0
check "bootstrap: says what get.sh left" sh -c 'printf "%s" "$1" | grep -q "get.sh downloaded the cockpit to"' _ "$out"
check "bootstrap: and that it stays" test -d "$H/orrery"

printf '\n%s\n' "$([ "$failures" -eq 0 ] && echo "all passed" || echo "${failures} failed")"
[ "$failures" -eq 0 ]
