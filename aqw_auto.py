#!/usr/bin/env python3
"""
Dage Auto - Refined CLI for Adventure Quest Worlds automation.
Auto abilities and quest turn-in. Cross-platform (Mac/Windows/Linux).
"""

import argparse
import queue
import subprocess
import sys
import time
import threading

try:
    import pyautogui
    from pynput import keyboard
    from pynput.keyboard import Controller as KeyController
except ImportError:
    print("Missing dependencies. Run: pip install pyautogui pynput")
    sys.exit(1)

# Use pynput for key presses (pyautogui has "Key not implemented" on macOS for numbers)
# Lazy-initialized on first key press to avoid blocking the GUI during import
_keyboard_ctrl = None


def _get_keyboard_ctrl() -> KeyController:
    global _keyboard_ctrl
    if _keyboard_ctrl is None:
        _keyboard_ctrl = KeyController()
    return _keyboard_ctrl

# When set, keys are sent to this app (macOS only) - allows multitasking
target_pid = None
target_pids = []  # PIDs to try (main first for Electron, then Renderer)
use_psn_backend = False  # Use CGEventPostToPSN instead of postToPid (may work for Electron)
target_app_name = None

# Apps to try for --background (first running one is used)
# Artix Game Launcher = installed desktop client (exact name from /Applications)
BACKGROUND_APP_ORDER = [
    "Artix Game Launcher",
    "Google Chrome",
    "Safari",
    "Arc",
    "Firefox",
]

# macOS key codes for digits 1-6
# Note: 0x16=22 is key 6, 0x17=23 is key 5 on Mac number row
MAC_KEY_CODES = {"1": 18, "2": 19, "3": 20, "4": 21, "5": 23, "6": 22}

# Class combos: (combo, delay). Delay None = compute from CLASS_COOLDOWNS.
CLASSES = {
    "random": ("2345", 0.1),
    "archmage": ("3214321432145", None),  # Arcane Sigil (5) costs 40% HP
    "lightcaster": ("423523232", None),
    "archpaladin": ("423523", None),  # Hymn of Light (3) heals self
    "scarlet sorceress": ("523532534", None),
    "cavalier guard": ("6524325234", None),
    "dragon of time": ("23543", None),  # 2&4 cost 10% HP per target; use Safe mode for solo
    "blaze binder": ("2354", None),
    "legion revenant": ("4523", None),  # Depraved Empowerment (4) targets self
    "lord of order": ("2345", None),
    "void highlord": ("2345234234", None),  # 2&4 cost 20% HP; 3 has lifesteal heal
    "timeless chronomancer": ("42224253", None),  # Delay auto-computed when pattern selected
    "chrono shadowhunter": ("24444445", None),  # 2=Reload, 4=FMJ bullets, 5=Silver Bullet nuke
}

# Skill cooldowns (seconds) - from AQW wiki. Used to compute min delay.
CLASS_COOLDOWNS = {
    "archmage": {"1": 1.5, "2": 4.0, "3": 2.4, "4": 4.0, "5": 3.0},
    "archpaladin": {"1": 2.0, "2": 5.0, "3": 10.0, "4": 25.0, "5": 25.0},
    "blaze binder": {"1": 2.0, "2": 4.0, "3": 8.0, "4": 16.0, "5": 12.0},
    "cavalier guard": {"1": 2.0, "2": 4.0, "3": 5.0, "4": 6.0, "5": 8.0, "6": 20.0},
    "dragon of time": {"1": 2.0, "2": 6.0, "3": 3.0, "4": 6.0, "5": 8.0},
    "legion revenant": {"1": 1.5, "2": 6.0, "3": 6.0, "4": 6.0, "5": 12.0},
    "lightcaster": {"1": 2.0, "2": 4.0, "3": 4.0, "4": 12.0, "5": 15.0},
    "lord of order": {"1": 2.0, "2": 4.0, "3": 5.0, "4": 6.0},
    "scarlet sorceress": {"1": 2.0, "2": 4.0, "3": 4.0, "4": 5.0, "5": 6.0},
    "void highlord": {"1": 2.3, "2": 4.0, "3": 5.0, "4": 4.0, "5": 15.0},
    # Chrono ShadowHunter (same as Chrono ShadowSlayer): 2=Reload 6s, 4=FMJ 1.5s, 5=Silver Bullet 6s
    "chrono shadowhunter": {"2": 6.0, "4": 1.5, "5": 6.0},
}

# TCM skill cooldowns (seconds) - from AQW wiki
# Skill 1: Corrupted Sand Strike (2s) — auto attack
# Skill 2: Sand Rift (2.5s) — deals dmg, applies Temporal Rift (stacks 4x, 30s) used by other skills
# Skill 3: Hourglass Inversion (8s) — heal self, consumes Temporal Rift stacks
#   + Hourglass of Power: grants Power (+10% all stats) for 30s
#   + Infinite Corruption: grants Hourglass Heal (HoT) for 20s
# Skill 4: Corruption Through Time (6s) — +20% damage for 10s (doesn't stack)
#   + Entropic Corruption: Entropic Power (+100% dmg, 4s), Entropic Mana (+30% haste/-50% mana, 7s),
#                          Entropic Harm (enemy +150% dmg taken, 10s), Focus (enemy attacks you, 3s)
#   + Hourglass of Transience: 1st press = Transient (self DoT, 10s);
#                              2nd press while Transient active = Ephemeral (+50% dodge/dmg, 5s)
# Skill 5: Temporal Collapse (15s) — deals dmg based on recent dmg dealt, consumes Temporal Rift stacks
TCM_COOLDOWNS = {"1": 2.0, "2": 2.5, "3": 8.0, "4": 6.0, "5": 15.0, "6": 20.0}


def _min_delay_for_combo(combo: str, cooldowns: dict) -> float:
    """
    Compute minimum uniform delay (seconds) between keys so no skill is used before its cooldown.
    For each key K at positions [i1, i2, ...], we need (gap in keys) * delay >= cooldown[K].
    Returns delay with small buffer (1.02x) for input latency.
    """
    n = len(combo)
    min_d = 0.0
    for key in set(combo):
        cd = cooldowns.get(key, 0)
        if cd <= 0:
            continue
        positions = [i for i, c in enumerate(combo) if c == key]
        for idx in range(len(positions)):
            curr = positions[idx]
            nxt = positions[(idx + 1) % len(positions)]
            if idx + 1 < len(positions):
                gap = nxt - curr  # keys between = delays between
            else:
                gap = n - curr + nxt  # wrap to next cycle
            if gap <= 0:
                continue
            required = cd / gap
            min_d = max(min_d, required)
    return round(min_d * 1.02, 2)  # 2% buffer for input latency


# Classes with multiple patterns: user can toggle between them in GUI
# Each entry: (combo, delay, display_name) or (combo, delay, display_name, consumable_hint).
# consumable_hint: text for slot 6 (class item) — shown for TCM.
#
# TCM class item combo resources:
#   AQW Hub:  https://www.aqwhub.com/class-usage-guides/timeless-chronomancer/
#   Power:    https://www.aqwhub.com/class-usage-guides/tcm-power/
#   Transience: https://www.aqwhub.com/class-usage-guides/tcm-transience/
#   Paradise: https://www.aqwhub.com/class-usage-guides/tcm-paradise/
#   SLGMA:    https://docs.google.com/document/d/1pHEYDB5JM2qSBFYwVs6Hkj17x24TElB1mtuQUyidv18/edit
#   AQW Wiki: https://aqwwiki.wikidot.com/timeless-chronomancer
CLASS_PATTERNS = {
    "dragon of time": [
        ("23543", None, "DPS (2&4 cost 10% HP each)"),
        ("2353", None, "Safe (no Burning Fates, no self-damage from 4)"),
    ],
    # TCM: 6 class items + Power+Entropic (pre-apply hourglass, swap to corruption). Key 6 (20s CD) = consumable thread.
    "timeless chronomancer": [
        ("34222425", None, "Hourglass of Power", "Hourglass of Power"),
        ("42242253", None, "Hourglass of Transience", "Hourglass of Transience"),
        ("42224253", None, "Hourglass of Paradise", "Hourglass of Paradise"),
        ("634222425", None, "Entropic Corruption", "Entropic Corruption"),
        ("634222425", None, "Power + Entropic (pre-apply Power, equip Entropic)", "Pre-apply Hourglass of Power (3), then equip Entropic Corruption"),
        ("142224253", None, "Infinite Corruption", "Infinite Corruption"),
        ("642434223422342262422253", None, "Foresee Corruption", "Foresee Corruption"),
    ],
}


running = True
is_paused = False
_log_queue = None  # When set (by GUI), log lines go here instead of print


def _log(msg: str = "", end: str = "\n"):
    """Log to queue (GUI) or print (CLI)."""
    if _log_queue is not None:
        try:
            _log_queue.put(msg + end)
        except Exception:
            pass
    else:
        print(msg, end=end)


def _find_background_app() -> tuple[str, int] | None:
    """Find first running AQW-capable app (macOS). Returns (app_name, pid) or None."""
    for app_name in BACKGROUND_APP_ORDER:
        pid = _get_pid_for_app(app_name)
        if pid:
            return (app_name, pid)
    return None


def _get_renderer_pids(main_pid: int) -> list[int]:
    """Get Renderer process PIDs for Electron apps. The game runs in a Renderer."""
    if sys.platform != "darwin":
        return []
    try:
        result = subprocess.run(
            ["pgrep", "-P", str(main_pid)],
            capture_output=True, text=True, timeout=2
        )
        if result.returncode != 0:
            return []
        child_pids = result.stdout.strip().split()
        if not child_pids:
            return []
        # Single ps call for all children instead of N calls
        proc = subprocess.run(
            ["ps", "-o", "pid=,comm=", "-p", ",".join(child_pids)],
            capture_output=True, text=True, timeout=2
        )
        if proc.returncode != 0:
            return []
        renderer_pids = []
        for line in proc.stdout.strip().splitlines():
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and "Renderer" in parts[1]:
                renderer_pids.append(int(parts[0]))
        return renderer_pids
    except Exception:
        return []


def _get_pid_for_app(app_name: str) -> int | None:
    """Get PID of app by name (macOS). Returns None if not found."""
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace
        workspace = NSWorkspace.sharedWorkspace()
        app_name_lower = app_name.lower()
        for app in workspace.runningApplications():
            name = (app.localizedName() or "").lower()
            if name == app_name_lower or app_name_lower in name:
                return int(app.processIdentifier())
        return None
    except Exception:
        return None


def _get_psn_for_pid(pid: int):
    """Get ProcessSerialNumber from PID. Returns PSN object or None."""
    if sys.platform != "darwin":
        return None
    try:
        from HIServices import GetProcessForPID
        result, psn = GetProcessForPID(pid, None)
        if result == 0 and psn:
            return psn
    except Exception:
        pass
    return None


def _press_key_to_app(char: str, pid: int, use_psn: bool = False):
    """Send key to app (macOS). Uses CGEventPostToPSN (legacy) or postToPid."""
    if sys.platform != "darwin" or char not in MAC_KEY_CODES:
        return
    key_code = MAC_KEY_CODES[char]
    try:
        from Quartz import (
            CGEventCreateKeyboardEvent,
            CGEventSourceCreate,
            kCGEventSourceStateHIDSystemState,
            CGEventPostToPSN,
        )
        source = CGEventSourceCreate(kCGEventSourceStateHIDSystemState)
        event_down = CGEventCreateKeyboardEvent(source, key_code, True)
        event_up = CGEventCreateKeyboardEvent(source, key_code, False)
        if event_down and event_up:
            if use_psn:
                psn = _get_psn_for_pid(pid)
                if psn:
                    CGEventPostToPSN(psn, event_down)
                    CGEventPostToPSN(psn, event_up)
                    return
            event_down.postToPid(pid)
            event_up.postToPid(pid)
    except Exception:
        try:
            from Quartz import CGEventCreateKeyboardEvent, CGEventPostToPSN
            event_down = CGEventCreateKeyboardEvent(None, key_code, True)
            event_up = CGEventCreateKeyboardEvent(None, key_code, False)
            if event_down and event_up:
                if use_psn:
                    psn = _get_psn_for_pid(pid)
                    if psn:
                        CGEventPostToPSN(psn, event_down)
                        CGEventPostToPSN(psn, event_up)
                        return
                event_down.postToPid(pid)
                event_up.postToPid(pid)
        except Exception:
            pass


_key_lock = threading.Lock()
_KEY_MIN_INTERVAL = 0.08  # Min seconds between keys so game registers each (avoids drop after consumable 6)


def _sleep(seconds: float):
    """Sleep in small chunks so the loop exits quickly when running is cleared."""
    end = time.time() + seconds
    while running:
        remaining = end - time.time()
        if remaining <= 0:
            break
        time.sleep(min(0.05, remaining))


def _press_key(char: str):
    """Press a key using pynput, or send to target app if --app is set (macOS)."""
    global target_pid, target_pids
    with _key_lock:
        pid_to_use = target_pids[0] if target_pids else target_pid
        if pid_to_use and char in MAC_KEY_CODES:
            _press_key_to_app(char, pid_to_use, use_psn_backend)
        else:
            ctrl = _get_keyboard_ctrl()
            ctrl.press(char)
            ctrl.release(char)
        time.sleep(_KEY_MIN_INTERVAL)


def run_ability_combo(combo: str, delay: float):
    """Loop: press 1 (target enemy first) + combo keys. delay: seconds between keys."""
    global running, is_paused
    while running:
        if not is_paused:
            _press_key("1")
            _sleep(0.12)
            for key in combo:
                if not running:
                    break
                _press_key(key)
                _sleep(delay)
        _sleep(0.03)


def run_consumable(interval: float = 6.0):
    """Press consumable key (6) periodically."""
    global running, is_paused
    while running:
        if not is_paused:
            _press_key("6")
        _sleep(interval)


def run_accept_drop(x: int, y: int, interval: float = 0.5):
    """Periodically click to accept dropped items when killing monsters."""
    global running, is_paused
    while running:
        if not is_paused:
            pyautogui.moveTo(x, y, duration=0)
            pyautogui.click()
        _sleep(interval)


def run_quest_turnin(quest_x: int, quest_y: int, turnin_x: int, turnin_y: int,
                    accept_x: int | None = None, accept_y: int | None = None):
    """Loop: click quest, turn-in, then optionally accept item."""
    global running, is_paused
    has_accept = accept_x is not None and accept_y is not None
    while running:
        if not is_paused:
            pyautogui.moveTo(quest_x, quest_y, duration=0)
            pyautogui.click()
            _sleep(0.4)
            if not running:
                break
            pyautogui.moveTo(turnin_x, turnin_y, duration=0)
            pyautogui.click()
            if has_accept and running:
                _sleep(0.25)
                if running:
                    pyautogui.moveTo(accept_x, accept_y, duration=0)
                    pyautogui.click()
        _sleep(0.05)


def run_stdin_fallback():
    """Press Enter in terminal to stop (CLI only; GUI uses Stop button)."""
    global running
    try:
        input("\n[Press Enter in this terminal to stop]\n")
        running = False
    except EOFError:
        pass  # No stdin (e.g. when run from GUI) — just exit thread


def run_ability_from_gui(config: dict, log_queue: queue.Queue):
    """
    Run ability combo in-process (from GUI). Avoids spawning a second app in the Dock.
    config: class_name, attack, delay, quest_turnin, quest_pos, no_consumable, no_background
    """
    global running, is_paused, target_pid, target_pids, target_app_name, use_psn_backend
    globals()["_log_queue"] = log_queue

    class_name = config.get("class_name") or ""
    attack = config.get("attack", "")
    delay = config.get("delay", 1.0)
    quest_turnin = config.get("quest_turnin", False)
    quest_pos = config.get("quest_pos")
    accept_drop = config.get("accept_drop", False)
    accept_drop_pos = config.get("accept_drop_pos")
    no_consumable = config.get("no_consumable", False)
    no_background = config.get("no_background", False)
    pattern_index = config.get("pattern_index")

    # Resolve combo and delay
    if class_name and class_name in CLASSES:
        # Use selected pattern if class has multiple patterns
        if class_name in CLASS_PATTERNS and pattern_index is not None:
            patterns = CLASS_PATTERNS[class_name]
            idx = min(pattern_index, len(patterns) - 1)
            combo, delay_val = patterns[idx][0], patterns[idx][1]
            if delay_val is None:
                cooldowns = TCM_COOLDOWNS if class_name == "timeless chronomancer" else CLASS_COOLDOWNS.get(class_name, {})
                delay = _min_delay_for_combo(combo, cooldowns) if cooldowns else config.get("delay", 1.0)
            else:
                delay = delay_val
        else:
            preset = CLASSES[class_name]
            combo, delay_val = preset[0], preset[1]
            if delay_val is None:
                cooldowns = CLASS_COOLDOWNS.get(class_name, {})
                delay = _min_delay_for_combo(combo, cooldowns) if cooldowns else config.get("delay", 1.0)
            else:
                delay = delay_val
    else:
        combo = attack if attack and all(c in "123456" for c in attack) else "412344"

    # If combo already includes key 6, suppress the consumable thread to avoid double-pressing
    if "6" in combo:
        no_consumable = True

    # Consumable interval: TCM hourglass 20s; others use 6s minimum (AQW consumable cooldown)
    consumable_interval = TCM_COOLDOWNS.get("6", 6.0) if class_name == "timeless chronomancer" else 6.0

    # Target app (macOS)
    target_pid = None
    target_pids = []
    target_app_name = None
    use_psn_backend = True
    app_name = None
    if sys.platform == "darwin" and not no_background:
        found = _find_background_app()
        if found:
            app_name, target_pid = found
            target_app_name = app_name
            renderers = _get_renderer_pids(target_pid)
            target_pids = [target_pid] + renderers if renderers else [target_pid]

    _log("\n--- Running ---")
    pattern_name = ""
    if class_name in CLASS_PATTERNS and pattern_index is not None:
        patterns = CLASS_PATTERNS[class_name]
        idx = min(pattern_index, len(patterns) - 1)
        pattern_name = f"  Pattern: {patterns[idx][2]}\n"
    delay_str = f"{delay}s"
    _log(f"{pattern_name}  Combo: {combo}  Delay: {delay_str}")
    _log(f"  Consumable (key 6): {'Off (6 in combo)' if no_consumable and '6' in combo else 'Off' if no_consumable else f'On (every {consumable_interval:.0f}s)'}")
    _log(f"  Target app: {target_app_name or 'focused window'}")
    _log(f"  Quest turn-in: {'Yes' if quest_pos else 'No'}")
    _log(f"  Accept drop: {'Yes' if accept_drop_pos else 'No'}")
    running = True
    threads = [
        threading.Thread(target=run_ability_combo, args=(combo, delay), daemon=True),
        threading.Thread(target=run_stdin_fallback, daemon=True),
    ]
    if not no_consumable:
        threads.append(threading.Thread(target=run_consumable, args=(consumable_interval,), daemon=True))
    if quest_pos and len(quest_pos) >= 4:
        args = tuple(quest_pos[:6]) if len(quest_pos) >= 6 else tuple(quest_pos[:4])
        threads.append(threading.Thread(target=run_quest_turnin, args=args, daemon=True))
    if accept_drop_pos and len(accept_drop_pos) == 2:
        threads.append(threading.Thread(target=run_accept_drop, args=accept_drop_pos, daemon=True))

    for t in threads:
        t.start()

    try:
        while running:
            time.sleep(0.05)
    except KeyboardInterrupt:
        running = False

    _log("Done.")
    globals()["_log_queue"] = None


def record_positions():
    """Record quest, turn-in, and optionally accept positions (use Enter - no special permissions needed)."""
    print("\n--- Record positions ---")
    print("  1. Move cursor over QUEST, then press Enter")
    input()
    qx, qy = pyautogui.position()
    print(f"     Quest: ({qx}, {qy})")
    print("  2. Move cursor over TURN-IN button, then press Enter")
    input()
    tx, ty = pyautogui.position()
    print(f"     Turn-in: ({tx}, {ty})")
    print("  3. (Optional) Move cursor over ACCEPT, press Enter. Type n+Enter to skip.")
    if input().strip().lower() == "n":
        print("     Skipped accept")
        return qx, qy, tx, ty
    ax, ay = pyautogui.position()
    print(f"     Accept: ({ax}, {ay})")
    return qx, qy, tx, ty, ax, ay


def main():
    parser = argparse.ArgumentParser(
        description="Dage Auto - Auto abilities & quest turn-in for Adventure Quest Worlds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python aqw_auto.py ability --class "legion revenant"  # Use class preset
  python aqw_auto.py ability --attack 412344    # Custom attack pattern
  python aqw_auto.py list                      # Show class list

  (Quest turn-in: use Enter in terminal to record positions)
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # ability
    ap = subparsers.add_parser("ability", help="Run auto ability combo")
    ap.add_argument(
        "-C", "--class",
        dest="class_name",
        choices=list(CLASSES.keys()),
        help="Class preset (use 'list' to see options)",
    )
    ap.add_argument(
        "--attack",
        type=str,
        metavar="KEYS",
        help="Custom attack pattern to loop (e.g. 412344)",
    )
    ap.add_argument(
        "-d", "--delay",
        type=float,
        default=None,
        metavar="SEC",
        help="Delay between keys (default: class preset or 1.0 for --attack)",
    )
    ap.add_argument(
        "-q", "--quest-turnin",
        action="store_true",
        help="Also auto turn-in quests (records positions interactively)",
    )
    ap.add_argument(
        "--quest-positions",
        type=str,
        metavar="QX,QY,TX,TY[,AX,AY]",
        help="Quest/turn-in coords (e.g. 100,200,300,400 or 100,200,300,400,50,60 for accept)",
    )
    ap.add_argument(
        "--accept-drop",
        action="store_true",
        help="Auto-click to accept dropped items when killing monsters",
    )
    ap.add_argument(
        "--accept-drop-position",
        type=str,
        metavar="X,Y",
        help="Position for accept drop (e.g. 400,300)",
    )
    ap.add_argument(
        "--no-consumable",
        action="store_true",
        help="Don't auto-press consumable (key 6)",
    )
    ap.add_argument(
        "--app",
        type=str,
        metavar="NAME",
        help="Target app by name (macOS). e.g. 'Artix Game Launcher', 'Google Chrome'",
    )
    ap.add_argument(
        "--no-background",
        action="store_true",
        help="Keys go to focused window instead of auto-targeting app.",
    )
    ap.add_argument(
        "--no-psn",
        action="store_true",
        help="Use postToPid instead of PSN (default is PSN for Artix).",
    )
    ap.add_argument(
        "--pattern",
        type=int,
        default=0,
        metavar="N",
        help="Pattern index for classes with multiple (e.g. dragon of time: 0=DPS, 1=Safe).",
    )

    # list
    subparsers.add_parser("list", help="Show class list")

    args = parser.parse_args()

    if args.command == "list":
        print("\nClasses:\n")
        for name, preset in CLASSES.items():
            combo, delay_val = preset[0], preset[1]
            delay_str = f"{delay_val}s" if delay_val is not None else "auto"
            patterns_note = f"  ({len(CLASS_PATTERNS[name])} patterns)" if name in CLASS_PATTERNS else ""
            print(f"  {name:20} combo={combo:15} delay={delay_str}{patterns_note}")
        print("\nUse: python aqw_auto.py ability --class <name>")
        print("Or:  python aqw_auto.py ability --attack 412344")
        return

    if args.command != "ability":
        parser.print_help()
        return

    # Resolve combo and delay
    if getattr(args, "class_name", None):
        class_name = args.class_name
        pattern_index = getattr(args, "pattern", 0)
        if class_name in CLASS_PATTERNS and pattern_index < len(CLASS_PATTERNS[class_name]):
            combo, delay_val = CLASS_PATTERNS[class_name][pattern_index][0], CLASS_PATTERNS[class_name][pattern_index][1]
        else:
            preset = CLASSES[class_name]
            combo, delay_val = preset[0], preset[1]
        if args.delay is not None:
            delay = args.delay
        elif delay_val is None:
            cooldowns = TCM_COOLDOWNS if class_name == "timeless chronomancer" else CLASS_COOLDOWNS.get(class_name, {})
            delay = _min_delay_for_combo(combo, cooldowns) if cooldowns else 1.0
        else:
            delay = delay_val
        print(f"Using class '{class_name}': {combo} @ {delay}s")
    elif args.attack:
        combo = args.attack
        delay = args.delay if args.delay is not None else 1.0
        print(f"Using attack pattern: {combo} @ {delay}s")
    else:
        print("Error: provide --class or --attack")
        ap.print_help()
        sys.exit(1)

    # Target app for background key sending (macOS) - default: auto-find app
    global target_pid, target_pids, target_app_name, use_psn_backend
    if sys.platform != "darwin":
        if args.app or not args.no_background:
            print("Warning: Background mode is macOS only. Keys will go to focused window.")
    else:
        if args.app:
            target_pid = _get_pid_for_app(args.app)
            if target_pid:
                target_app_name = args.app
                use_psn_backend = not args.no_psn
                renderers = _get_renderer_pids(target_pid)
                target_pids = [target_pid] + renderers if renderers else [target_pid]
                method = "PSN" if use_psn_backend else "PID"
                pid_info = f"{method} {target_pids[0]}" + (f" (+{len(target_pids)-1} fallback)" if len(target_pids) > 1 else "")
                print(f"Targeting app: {args.app} ({pid_info})")
            else:
                print(f"Warning: App '{args.app}' not found. Keys will go to focused window.")
                target_pid = None
                target_pids = []
                target_app_name = None
                use_psn_backend = False
        elif not args.no_background:
            found = _find_background_app()
            if found:
                app_name, target_pid = found
                target_app_name = app_name
                args.app = app_name  # For display
                use_psn_backend = not args.no_psn
                renderers = _get_renderer_pids(target_pid)
                target_pids = [target_pid] + renderers if renderers else [target_pid]
                method = "PSN" if use_psn_backend else "PID"
                pid_info = f"{method} {target_pids[0]}" + (f" (+{len(target_pids)-1} fallback)" if len(target_pids) > 1 else "")
                print(f"Background mode: targeting {app_name} ({pid_info})")
            else:
                print("Warning: No AQW app found (Chrome, Safari, Arc, etc.). Keys will go to focused window.")
                target_pid = None
                target_pids = []
                target_app_name = None
                use_psn_backend = False

    # Quest turn-in positions
    quest_pos = None
    if args.quest_turnin:
        pos_str = getattr(args, "quest_positions", None)
        if pos_str:
            try:
                parts = [int(x.strip()) for x in pos_str.split(",")]
                if len(parts) == 4:
                    quest_pos = tuple(parts)
                    print(f"Using quest positions: quest={quest_pos[:2]} turnin={quest_pos[2:]}")
                elif len(parts) == 6:
                    quest_pos = tuple(parts)
                    print(f"Using quest positions: quest={quest_pos[:2]} turnin={quest_pos[2:4]} accept={quest_pos[4:]}")
            except (ValueError, AttributeError):
                pass
        if quest_pos is None:
            quest_pos = record_positions()
            print("\nStarting in 3 seconds... Switch to AQW window!")
            time.sleep(3)

    # Accept drop position (for loot when killing monsters)
    accept_drop_pos = None
    if getattr(args, "accept_drop", False):
        pos_str = getattr(args, "accept_drop_position", None)
        if pos_str:
            try:
                parts = [int(x.strip()) for x in pos_str.split(",")]
                if len(parts) == 2:
                    accept_drop_pos = tuple(parts)
                    print(f"Accept drop position: {accept_drop_pos}")
            except (ValueError, AttributeError):
                pass
        if accept_drop_pos is None:
            print("\n--- Record accept drop ---")
            print("  Move cursor over ACCEPT button (for loot drops), then press Enter")
            input()
            ax, ay = pyautogui.position()
            accept_drop_pos = (ax, ay)
            print(f"  Accept drop: ({ax}, {ay})")
            print("\nStarting in 3 seconds... Switch to AQW window!")
            time.sleep(3)

    # If combo includes key 6, suppress the consumable thread to avoid double-pressing
    if "6" in combo:
        args.no_consumable = True

    consumable_interval = TCM_COOLDOWNS.get("6", 6.0) if getattr(args, "class_name", None) == "timeless chronomancer" else 6.0

    print("\n--- Running ---")
    print(f"  Combo: {combo}  Delay: {delay}s")
    if not (target_pid or target_pids):
        print(f"  Target: focused window (click AQW game first!)")
    else:
        print(f"  Target app: {target_app_name or args.app or 'background'}")
    print(f"  Consumable (key 6): {'Off' if args.no_consumable else f'On (every {consumable_interval:.0f}s)'}")
    print(f"  Quest turn-in: {'Yes' if quest_pos else 'No'}")
    print(f"  Accept drop: {'Yes' if accept_drop_pos else 'No'}")
    print("  (Press Enter in terminal to stop)")
    print()

    global running
    running = True

    threads = [
        threading.Thread(target=run_ability_combo, args=(combo, delay), daemon=True),
        threading.Thread(target=run_stdin_fallback, daemon=True),
    ]

    if not args.no_consumable:
        threads.append(threading.Thread(target=run_consumable, args=(consumable_interval,), daemon=True))
    if quest_pos and len(quest_pos) >= 4:
        qargs = tuple(quest_pos[:6]) if len(quest_pos) >= 6 else tuple(quest_pos[:4])
        threads.append(threading.Thread(target=run_quest_turnin, args=qargs, daemon=True))
    if accept_drop_pos and len(accept_drop_pos) == 2:
        threads.append(threading.Thread(target=run_accept_drop, args=accept_drop_pos, daemon=True))

    for t in threads:
        t.start()

    try:
        while running:
            time.sleep(0.05)
    except KeyboardInterrupt:
        running = False

    print("Done.")


if __name__ == "__main__":
    main()
