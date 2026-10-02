#!/usr/bin/env bash
# The research set for ORRERY, with one line: the digest-paper add-on (a Claude
# or Codex team turns a paper into a reading note) and the demo vault.
#
#   curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/research-set.sh | bash
#   ... | bash -s -- --check              # only look; change nothing
#   ... | bash -s -- --vault-dir DIR      # put the demo vault somewhere else
#
# It needs ORRERY itself first (the one-line install, scripts/get.sh), and does
# three things, each reported at the end:
#   1. digest-paper: cloned to $AGENTSTACK_HOME/addons/digest-paper/src (or
#      updated there) and installed with its own scripts/install.sh, which links
#      it for Claude and Codex and never replaces a skill it did not install.
#   2. The demo vault: a GitHub tarball unpacked to ~/Documents/orrery-demo-vault
#      (on WSL, the Windows Documents folder, since Obsidian runs on Windows). A
#      folder that already exists is never touched, so your notes and the API
#      key you entered stay as they are. It is not a git checkout on purpose.
#   3. What to do next: where to open the vault in Obsidian, how to enter the
#      Mistral key (or go without one), and requests to paste, paths filled in.
# It never reads or writes an API key, never uses sudo and trusts only the
# gyroid-eth repositories on GitHub. Running it again updates the add-on.
#
# Everything is inside main(), so a download cut off halfway runs nothing.
# Works on macOS (including /bin/bash 3.2) and on Linux inside WSL2.

main() {
  set -eu

  override_url="${ORRERY_RESEARCH_ADDON_URL:-}"
  addon_url="${override_url:-https://github.com/gyroid-eth/orrery-digest-paper.git}"
  vault_repo="https://github.com/gyroid-eth/orrery-demo-vault.git"
  # Tests point these at local copies.
  vault_tarball="${ORRERY_RESEARCH_VAULT_TARBALL:-}"
  agentstack="${AGENTSTACK_HOME:-${HOME}/.agentstack}"
  addon="${agentstack}/addons/digest-paper"
  src="${addon}/src"

  say() { printf '%s\n' "$*"; }
  stop() {
    printf '\n  NG    %s\n' "$1"
    shift
    for line in "$@"; do printf '        %s\n' "$line"; done
    exit 1
  }

  read_only=false
  vault_dir=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --check | --dry-run) read_only=true; shift ;;
      --vault-dir)
        [ $# -ge 2 ] || stop "--vault-dir needs a folder."
        vault_dir="$2"; shift 2 ;;
      -h | --help) sed -n '2,26p' "$0" 2>/dev/null || true; exit 0 ;;
      *) stop "Unknown option: $1" "Options: --check, --vault-dir DIR" ;;
    esac
  done

  say "ORRERY research set (digest-paper + demo vault)"
  [ -z "${ORRERY_RESEARCH_ADDON_URL:-}${ORRERY_RESEARCH_VAULT_TARBALL:-}" ] || say "  note  test override in use"
  [ "$read_only" = true ] && say "  note  --check: nothing will be changed"

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
    stop "Do not run this as root or with sudo." "Run it as yourself; it only writes into your home folder."
  fi
  for tool in git python3 curl tar; do
    command -v "$tool" >/dev/null 2>&1 || stop "${tool} is not installed." \
      "It comes with the ORRERY one-line install's requirements; install it and run this again."
  done
  [ -f "${agentstack}/skills/delegate/SKILL.md" ] || stop "ORRERY is not installed here (${agentstack})." \
    "Run the ORRERY one-line install first:" \
    "  curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/get.sh | bash"

  # ------------------------------------------------------------ agents
  # One kind is enough: two agents of it write and check the note.
  have_claude=false
  have_codex=false
  codex_note=""
  command -v claude >/dev/null 2>&1 && have_claude=true
  codex_bin="${AGENTSTACK_CODEX_BIN:-}"
  if [ -z "$codex_bin" ] && [ -f "${agentstack}/env.sh" ]; then
    codex_bin="$(sed -n "s/^export AGENTSTACK_CODEX_BIN=//p" "${agentstack}/env.sh" | tail -n 1 | tr -d "'\"")"
  fi
  [ -n "$codex_bin" ] || codex_bin="$(command -v codex 2>/dev/null || true)"
  if [ -n "$codex_bin" ]; then
    # codex --version writes into CODEX_HOME; give it a throwaway one.
    probe_home="$(mktemp -d)"
    if CODEX_HOME="$probe_home" "$codex_bin" --version >/dev/null 2>&1; then
      have_codex=true
    else
      case "$codex_bin" in
        /mnt/*) codex_note="${codex_bin} is the Windows Codex; it does not run in WSL. Install Codex inside WSL to use it." ;;
        *) codex_note="${codex_bin} does not run (--version failed)." ;;
      esac
    fi
    rm -rf "$probe_home"
  fi
  if [ "$have_claude" = true ] && [ "$have_codex" = true ]; then
    team="cross-vendor"
  elif [ "$have_claude" = true ]; then
    team="claude-only"
  elif [ "$have_codex" = true ]; then
    team="codex-only"
  else
    team="none"
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

  # ------------------------------------------------------------ 1. digest-paper
  addon_state=""
  if [ -e "$src" ]; then
    origin="$(git -C "$src" remote get-url origin 2>/dev/null || true)"
    official_remote "$origin" orrery-digest-paper "$override_url" \
      || stop "${src} exists but is not this research set's copy of digest-paper; nothing was changed." \
        "Move it away and run this again."
  fi
  if [ "$read_only" = true ]; then
    if [ -e "$src" ]; then
      addon_state="would update ${src} and install it again"
    else
      addon_state="would clone ${addon_url} to ${src} and install it"
    fi
  else
    mkdir -p "$addon"
    if [ -e "$src" ]; then
      git -C "$src" fetch -q --depth 1 origin HEAD || stop "Could not fetch digest-paper." "Check the network and run this again."
      git -C "$src" checkout -q --detach FETCH_HEAD || stop "Could not update ${src} (changed by hand?)." \
        "Move it away and run this again."
    else
      git clone -q --depth 1 "$addon_url" "$src" || stop "Could not download digest-paper." "Check the network and run this again."
    fi
    say ""
    "${src}/scripts/install.sh" || stop "The digest-paper install failed (above); nothing else was done."
    addon_state="$(git -C "$src" rev-parse --short HEAD)"
  fi
  skill="${addon}/current/skills/digest-paper/SKILL.md"
  collision=false
  if [ -e "${HOME}/.claude/skills/digest-paper" ] || [ -L "${HOME}/.claude/skills/digest-paper" ]; then
    [ "$(readlink "${HOME}/.claude/skills/digest-paper" 2>/dev/null || true)" = "${addon}/current/skills/digest-paper" ] || collision=true
  fi

  # ------------------------------------------------------------ 2. the demo vault
  win_form=""
  if [ -z "$vault_dir" ]; then
    if [ "$os" = wsl ]; then
      profile="$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r' || true)"
      case "$profile" in
        [A-Za-z]:\\*) vault_dir="$(wslpath -u "$profile")/Documents/orrery-demo-vault" ;;
        *) stop "Could not find your Windows user folder (Windows interop is off?)." \
          "Give the folder yourself, for example:" \
          "  ... | bash -s -- --vault-dir /mnt/c/Users/<you>/Documents/orrery-demo-vault" ;;
      esac
    else
      vault_dir="${HOME}/Documents/orrery-demo-vault"
    fi
  fi
  case "$vault_dir" in /*) ;; *) vault_dir="$(pwd)/${vault_dir}" ;; esac
  vault_warn=""
  if [ "$os" = wsl ]; then
    case "$vault_dir" in
      /mnt/*) ;;
      *) vault_warn="${vault_dir} is inside WSL; Windows Obsidian opens it slowly and may miss changes. A folder under /mnt/c is better." ;;
    esac
  fi
  if [ -e "$vault_dir" ]; then
    vault_state="kept (already there; not changed)"
  elif [ "$read_only" = true ]; then
    vault_state="would download the demo vault to ${vault_dir}"
  else
    work="$(mktemp -d)"
    if [ -n "$vault_tarball" ]; then
      cp "$vault_tarball" "${work}/vault.tar.gz"
      vault_rev="local"
    else
      vault_rev="$(git ls-remote "$vault_repo" refs/heads/main | cut -c1-40)"
      [ -n "$vault_rev" ] || stop "Could not reach the demo vault on GitHub." "Check the network and run this again."
      curl -fsSL "https://codeload.github.com/gyroid-eth/orrery-demo-vault/tar.gz/${vault_rev}" -o "${work}/vault.tar.gz" \
        || stop "Could not download the demo vault." "Check the network and run this again."
      vault_rev="$(printf '%s' "$vault_rev" | cut -c1-7)"
    fi
    # Unpack next to the target and rename, so a half-written vault never has
    # the final name.
    partial="${vault_dir}.partial-$$"
    mkdir -p "$partial"
    tar -xzf "${work}/vault.tar.gz" -C "$partial" --strip-components 1 --no-same-owner --no-same-permissions \
      || { rm -rf "$partial" "$work"; stop "Could not unpack the demo vault."; }
    mv "$partial" "$vault_dir"
    rm -rf "$work"
    vault_state="downloaded (${vault_rev})"
  fi
  if [ "$os" = wsl ]; then
    win_form="$(wslpath -w "$vault_dir" 2>/dev/null || true)"
  fi
  open_form="${win_form:-$vault_dir}"

  # ------------------------------------------------------------ 3. report
  have_uv=false
  command -v uv >/dev/null 2>&1 && have_uv=true
  say ""
  say "  ok    ORRERY                $(cat "${agentstack}/VERSION" 2>/dev/null || echo installed)"
  case "$team" in
    cross-vendor) say "  ok    agents                Claude writes, Codex checks (cross-vendor)" ;;
    claude-only) say "  ok    agents                Claude only: two Claude agents write and check (same-vendor)" ;;
    codex-only) say "  ok    agents                Codex only: two Codex agents write and check (same-vendor)" ;;
    none) say "  NG    agents                neither Claude Code nor a working Codex; install one to make notes" ;;
  esac
  [ -z "$codex_note" ] || say "  note  ${codex_note}"
  say "  ok    digest-paper          ${addon_state}"
  [ "$collision" = false ] || say "  note  another digest-paper skill is in ~/.claude/skills; the requests below name this add-on's SKILL.md"
  say "  ok    demo vault            ${vault_dir}: ${vault_state}"
  [ -z "$vault_warn" ] || say "  note  ${vault_warn}"
  [ "$have_uv" = true ] || say "  note  uv not found: the no-key (local) conversion needs it; it comes with ORRERY"
  [ "$read_only" = false ] || { say ""; say "  --check: nothing was changed."; exit 0; }

  paper_dir="${vault_dir}/20_MDPapers"
  prefix=""
  [ "$collision" = false ] || prefix="${skill} を読んで、それに従って。"
  say ""
  say "  Next:"
  say "  1. Obsidian: \"Open folder as vault\" ->  ${open_form}"
  say "     Asked about community plugins: choose \"Trust\"."
  say "     Open this vault as it is: its Kanban board, Daily Note lists and PDF conversion come from"
  say "     the plugins inside it. Copied into another vault, they need Kanban, Dataview, Templater,"
  say "     Calendar, Task Done At, QuickAdd and PDF Mistral (Hi-Res) installed there."
  say "  2. With a Mistral API key: Settings -> Community plugins -> PDF Mistral (Hi-Res) -> API key."
  say "     Keep the key there only. Open a PDF in 10_Reference/Papers, then Ctrl/Cmd+P ->"
  say "     \"Convert PDF to Markdown with images\"."
  say "  3. In the cockpit, NEW AGENT with the vault as its working folder (${vault_dir})."
  say "     Started anywhere else, the agent does not see the vault's /addtodo, /adddone, /log"
  say "     and rules. Then paste one of these:"
  say ""
  say "     (a) a paper you converted with pdf-mistral:"
  say "     ${prefix}digest-paper で、この論文のノートを作って。"
  say "     論文: ${paper_dir}/<論文名>.md"
  say "     vault: ${vault_dir}"
  say "     図のフォルダ: ${paper_dir}/pdf-mistral-images"
  say "     保存先: ${vault_dir}/10_Reference/Notes"
  say ""
  say "     (b) no Mistral key (the PDF is converted on this machine; figures are rougher):"
  say "     ${prefix}digest-paper で、Mistral のキーが無いので、この PDF を local で変換してからノートにして。"
  say "     PDF: ${vault_dir}/10_Reference/Papers/<論文名>.pdf"
  say "     vault: ${vault_dir}"
  say "     保存先: ${vault_dir}/10_Reference/Notes"
  say ""
  say "     (c) quickest: the paper already converted in the vault (the vault has a sample note"
  say "         of it, so yours is saved beside it as ...-r2):"
  say "     ${prefix}digest-paper で、この論文のノートを作って。"
  say "     論文: ${paper_dir}/Onimaru et al. 2016 - The fin-to-limb transition as the re-organization of a Turing pattern.md"
  say "     vault: ${vault_dir}"
  say "     図のフォルダ: ${paper_dir}/pdf-mistral-images"
  say "     保存先: ${vault_dir}/10_Reference/Notes"
  say ""
  say "  Run this line again later to update digest-paper (the vault is left as it is)."
}

main "$@"
