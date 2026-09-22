#!/usr/bin/env bash
# Wrap dist/XT-Forge.app into dist/XT-Forge.dmg using create-dmg.
# Prereq (Homebrew):  brew install create-dmg
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HERE/dist/XT-Forge.app"
DMG="$HERE/dist/XT-Forge.dmg"

if [ ! -d "$APP" ]; then
  echo "Error: $APP not found. Run 'pyinstaller packaging/pyinstaller_mac.spec' first." >&2
  exit 1
fi

rm -f "$DMG"

# create-dmg options are conservative here; users can prettify the icon layout
# once the tool is on the machine.
create-dmg \
  --volname "XT-Forge" \
  --window-size 540 380 \
  --icon-size 96 \
  --icon "XT-Forge.app" 140 190 \
  --app-drop-link 400 190 \
  --hide-extension "XT-Forge.app" \
  "$DMG" \
  "$APP"

echo "Built: $DMG"
