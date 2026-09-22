#!/usr/bin/env bash
# XT-Forge — per-user installer for macOS.
#
# Installs XT-Forge.app into ~/Applications so the target user does not
# need admin rights, strips the Gatekeeper quarantine flag so the app
# launches without the "translocated location" prompt, then opens it.
#
# Ships inside the DMG next to XT-Forge.app. User double-clicks this
# file after mounting the DMG.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$HERE/XT-Forge.app"
DEST_DIR="$HOME/Applications"
APP_DEST="$DEST_DIR/XT-Forge.app"

if [[ ! -d "$APP_SRC" ]]; then
  echo "XT-Forge.app not found next to the installer at:"
  echo "  $APP_SRC"
  echo
  echo "Make sure you double-clicked install.command from inside the mounted"
  echo "XT-Forge.dmg — not from a copy on your Desktop or Downloads."
  read -r -p "Press return to close…" _
  exit 1
fi

mkdir -p "$DEST_DIR"

if [[ -d "$APP_DEST" ]]; then
  echo "Replacing existing install at $APP_DEST"
  rm -rf "$APP_DEST"
fi

echo "Copying XT-Forge.app to $DEST_DIR …"
cp -R "$APP_SRC" "$DEST_DIR/"

# Strip the download quarantine flag — this is what makes macOS ask to
# "move to the Applications folder" and blocks the first launch on
# unsigned apps.
echo "Removing quarantine flag…"
xattr -dr com.apple.quarantine "$APP_DEST" 2>/dev/null || true

echo "Launching XT-Forge Agent…"
open "$APP_DEST"

echo
echo "Done. XT-Forge Agent is installed in ~/Applications."
echo "You can eject the DMG now."
