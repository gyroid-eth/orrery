#!/usr/bin/env bash
# Install or update ORRERY (orrery-telemetry + the cockpit) with one line:
#
#   curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/get.sh | bash
#
# This file only gets the cockpit checkout and hands over to scripts/setup.sh,
# which decides everything else (see that file).
#   - It writes nothing but a new cockpit checkout (~/orrery by default); an
#     existing checkout is never changed here.
#   - It only trusts github.com/gyroid-eth/orrery (exact URL match).
#   - With --check or --dry-run it changes nothing at all: what it needs is
#     cloned into a temporary folder that is removed afterwards.
#
# Everything is inside main(), so a download cut off halfway runs nothing.
# Works on macOS (including /bin/bash 3.2) and on Linux inside WSL2.

main() {
  set -eu

  # The setup.sh contract this get.sh needs. A checkout whose setup.sh is
  # older (or missing) is set up with the remote's setup.sh instead.
  required_contract=1
  ref="${ORRERY_REF:-master}"
  default_dir="${HOME}/orrery"
  override_url="${ORRERY_REPO_URL:-}"
  repo_url="${override_url:-https://github.com/gyroid-eth/orrery.git}"

  say() { printf '%s\n' "$*"; }
  stop() {
    printf '\n  NG    %s\n' "$1"
    shift
    for line in "$@"; do printf '        %s\n' "$line"; done
    exit 1
  }

  read_only=false
  for arg in "$@"; do
    case "$arg" in
      --check | --dry-run) read_only=true ;;
    esac
  done

  say "ORRERY one-command install"
  [ -z "$override_url" ] || say "  note  test override: ORRERY_REPO_URL=${override_url}"

  # ------------------------------------------------------------ where am I
  case "$(uname -s)" in
    Darwin) os=mac ;;
    Linux)
      os=linux
      if [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/version 2>/dev/null; then
        os=wsl
      fi
      ;;
    MINGW* | MSYS* | CYGWIN*)
      stop "This is Windows (Git Bash / MSYS), not WSL2." \
        "Open the Ubuntu app (WSL2) and run the same line there." ;;
    *) stop "Unsupported OS: $(uname -s). ORRERY runs on macOS and on Linux / WSL2." ;;
  esac
  if [ "$(id -u)" = 0 ]; then
    stop "Do not run this as root or with sudo." \
      "Run it as yourself; it only writes into your home folder."
  fi
  if ! command -v git >/dev/null 2>&1; then
    case "$os" in
      mac) stop "git is not installed." "Fix: xcode-select --install   (or: brew install git), then run this again." ;;
      *) stop "git is not installed." "Fix: sudo apt update && sudo apt install -y git, then run this again." ;;
    esac
  fi

  # ------------------------------------------------------------ trust
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

  # A folder counts as an ORRERY checkout when it is the top of a git
  # checkout that has the cockpit's start script. Whether its origin is
  # trusted is checked separately, so a fork is reported, not skipped.
  is_checkout() { # $1 = folder
    [ -x "$1/scripts/start-cockpit.sh" ] || return 1
    top="$(git -C "$1" rev-parse --show-toplevel 2>/dev/null || true)"
    [ -n "$top" ] && [ "$(cd "$top" && pwd -P)" = "$(cd "$1" && pwd -P)" ]
  }
  origin_of() { git -C "$1" remote get-url origin 2>/dev/null || true; }

  # ------------------------------------------------------------ the cockpit checkout
  cockpit=""
  target=""
  if [ -n "${ORRERY_DIR:-}" ]; then
    if is_checkout "$ORRERY_DIR"; then
      cockpit="$(cd "$ORRERY_DIR" && pwd)"
    elif [ -e "$ORRERY_DIR" ]; then
      stop "ORRERY_DIR=${ORRERY_DIR} exists but is not an ORRERY checkout; nothing was changed." \
        "Point ORRERY_DIR at your ORRERY checkout, or at a folder that does not exist yet."
    else
      target="$ORRERY_DIR"
    fi
  else
    if is_checkout "$default_dir"; then
      cockpit="$default_dir"
    else
      # Next to the orrery-telemetry checkout this machine installed from.
      state="${AGENTSTACK_HOME:-${HOME}/.agentstack}/install-state.json"
      if [ -r "$state" ]; then
        tel_root="$(sed -n 's/^ *"repo_root": *"\(.*\)",*$/\1/p' "$state" | head -n 1)"
        if [ -n "$tel_root" ]; then
          for candidate in "$(dirname "$tel_root")/orrery" "$(dirname "$tel_root")/orrery-public"; do
            if is_checkout "$candidate" && official_remote "$(origin_of "$candidate")" orrery "$override_url"; then
              cockpit="$candidate"
              break
            fi
          done
        fi
      fi
      if [ -z "$cockpit" ]; then
        [ -e "$default_dir" ] && stop "${default_dir} already exists but is not an ORRERY checkout; nothing was changed." \
          "Move it away, or choose another folder: ORRERY_DIR=/path/to/new/folder"
        target="$default_dir"
      fi
    fi
  fi

  if [ -n "$cockpit" ]; then
    origin="$(origin_of "$cockpit")"
    official_remote "$origin" orrery "$override_url" \
      || stop "The ORRERY checkout ${cockpit} has origin '${origin:-none}'." \
        "That is not the official repository (https://github.com/gyroid-eth/orrery), so this" \
        "script does not fetch from it, run anything from it, or change it." \
        "Use another folder for the official one:  ORRERY_DIR=/path/to/new/folder"
  fi

  if [ "$os" = wsl ]; then
    case "${cockpit:-$target}" in
      /mnt/[a-z]/* | /mnt/[a-z]) stop "${cockpit:-$target} is on the Windows drive (/mnt/...)." \
        "Use a folder in the Ubuntu home instead, e.g. ORRERY_DIR=~/orrery." ;;
    esac
  fi

  # Clone with up to 3 tries. Shallow, and without docs/images (about 110 MB
  # of screen recordings the cockpit does not need to run); a plain shallow
  # clone if this git cannot do a partial clone.
  clone_cockpit() { # $1 = destination (must not exist)
    tries=0
    while :; do
      tries=$((tries + 1))
      if git clone --quiet --depth 1 --filter=blob:none --no-checkout --branch "$ref" "$repo_url" "$1" 2>/dev/null \
        && git -C "$1" sparse-checkout set --no-cone '/*' '!/docs/images/' 2>/dev/null \
        && git -C "$1" checkout --quiet "$ref" 2>/dev/null; then
        return 0
      fi
      rm -rf "$1"
      if git clone --quiet --depth 1 --branch "$ref" "$repo_url" "$1"; then
        return 0
      fi
      rm -rf "$1"
      [ "$tries" -lt 3 ] || return 1
      say "  note  download failed; trying again in $((tries * ${ORRERY_RETRY_SLEEP:-5})) seconds (${tries}/3)"
      sleep $((tries * ${ORRERY_RETRY_SLEEP:-5}))
    done
  }
  contract_of() { # $1 = setup.sh; prints its contract number (0 if none)
    n="$(sed -n 's/^ORRERY_SETUP_CONTRACT=\([0-9][0-9]*\).*/\1/p' "$1" 2>/dev/null | head -n 1)"
    printf '%s' "${n:-0}"
  }
  describe() { git -C "$1" log -1 --format='%h (%cd)' --date=short 2>/dev/null || printf '?'; }

  tmp_root=""
  cleanup() { [ -z "$tmp_root" ] || rm -rf "$tmp_root"; }
  trap cleanup EXIT

  # ------------------------------------------------------------ read-only runs
  if [ "$read_only" = true ]; then
    tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/orrery-check.XXXXXX")"
    say "  get   ORRERY into a temporary folder (removed afterwards; nothing else is written)"
    clone_cockpit "${tmp_root}/orrery" \
      || stop "Could not download ORRERY from ${repo_url}." "Check the network connection, then run this again."
    say "  ok    got ORRERY $(describe "${tmp_root}/orrery") from ${repo_url}"
    if [ -n "$cockpit" ]; then
      export ORRERY_DIR="$cockpit"
    else
      export ORRERY_DIR=""
      export ORRERY_PLANNED_DIR="$target"
    fi
    export ORRERY_TEMP_SETUP=1
    # Not exec: the temporary folder is removed when setup returns.
    status=0
    if [ -r /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
      "${tmp_root}/orrery/scripts/setup.sh" "$@" </dev/tty || status=$?
    else
      "${tmp_root}/orrery/scripts/setup.sh" "$@" || status=$?
    fi
    exit "$status"
  fi

  # ------------------------------------------------------------ get it
  if [ -n "$cockpit" ]; then
    say "  ok    cockpit: ${cockpit} at $(describe "$cockpit")"
  else
    say "  get   cockpit -> ${target}"
    parent="$(dirname "$target")"
    mkdir -p "$parent"
    tmp_root="$(mktemp -d "${parent}/.orrery-get.XXXXXX")"
    clone_cockpit "${tmp_root}/orrery" \
      || stop "Could not download ORRERY from ${repo_url} (3 tries); nothing was changed." \
        "Check the network connection, then run the same line again."
    # Another run may have created it meanwhile; never move into an existing folder.
    [ ! -e "$target" ] || stop "${target} appeared while downloading (another install running?); nothing was changed."
    mv "${tmp_root}/orrery" "$target"
    cockpit="$target"
    export ORRERY_BOOTSTRAP_DID="downloaded the cockpit to ${target}"
    say "  ok    cockpit: ${cockpit} at $(describe "$cockpit")"
  fi

  # ------------------------------------------------------------ which setup
  # The newest setup.sh and update.sh always run, also on an older checkout:
  # a fix to them then works on this run, not only on the next one. Only
  # .git's remote-tracking data and FETCH_HEAD change here; the checkout's
  # files are updated later by update.sh (which stops, changing nothing, on
  # uncommitted changes or a checkout that cannot be fast-forwarded).
  setup="${cockpit}/scripts/setup.sh"
  local_ok=true
  if [ ! -x "$setup" ] || [ "$(contract_of "$setup")" -lt "$required_contract" ]; then local_ok=false; fi
  if git -C "$cockpit" fetch --quiet origin "$ref" 2>/dev/null; then
    newest="$(git -C "$cockpit" rev-parse FETCH_HEAD)"
    if [ "$local_ok" != true ] || [ "$(git -C "$cockpit" rev-parse HEAD)" != "$newest" ]; then
      [ -n "$tmp_root" ] || tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/orrery-setup.XXXXXX")"
      mkdir -p "${tmp_root}/scripts"
      git -C "$cockpit" show "${newest}:scripts/setup.sh" >"${tmp_root}/scripts/setup.sh" 2>/dev/null \
        || stop "The remote of ${cockpit} has no scripts/setup.sh; nothing was changed."
      git -C "$cockpit" show "${newest}:scripts/update.sh" >"${tmp_root}/scripts/update.sh" 2>/dev/null \
        || stop "The remote of ${cockpit} has no scripts/update.sh; nothing was changed."
      chmod +x "${tmp_root}/scripts/setup.sh" "${tmp_root}/scripts/update.sh"
      setup="${tmp_root}/scripts/setup.sh"
      export ORRERY_BOOTSTRAP_DID="fetched the newest version into ${cockpit}/.git (its files are unchanged)"
      say "  ok    setup: from $(origin_of "$cockpit") at $(git -C "$cockpit" log -1 --format='%h (%cd)' --date=short "$newest")"
      say "        (this checkout, at $(describe "$cockpit"), is older; the newest setup updates it)"
      export ORRERY_TEMP_SETUP=1
    else
      say "  ok    setup: ${setup} (the checkout is at the newest version)"
    fi
  elif [ "$local_ok" = true ]; then
    say "  note  could not reach the remote of ${cockpit}; using its own setup"
  else
    stop "Could not reach the remote of ${cockpit}; nothing was changed." \
      "Check the network connection, then run this again."
  fi
  export ORRERY_DIR="$cockpit"
  say "  ok    got ORRERY; handing over to the setup"

  # Under `curl | bash` this script's stdin is the download itself; give the
  # setup the terminal back so its questions can be answered. Without a
  # terminal (CI) stdin stays as it is and the setup needs --yes.
  # Not exec when the setup lives in the temporary folder, so it is removed.
  if [ -n "$tmp_root" ] && [ "${ORRERY_TEMP_SETUP:-0}" = 1 ]; then
    status=0
    if [ -r /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
      "$setup" "$@" </dev/tty || status=$?
    else
      "$setup" "$@" || status=$?
    fi
    exit "$status"
  fi
  trap - EXIT
  cleanup
  if [ -r /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
    exec "$setup" "$@" </dev/tty
  fi
  exec "$setup" "$@"
}

main "$@"
