#!/bin/bash
cd "$(dirname "$0")"
# Use venv if it exists
[ -d "venv" ] && source venv/bin/activate
python3 aqw_gui.py
read -p "Press Enter to close..."
