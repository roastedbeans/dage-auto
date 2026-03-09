# Dage Auto

Adventure Quest Worlds automation — auto abilities and quest turn-in.

## Quick start

```bash
pip install -r requirements.txt
python aqw_gui.py
```

Opens a desktop window. Pick class, set delay, Start/Stop.

## Build standalone app (no Python needed)

```bash
./build.sh
```

Output: `dist/Dage Auto.app`

## CLI

```bash
python aqw_auto.py ability --class "legion revenant"
python aqw_auto.py ability --attack 412344
python aqw_auto.py list
```

**Hotkeys:** Ctrl+Q exit, Ctrl+Shift+Q pause, Ctrl+Space resume
