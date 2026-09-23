#!/usr/bin/env bash
# Build a macOS .pkg installer for XT-Forge that installs into the
# current user's ~/Applications with no admin prompt.
#
# Output: dist/XT-Forge-Installer.pkg
#
# How it works:
#   1. pkgbuild wraps XT-Forge.app as a component pkg whose payload
#      installs to /Applications.
#   2. productbuild wraps the component pkg with a Distribution.xml
#      that enables user-scope install (enable_currentUserHome=true).
#      In that mode macOS Installer re-roots /Applications to
#      $HOME/Applications, so the .app lands in ~/Applications
#      without an admin password.
#   3. packaging/scripts/postinstall strips the Gatekeeper quarantine
#      flag and launches the app.
#
# User experience: double-click XT-Forge-Installer.pkg → Continue →
# Install → app opens automatically. No admin, no Terminal.
set -euo pipefail

HERE="$(cd "$(dirname "$0")/.." && pwd)"
APP="$HERE/dist/XT-Forge.app"
COMPONENT="$HERE/dist/XT-Forge-Component.pkg"
DIST_PKG="$HERE/dist/XT-Forge-Installer.pkg"
SCRIPTS_DIR="$HERE/packaging/scripts"

if [ ! -d "$APP" ]; then
  echo "Error: $APP not found. Run 'pyinstaller packaging/pyinstaller_mac.spec' first." >&2
  exit 1
fi

# Stage just the .app so pkgbuild's payload is exactly one item at
# /Applications/XT-Forge.app when extracted.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$APP" "$STAGE/"

chmod +x "$SCRIPTS_DIR/postinstall"

rm -f "$COMPONENT" "$DIST_PKG"

pkgbuild \
  --root "$STAGE" \
  --scripts "$SCRIPTS_DIR" \
  --install-location /Applications \
  --identifier com.xtforge.desktop \
  --version 0.1.0 \
  "$COMPONENT"

productbuild \
  --distribution "$HERE/packaging/distribution.xml" \
  --package-path "$HERE/dist" \
  "$DIST_PKG"

# Component pkg was just a staging artifact — the shipped file is the
# distribution pkg.
rm -f "$COMPONENT"

echo "Built: $DIST_PKG"
echo
echo "Users install by double-clicking XT-Forge-Installer.pkg. The"
echo "installer copies the app into ~/Applications, strips quarantine,"
echo "and launches it automatically. No admin required."
