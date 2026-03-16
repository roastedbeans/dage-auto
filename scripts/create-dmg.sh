#!/bin/bash
# Create DMG for Dage Auto (macOS disk image for distribution)
# Run from project root after build.sh
set -e
cd "$(dirname "$0")/.."

APP="dist/Dage Auto.app"
DMG_NAME="Dage-Auto-macOS"
DMG_DIR="dist/dmg-build"

if [ ! -d "$APP" ]; then
  echo "Error: $APP not found. Run ./build.sh first."
  exit 1
fi

# Clean and prepare DMG folder
rm -rf "$DMG_DIR"
mkdir -p "$DMG_DIR"

# Copy app and helper files
cp -R "$APP" "$DMG_DIR/"
[ -f "dist/fix-quarantine.command" ] && cp dist/fix-quarantine.command "$DMG_DIR/"
# Step images (from dist/ or steps/ depending on how script is run)
if [ -f "dist/1st-step.png" ]; then
  cp dist/1st-step.png dist/2nd-step.png dist/3rd-step.png "$DMG_DIR/" 2>/dev/null || true
elif [ -f "steps/1st-step.png" ]; then
  cp steps/1st-step.png steps/2nd-step.png steps/3rd-step.png "$DMG_DIR/" 2>/dev/null || true
fi

# Symlink to Applications (standard Mac install UX)
ln -s /Applications "$DMG_DIR/Applications"

# Create DMG
rm -f "dist/${DMG_NAME}.dmg"
hdiutil create -volname "Dage Auto" -srcfolder "$DMG_DIR" -ov -format UDZO "dist/${DMG_NAME}.dmg"

# Cleanup
rm -rf "$DMG_DIR"

echo "Done: dist/${DMG_NAME}.dmg"
