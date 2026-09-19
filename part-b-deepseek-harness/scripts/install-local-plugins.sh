#!/usr/bin/env bash
# Pack and install the two plugins written from scratch in this repo.
#
#   ./install-local-plugins.sh [profile]          # default profile: web
#
# Why pack instead of `dsh plugin add ./plugins/<name>`: adding a folder creates a
# pnpm link, and a linked folder outside $DSH_HOME cannot resolve the in-box
# @deepseek-ai/* packages (dsh symlinks those into $DSH_HOME/profiles/node_modules).
# A tarball installs a real copy inside the profile, which resolves.
set -euo pipefail
PROFILE="${1:-web}"
DSH="${DSH_BIN:-dsh}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$(mktemp -d)"
trap 'rm -rf "$OUT"' EXIT

for name in dsh-second-brain dsh-dino-break; do
  echo "--- packing $name"
  npm pack "$HERE/plugins/$name" --pack-destination "$OUT" >/dev/null
  tarball="$(ls "$OUT"/${name}-*.tgz | head -1)"
  echo "--- installing $tarball"
  "$DSH" plugin --profile "$PROFILE" add "$tarball"
done

echo
echo "Done. Restart 'dsh web'. Look for the 'Brain' and 'Break' buttons in the composer row."
