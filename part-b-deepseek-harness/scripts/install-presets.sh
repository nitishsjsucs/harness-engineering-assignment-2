#!/usr/bin/env bash
# Copy the custom agent presets into $DSH_HOME/.agent-presets so they appear in
# the mode dropdown beside Standard / Creator / PTC / Minimal.
#
#   ./install-presets.sh
#
# Presets are trusted configuration: a preset grants whatever its plugin rows
# grant. Read a preset before installing it, exactly as you would a plugin.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${DSH_HOME:-$HOME/.dsh}/.agent-presets"

mkdir -p "$DEST"
for preset in ml-researcher research-librarian; do
  rm -rf "${DEST:?}/$preset"
  cp -R "$HERE/presets/$preset" "$DEST/$preset"
  echo "installed $DEST/$preset"
done

echo
echo "Restart 'dsh web'. The presets appear in the session mode dropdown."
