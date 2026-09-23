#!/usr/bin/env bash
# Build a macOS .pkg installer for XT-Forge that installs into the
# current user's ~/Applications with no admin prompt.
#
# Output: dist/XT-Forge-Installer.pkg
#
# How it works:
#   1. pkgbuild wraps XT-Forge.app as a component pkg whose payload
#      lands at /private/tmp/xt-forge-install/ at install time.
#   2. productbuild wraps the component pkg with a Distribution.xml
#      that enables user-scope install (enable_currentUserHome=true).
#   3. macOS Installer.app runs packaging/scripts/postinstall, which
#      moves the .app into $HOME/Applications, strips the Gatekeeper
#      quarantine flag, and launches it.
#
# The user experience is: double-click XT-Forge-Installer.pkg →
# Installer wizard → click Install → app opens automatically. No
# admin, no Terminal.
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

# Stage the .app under a per-build temp root so pkgbuild's --root
# packs exactly one thing at /private/tmp/xt-forge-install/.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/xt-forge-install"
cp -R "$APP" "$STAGE/xt-forge-install/"

chmod +x "$SCRIPTS_DIR/postinstall"

rm -f "$COMPONENT" "$DIST_PKG"

pkgbuild \
  --root "$STAGE" \
  --scripts "$SCRIPTS_DIR" \
  --install-location /private/tmp \
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
echo "postinstall script copies the app into ~/Applications, strips"
echo "quarantine, and launches it automatically. No admin required."
