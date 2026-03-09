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

## Download (Releases)

Pre-built macOS app: [Releases](https://github.com/roastedbeans/dage-auto/releases)

To create a new release, push a version tag:

```bash
git tag v1.0.0
git push origin v1.0.0
```

This triggers a build and publishes the app as a downloadable zip on the Releases page.

## CLI

```bash
python aqw_auto.py ability --class "legion revenant"
python aqw_auto.py ability --attack 412344
python aqw_auto.py list
```

**Hotkeys:** Ctrl+Q exit, Ctrl+Shift+Q pause, Ctrl+Space resume
