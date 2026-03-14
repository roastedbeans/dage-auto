# Dage Auto

Adventure Quest Worlds automation — auto abilities and quest turn-in.

## Quick start

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python aqw_gui.py
```

Opens a desktop window. Pick class, set delay, Start/Stop.

## Build standalone app (no Python needed)

```bash
./build.sh
```

Output: `dist/Dage Auto.app`

## Using the macOS standalone app

1. **Download** the latest release: [Releases](https://github.com/roastedbeans/dage-auto/releases) → download `Dage-Auto-macOS.zip`
2. **Extract** the zip (double-click or right-click → Open)
3. **Fix quarantine** (if you see "damaged and can't be opened"):
   - Double-click `fix-quarantine.command` in the folder, or
   - In Terminal: `xattr -cr "/path/to/Dage Auto.app"`
4. **Grant Accessibility** (System Settings → Privacy & Security → Accessibility → add Dage Auto) — required for sending keys to the game
5. **Open** `Dage Auto.app`

**If you rebuilt or updated the app:** Remove the old Dage Auto from Accessibility first, then add the new app again. Old entries can block the new build from working.

The zip includes step images (`1st-step.png`, `2nd-step.png`, `3rd-step.png`) as a visual guide.

## Creating a release

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

## TCM class item combo resources

Timeless Chronomancer patterns are based on these guides:

- [AQW Hub – Timeless Chronomancer](https://www.aqwhub.com/class-usage-guides/timeless-chronomancer/)
- [AQW Hub – Power](https://www.aqwhub.com/class-usage-guides/tcm-power/)
- [AQW Hub – Transience](https://www.aqwhub.com/class-usage-guides/tcm-transience/)
- [AQW Hub – Paradise](https://www.aqwhub.com/class-usage-guides/tcm-paradise/)
- [SLGMA guide (Google Doc)](https://docs.google.com/document/d/1pHEYDB5JM2qSBFYwVs6Hkj17x24TElB1mtuQUyidv18/edit)
- [AQW Wiki – Timeless Chronomancer](https://aqwwiki.wikidot.com/timeless-chronomancer)
