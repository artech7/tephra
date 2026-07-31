#!/usr/bin/env bash
# Build Tephra.app and a .dmg. Run on macOS.
#
#   ./packaging/build_macos.sh                       unsigned, local use
#   SIGN_ID="Developer ID Application: You (TEAM)" \
#   NOTARY_PROFILE=tephra ./packaging/build_macos.sh  signed + notarised
set -euo pipefail
cd "$(dirname "$0")/.."

VERSION="${VERSION:-1.0.0}"
ARCH="$(uname -m)"
DMG="dist/Tephra-${VERSION}-macos-${ARCH}.dmg"

echo "==> deps"
python3 -m pip install -q -r requirements-desktop.txt

echo "==> icon"
# .icns can only be produced by iconutil, which is macOS-only.
iconutil -c icns packaging/icon.iconset -o packaging/icon.icns

echo "==> freeze"
rm -rf build dist
python3 -m PyInstaller tephra.spec --noconfirm --log-level WARN

APP="dist/Tephra.app"
[ -d "$APP" ] || { echo "no app bundle produced"; exit 1; }

if [ -n "${SIGN_ID:-}" ]; then
  echo "==> sign"
  # Deep-sign every nested binary first, then the bundle. Hardened runtime is
  # mandatory for notarisation.
  find "$APP" -type f \( -name "*.dylib" -o -name "*.so" \) -exec \
    codesign --force --timestamp --options runtime --sign "$SIGN_ID" {} \;
  codesign --force --deep --timestamp --options runtime \
           --entitlements packaging/entitlements.plist \
           --sign "$SIGN_ID" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
else
  echo "==> skipping signing (SIGN_ID unset)"
  echo "    Gatekeeper will block this build on other Macs. Users must"
  echo "    right-click > Open, or run: xattr -dr com.apple.quarantine /Applications/Tephra.app"
fi

echo "==> dmg"
rm -f "$DMG"
if command -v create-dmg >/dev/null 2>&1; then
  create-dmg --volname "Tephra" --window-size 560 380 \
    --icon "Tephra.app" 150 180 --app-drop-link 410 180 \
    --icon-size 110 --hide-extension "Tephra.app" \
    "$DMG" "$APP"
else
  # hdiutil fallback: no drag-to-Applications affordance, but a valid dmg
  STAGE="$(mktemp -d)"
  cp -R "$APP" "$STAGE/"
  ln -s /Applications "$STAGE/Applications"
  hdiutil create -volname "Tephra" -srcfolder "$STAGE" -ov -format UDZO "$DMG"
  rm -rf "$STAGE"
fi

if [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "==> notarise (this waits on Apple, usually 2-10 min)"
  xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  xcrun stapler staple "$DMG"
  xcrun stapler validate "$DMG"
fi

echo "==> done: $DMG"
