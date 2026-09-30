#!/usr/bin/env bash
# Update orrery-telemetry and this ORRERY cockpit with one command.
#
# Order: check both checkouts first (nothing changes if either is not ready),
# then orrery-telemetry (git pull --ff-only, ./scripts/install.sh, and the
# Codex plugin refresh when that integration is installed), then this
# checkout (git pull --ff-only). The cockpit is never updated when the
# orrery-telemetry step fails, since the cockpit is built for the newer one.
#
# Works on macOS (including /bin/bash 3.2) and on Linux inside WSL2.
# It does not reinstall Python packages: scripts/start-cockpit.sh does that
# when bridge/requirements.txt has changed.
set -eu

SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
COCKPIT_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
AGENTSTACK_DIR="${AGENTSTACK_HOME:-${HOME}/.agentstack}"
INSTALL_STATE="${AGENTSTACK_DIR}/install-state.json"
CODEX_INTEGRATION_DIR="${AGENTSTACK_DIR}/integrations/codex_app"

dry_run=false

usage() {
  cat <<'EOF'
Usage: scripts/update.sh [--dry-run] [-h|--help]

Update orrery-telemetry and this ORRERY cockpit to the latest version:
  1. orrery-telemetry: git pull --ff-only, then ./scripts/install.sh
     (and the Codex plugin refresh, if the Codex app integration is installed)
  2. this cockpit: git pull --ff-only
Nothing is changed when either checkout has uncommitted changes, cannot be
fast-forwarded, or its remote cannot be reached.

Options:
  --dry-run  Show what would be done; change nothing (not even git fetch).
  -h, --help Show this help text.

orrery-telemetry is found through its install record,
$AGENTSTACK_HOME/install-state.json (default ~/.agentstack).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=true ;;
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
# Stop with a reason; each further argument is one more line.
fail() {
  printf '\n  NG    %s\n' "$1"
  shift
  for line in "$@"; do
    printf '        %s\n' "$line"
  done
  exit 1
}
# Show a command, then run it unless this is a dry run.
run() {
  printf '  run   %s\n' "$*"
  [ "$dry_run" = true ] || "$@"
}

python_bin="$(command -v python3 2>/dev/null || true)"
[ -n "$python_bin" ] || fail "python3 is not on PATH (needed to read the orrery-telemetry install record)."

if [ "$dry_run" = true ]; then
  say "ORRERY update (dry run: nothing will be changed)"
else
  say "ORRERY update"
fi

# ---------------------------------------------------------------- where
[ -r "$INSTALL_STATE" ] || fail "orrery-telemetry is not installed (no ${INSTALL_STATE})." \
  "Install it first: docs/install.md, step 0, links to its install guide."
telemetry_root="$("$python_bin" - "$INSTALL_STATE" <<'PY' 2>/dev/null || true
import json, sys
try:
    value = json.load(open(sys.argv[1], encoding="utf-8")).get("repo_root", "")
except Exception:
    value = ""
print(value if isinstance(value, str) else "")
PY
)"
[ -n "$telemetry_root" ] || fail "${INSTALL_STATE} does not say where orrery-telemetry was installed from." \
  "Run ./scripts/install.sh once in your orrery-telemetry checkout, then run this again."
# Ask git, so a linked worktree (whose .git is a file) counts as a checkout.
telemetry_top="$(git -C "$telemetry_root" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$telemetry_top" ] || [ ! -x "${telemetry_root}/scripts/install.sh" ] \
  || [ "$(cd "$telemetry_top" && pwd -P)" != "$(cd "$telemetry_root" && pwd -P)" ]; then
  fail "orrery-telemetry was installed from ${telemetry_root}, which is no longer an orrery-telemetry checkout." \
    "Run ./scripts/install.sh once in your orrery-telemetry checkout, then run this again."
fi
ok "orrery-telemetry: ${telemetry_root}"
ok "cockpit:          ${COCKPIT_ROOT}"

# ---------------------------------------------------------------- ready?
# Both checkouts are checked before either is changed, so a problem in the
# cockpit never leaves orrery-telemetry updated alone.
check_clean() { # $1 = label, $2 = checkout
  changed="$(git -C "$2" status --porcelain --untracked-files=no)"
  [ -z "$changed" ] && return 0
  printf '\n  NG    %s has uncommitted changes; nothing was updated.\n' "$1"
  printf '        In %s:\n' "$2"
  printf '%s\n' "$changed" | sed 's/^/          /'
  printf '        Commit or discard them, then run this again.\n'
  exit 1
}
check_upstream() { # $1 = label, $2 = checkout
  git -C "$2" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1 \
    || fail "$1 (${2}) is on a branch with nothing to pull from; nothing was updated." \
      "Switch it back to the branch you cloned (e.g. git -C \"$2\" switch master), then run this again."
}
check_clean orrery-telemetry "$telemetry_root"
check_clean cockpit "$COCKPIT_ROOT"
check_upstream orrery-telemetry "$telemetry_root"
check_upstream cockpit "$COCKPIT_ROOT"

# What the remote has, without changing anything in a dry run.
remote_head() { # $1 = checkout; prints the remote's commit for the upstream branch
  upstream="$(git -C "$1" rev-parse --abbrev-ref --symbolic-full-name '@{u}')"
  remote="${upstream%%/*}"
  branch="${upstream#*/}"
  git -C "$1" ls-remote --exit-code "$remote" "refs/heads/${branch}" 2>/dev/null | cut -f1
}
fetch() { # $1 = label, $2 = checkout
  if [ "$dry_run" = true ]; then
    head="$(remote_head "$2")" || head=""
    [ -n "$head" ] || fail "could not reach the remote of $1 (${2}); nothing was updated." \
      "Check the network connection, then run this again."
    if [ "$head" = "$(git -C "$2" rev-parse HEAD)" ]; then
      ok "$1 is up to date"
    else
      note "$1 has new commits on its remote (the dry run does not fetch them, so whether they"
      note "      apply cleanly is checked only by the real run, before anything is changed)"
    fi
    return 0
  fi
  git -C "$2" fetch --quiet 2>/dev/null \
    || fail "could not reach the remote of $1 (${2}); nothing was updated." \
      "Check the network connection, then run this again."
  if ! git -C "$2" merge-base --is-ancestor HEAD '@{u}'; then
    fail "$1 (${2}) has commits of its own that are not on its remote, so it cannot be fast-forwarded; nothing was updated." \
      "Look at them with: git -C \"$2\" log @{u}..HEAD"
  fi
  # Untracked files that an incoming commit would overwrite stop the pull, so
  # find them now, before either checkout changes.
  # Paths come NUL-separated and unquoted (a name like 日本語.md is not
  # rewritten), and an untracked file in the place of an incoming file's
  # folder, or an untracked folder in the place of an incoming file, counts.
  blocking="$("$python_bin" - "$2" <<'PY'
import subprocess, sys
repo = sys.argv[1]
def paths(*args):
    out = subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True).stdout
    return [p.decode("utf-8", "surrogateescape") for p in out.split(b"\0") if p]
incoming = paths("diff", "--name-only", "-z", "--no-renames", "--diff-filter=AM", "HEAD", "@{u}")
untracked = set(paths("ls-files", "--others", "--exclude-standard", "-z"))
blocked = set()
for path in incoming:
    parts = path.split("/")
    parents = {"/".join(parts[:i]) for i in range(1, len(parts))}
    blocked |= (untracked & ({path} | parents)) | {u for u in untracked if u.startswith(path + "/")}
print("\n".join(sorted(blocked)))
PY
)" || fail "could not compare $1 (${2}) with its remote; nothing was updated."
  if [ -n "$blocking" ]; then
    printf '\n  NG    %s has untracked files that the update would overwrite; nothing was updated.\n' "$1"
    printf '        In %s:\n' "$2"
    printf '%s\n' "$blocking" | sed 's/^/          /'
    printf '        Move or rename them, then run this again.\n'
    exit 1
  fi
  behind="$(git -C "$2" rev-list --count 'HEAD..@{u}')"
  if [ "$behind" = 0 ]; then
    ok "$1 is up to date"
  else
    note "$1: ${behind} new commit(s)"
  fi
}
fetch orrery-telemetry "$telemetry_root"
fetch cockpit "$COCKPIT_ROOT"

# ---------------------------------------------------------------- orrery-telemetry
say ""
say "Updating orrery-telemetry ..."
run git -C "$telemetry_root" pull --ff-only --quiet \
  || fail "git pull of orrery-telemetry failed (see above); nothing else was changed."
# install.sh keeps the previous settings (project key, ports, Mail) and
# replaces the running dashboard with the new one.
# install.sh reads some saved settings back from env.sh by itself (project
# key, launch presets, Codex policy, ...) but takes others only from the
# environment (dashboard port, service label prefix, terminal, Mail URL,
# PATH, Python, Mail DB and env, language, ...). A fresh terminal does not
# have env.sh loaded, so load it here; values already set in this
# environment win, as they would for install.sh itself.
telemetry_install() {
  (
    cd "$telemetry_root"
    if [ -r "${AGENTSTACK_DIR}/env.sh" ]; then
      explicit=""
      for name in $(compgen -e); do
        case "$name" in
          AGENTSTACK_*) explicit="${explicit} ${name}"; eval "saved_${name}=\"\${${name}}\"" ;;
        esac
      done
      # shellcheck disable=SC1090
      . "${AGENTSTACK_DIR}/env.sh"
      for name in $explicit; do
        eval "export ${name}=\"\${saved_${name}}\""
      done
    fi
    exec ./scripts/install.sh
  )
}
printf '  run   cd %s && ./scripts/install.sh   (with the saved settings in %s/env.sh)\n' \
  "$telemetry_root" "$AGENTSTACK_DIR"
if [ "$dry_run" != true ] && ! telemetry_install; then
  fail "orrery-telemetry's install.sh failed (see its output above); the cockpit was not updated." \
    "Fix what it reports, then run this again."
fi
plugin_status=0
# The core installer also puts the child MCP proxy under integrations/codex_app,
# so the folder alone does not mean the optional Codex plugin is there. Its own
# installer records the plugin in install-state.json in that folder.
codex_plugin_enabled() {
  "$python_bin" - "${CODEX_INTEGRATION_DIR}/install-state.json" <<'PY' 2>/dev/null
import json, sys
try:
    state = json.load(open(sys.argv[1], encoding="utf-8"))
except Exception:
    sys.exit(1)
plugin = state.get("plugin") if isinstance(state, dict) else None
sys.exit(0 if state.get("tool") == "agentstack-codex-app"
         and isinstance(plugin, dict) and plugin.get("enabled") is True else 1)
PY
}
if codex_plugin_enabled; then
  # Skips by itself, with a reason, when the plugin is not installed and enabled.
  run env CODEX_HOME="${CODEX_HOME:-${HOME}/.codex}" \
    "${telemetry_root}/scripts/install-codex-app-integration.sh" \
    --refresh-plugin-only --install-dir "$CODEX_INTEGRATION_DIR" || plugin_status=$?
fi

# ---------------------------------------------------------------- cockpit
say ""
say "Updating the cockpit ..."
run git -C "$COCKPIT_ROOT" pull --ff-only --quiet \
  || fail "git pull of the cockpit failed (see above); orrery-telemetry was updated." \
    "Fix what git reports, then run this again."

# ---------------------------------------------------------------- summary
[ "$dry_run" = true ] && { say ""; say "Dry run finished: nothing was changed."; exit 0; }

# The dashboard port, as start-cockpit.sh finds it.
dashboard_port="$( [ -r "${AGENTSTACK_DIR}/env.sh" ] && (. "${AGENTSTACK_DIR}/env.sh" >/dev/null 2>&1; printf '%s' "${AGENTSTACK_PORT:-}") || true)"
dashboard_url="${ORRERY_DASHBOARD_URL:-http://127.0.0.1:${dashboard_port:-8770}}"
dashboard_url="${dashboard_url%/}"
# The installer restarts the dashboard; give it a few seconds to answer.
answer="$("$python_bin" - "${dashboard_url}/api/version" <<'PY' 2>/dev/null || true
import json, sys, time, urllib.request
for _ in range(10):
    try:
        with urllib.request.urlopen(sys.argv[1], timeout=2) as response:
            data = json.loads(response.read(1 << 16))
        print("%s (API %s)" % (data.get("version", "?"), data.get("api", "?")))
        break
    except Exception:
        time.sleep(1)
PY
)"

say ""
say "=============================================================="
say "  Updated."
say "  orrery-telemetry: ${answer:-dashboard not answering at ${dashboard_url} yet}"
say "  cockpit:          $(git -C "$COCKPIT_ROOT" log -1 --format='%h %s')"
say ""
say "  The installer has restarted the dashboard. If it is not"
say "  answering, check it with ${AGENTSTACK_DIR}/bin/agentstack-doctor"
say "  and start it with ${AGENTSTACK_DIR}/dashboard/agentctl.sh start."
say "  Restart the cockpit: press Ctrl-C in its window, then run"
say "  ./scripts/start-cockpit.sh again."
say "=============================================================="
if [ "$plugin_status" -ne 0 ]; then
  say ""
  say "  NG    The Codex plugin refresh failed (see its output above);"
  say "        everything else was updated. See orrery-telemetry's docs/codex-app.md."
  exit 1
fi
