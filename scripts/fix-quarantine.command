#!/bin/bash
# Fixes "damaged and can't be opened" on macOS (removes quarantine attribute)
# Clears quarantine from this folder - app, this script, and any other files
cd "$(dirname "$0")"
if [ -d "Dage Auto.app" ]; then
  xattr -cr .
  echo "Done. You can now open Dage Auto.app"
else
  echo "Error: Dage Auto.app not found. Run this from the extracted release folder."
  exit 1
fi
