#!/usr/bin/env bash
# Tests for scripts/research-set.sh in a throwaway HOME, with local copies of
# digest-paper and the demo vault (no network). Run: tools/test_research_set.sh
# DIGEST_PAPER_SRC and DEMO_VAULT_SRC default to sibling checkouts.
# DEMO_VAULT_EN_SRC (default: sibling orrery-demo-vault-en) is optional; the
# --lang en tests are skipped (not the whole file) if it's missing.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
script="${here}/scripts/research-set.sh"
digest="${DIGEST_PAPER_SRC:-${here}/../orrery-digest-paper}"
vault_src="${DEMO_VAULT_SRC:-${here}/../orrery-demo-vault}"
vault_en_src="${DEMO_VAULT_EN_SRC:-${here}/../orrery-demo-vault-en}"
[ -e "$digest/.git" ] && [ -e "$vault_src/.git" ] || { echo "skip: need checkouts of orrery-digest-paper and orrery-demo-vault"; exit 0; }
have_en_vault=false
[ -e "$vault_en_src/.git" ] && have_en_vault=true

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
git -C "$vault_src" archive --prefix=orrery-demo-vault-main/ -o "$tmp/vault.tar.gz" HEAD
[ "$have_en_vault" = false ] || git -C "$vault_en_src" archive --prefix=orrery-demo-vault-en-main/ -o "$tmp/vault-en.tar.gz" HEAD
git clone -q "$digest" "$tmp/digest-origin"

run() { # $1 = HOME; rest = args
  local home="$1"; shift
  env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" \
    ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
    /bin/bash "$script" "$@"
}
run_en() { # $1 = HOME; rest = args (the English vault tarball instead of the Japanese one)
  local home="$1"; shift
  env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" \
    ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault-en.tar.gz" \
    /bin/bash "$script" "$@"
}
mkdir -p "$tmp/bin"
printf '#!/bin/sh\nexit 0\n' >"$tmp/bin/claude"; chmod +x "$tmp/bin/claude"

# No ORRERY: stop before doing anything.
home="$tmp/h0"; mkdir -p "$home"
out="$(run "$home" 2>&1 || true)"
echo "$out" | grep -q "ORRERY is not installed" || fail "no ORRERY: $out"
[ -z "$(ls -A "$home")" ] || fail "no ORRERY wrote something"

# --check writes nothing.
home="$tmp/h1"; mkdir -p "$home/.agentstack/skills/delegate"; touch "$home/.agentstack/skills/delegate/SKILL.md"
before="$(cd "$home" && find . | sort)"
out="$(run "$home" --check)" || fail "check: $out"
echo "$out" | grep -q "would clone" || fail "check plan: $out"
[ "$before" = "$(cd "$home" && find . | sort)" ] || fail "--check changed files"

# Install: add-on linked, vault unpacked, claude-only team, requests filled in.
out="$(run "$home")" || fail "install: $out"
[ -L "$home/.claude/skills/digest-paper" ] || fail "claude link missing"
[ -f "$home/.agentstack/addons/digest-paper/current/skills/digest-paper/SKILL.md" ] || fail "add-on missing"
v="$home/Documents/orrery-demo-vault"
[ -f "$v/00_Inbox/はじめに.md" ] && [ -d "$v/.obsidian" ] || fail "vault not unpacked"
[ ! -d "$v/.git" ] || fail "vault must not be a git checkout"
echo "$out" | grep -q "Claude only" || fail "team: $out"
echo "$out" | grep -q "論文: $v/20_MDPapers/Onimaru" || fail "request paths: $out"
! echo "$out" | grep -q "を読んで、それに従って" || fail "no collision expected"

# Again: the vault and a key entered in it are kept; the add-on is updated.
echo '{"mistralApiKey": "kept"}' >"$v/.obsidian/plugins/pdf-mistral-plugin/data.json"
out="$(run "$home")" || fail "rerun: $out"
grep -q kept "$v/.obsidian/plugins/pdf-mistral-plugin/data.json" || fail "vault changed on rerun"
echo "$out" | grep -q "kept (already there" || fail "rerun vault state: $out"

# Another digest-paper skill: kept, and the requests name the add-on's SKILL.md.
home="$tmp/h2"; mkdir -p "$home/.agentstack/skills/delegate" "$home/.claude/skills/digest-paper"
touch "$home/.agentstack/skills/delegate/SKILL.md" "$home/.claude/skills/digest-paper/SKILL.md"
out="$(run "$home" --vault-dir "$tmp/elsewhere/vault")" || fail "collision: $out"
[ -d "$home/.claude/skills/digest-paper" ] && [ ! -L "$home/.claude/skills/digest-paper" ] || fail "other skill replaced"
echo "$out" | grep -q "addons/digest-paper/current/skills/digest-paper/SKILL.md を読んで" || fail "collision request: $out"
[ -f "$tmp/elsewhere/vault/CLAUDE.md" ] || fail "--vault-dir"

# A src folder that is not ours is left alone.
home="$tmp/h3"; mkdir -p "$home/.agentstack/skills/delegate" "$home/.agentstack/addons/digest-paper/src"
touch "$home/.agentstack/skills/delegate/SKILL.md"
out="$(run "$home" 2>&1 || true)"
echo "$out" | grep -q "not this research set's copy" || fail "foreign src: $out"

# Codex only, with another digest-paper kept on the Codex side (review P2-3).
home="$tmp/h4"; mkdir -p "$home/.agentstack/skills/delegate" "$home/.codex/skills/digest-paper"
touch "$home/.agentstack/skills/delegate/SKILL.md" "$home/.codex/skills/digest-paper/SKILL.md"
mkdir -p "$tmp/bin4"; printf '#!/bin/sh\nexit 0\n' >"$tmp/bin4/codex"; chmod +x "$tmp/bin4/codex"
out="$(env -i PATH="$tmp/bin4:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" \
  ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script")" || fail "codex collision: $out"
echo "$out" | grep -q "Codex only" || fail "codex-only team: $out"
echo "$out" | grep -q "SKILL.md を読んで" || fail "codex-side collision not named: $out"

# A Windows codex under /mnt/ is never used, even before asking it anything (P2-4).
home="$tmp/h5"; mkdir -p "$home/.agentstack/skills/delegate"; touch "$home/.agentstack/skills/delegate/SKILL.md"
out="$(env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" \
  AGENTSTACK_CODEX_BIN=/mnt/c/Users/test/AppData/Roaming/npm/codex \
  ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" --check)" || fail "windows codex: $out"
echo "$out" | grep -q "Windows Codex; ORRERY cannot use it" || fail "windows codex note: $out"
echo "$out" | grep -q "Claude only" || fail "windows codex counted: $out"

# Something is put into the vault folder while downloading: left as it is (P2-5).
home="$tmp/h6"; mkdir -p "$home/.agentstack/skills/delegate"; touch "$home/.agentstack/skills/delegate/SKILL.md"
mkdir -p "$tmp/bin6"; cp "$tmp/bin/claude" "$tmp/bin6/"
real_tar="$(command -v tar)"
printf '#!/bin/sh\nmkdir -p "%s" && echo mine >"%s/sentinel"\nexec "%s" "$@"\n' "$tmp/race" "$tmp/race" "$real_tar" >"$tmp/bin6/tar"
chmod +x "$tmp/bin6/tar"
race() { env -i PATH="$tmp/bin6:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" \
  ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" --vault-dir "$1" 2>&1 || true; }
out="$(race "$tmp/race")"
echo "$out" | grep -q "was put into .* while the demo vault was downloading" || fail "race: $out"
[ "$(ls -A "$tmp/race")" = "sentinel" ] || fail "race wrote into the folder: $(ls -A "$tmp/race")"
! ls -d "$tmp"/race.partial-* >/dev/null 2>&1 || fail "partial left behind"
# An empty folder made meanwhile (the reviewer's case) is never replaced by
# someone else's: this run claimed the name first, so the other mkdir -p finds ours.
printf '#!/bin/sh\nmkdir -p "%s"\nexec "%s" "$@"\n' "$tmp/race2" "$real_tar" >"$tmp/bin6/tar"
out="$(race "$tmp/race2")"
[ -f "$tmp/race2/CLAUDE.md" ] || fail "empty-folder race: $out"
# An empty folder left by an interrupted run is used; one with anything in it is kept.
mkdir -p "$tmp/empty"; printf '#!/bin/sh\nexec "%s" "$@"\n' "$real_tar" >"$tmp/bin6/tar"
out="$(race "$tmp/empty")"
[ -f "$tmp/empty/CLAUDE.md" ] || fail "empty folder not used: $out"

# The no-key request names the PDF that the new vault has (P3-2).
out="$(run "$tmp/h1")"
echo "$out" | grep -q "PDF: .*Guo et al. 2024" || fail "Guo PDF not named: $out"

# --lang en: the English vault (a different folder; the ja vault above is untouched), English requests.
if [ "$have_en_vault" = true ]; then
  out="$(run_en "$tmp/h1" --lang en)" || fail "lang en: $out"
  ven="$tmp/h1/Documents/orrery-demo-vault-en"
  [ -f "$ven/00_Inbox/Getting started.md" ] && [ -d "$ven/.obsidian" ] || fail "en vault not unpacked"
  [ ! -d "$ven/.git" ] || fail "en vault must not be a git checkout"
  [ -f "$v/CLAUDE.md" ] || fail "en run touched the ja vault"
  echo "$out" | grep -q "Write the note in English." || fail "en request missing: $out"
  echo "$out" | grep -q "Paper: ${ven}/20_MDPapers/Onimaru" || fail "en request paths: $out"
  ! echo "$out" | grep -q "論文:" || fail "ja text leaked into en request: $out"
else
  echo "skip: --lang en needs a checkout of orrery-demo-vault-en (DEMO_VAULT_EN_SRC)"
fi

# WSL without interop: stop before writing anything (review P3-1).
home="$tmp/h7"; mkdir -p "$home/.agentstack/skills/delegate"; touch "$home/.agentstack/skills/delegate/SKILL.md"
mkdir -p "$tmp/bin7"; cp "$tmp/bin/claude" "$tmp/bin7/"; printf '#!/bin/sh\necho Linux\n' >"$tmp/bin7/uname"; chmod +x "$tmp/bin7/uname"
before="$(cd "$home" && find . | sort)"
out="$(env -i PATH="$tmp/bin7:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" WSL_DISTRO_NAME=Ubuntu \
  ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" 2>&1 || true)"
echo "$out" | grep -q "Could not find your Windows user folder" || fail "no interop: $out"
[ "$before" = "$(cd "$home" && find . | sort)" ] || fail "no interop wrote something"

# The work folder: the vault replaces the default one only (setup is a stub here).
rp() { python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "$1"; }
cat >"$tmp/setup-stub" <<'STUB'
#!/bin/bash
printf '%s\n' "$*" >>"$STUB_LOG"
# Like the real setup: a successful run has saved the new folder.
[ "${STUB_EXIT:-0}" != 0 ] || printf 'export AGENTSTACK_PROJECT_KEY=%q\n' "$2" >"$HOME/.agentstack/env.sh"
exit "${STUB_EXIT:-0}"
STUB
chmod +x "$tmp/setup-stub"
wf_home() { # $1 = name, $2 = saved project key (empty: no env.sh); prints the HOME
  local h="$tmp/$1"; mkdir -p "$h/.agentstack/skills/delegate"; touch "$h/.agentstack/skills/delegate/SKILL.md"
  [ -z "$2" ] || printf "export AGENTSTACK_PROJECT_KEY=%s\n" "$2" >"$h/.agentstack/env.sh"
  printf '%s' "$h"
}
wf_run() { # $1 = HOME, $2 = stub exit; rest = options
  local h="$1" ex="$2"; shift 2
  env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$h" STUB_LOG="$tmp/stub.log" STUB_EXIT="$ex" \
    ORRERY_SETUP="$tmp/setup-stub" ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
    /bin/bash "$script" "$@" 2>&1
}
# default work folder: the setup is run again with the vault
home="$(wf_home h8 "$tmp/h8/orrery-work")"; : >"$tmp/stub.log"
out="$(wf_run "$home" 0)" || fail "work folder default: $out"
v8="$(rp "$home/Documents/orrery-demo-vault")"
[ "$(cat "$tmp/stub.log")" = "--project-key $v8" ] || fail "setup args: $(cat "$tmp/stub.log")"
echo "$out" | grep -q "ok    work folder           the vault" || fail "work folder state: $out"
echo "$out" | grep -q "Agents that were already running stay on the old folder" || fail "old agents note: $out"
echo "$out" | grep -q "NEW AGENT (it starts in the vault" || fail "next step for the vault: $out"
# --check: the plan only
home="$(wf_home h9 "$tmp/h9/orrery-work")"; : >"$tmp/stub.log"
out="$(wf_run "$home" 0 --check)" || fail "work folder check: $out"
[ ! -s "$tmp/stub.log" ] || fail "--check ran the setup"
echo "$out" | grep -q "would make the vault the work folder" || fail "check plan for the work folder: $out"
# a folder the user chose is kept; the line that changes it is shown
home="$(wf_home h10 "$tmp/h10/mine")"; : >"$tmp/stub.log"
out="$(wf_run "$home" 0)" || fail "work folder chosen: $out"
[ ! -s "$tmp/stub.log" ] || fail "a chosen folder was changed"
echo "$out" | grep -q "kept: $tmp/h10/mine (a folder you chose)" || fail "chosen folder note: $out"
echo "$out" | grep -q -- "--project-key $(printf '%q' "$(rp "$home/Documents/orrery-demo-vault")")" || fail "retry line: $out"
# already the vault: nothing to do
home="$(wf_home h11 "")"; printf "export AGENTSTACK_PROJECT_KEY=%s\n" "$(rp "$home")/Documents/orrery-demo-vault" >"$home/.agentstack/env.sh"; : >"$tmp/stub.log"
out="$(wf_run "$home" 0)" || fail "work folder already: $out"
[ ! -s "$tmp/stub.log" ] || fail "the setup ran although the vault is the work folder"
echo "$out" | grep -q "work folder           already the vault" || fail "already note: $out"
# no saved project key (ORRERY not installed through setup): not touched
home="$(wf_home h12 "")"; : >"$tmp/stub.log"
out="$(wf_run "$home" 0)" || fail "work folder unknown: $out"
[ ! -s "$tmp/stub.log" ] || fail "setup ran without a saved project key"
echo "$out" | grep -q "work folder           not known" || fail "unknown note: $out"
# the setup stops: reported, the rest is still done, the exit status is 1
home="$(wf_home h13 "$tmp/h13/orrery-work")"; : >"$tmp/stub.log"
if out="$(wf_run "$home" 1)"; then fail "a failed setup must exit 1: $out"; fi
echo "$out" | grep -q "NG    work folder           NOT changed" || fail "failed setup note: $out"
[ -f "$home/Documents/orrery-demo-vault/CLAUDE.md" ] || fail "the vault is still put there"
# the setup is missing: said, with the line that does it
home="$(wf_home h14 "$tmp/h14/orrery-work")"
out="$(env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" \
  ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" 2>&1)" || fail "no setup: $out"
echo "$out" | grep -q "the ORRERY setup was not found at" || fail "no setup note: $out"

# A quote in HOME: env.sh holds shell-quoted values, and the default folder is still recognised.
home="$tmp/ap'ostrophe"; mkdir -p "$home/.agentstack/skills/delegate"; touch "$home/.agentstack/skills/delegate/SKILL.md"
python3 -c 'import shlex, sys; print("export AGENTSTACK_PROJECT_KEY=" + shlex.quote(sys.argv[1]))' "$home/orrery-work" >"$home/.agentstack/env.sh"
: >"$tmp/stub.log"
out="$(wf_run "$home" 0)" || fail "apostrophe in HOME: $out"
[ "$(cat "$tmp/stub.log")" = "--project-key $(rp "$home/Documents/orrery-demo-vault")" ] || fail "apostrophe: the default folder was not recognised: $out"
# The printed line is safe to paste: a path with a quote and a command substitution is not executed.
home="$(wf_home h15 "$tmp/h15/mine")"; : >"$tmp/stub.log"
vd="$tmp/v'\$(touch $tmp/INJECTED)'x"
out="$(wf_run "$home" 0 --vault-dir "$vd")" || fail "odd vault path: $out"
line="$(echo "$out" | grep -o -- "--project-key .*" | head -1)"
arg="${line#--project-key }"
[ "$(eval "printf '%s' $arg")" = "$(rp "$vd")" ] || fail "retry line does not give back the path: $line"
[ ! -e "$tmp/INJECTED" ] || fail "the printed line ran a command from the path"

# The setup writes the new folder and then stops at a later check: said as changed (read from env.sh, not the exit status).
cat >"$tmp/setup-stub-writes" <<'STUB'
#!/bin/bash
printf '%s\n' "$*" >>"$STUB_LOG"
printf 'export AGENTSTACK_PROJECT_KEY=%q\n' "$2" >"$HOME/.agentstack/env.sh"
exit 1
STUB
chmod +x "$tmp/setup-stub-writes"
home="$(wf_home h16 "$tmp/h16/orrery-work")"; : >"$tmp/stub.log"
if out="$(env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" STUB_LOG="$tmp/stub.log" \
  ORRERY_SETUP="$tmp/setup-stub-writes" ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" 2>&1)"; then fail "a setup that stops late must still exit 1: $out"; fi
echo "$out" | grep -q "is saved as the work folder, but the ORRERY setup stopped at a later check" || fail "late stop not said as changed: $out"
! echo "$out" | grep -q "NOT changed" || fail "a changed folder was reported as not changed: $out"
echo "$out" | grep -q "NEW AGENT (it starts in the vault" || fail "next step after a late stop: $out"
# env.sh that cannot be loaded: unknown, even if this shell carries a default key from elsewhere.
home="$(wf_home h17 "")"; printf 'return 1\n' >"$home/.agentstack/env.sh"; : >"$tmp/stub.log"
out="$(env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" STUB_LOG="$tmp/stub.log" \
  AGENTSTACK_PROJECT_KEY="$home/orrery-work" ORRERY_SETUP="$tmp/setup-stub" \
  ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" 2>&1)" || fail "unreadable env.sh: $out"
[ ! -s "$tmp/stub.log" ] || fail "setup ran although env.sh could not be read"
echo "$out" | grep -q "env.sh could not be read); not changed" || fail "unreadable env.sh note: $out"

# The setup leaves an env.sh that cannot be read: said as not confirmed, not as unchanged.
cat >"$tmp/setup-stub-broken" <<'STUB'
#!/bin/bash
printf '%s\n' "$*" >>"$STUB_LOG"
printf 'return 1\n' >"$HOME/.agentstack/env.sh"
exit 1
STUB
chmod +x "$tmp/setup-stub-broken"
home="$(wf_home h18 "$tmp/h18/orrery-work")"; : >"$tmp/stub.log"
if out="$(env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" STUB_LOG="$tmp/stub.log" \
  ORRERY_SETUP="$tmp/setup-stub-broken" ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" 2>&1)"; then fail "an unreadable env.sh after the setup must exit 1: $out"; fi
echo "$out" | grep -q "could not confirm the saved work folder" || fail "unreadable env.sh after the setup: $out"
! echo "$out" | grep -q "NOT changed" || fail "an unknown state was reported as not changed: $out"

echo "ok: research-set"
