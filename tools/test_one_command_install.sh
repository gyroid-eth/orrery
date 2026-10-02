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

printf '\n%s\n' "$([ "$failures" -eq 0 ] && echo "all passed" || echo "${failures} failed")"
[ "$failures" -eq 0 ]
