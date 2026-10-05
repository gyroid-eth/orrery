#!/usr/bin/env bash
# The research set for ORRERY, with one line: the digest-paper add-on (a Claude
# or Codex team turns a paper into a reading note) and the demo vault.
#
#   curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/research-set.sh | bash
#   ... | bash -s -- --check              # only look; change nothing
#   ... | bash -s -- --vault-dir DIR      # put the demo vault somewhere else
#   ... | bash -s -- --lang en            # English demo vault and requests (default: ja)
#
# It needs ORRERY itself first (the one-line install, scripts/get.sh), and does
# these things, each reported at the end:
#   1. digest-paper: cloned to $AGENTSTACK_HOME/addons/digest-paper/src (or
#      updated there) and installed with its own scripts/install.sh, which links
#      it for Claude and Codex and never replaces a skill it did not install.
#   2. The demo vault: a GitHub tarball unpacked to ~/Documents/orrery-demo-vault
#      (orrery-demo-vault-en with --lang en; on WSL, the Windows Documents
#      folder, since Obsidian runs on Windows). A folder that already exists
#      and has anything in it is never touched, so your notes and the API key
#      you entered stay as they are. The one exception is an empty folder (left
#      by an interrupted run, or made by hand): it is not a vault, so the demo
#      vault is put there. It is not a git checkout on purpose.
#   3. The work folder: if the agents' work folder is still the default
#      (~/orrery-work), the vault becomes it (the ORRERY setup is run again with
#      --project-key <vault>; it shows its plan and asks once), so that an agent
#      started from now on works in the vault with ORRERY's instructions. A
#      folder you chose yourself is never changed; with --check nothing is.
#   4. What to do next: where to open the vault in Obsidian, how to enter the
#      Mistral key (or go without one), and requests to paste, paths filled in
#      (in English with --lang en).
# It never reads or writes an API key, never uses sudo and trusts only the
# gyroid-eth repositories on GitHub. Running it again updates the add-on.
#
# Everything is inside main(), so a download cut off halfway runs nothing.
# Works on macOS (including /bin/bash 3.2) and on Linux inside WSL2.

main() {
  set -eu

  override_url="${ORRERY_RESEARCH_ADDON_URL:-}"
  addon_url="${override_url:-https://github.com/gyroid-eth/orrery-digest-paper.git}"
  lang="ja"
  # Tests point these at local copies.
  vault_tarball="${ORRERY_RESEARCH_VAULT_TARBALL:-}"
  agentstack="${AGENTSTACK_HOME:-${HOME}/.agentstack}"
  addon="${agentstack}/addons/digest-paper"
  src="${addon}/src"
  # Tests point these at a stub.
  cockpit="${ORRERY_DIR:-${HOME}/orrery}"
  setup_sh="${ORRERY_SETUP:-${cockpit}/scripts/setup.sh}"

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
      --lang)
        [ $# -ge 2 ] || stop "--lang needs ja or en."
        lang="$2"; shift 2 ;;
      -h | --help) sed -n '2,34p' "$0" 2>/dev/null || true; exit 0 ;;
      *) stop "Unknown option: $1" "Options: --check, --vault-dir DIR, --lang ja|en" ;;
    esac
  done
  case "$lang" in
    ja | en) ;;
    *) stop "Unknown --lang: ${lang}" "Options: ja, en" ;;
  esac
  vault_name="orrery-demo-vault"
  [ "$lang" = en ] && vault_name="orrery-demo-vault-en"
  vault_repo="https://github.com/gyroid-eth/${vault_name}.git"

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
  codex_real=""
  [ -z "$codex_bin" ] || codex_real="$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$codex_bin" 2>/dev/null || true)"
  case "${codex_bin}|${codex_real}" in
    /mnt/* | *"|/mnt/"*)
      # A Windows Codex seen from WSL: even if it answers --version through
      # interop, ORRERY cannot run it as a Linux child. Never used.
      codex_note="${codex_bin} is the Windows Codex; ORRERY cannot use it from WSL. Install Codex inside WSL to use it."
      codex_bin="" ;;
  esac
  if [ -n "$codex_bin" ]; then
    # codex --version writes into CODEX_HOME; give it a throwaway one.
    probe_home="$(mktemp -d)"
    if CODEX_HOME="$probe_home" "$codex_bin" --version >/dev/null 2>&1; then
      have_codex=true
    else
      codex_note="${codex_bin} does not run (--version failed)."
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

  # ------------------------------------------------------------ where the vault goes
  # Decided before anything is written, so a stop here leaves nothing behind.
  win_form=""
  if [ -z "$vault_dir" ]; then
    if [ "$os" = wsl ]; then
      profile="$(cmd.exe /c 'echo %USERPROFILE%' 2>/dev/null | tr -d '\r' || true)"
      case "$profile" in
        [A-Za-z]:\\*) vault_dir="$(wslpath -u "$profile")/Documents/${vault_name}" ;;
        *) stop "Could not find your Windows user folder (Windows interop is off?)." \
          "Give the folder yourself, for example:" \
          "  ... | bash -s -- --vault-dir /mnt/c/Users/<you>/Documents/${vault_name}" ;;
      esac
    else
      vault_dir="${HOME}/Documents/${vault_name}"
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
  # Another digest-paper skill (not this add-on's link) on either side means
  # the requests must name this add-on's SKILL.md. The installer records what
  # it kept in install-state.json; before an install, look at both homes.
  collision=false
  collision_where=""
  state_file="${addon}/install-state.json"
  if [ "$read_only" = false ] && [ -f "$state_file" ]; then
    collision_where="$(python3 -c 'import json, sys; print(" ".join(json.load(open(sys.argv[1])).get("collisions", [])))' "$state_file" 2>/dev/null || true)"
  else
    for dir in "${CLAUDE_SKILLS_DIR:-${HOME}/.claude/skills}" "${CODEX_HOME:-${HOME}/.codex}/skills"; do
      target="${dir}/digest-paper"
      if [ -e "$target" ] || [ -L "$target" ]; then
        [ "$(readlink "$target" 2>/dev/null || true)" = "${addon}/current/skills/digest-paper" ] \
          || collision_where="${collision_where} ${target}"
      fi
    done
  fi
  [ -z "$(printf '%s' "$collision_where" | tr -d ' ')" ] || collision=true

  # ------------------------------------------------------------ 2. the demo vault
  # An empty folder is not a vault (it may be one left by an interrupted run);
  # anything else at that path is never touched.
  vault_empty=false
  if [ -d "$vault_dir" ] && [ ! -L "$vault_dir" ] && [ -z "$(ls -A "$vault_dir" 2>/dev/null)" ]; then
    vault_empty=true
  fi
  if [ -e "$vault_dir" ] && [ "$vault_empty" = false ]; then
    vault_state="kept (already there; not changed)"
  elif [ "$read_only" = true ]; then
    vault_state="would download the demo vault to ${vault_dir}"
  else
    # Claim the folder first: mkdir (without -p) fails if anyone else has it,
    # so from here on only this run owns that name. An empty folder already
    # there is taken over the same way (rmdir fails if it is not empty).
    mkdir -p "$(dirname "$vault_dir")"
    if [ "$vault_empty" = true ]; then
      rmdir "$vault_dir" 2>/dev/null || stop "${vault_dir} is no longer empty; nothing was written into it." \
        "Run this again (the existing folder will be used as it is)."
    fi
    mkdir "$vault_dir" 2>/dev/null || stop "${vault_dir} appeared just now; nothing was written into it." \
      "Run this again (the existing folder will be used as it is)."
    claimed="$vault_dir"
    trap 'rmdir "$claimed" 2>/dev/null || true' EXIT
    work="$(mktemp -d)"
    if [ -n "$vault_tarball" ]; then
      cp "$vault_tarball" "${work}/vault.tar.gz"
      vault_rev="local"
    else
      vault_rev="$(git ls-remote "$vault_repo" refs/heads/main | cut -c1-40)"
      [ -n "$vault_rev" ] || stop "Could not reach the demo vault on GitHub." "Check the network and run this again."
      curl -fsSL "https://codeload.github.com/gyroid-eth/${vault_name}/tar.gz/${vault_rev}" -o "${work}/vault.tar.gz" \
        || stop "Could not download the demo vault." "Check the network and run this again."
      vault_rev="$(printf '%s' "$vault_rev" | cut -c1-7)"
    fi
    # Unpack next to the target and rename, so a half-written vault never has
    # the final name.
    partial="${vault_dir}.partial-$$"
    mkdir -p "$partial"
    tar -xzf "${work}/vault.tar.gz" -C "$partial" --strip-components 1 --no-same-owner --no-same-permissions \
      || { rm -rf "$partial" "$work"; stop "Could not unpack the demo vault."; }
    # rename(2) through Python replaces only our own claimed, still empty
    # folder; if anything was put into it meanwhile it fails (ENOTEMPTY), and
    # unlike mv it never moves the vault *into* a folder.
    if ! python3 -c 'import os, sys; os.rename(sys.argv[1], sys.argv[2])' "$partial" "$vault_dir" 2>/dev/null; then
      rm -rf "$partial" "$work"
      stop "Something was put into ${vault_dir} while the demo vault was downloading; it was left as it is." \
        "Move it away, or use another folder with --vault-dir, and run this again."
    fi
    trap - EXIT
    rm -rf "$work"
    vault_state="downloaded (${vault_rev})"
  fi
  if [ "$os" = wsl ]; then
    win_form="$(wslpath -w "$vault_dir" 2>/dev/null || true)"
  fi
  open_form="${win_form:-$vault_dir}"

  # ------------------------------------------------------------ 3. the work folder
  # The agents' work folder (ORRERY's project key) is a folder that gets ORRERY's
  # instructions (CLAUDE.md) and whose files are reservation-protected. Only
  # the default is replaced; one the user chose stays.
  # The folder with symbolic links resolved (python3 would leave a cache in HOME, also under --check).
  realpath_of() {
    if [ -d "$1" ]; then (cd "$1" && pwd -P)
    elif [ -d "$(dirname "$1")" ]; then printf '%s/%s\n' "$(cd "$(dirname "$1")" && pwd -P)" "$(basename "$1")"
    else printf '%s\n' "$1"
    fi
  }
  vault_real="$(realpath_of "$vault_dir")"
  cur_key=""
  # env.sh holds shell-quoted values (a quote or a space in HOME), so read it by sourcing, as the setup does.
  # A file that fails to load counts as unknown (never the value this shell may carry from elsewhere).
  env_readable=true
  if [ -f "${agentstack}/env.sh" ]; then
    if ! cur_key="$( ( unset AGENTSTACK_PROJECT_KEY; . "${agentstack}/env.sh" >/dev/null 2>&1 || exit 1; printf '%s' "${AGENTSTACK_PROJECT_KEY:-}" ) )"; then
      cur_key=""; env_readable=false
    fi
  fi
  default_key="${HOME}/orrery-work"
  work_state=""
  work_failed=false
  work_is_vault=false
  # printf %q quotes a path so that it can be pasted into a shell as it is, whatever it contains.
  retry_line="curl -fsSL https://raw.githubusercontent.com/gyroid-eth/orrery/master/scripts/get.sh | bash -s -- --project-key $(printf '%q' "$vault_real")"
  if [ "$env_readable" = false ]; then
    work_state="not known (${agentstack}/env.sh could not be read); not changed"
  elif [ -z "$cur_key" ]; then
    work_state="not known (no project key in ${agentstack}/env.sh); not changed"
  elif [ "$(realpath_of "$cur_key")" = "$vault_real" ]; then
    work_state="already the vault"
    work_is_vault=true
  elif [ "$(realpath_of "$cur_key")" != "$(realpath_of "$default_key")" ]; then
    work_state="kept: ${cur_key} (a folder you chose). To use the vault instead: ${retry_line}"
  elif [ "$read_only" = true ]; then
    work_state="would make the vault the work folder (the ORRERY setup is run again with --project-key)"
  elif [ ! -f "$setup_sh" ]; then
    work_state="not changed: the ORRERY setup was not found at ${setup_sh}. To use the vault: ${retry_line}"
  else
    say ""
    say "  The work folder is still the default (${cur_key}); making the vault the work folder ..."
    status=0
    # The setup asks once (type yes); under curl | bash, stdin is this script, so give it the terminal.
    if [ -r /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
      env ORRERY_NO_OPEN=1 ORRERY_DIR="$cockpit" "$setup_sh" --project-key "$vault_real" </dev/tty || status=$?
    else
      env ORRERY_NO_OPEN=1 ORRERY_DIR="$cockpit" "$setup_sh" --project-key "$vault_real" || status=$?
    fi
    # The exit status alone does not say what changed (the setup can stop at a check after it
    # wrote the new folder), so read the saved folder again.
    now_key=""
    now_key="$( ( unset AGENTSTACK_PROJECT_KEY; . "${agentstack}/env.sh" >/dev/null 2>&1 || exit 1; printf '%s' "${AGENTSTACK_PROJECT_KEY:-}" ) )" || now_key=""
    if [ -n "$now_key" ] && [ "$(realpath_of "$now_key")" = "$vault_real" ]; then
      work_is_vault=true
      if [ "$status" -eq 0 ]; then
        work_state="the vault (${vault_real})"
      else
        work_state="the vault (${vault_real}) is saved as the work folder, but the ORRERY setup stopped at a later check (above). To check again: ${retry_line}"
        work_failed=true
      fi
    else
      work_state="NOT changed: the ORRERY setup stopped (above). To try again: ${retry_line}"
      work_failed=true
    fi
  fi

  # ------------------------------------------------------------ 4. report
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
  [ "$collision" = false ] || say "  note  another digest-paper skill is kept at${collision_where}; the requests below name this add-on's SKILL.md"
  say "  ok    demo vault            ${vault_dir}: ${vault_state}"
  [ -z "$vault_warn" ] || say "  note  ${vault_warn}"
  if [ "$work_failed" = true ]; then say "  NG    work folder           ${work_state}"; else say "  ok    work folder           ${work_state}"; fi
  if [ "$work_is_vault" = true ] && [ "$read_only" = false ]; then
    say "  note  agents started from now on work in the vault: its CLAUDE.md has ORRERY's block (your own text stays;"
    say "        Codex's instructions are in ~/.codex/AGENTS.md), file reservations cover the vault, and NEW AGENT"
    say "        starts there. Agents that were already running stay on the old folder: start new ones."
  fi
  [ "$have_uv" = true ] || say "  note  uv not found: the no-key (local) conversion needs it; it comes with ORRERY"
  [ "$read_only" = false ] || { say ""; say "  --check: nothing was changed."; exit 0; }

  paper_dir="${vault_dir}/20_MDPapers"
  prefix=""
  if [ "$collision" = true ]; then
    if [ "$lang" = en ]; then
      prefix="Read ${skill} and follow it. "
    else
      prefix="${skill} を読んで、それに従って。"
    fi
  fi
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
  if [ "$work_is_vault" = true ]; then
    say "  3. In the cockpit, NEW AGENT (it starts in the vault: ${vault_dir}). Then paste one of these:"
  else
    say "  3. In the cockpit, NEW AGENT with the vault as its working folder (${vault_dir})."
    say "     Started anywhere else, the agent does not see the vault's /addtodo, /adddone, /log"
    say "     and rules. Then paste one of these:"
  fi
  say ""
  guo="${vault_dir}/10_Reference/Papers/Guo et al. 2024 - Self-regulated reversal deformation and locomotion of structurally homogenous hydrogels subjected to constant light illumination.pdf"
  onimaru="${paper_dir}/Onimaru et al. 2016 - The fin-to-limb transition as the re-organization of a Turing pattern.md"
  if [ "$lang" = en ]; then
    say "     (a) a paper you converted with pdf-mistral:"
    say "     ${prefix}Use digest-paper to write a reading note for this paper."
    say "     Paper: ${paper_dir}/<paper name>.md"
    say "     Vault: ${vault_dir}"
    say "     Figures folder: ${paper_dir}/pdf-mistral-images"
    say "     Save to: ${vault_dir}/10_Reference/Notes"
    say "     Write the note in English."
    say ""
    say "     (b) no Mistral key (the PDF is converted on this machine; figures are rougher):"
    say "     ${prefix}Use digest-paper. I don't have a Mistral key, so convert this PDF locally first, then write the note."
    if [ -f "$guo" ]; then
      say "     PDF: ${guo}"
    else
      say "     PDF: ${vault_dir}/10_Reference/Papers/<paper name>.pdf   (replace <paper name> with your own PDF's name)"
    fi
    say "     Vault: ${vault_dir}"
    say "     Save to: ${vault_dir}/10_Reference/Notes"
    say "     Write the note in English."
    say ""
    say "     (c) quickest: the paper already converted in the vault (the vault has a sample note"
    say "         of it, so yours is saved beside it as ...-r2):"
    say "     ${prefix}Use digest-paper to write a reading note for this paper."
    say "     Paper: ${onimaru}"
    say "     Vault: ${vault_dir}"
    say "     Figures folder: ${paper_dir}/pdf-mistral-images"
    say "     Save to: ${vault_dir}/10_Reference/Notes"
    say "     Write the note in English."
  else
    say "     (a) a paper you converted with pdf-mistral:"
    say "     ${prefix}digest-paper で、この論文のノートを作って。"
    say "     論文: ${paper_dir}/<論文名>.md"
    say "     vault: ${vault_dir}"
    say "     図のフォルダ: ${paper_dir}/pdf-mistral-images"
    say "     保存先: ${vault_dir}/10_Reference/Notes"
    say ""
    say "     (b) no Mistral key (the PDF is converted on this machine; figures are rougher):"
    say "     ${prefix}digest-paper で、Mistral のキーが無いので、この PDF を local で変換してからノートにして。"
    if [ -f "$guo" ]; then
      say "     PDF: ${guo}"
    else
      say "     PDF: ${vault_dir}/10_Reference/Papers/<論文名>.pdf   (<論文名> を自分の PDF の名前に)"
    fi
    say "     vault: ${vault_dir}"
    say "     保存先: ${vault_dir}/10_Reference/Notes"
    say ""
    say "     (c) quickest: the paper already converted in the vault (the vault has a sample note"
    say "         of it, so yours is saved beside it as ...-r2):"
    say "     ${prefix}digest-paper で、この論文のノートを作って。"
    say "     論文: ${onimaru}"
    say "     vault: ${vault_dir}"
    say "     図のフォルダ: ${paper_dir}/pdf-mistral-images"
    say "     保存先: ${vault_dir}/10_Reference/Notes"
  fi
  say ""
  say "  Run this line again later to update digest-paper (the vault is left as it is)."
  [ "$work_failed" = false ] || exit 1
}

main "$@"
