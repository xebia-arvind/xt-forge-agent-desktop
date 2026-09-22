#!/usr/bin/env bash
# Wrap dist/XT-Forge.app into dist/XT-Forge.dmg using create-dmg.
# Prereq (Homebrew):  brew install create-dmg
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HERE/dist/XT-Forge.app"
DMG="$HERE/dist/XT-Forge.dmg"
INSTALLER="$HERE/packaging/install.command"

if [ ! -d "$APP" ]; then
  echo "Error: $APP not found. Run 'pyinstaller packaging/pyinstaller_mac.spec' first." >&2
  exit 1
fi

# Stage the DMG payload in a temp dir so the installer sits next to the .app
# on the mounted volume. Users on machines without admin rights can't drop
# into /Applications, so we ship a double-clickable installer that copies
# into ~/Applications and strips the Gatekeeper quarantine flag.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"
cp "$INSTALLER" "$STAGE/"
chmod +x "$STAGE/$(basename "$INSTALLER")"

rm -f "$DMG"

create-dmg \
  --volname "XT-Forge" \
  --window-size 540 380 \
  --icon-size 96 \
  --icon "XT-Forge.app" 140 190 \
  --icon "install.command" 400 190 \
  --hide-extension "XT-Forge.app" \
  "$DMG" \
  "$STAGE"

echo "Built: $DMG"
echo
echo "Users install by double-clicking install.command inside the mounted DMG."
echo "The app is copied to ~/Applications — no admin password required."
