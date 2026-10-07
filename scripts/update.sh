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
# The checkout to update: this file's own, unless setup.sh runs a newer copy of
# this file on an older checkout (ORRERY_COCKPIT_ROOT names that checkout).
COCKPIT_ROOT="$(cd -- "${ORRERY_COCKPIT_ROOT:-${SCRIPT_DIR}/..}" && pwd)"
AGENTSTACK_DIR="${AGENTSTACK_HOME:-${HOME}/.agentstack}"
INSTALL_STATE="${AGENTSTACK_DIR}/install-state.json"
CODEX_INTEGRATION_DIR="${AGENTSTACK_DIR}/integrations/codex_app"

dry_run=false
# ORRERY Mail on this update; always passed to install.sh explicitly.
mail_mode=keep

usage() {
  cat <<'EOF'
Usage: scripts/update.sh [--mail auto|update|keep] [--dry-run] [-h|--help]

Update orrery-telemetry and this ORRERY cockpit to the latest version:
  1. orrery-telemetry: git pull --ff-only, then ./scripts/install.sh
     (and the Codex plugin refresh, if the Codex app integration is installed)
  2. this cockpit: git pull --ff-only
Nothing is changed when either checkout has uncommitted changes, cannot be
fast-forwarded, or its remote cannot be reached.

Options:
  --mail auto|update|keep
             ORRERY Mail: keep the running one (default), update it to this
             orrery-telemetry's build, or auto (update when it is safe).
             Passed to install.sh as --mail (older ones: --update-mail, or
             AGENTSTACK_MAIL_UPDATE for keep / auto).
  --dry-run  Show what would be done; change nothing (not even git fetch).
  -h, --help Show this help text.

orrery-telemetry is found through its install record,
$AGENTSTACK_HOME/install-state.json (default ~/.agentstack).
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    --dry-run) dry_run=true ;;
    --mail)
      [ $# -ge 2 ] || { printf 'Missing value for --mail (auto|update|keep)\n' >&2; exit 2; }
      mail_mode="$2"; shift ;;
    --mail=*) mail_mode="${1#*=}" ;;
    -h | --help) usage; exit 0 ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

case "$mail_mode" in
  auto | update | keep) ;;
  *) printf 'Unknown --mail value: %s (auto|update|keep)\n' "$mail_mode" >&2; exit 2 ;;
esac

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
  if [ "$1" = cockpit ]; then
    printf '        Back up or commit your changes, then run this again. Do not reset unsaved work.\n'
  else
    printf '        Commit or discard them, then run this again.\n'
  fi
  exit 1
}
# Read-only recovery advice for the documented origin/master history rewrite.
# Divergence alone is not proof: local commits can produce the same graph.
cockpit_non_ff_help() { # $1 = checkout
  [ "$(git -C "$1" symbolic-ref --quiet --short HEAD 2>/dev/null || true)" = master ] || return 0
  [ "$(git -C "$1" rev-parse --abbrev-ref --symbolic-full-name '@{u}' 2>/dev/null || true)" = origin/master ] || return 0
  ancestry=0
  git -C "$1" merge-base --is-ancestor HEAD origin/master 2>/dev/null || ancestry=$?
  [ "$ancestry" = 1 ] || return 0  # 0 = can fast-forward, >1 = cannot diagnose
  # A checkout only ahead of its remote has local work, not divergent history.
  ancestry=0
  git -C "$1" merge-base --is-ancestor origin/master HEAD 2>/dev/null || ancestry=$?
  [ "$ancestry" = 1 ] || return 0
  changed="$(git -C "$1" status --porcelain --untracked-files=all 2>/dev/null)" || return 0
  if [ -n "$changed" ]; then
    note "cockpit has local changes or untracked files; back up or commit them before retrying."
    note "Do not reset unsaved work."
    return 0
  fi
  note "cockpit's remote history may have been rewritten, or this checkout has local commits."
  note "See https://github.com/gyroid-eth/orrery/issues/20"
  note "Only if you want the upstream version: back up local work first; reset --hard discards local commits and changes."
  note "No reset is performed automatically. Run these yourself after checking:"
  printf -v quoted_cockpit '%q' "$1"
  printf '        git -C %s fetch origin master\n' "$quoted_cockpit"
  printf '        git -C %s reset --hard origin/master\n' "$quoted_cockpit"
}
check_upstream() { # $1 = label, $2 = checkout
  if ! git -C "$2" rev-parse --abbrev-ref --symbolic-full-name '@{u}' >/dev/null 2>&1; then
    printf -v quoted_checkout '%q' "$2"
    fail "$1 (${2}) is on a branch with nothing to pull from; nothing was updated." \
      "Switch it back to the branch you cloned, then run this again. For master:" \
      "git -C $quoted_checkout switch master"
  fi
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
  ancestry=0
  git -C "$2" merge-base --is-ancestor HEAD '@{u}' || ancestry=$?
  if [ "$ancestry" = 1 ]; then
    [ "$1" != cockpit ] || cockpit_non_ff_help "$2"
    printf -v quoted_checkout '%q' "$2"
    fail "$1 (${2}) cannot be fast-forwarded; nothing was updated." \
      "Look at them with: git -C $quoted_checkout log @{u}..HEAD"
  elif [ "$ancestry" != 0 ]; then
    fail "could not compare $1 (${2}) with its remote; nothing was updated."
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

# >>> child-window-setting
# get.sh can run setup.sh/update.sh outside the checkout: keep this small
# policy in both scripts rather than source a file from an older checkout.
# A shell value equal to a recorded value is env.sh's echo, just as in the
# installer merge below. Only the choice record can distinguish its default.
child_window_setting() (
  file="$1"
  saved=""; chosen=""; recorded=false
  if [ -r "$file" ]; then
    saved="$( unset AGENTSTACK_AUTO_OPEN_CHILD AGENTSTACK_CHOSEN_SETTINGS; . "$file" >/dev/null 2>&1; printf '%s' "${AGENTSTACK_AUTO_OPEN_CHILD:-}" )"
    chosen="$( unset AGENTSTACK_AUTO_OPEN_CHILD AGENTSTACK_CHOSEN_SETTINGS; . "$file" >/dev/null 2>&1; printf '%s' "${AGENTSTACK_CHOSEN_SETTINGS:-}" )"
    if grep -q '^export AGENTSTACK_CHOSEN_SETTINGS=' "$file"; then recorded=true; fi
  fi
  if [ "${AGENTSTACK_AUTO_OPEN_CHILD+x}" = x ]; then
    if [ "$recorded" != true ] || [ "${AGENTSTACK_AUTO_OPEN_CHILD}" != "$saved" ]; then
      printf '%s' "${AGENTSTACK_AUTO_OPEN_CHILD:-0}"; return
    fi
  fi
  if [ "${AGENTSTACK_RESET_SETTINGS:-0}" != 1 ]; then
    case " $chosen " in
      *" AGENTSTACK_AUTO_OPEN_CHILD "*) printf '%s' "$saved"; return ;;
    esac
    # Before the choice record, a saved 1 is indistinguishable from a
    # deliberate choice. Preserve it (and any other saved value).
    if [ "$recorded" != true ] && [ -n "$saved" ]; then printf '%s' "$saved"; return; fi
  fi
  printf '0'
)
# <<< child-window-setting

export AGENTSTACK_AUTO_OPEN_CHILD="$(child_window_setting "${AGENTSTACK_DIR}/env.sh")"

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
      for name in $explicit; do unset "$name"; done   # so the next line shows env.sh's own values
      # shellcheck disable=SC1090
      . "${AGENTSTACK_DIR}/env.sh"
      # What install.sh reads back from env.sh by itself (its resolve_setting
      # lines) is left to it: in its environment a value counts as chosen on
      # purpose, so a saved Codex path that no longer runs would be refused
      # instead of looked up again. A value set in this shell is passed on as a
      # choice only when it differs from env.sh's; one equal to it is treated as
      # the saved value (that is the rule, not a proof of where it came from: a
      # login shell that sources env.sh, like ~/.zshenv, puts exactly these here).
      # The names come from install.sh's resolve_setting lines, so a change to
      # that form in install.sh must come with a change here.
      echoed=""
      for name in $(sed -n 's/^resolve_setting [A-Z_]* \(AGENTSTACK_[A-Z_]*\).*/\1/p' ./scripts/install.sh 2>/dev/null); do
        case " $explicit " in
          *" $name "*)
            eval "from_file=\${${name}-__not_in_env_sh__}"
            eval "from_shell=\${saved_${name}}"
            # Keep ambiguous legacy auto-open as a choice: otherwise core
            # writes an empty choice record and flips it on the next update.
            if [ "$from_shell" = "$from_file" ] && {
              [ "$name" != AGENTSTACK_AUTO_OPEN_CHILD ] || grep -q '^export AGENTSTACK_CHOSEN_SETTINGS=' "${AGENTSTACK_DIR}/env.sh";
            }; then echoed="${echoed} ${name}"; fi
            ;;
        esac
        unset "$name"
      done
      for name in $explicit; do
        case " $echoed " in *" $name "*) continue ;; esac
        eval "export ${name}=\"\${saved_${name}}\""
      done
    fi
    # The Mail choice, in the form this install.sh understands.
    # (Read from the file, not by running it.)
    if grep -q -- '--mail auto|update|keep' ./scripts/install.sh 2>/dev/null; then
      exec ./scripts/install.sh --mail "$mail_mode"
    fi
    case "$mail_mode" in
      update) exec ./scripts/install.sh --update-mail ;;
      *) export AGENTSTACK_MAIL_UPDATE="$mail_mode"; exec ./scripts/install.sh ;;
    esac
  )
}
printf '  run   cd %s && ./scripts/install.sh --mail %s   (with the saved settings in %s/env.sh)\n' \
  "$telemetry_root" "$mail_mode" "$AGENTSTACK_DIR"
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
if ! run git -C "$COCKPIT_ROOT" pull --ff-only --quiet; then
  cockpit_non_ff_help "$COCKPIT_ROOT"
  fail "git pull of the cockpit failed (see above); orrery-telemetry was updated." \
    "Fix what git reports, then run this again."
fi

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
