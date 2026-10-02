#!/usr/bin/env bash
# Tests for scripts/research-set.sh in a throwaway HOME, with local copies of
# digest-paper and the demo vault (no network). Run: tools/test_research_set.sh
# DIGEST_PAPER_SRC and DEMO_VAULT_SRC default to sibling checkouts.
set -euo pipefail
here="$(cd "$(dirname "$0")/.." && pwd)"
script="${here}/scripts/research-set.sh"
digest="${DIGEST_PAPER_SRC:-${here}/../orrery-digest-paper}"
vault_src="${DEMO_VAULT_SRC:-${here}/../orrery-demo-vault}"
[ -e "$digest/.git" ] && [ -e "$vault_src/.git" ] || { echo "skip: need checkouts of orrery-digest-paper and orrery-demo-vault"; exit 0; }

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
fail() { echo "FAIL: $*"; exit 1; }
git -C "$vault_src" archive --prefix=orrery-demo-vault-main/ -o "$tmp/vault.tar.gz" HEAD
git clone -q "$digest" "$tmp/digest-origin"

run() { # $1 = HOME; rest = args
  local home="$1"; shift
  env -i PATH="$tmp/bin:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" \
    ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
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

# WSL without interop: stop before writing anything (review P3-1).
home="$tmp/h7"; mkdir -p "$home/.agentstack/skills/delegate"; touch "$home/.agentstack/skills/delegate/SKILL.md"
mkdir -p "$tmp/bin7"; cp "$tmp/bin/claude" "$tmp/bin7/"; printf '#!/bin/sh\necho Linux\n' >"$tmp/bin7/uname"; chmod +x "$tmp/bin7/uname"
before="$(cd "$home" && find . | sort)"
out="$(env -i PATH="$tmp/bin7:/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin" HOME="$home" WSL_DISTRO_NAME=Ubuntu \
  ORRERY_RESEARCH_ADDON_URL="$tmp/digest-origin" ORRERY_RESEARCH_VAULT_TARBALL="$tmp/vault.tar.gz" \
  /bin/bash "$script" 2>&1 || true)"
echo "$out" | grep -q "Could not find your Windows user folder" || fail "no interop: $out"
[ "$before" = "$(cd "$home" && find . | sort)" ] || fail "no interop wrote something"

echo "ok: research-set"
