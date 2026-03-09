#!/bin/bash
# Build Dage Auto.app (standalone, no Python needed to run)
set -e
cd "$(dirname "$0")"
if [ -d "venv" ]; then
  PYTHON="./venv/bin/python"
  "$PYTHON" -m pip install -q pyinstaller pyautogui pynput PySide6
else
  PYTHON="python3"
  pip install -q pyinstaller pyautogui pynput PySide6
fi
"$PYTHON" -m PyInstaller aqw.spec --noconfirm

APP="dist/Dage Auto.app"
EXE="dist/Dage Auto"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
mv "$EXE" "$APP/Contents/MacOS/"

# Create app icon from dage-icon.png
if [ -f "dage-icon.png" ]; then
  ICONSET="build/Dage.iconset"
  mkdir -p "$ICONSET"
  sips -z 16 16     dage-icon.png --out "$ICONSET/icon_16x16.png" 2>/dev/null || true
  sips -z 32 32     dage-icon.png --out "$ICONSET/icon_16x16@2x.png" 2>/dev/null || true
  sips -z 32 32     dage-icon.png --out "$ICONSET/icon_32x32.png" 2>/dev/null || true
  sips -z 64 64     dage-icon.png --out "$ICONSET/icon_32x32@2x.png" 2>/dev/null || true
  sips -z 128 128   dage-icon.png --out "$ICONSET/icon_128x128.png" 2>/dev/null || true
  sips -z 256 256   dage-icon.png --out "$ICONSET/icon_128x128@2x.png" 2>/dev/null || true
  sips -z 256 256   dage-icon.png --out "$ICONSET/icon_256x256.png" 2>/dev/null || true
  sips -z 512 512   dage-icon.png --out "$ICONSET/icon_256x256@2x.png" 2>/dev/null || true
  sips -z 512 512   dage-icon.png --out "$ICONSET/icon_512x512.png" 2>/dev/null || true
  sips -z 1024 1024 dage-icon.png --out "$ICONSET/icon_512x512@2x.png" 2>/dev/null || true
  if iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/Dage.icns" 2>/dev/null; then
    ICON_PLIST="<key>CFBundleIconFile</key><string>Dage</string>"
  else
    ICON_PLIST=""
  fi
  rm -rf "$ICONSET"
else
  ICON_PLIST=""
fi

cat > "$APP/Contents/Info.plist" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>Dage Auto</string>
<key>CFBundleIdentifier</key><string>com.dage.auto</string>
<key>CFBundleName</key><string>Dage Auto</string>
<key>LSMinimumSystemVersion</key><string>10.13</string>
$ICON_PLIST
</dict></plist>
EOF

echo "Done: $APP"
