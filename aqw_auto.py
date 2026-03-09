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
    from pynput.keyboard import Controller as KeyController, Key
except ImportError:
    print("Missing dependencies. Run: pip install pyautogui pynput")
    sys.exit(1)

# Use pynput for key presses (pyautogui has "Key not implemented" on macOS for numbers)
keyboard_ctrl = KeyController()

# When set, keys are sent to this app (macOS only) - allows multitasking
target_pid = None
target_pids = []  # PIDs to try (main first for Electron, then Renderer)
use_psn_backend = False  # Use CGEventPostToPSN instead of postToPid (may work for Electron)
target_app_name = None
# Focus mode: briefly activate app, send keys, restore (for Electron apps like Artix Launcher)
use_focus_mode = False

# Apps to try for --background (first running one is used)
# Artix Game Launcher = installed desktop client (exact name from /Applications)
BACKGROUND_APP_ORDER = [
    "Artix Game Launcher",
    "Google Chrome",
    "Safari",
    "Arc",
    "Firefox",
]

# macOS key codes for digits 1-6 and Escape (kVK_Escape = 53)
MAC_KEY_CODES = {"1": 18, "2": 19, "3": 20, "4": 21, "5": 22, "6": 23, "escape": 53}

# Class combos: (combo, delay) or (combo, delay, escape_after_keys)
# escape_after_keys: keys that trigger Escape after press (e.g. buff skills that target self)
CLASSES = {
    "random": ("2345", 0.1),
    "lightcaster": ("423523232", 0.65),
    "archpaladin": ("42352235", 1.0, {"3"}),  # 3 is heal, Escape after to avoid self-target
    "scarlet sorceress": ("523532534", 0.65),
    "cavalier guard": ("6452324325", 0.75),
    "dragon of time": ("23543", 0.8),
    "blaze binder": ("2354", 0.1),
    "legion revenant": ("4523", 1.0, {"4"}),  # 4 is buff, Escape after to avoid self-target
    "lord of order": ("2345", 0.5),
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


def _activate_app_by_name(name: str) -> bool:
    """Activate (focus) app by name. Uses AppleScript for reliability."""
    if sys.platform != "darwin":
        return False
    try:
        script = f'tell application "{name}" to activate'
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=2)
        return True
    except Exception:
        return False


def _get_frontmost_app():
    """Get (app_name, pid) of frontmost app, or None."""
    if sys.platform != "darwin":
        return None
    try:
        from AppKit import NSWorkspace
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app:
            return (app.localizedName(), int(app.processIdentifier()))
        return None
    except Exception:
        return None


def _press_key_via_applescript(char: str) -> bool:
    """Send key via AppleScript (to frontmost app). Returns True if successful."""
    if sys.platform != "darwin":
        return False
    try:
        if char == "escape":
            script = 'tell application "System Events" to key code 53'  # Escape
        elif char in "123456":
            script = f'tell application "System Events" to keystroke "{char}"'
        else:
            return False
        subprocess.run(["osascript", "-e", script], capture_output=True, timeout=1)
        return True
    except Exception:
        return False


def _press_key(char: str):
    """Press a key using pynput, or send to target app if --app is set (macOS)."""
    global target_pid, target_pids, use_focus_mode
    # Focus mode: caller activates app first, we send to focused window
    if use_focus_mode:
        if _press_key_via_applescript(char):
            return
        if char == "escape":
            keyboard_ctrl.press(Key.esc)
            keyboard_ctrl.release(Key.esc)
        else:
            keyboard_ctrl.press(char)
            keyboard_ctrl.release(char)
        return
    pid_to_use = target_pids[0] if target_pids else target_pid
    if char == "escape":
        if pid_to_use:
            _press_key_to_app("escape", pid_to_use, use_psn_backend)
        else:
            keyboard_ctrl.press(Key.esc)
            keyboard_ctrl.release(Key.esc)
    elif pid_to_use and char in MAC_KEY_CODES:
        _press_key_to_app(char, pid_to_use, use_psn_backend)
    else:
        keyboard_ctrl.press(char)
        keyboard_ctrl.release(char)


def run_ability_combo(combo: str, delay: float, escape_after_keys: frozenset | set | None = None):
    """Loop: press 1 (target enemy first) + combo keys. escape_after_keys: press Escape after these (e.g. buff skills)."""
    global running, is_paused, use_focus_mode, target_app_name
    escape_after = escape_after_keys or frozenset()
    prev = None
    while running:
        if not is_paused:
            if use_focus_mode and target_app_name:
                prev = _get_frontmost_app()
                _activate_app_by_name(target_app_name)
                time.sleep(0.06)
            _press_key("1")
            time.sleep(0.12)
            for key in combo:
                _press_key(key)
                if key in escape_after:
                    time.sleep(0.04)
                    _press_key("escape")
                time.sleep(delay)
            if use_focus_mode and prev:
                time.sleep(0.02)
                _activate_app_by_name(prev[0])
        time.sleep(0.03)


def run_consumable(interval: float = 1.0):
    """Press consumable key (6) periodically."""
    global running, is_paused, use_focus_mode, target_app_name
    while running:
        if not is_paused:
            prev = None
            if use_focus_mode and target_app_name:
                prev = _get_frontmost_app()
                _activate_app_by_name(target_app_name)
                time.sleep(0.05)
            _press_key("6")
            if use_focus_mode and prev:
                time.sleep(0.02)
                _activate_app_by_name(prev[0])
        time.sleep(interval)


def run_accept_drop(x: int, y: int, interval: float = 0.5):
    """Periodically click to accept dropped items when killing monsters."""
    global running, is_paused
    while running:
        if not is_paused:
            pyautogui.moveTo(x, y, duration=0)
            pyautogui.click()
        time.sleep(interval)


def run_quest_turnin(quest_x: int, quest_y: int, turnin_x: int, turnin_y: int,
                    accept_x: int | None = None, accept_y: int | None = None):
    """Loop: click quest, turn-in, then optionally accept item."""
    global running, is_paused
    has_accept = accept_x is not None and accept_y is not None
    while running:
        if not is_paused:
            pyautogui.moveTo(quest_x, quest_y, duration=0)
            pyautogui.click()
            time.sleep(0.4)
            pyautogui.moveTo(turnin_x, turnin_y, duration=0)
            pyautogui.click()
            if has_accept:
                time.sleep(0.25)
                pyautogui.moveTo(accept_x, accept_y, duration=0)
                pyautogui.click()
        time.sleep(0.05)


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
    global running, is_paused, target_pid, target_pids, target_app_name, use_focus_mode, use_psn_backend
    globals()["_log_queue"] = log_queue

    class_name = config.get("class_name") or ""
    attack = config.get("attack", "")
    delay = config.get("delay", 0.5)
    quest_turnin = config.get("quest_turnin", False)
    quest_pos = config.get("quest_pos")
    accept_drop = config.get("accept_drop", False)
    accept_drop_pos = config.get("accept_drop_pos")
    no_consumable = config.get("no_consumable", False)
    no_background = config.get("no_background", False)

    # Resolve combo, delay, escape_after_keys
    escape_after_keys = None
    if class_name and class_name in CLASSES:
        preset = CLASSES[class_name]
        combo, delay = preset[0], preset[1]
        escape_after_keys = frozenset(preset[2]) if len(preset) > 2 else None
    else:
        combo = attack if attack and all(c in "123456" for c in attack) else "412344"

    # Target app (macOS)
    target_pid = None
    target_pids = []
    target_app_name = None
    use_focus_mode = False
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
    _log(f"  Combo: {combo}  Delay: {delay}s")
    _log(f"  Target app: {target_app_name or 'focused window'}")
    _log(f"  Quest turn-in: {'Yes' if quest_pos else 'No'}")
    _log(f"  Accept drop: {'Yes' if accept_drop_pos else 'No'}")
    running = True
    threads = [
        threading.Thread(target=run_ability_combo, args=(combo, delay), kwargs={"escape_after_keys": escape_after_keys}, daemon=True),
        threading.Thread(target=run_stdin_fallback, daemon=True),
    ]
    if not no_consumable:
        threads.append(threading.Thread(target=run_consumable, daemon=True))
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
        help="Delay between keys (default: class preset or 0.5 for --attack)",
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
        "--focus",
        action="store_true",
        help="Force focus mode (activate window per combo).",
    )
    ap.add_argument(
        "--no-focus",
        action="store_true",
        help="Disable focus mode (background keys may not work for Artix).",
    )
    ap.add_argument(
        "--no-psn",
        action="store_true",
        help="Use postToPid instead of PSN (default is PSN for Artix).",
    )

    # list
    subparsers.add_parser("list", help="Show class list")

    args = parser.parse_args()

    if args.command == "list":
        print("\nClasses:\n")
        for name, preset in CLASSES.items():
            combo, delay = preset[0], preset[1]
            extra = f"  (Escape after {', '.join(preset[2])})" if len(preset) > 2 else ""
            print(f"  {name:15} combo={combo}  delay={delay}s{extra}")
        print("\nUse: python aqw_auto.py ability --class <name>")
        print("Or:  python aqw_auto.py ability --attack 412344")
        return

    if args.command != "ability":
        parser.print_help()
        return

    # Resolve combo, delay, and escape_after_keys
    escape_after_keys = None
    if getattr(args, "class_name", None):
        preset = CLASSES[args.class_name]
        combo, delay = preset[0], preset[1]
        if args.delay is not None:
            delay = args.delay
        escape_after_keys = preset[2] if len(preset) > 2 else None
        esc_note = " (Escape after 4)" if escape_after_keys else ""
        print(f"Using class '{args.class_name}': {combo} @ {delay}s{esc_note}")
    elif args.attack:
        combo = args.attack
        delay = args.delay if args.delay is not None else 0.5
        print(f"Using attack pattern: {combo} @ {delay}s")
    else:
        print("Error: provide --class or --attack")
        ap.print_help()
        sys.exit(1)

    # Target app for background key sending (macOS) - default: auto-find app
    global target_pid, target_pids, target_app_name, use_focus_mode, use_psn_backend
    if sys.platform != "darwin":
        if args.app or not args.no_background:
            print("Warning: Background mode is macOS only. Keys will go to focused window.")
    else:
        if args.app:
            target_pid = _get_pid_for_app(args.app)
            if target_pid:
                target_app_name = args.app
                use_focus_mode = args.focus or False
                use_psn_backend = not args.no_psn
                renderers = _get_renderer_pids(target_pid)
                target_pids = [target_pid] + renderers if renderers else [target_pid]
                if use_focus_mode:
                    print(f"Targeting {args.app} (focus mode)")
                else:
                    method = "PSN" if use_psn_backend else "PID"
                    pid_info = f"{method} {target_pids[0]}" + (f" (+{len(target_pids)-1} fallback)" if len(target_pids) > 1 else "")
                    print(f"Targeting app: {args.app} ({pid_info})")
            else:
                print(f"Warning: App '{args.app}' not found. Keys will go to focused window.")
                target_pid = None
                target_pids = []
                target_app_name = None
                use_focus_mode = False
                use_psn_backend = False
        elif not args.no_background:
            found = _find_background_app()
            if found:
                app_name, target_pid = found
                target_app_name = app_name
                args.app = app_name  # For display
                use_focus_mode = args.focus or False
                use_psn_backend = not args.no_psn
                renderers = _get_renderer_pids(target_pid)
                target_pids = [target_pid] + renderers if renderers else [target_pid]
                if use_focus_mode:
                    print(f"Background mode: targeting {app_name} (focus mode)")
                else:
                    method = "PSN" if use_psn_backend else "PID"
                    pid_info = f"{method} {target_pids[0]}" + (f" (+{len(target_pids)-1} fallback)" if len(target_pids) > 1 else "")
                    print(f"Background mode: targeting {app_name} ({pid_info})")
            else:
                print("Warning: No AQW app found (Chrome, Safari, Arc, etc.). Keys will go to focused window.")
                target_pid = None
                target_pids = []
                target_app_name = None
                use_focus_mode = False
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

    print("\n--- Running ---")
    print(f"  Combo: {combo}  Delay: {delay}s")
    if not (target_pid or target_pids):
        print(f"  Target: focused window (click AQW game first!)")
    else:
        print(f"  Target app: {target_app_name or args.app or 'background'}")
    print(f"  Quest turn-in: {'Yes' if quest_pos else 'No'}")
    print(f"  Accept drop: {'Yes' if accept_drop_pos else 'No'}")
    print("  (Press Enter in terminal to stop)")
    print()

    global running
    running = True

    threads = [
        threading.Thread(target=run_ability_combo, args=(combo, delay), kwargs={"escape_after_keys": escape_after_keys}, daemon=True),
        threading.Thread(target=run_stdin_fallback, daemon=True),
    ]

    if not args.no_consumable:
        threads.append(threading.Thread(target=run_consumable, daemon=True))
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
