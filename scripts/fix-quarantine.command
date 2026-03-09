#!/bin/bash
# Fixes "damaged and can't be opened" on macOS (removes quarantine attribute)
cd "$(dirname "$0")"
APP="Dage Auto.app"
if [ -d "$APP" ]; then
  xattr -cr "$APP"
  echo "Done. You can now open Dage Auto.app"
else
  echo "Error: Dage Auto.app not found. Run this from the extracted release folder."
  exit 1
fi
