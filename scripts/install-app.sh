#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
SOURCE_APP="${REPO_ROOT}/app/src-tauri/target/release/bundle/macos/ORRERY.app"
DEST_APP="/Applications/ORRERY.app"

dry_run=false
assume_yes=false

usage() {
  cat <<'EOF'
Usage: scripts/install-app.sh [--dry-run] [-y|--yes]

Copy the release bundle to /Applications/ORRERY.app with rsync.

Options:
  --dry-run  Show the rsync changes without copying anything.
  -y, --yes  Skip the confirmation prompt.
  -h, --help Show this help text.
EOF
}

while (($# > 0)); do
  case "$1" in
    --dry-run)
      dry_run=true
      ;;
    -y | --yes)
      assume_yes=true
      ;;
    -h | --help)
      usage
      exit 0
      ;;
    *)
      printf 'Unknown option: %s\n\n' "$1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

if [[ ! -f "${SOURCE_APP}/Contents/Info.plist" ]]; then
  printf 'Release bundle not found: %s\n' "${SOURCE_APP}" >&2
  printf 'Build it first with: (cd app && npm run build)\n' >&2
  exit 1
fi

if [[ "${dry_run}" == false && "${assume_yes}" == false ]]; then
  if [[ ! -t 0 ]]; then
    printf 'Refusing a non-interactive install without -y.\n' >&2
    exit 1
  fi
  printf 'Replace %s with the release bundle from:\n  %s\n' "${DEST_APP}" "${SOURCE_APP}"
  read -r -p 'Continue? [y/N] ' reply
  case "${reply}" in
    y | Y | yes | YES)
      ;;
    *)
      printf 'Install cancelled.\n'
      exit 0
      ;;
  esac
fi

rsync_args=(-a --delete --itemize-changes)
if [[ "${dry_run}" == true ]]; then
  rsync_args+=(--dry-run)
  printf 'Dry run: no files will be copied.\n'
fi

rsync "${rsync_args[@]}" "${SOURCE_APP}/" "${DEST_APP}/"

if [[ "${dry_run}" == true ]]; then
  printf '\nDry run complete. A real install would copy to %s.\n' "${DEST_APP}"
else
  printf '\nInstalled ORRERY to %s.\n' "${DEST_APP}"
fi

cat <<EOF

Manual verification commands (not executed):
  codesign --verify --deep --strict --verbose=2 "${DEST_APP}"
  open "${DEST_APP}"
EOF
