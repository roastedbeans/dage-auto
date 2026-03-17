#!/usr/bin/env python3
"""
Dage Auto - Refined CLI for Adventure Quest Worlds automation.
Auto abilities. Cross-platform (Mac/Windows/Linux).
"""

import argparse
import queue
import subprocess
import sys
import time
import threading

try:
    from pynput import keyboard
    from pynput.keyboard import Controller as KeyController
except ImportError:
    print("Missing dependencies. Run: pip install pynput")
    sys.exit(1)

# Use pynput for key presses (supports macOS number keys)
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

# Delay between skills (2–6) in the rotation. Auto (1) is independent, used for targeting only.
SKILL_DELAY = 1.20

# Class combos: (combo, delay). Combo = rotation keys 2–6; auto (1) is prepended for targeting.
CLASSES = {
    "random": ("2345", 0.1),
    "archmage": ("3214321432145", SKILL_DELAY),
    "lightcaster": ("423523232123423", SKILL_DELAY),
    "archpaladin": ("4235232323232323232323232", SKILL_DELAY),
    "scarlet sorceress": ("52353253423", SKILL_DELAY),
    "cavalier guard": ("65243252342323423234", SKILL_DELAY),
    "dragon of time": ("2354323232", SKILL_DELAY),
    "blaze binder": ("235423232323232323", SKILL_DELAY),
    "legion revenant": ("432532132432", SKILL_DELAY),
    "lord of order": ("234523423423", SKILL_DELAY),
    "void highlord": ("23452342342342", SKILL_DELAY),
    "timeless chronomancer": ("42224253", SKILL_DELAY),
    "chrono shadowhunter": ("24444445", SKILL_DELAY),
    "chaos avenger": ("3542242424242424", SKILL_DELAY),
    "yami no ronin": ("3225225", SKILL_DELAY),
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
    "lord of order": {"1": 2.0, "2": 4.0, "3": 5.0, "4": 6.0, "5": 8.0},
    "scarlet sorceress": {"1": 2.0, "2": 4.0, "3": 4.0, "4": 5.0, "5": 6.0},
    "void highlord": {"1": 2.3, "2": 4.0, "3": 5.0, "4": 4.0, "5": 15.0},
    # Chrono ShadowHunter: 2=Reload 6s, 3=Tracer 3s (dodge), 4=FMJ 1.5s, 5=Silver Bullet 6s
    "chrono shadowhunter": {"2": 6.0, "3": 3.0, "4": 1.5, "5": 6.0},
    # Chaos Avenger: 1=auto 3.0s (weapon speed); 5=Fury Unleashed (35s) excluded
    "chaos avenger": {"1": 3.0, "2": 6.0, "3": 15.0, "4": 6.0},
    # Yami no Ronin: 1=Batto 2s, 2=Tachi 3s, 3=Yami no Maku 14s, 4=Kettou 3s, 5=Jigen Kogeki 6s
    "yami no ronin": {"1": 2.0, "2": 3.0, "3": 14.0, "4": 3.0, "5": 6.0},
}

# TCM cooldowns (seconds) — from tcm-class-item.md
# Skills 1–5:
#   1: Corrupted Sand Strike 2s | 2: Sand Rift 2.5s | 3: Hourglass Inversion 8s
#   4: Corruption Through Time 6s | 5: Temporal Collapse 15s
# Class items (slot 6) — only TCM items from doc:
#   Corruptions: Entropic 6s, Foresee 60s, Infinite 6s
#   Hourglasses: 20s (doc: 2h duration; 20s reuse from wiki)
TCM_SKILL_COOLDOWNS = {"1": 2.0, "2": 2.5, "3": 8.0, "4": 6.0, "5": 15.0}
TCM_CLASS_ITEM_COOLDOWNS = {
    "entropic corruption": 6.0,
    "foresee corruption": 60.0,
    "infinite corruption": 6.0,
    "hourglass of power": 20.0,
    "hourglass of transience": 20.0,
    "hourglass of paradise": 20.0,
}
TCM_COOLDOWNS = {**TCM_SKILL_COOLDOWNS, "6": 20.0}  # default 6 = hourglass


def _tcm_cooldown_for_consumable(hint: str) -> float:
    """Resolve slot-6 cooldown from consumable_hint using TCM_CLASS_ITEM_COOLDOWNS."""
    if not hint:
        return 20.0
    hint_lower = hint.lower()
    # Longest match first (e.g. "entropic corruption" before "entropic")
    for item, cd in sorted(TCM_CLASS_ITEM_COOLDOWNS.items(), key=lambda x: -len(x[0])):
        if item in hint_lower:
            return cd
    return 20.0



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
        ("2354323232", SKILL_DELAY, "DPS (2&4 cost 10% HP each)"),
        ("235323232", SKILL_DELAY, "Safe (no Burning Fates, no self-damage from 4)"),
    ],
    # TCM: (combo, delay, display_name, consumable_hint).
    "timeless chronomancer": [
        ("34222425", SKILL_DELAY, "Power", "Hourglass of Power"),
        ("42242253", SKILL_DELAY, "Transience", "Hourglass of Transience"),
        ("42224253", SKILL_DELAY, "Paradise", "Hourglass of Paradise"),
        ("634222425", SKILL_DELAY, "Entropic (7s)", "Entropic Corruption"),
        ("634222425", SKILL_DELAY, "Power + Entropic", "Entropic Corruption"),
        ("6342225", SKILL_DELAY, "Entropic Short (5s)", "Entropic Corruption"),
        ("63424225", SKILL_DELAY, "Entropic (4 rift)", "Entropic Corruption"),
        ("6342222425", SKILL_DELAY, "Entropic (8s)", "Entropic Corruption"),
        ("63242224225", SKILL_DELAY, "Entropic (9s)", "Entropic Corruption"),
        ("634222242245", SKILL_DELAY, "Entropic (10s)", "Entropic Corruption"),
        ("6142224253", SKILL_DELAY, "Infinite", "Infinite Corruption"),
        ("6432422253", SKILL_DELAY, "Transience + Infinite", "Infinite Corruption"),
        ("6432222253", SKILL_DELAY, "Transience + Infinite (short)", "Infinite Corruption"),
        ("64324222422253", SKILL_DELAY, "Transience + Infinite (ext)", "Infinite Corruption"),
        ("4322462245", SKILL_DELAY, "Transience + Entropic", "Entropic Corruption"),
        ("4324224622453", SKILL_DELAY, "Entropic + Infinite", "Infinite Corruption"),
        ("6424342234223422426422253", SKILL_DELAY, "Foresee", "Foresee Corruption"),
    ],
    "yami no ronin": [
        ("3225225", SKILL_DELAY, "Dodge"),
        ("4344242425", SKILL_DELAY, "Full offence"),
        ("222345", SKILL_DELAY, "Stack Tachi"),
    ],
    "chrono shadowhunter": [
        ("24444445", SKILL_DELAY, "FMJ"),
        ("23333335", SKILL_DELAY, "Dodge"),
    ],
}


running = True
is_paused = False
consumable_enabled = False  # When False, run_consumable skips pressing (GUI toggleable mid-fight)
_log_queue = None  # When set (by GUI), log lines go here instead of print
_key_press_queue = None  # When set (by GUI), pressed keys go here for live skill highlight


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
_COOLDOWN_BUFFER = 0.15  # Extra wait when re-pressing same skill (covers input latency, server lag)


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
    if _key_press_queue is not None and char in "123456":
        try:
            _key_press_queue.put_nowait(char)
        except Exception:
            pass


# Classes that use a different targeting skill (e.g. Reload) — do not prepend auto (1)
CLASSES_NO_AUTO_PREPEND = frozenset({"chrono shadowhunter"})

# Live config for mid-fight combo switching (GUI only). When set, run_ability_combo reads from this each cycle.
LIVE_CONFIG: dict | None = None


def resolve_combo_delay(class_name: str, pattern_index: int | None, attack: str, base_delay: float) -> tuple[str, float, dict]:
    """Resolve combo, delay, and per-skill cooldown overrides from class/pattern.
    Returns (combo, delay, cooldown_overrides). Used by GUI for live switching.
    base_delay (from GUI) always overrides preset delay for all classes.
    For TCM: cooldown_overrides['6'] is derived from consumable_hint via TCM_CLASS_ITEM_COOLDOWNS."""
    cooldown_overrides: dict = {}
    if class_name and class_name in CLASSES:
        if class_name in CLASS_PATTERNS and pattern_index is not None:
            patterns = CLASS_PATTERNS[class_name]
            idx = min(pattern_index, len(patterns) - 1)
            entry = patterns[idx]
            combo = entry[0]
            if class_name == "timeless chronomancer" and len(entry) > 3 and entry[3]:
                cooldown_overrides["6"] = _tcm_cooldown_for_consumable(entry[3])
        else:
            preset = CLASSES[class_name]
            combo = preset[0]
    else:
        combo = attack if attack and all(c in "123456" for c in attack) else "412344"
    return (combo, base_delay, cooldown_overrides)


def _combo_with_auto(combo: str, class_name: str | None = None) -> str:
    """Prepend auto (1) for targeting when combo doesn't start with it. Skip for classes like Chrono ShadowHunter (uses Reload)."""
    if class_name and class_name in CLASSES_NO_AUTO_PREPEND:
        return combo
    return ("1" + combo) if combo and combo[0] != "1" else combo


def run_ability_combo(combo: str, delay: float, class_name: str | None = None, use_live_config: bool = False, cooldown_overrides: dict | None = None):
    """Loop: combo keys 2–6 only. Skill 1 runs independently via run_auto. When use_live_config, reads from LIVE_CONFIG each cycle.

    Between different skills: waits `delay` (1.20s). Between consecutive same skill: waits skill cooldown before re-press.
    cooldown_overrides: per-skill overrides merged on top of base class cooldowns (e.g. {"6": 6.0} for Entropic).
    """
    last_press: dict[str, float] = {}  # key → timestamp of last press (2–6 only)
    prev_key: str | None = None  # the key pressed immediately before the current one

    while running:
        if use_live_config and LIVE_CONFIG:
            new_combo = LIVE_CONFIG.get("combo", combo)
            new_class = LIVE_CONFIG.get("class_name", class_name)
            if new_combo != combo or new_class != class_name:
                last_press.clear()  # reset cooldown tracking on class/combo switch
                prev_key = None
            combo = new_combo
            delay = LIVE_CONFIG.get("delay", delay)
            class_name = new_class
            cooldown_overrides = LIVE_CONFIG.get("cooldown_overrides", cooldown_overrides)

        base_cooldowns = (
            TCM_COOLDOWNS if class_name == "timeless chronomancer"
            else CLASS_COOLDOWNS.get(class_name or "", {})
        )
        cooldowns = {**base_cooldowns, **(cooldown_overrides or {})}
        keys = [k for k in combo if k != "1"]  # skill 1 runs in run_auto, never in this loop

        if not is_paused:
            for key in keys:
                if not running:
                    break
                cd = cooldowns.get(key, 0)
                now = time.time()
                # Only use cooldown-wait when current key is the same as immediately preceding key (consecutive same-skill).
                # All other transitions (different skill, or same skill returning after others) use delay.
                if cd > 0 and prev_key is not None and key == prev_key and key in last_press:
                    elapsed = now - last_press[key]
                    wait = max(0, cd - elapsed + _COOLDOWN_BUFFER)  # consecutive same skill: wait cooldown
                else:
                    wait = delay  # different skill (or first press): wait delay
                _sleep(wait)
                _press_key(key)
                last_press[key] = time.time()
                prev_key = key
        _sleep(0.03)


def run_auto(interval: float):
    """Press skill 1 (auto) periodically. Runs independently behind the skill loop."""
    while running:
        if not is_paused:
            _press_key("1")
        _sleep(interval)


def run_consumable(interval: float = 6.0):
    """Press consumable key (6) periodically. Reads consumable_interval from LIVE_CONFIG each cycle when available."""
    while running:
        current_interval = LIVE_CONFIG.get("consumable_interval", interval) if LIVE_CONFIG else interval
        current_combo = LIVE_CONFIG.get("combo", "") if LIVE_CONFIG else ""
        if not is_paused and consumable_enabled and "6" not in current_combo:
            _press_key("6")
        _sleep(current_interval)



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
    config: class_name, attack, delay, no_consumable, no_background
    Supports mid-fight combo switching via LIVE_CONFIG when class/pattern changes.
    """
    global running, is_paused, target_pid, target_pids, target_app_name, use_psn_backend, LIVE_CONFIG, consumable_enabled
    globals()["_log_queue"] = log_queue
    globals()["_key_press_queue"] = config.get("key_press_queue")

    class_name = config.get("class_name") or ""
    attack = config.get("attack", "")
    base_delay = config.get("delay", SKILL_DELAY)
    no_consumable = config.get("no_consumable", False)
    no_background = config.get("no_background", False)
    pattern_index = config.get("pattern_index")

    combo, delay, cooldown_overrides = resolve_combo_delay(class_name, pattern_index, attack, base_delay)

    # Consumable interval: use per-pattern key-6 override when available, else TCM base (20s for hourglasses), else 6s
    if class_name == "timeless chronomancer":
        consumable_interval = cooldown_overrides.get("6", TCM_COOLDOWNS.get("6", 20.0))
    else:
        consumable_interval = 6.0

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

    base_cooldowns = TCM_COOLDOWNS if class_name == "timeless chronomancer" else CLASS_COOLDOWNS.get(class_name, {})
    auto_interval = {**base_cooldowns, **(cooldown_overrides or {})}.get("1", 2.0)

    _log("\n--- Running ---")
    pattern_name = ""
    if class_name in CLASS_PATTERNS and pattern_index is not None:
        patterns = CLASS_PATTERNS[class_name]
        idx = min(pattern_index, len(patterns) - 1)
        pattern_name = f"  Pattern: {patterns[idx][2]}\n"
    delay_str = f"{delay}s"
    _log(f"{pattern_name}  Combo: {_combo_with_auto(combo, class_name)}  Delay: {delay_str}")
    _log(f"  Auto (key 1): {'Off' if class_name in CLASSES_NO_AUTO_PREPEND else f'On (every {auto_interval:.1f}s)'}")
    _log(f"  Consumable (key 6): {'Off' if no_consumable else f'On (every {consumable_interval:.0f}s, skipped when 6 in combo)'}")
    _log(f"  Target app: {target_app_name or 'focused window'}")
    running = True
    consumable_enabled = not no_consumable
    LIVE_CONFIG = {"combo": combo, "delay": delay, "class_name": class_name, "cooldown_overrides": cooldown_overrides, "consumable_interval": consumable_interval}

    threads = [
        threading.Thread(target=run_ability_combo, args=(combo, delay, class_name, True, cooldown_overrides), daemon=True),
        threading.Thread(target=run_stdin_fallback, daemon=True),
        threading.Thread(target=run_consumable, args=(consumable_interval,), daemon=True),
    ]
    if class_name not in CLASSES_NO_AUTO_PREPEND and auto_interval > 0:
        threads.append(threading.Thread(target=run_auto, args=(auto_interval,), daemon=True))

    for t in threads:
        t.start()

    try:
        while running:
            time.sleep(0.05)
    except KeyboardInterrupt:
        running = False

    _log("Done.")
    globals()["_log_queue"] = None
    globals()["_key_press_queue"] = None
    LIVE_CONFIG = None



def main():
    parser = argparse.ArgumentParser(
        description="Dage Auto - Auto abilities for Adventure Quest Worlds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python aqw_auto.py ability --class "legion revenant"  # Use class preset
  python aqw_auto.py ability --attack 412344    # Custom attack pattern
  python aqw_auto.py list                      # Show class list
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
        help="Delay between skills 2-6 in seconds (default: 1.20)",
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
    cooldown_overrides: dict = {}
    if getattr(args, "class_name", None):
        class_name = args.class_name
        pattern_index = getattr(args, "pattern", 0)
        if class_name in CLASS_PATTERNS and pattern_index < len(CLASS_PATTERNS[class_name]):
            entry = CLASS_PATTERNS[class_name][pattern_index]
            combo, delay_val = entry[0], entry[1]
            if class_name == "timeless chronomancer" and len(entry) > 3 and entry[3]:
                cooldown_overrides["6"] = _tcm_cooldown_for_consumable(entry[3])
        else:
            preset = CLASSES[class_name]
            combo, delay_val = preset[0], preset[1]
        if args.delay is not None:
            delay = args.delay
        else:
            delay = delay_val
        print(f"Using class '{class_name}': {combo} @ {delay}s")
    elif args.attack:
        combo = args.attack
        delay = args.delay if args.delay is not None else SKILL_DELAY
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

    # If combo includes key 6, suppress the consumable thread to avoid double-pressing
    if "6" in combo:
        args.no_consumable = True

    cli_class = getattr(args, "class_name", None)
    if cli_class == "timeless chronomancer":
        consumable_interval = cooldown_overrides.get("6", TCM_COOLDOWNS.get("6", 20.0))
    else:
        consumable_interval = 6.0
    cli_base_cooldowns = TCM_COOLDOWNS if cli_class == "timeless chronomancer" else CLASS_COOLDOWNS.get(cli_class or "", {})
    auto_interval = {**cli_base_cooldowns, **(cooldown_overrides or {})}.get("1", 2.0)

    print("\n--- Running ---")
    print(f"  Combo: {_combo_with_auto(combo, cli_class)}  Delay: {delay}s")
    if not (target_pid or target_pids):
        print(f"  Target: focused window (click AQW game first!)")
    else:
        print(f"  Target app: {target_app_name or args.app or 'background'}")
    print(f"  Auto (key 1): {'Off' if cli_class in CLASSES_NO_AUTO_PREPEND else f'On (every {auto_interval:.1f}s)'}")
    print(f"  Consumable (key 6): {'Off' if args.no_consumable else f'On (every {consumable_interval:.0f}s)'}")
    print("  (Press Enter in terminal to stop)")
    print()

    global running
    running = True

    threads = [
        threading.Thread(target=run_ability_combo, args=(combo, delay, cli_class, False, cooldown_overrides), daemon=True),
        threading.Thread(target=run_stdin_fallback, daemon=True),
    ]
    if cli_class not in CLASSES_NO_AUTO_PREPEND and auto_interval > 0:
        threads.append(threading.Thread(target=run_auto, args=(auto_interval,), daemon=True))
    if not args.no_consumable:
        threads.append(threading.Thread(target=run_consumable, args=(consumable_interval,), daemon=True))

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
