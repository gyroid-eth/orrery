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

echo "ok: research-set"
