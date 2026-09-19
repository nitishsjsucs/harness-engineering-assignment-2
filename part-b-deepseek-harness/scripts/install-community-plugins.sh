#!/usr/bin/env bash
# Install the seven community plugins used in Part B into a dsh profile.
#
#   ./install-community-plugins.sh [profile]      # default profile: web
#
# Every plugin here is third-party code that runs in the harness process with
# your permissions. These seven were read before being listed; treat any other
# plugin the same way before installing it.
set -euo pipefail
PROFILE="${1:-web}"
DSH="${DSH_BIN:-dsh}"

PLUGINS=(
  dshmarket                      # plugin market inside Settings (browse + one-click install)
  dsh-find-plugin                # `find_dsh_plugin` tool: search the catalog from chat
  dsh-better-sidebar             # sidebar host: files, terminal, git, subagents
  dsh-context                    # context dashboard + /context command
  dsh-free-search                # keyless web search tools (no DeepSeek search key needed)
  dsh-chat-toc                   # table of contents / bookmarks for a long conversation
  @nonamelego/dsh-catppuccin     # Catppuccin themes + glassmorphism skin
)

echo "Installing ${#PLUGINS[@]} community plugins into profile '$PROFILE'"
for p in "${PLUGINS[@]}"; do
  echo "--- $p"
  if ! "$DSH" plugin --profile "$PROFILE" add "$p"; then
    cat <<'HINT'
That install failed. The usual cause is pnpm refusing a dependency's build script
(dsh-better-sidebar pulls node-pty for its terminal). dsh prints the package name;
allow it in the profile's pnpm-workspace.yaml:

    allowBuilds:
      node-pty: true

then re-run this script. Allowing a build runs that package's code at install time.
HINT
    exit 1
  fi
done

echo
echo "Done. Restart 'dsh web' (or use the Plugins page) to load them."
