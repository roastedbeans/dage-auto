#!/bin/bash
# Build Dage Auto for Ubuntu/Linux (standalone executable, no Python needed to run)
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

EXE="dist/Dage Auto"
if [ ! -f "$EXE" ]; then
  echo "Build failed: $EXE not found"
  ls -la dist/
  exit 1
fi
chmod +x "$EXE"
echo "Done: $EXE"
