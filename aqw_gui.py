#!/usr/bin/env python3
"""
Dage Auto - Desktop GUI for Adventure Quest Worlds automation.
"""

import ctypes
import os
import platform
import queue
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _is_accessibility_granted() -> bool:
    """Check if macOS Accessibility permission is granted."""
    try:
        lib = ctypes.cdll.LoadLibrary(
            "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
        )
        lib.AXIsProcessTrusted.restype = ctypes.c_bool
        return lib.AXIsProcessTrusted()
    except Exception:
        return True  # non-macOS or check failed — don't show warning


def _open_accessibility_settings():
    major = int(platform.mac_ver()[0].split(".")[0])
    if major >= 13:
        url = "x-apple.systempreferences:com.apple.settings.PrivacySecurity.extension?Privacy_Accessibility"
    else:
        url = "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"
    subprocess.run(["open", url])


def _icon_path():
    """Return path to app icon (icns in bundle, or png when running from source)."""
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
        icns = os.path.normpath(os.path.join(base, "..", "Resources", "Dage.icns"))
        if os.path.isfile(icns):
            return icns
    png = Path(__file__).parent / "dage-icon.png"
    if png.is_file():
        return str(png)
    return None


import aqw_auto
from aqw_auto import CLASSES, CLASS_PATTERNS, CLASS_COOLDOWNS, TCM_COOLDOWNS, _combo_with_auto, _min_delay_for_combo, resolve_combo_delay, run_ability_from_gui

try:
    import updater
    from version import APP_VERSION, GITHUB_REPO
    _UPDATER_AVAILABLE = True
except ImportError:
    _UPDATER_AVAILABLE = False

try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QComboBox, QLineEdit, QDoubleSpinBox, QCheckBox, QPushButton,
        QGroupBox, QTextEdit, QMessageBox, QProgressDialog,
    )
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtGui import QFont, QIcon
except ImportError:
    print("Install PySide6: pip install PySide6")
    sys.exit(1)

try:
    import pyautogui
except ImportError:
    pyautogui = None

CLASS_OPTIONS = ["Custom"] + list(CLASSES.keys())
ability_thread = None
log_queue = None
log_lines = []

# OTP-style skill box styles
_SKILL_BOX_INACTIVE = "background:#2d3748; border:2px solid #4a5568; border-radius:6px; color:#718096; font-size:14px; font-weight:bold;"
_SKILL_BOX_ACTIVE = "background:#2b6cb0; border:2px solid #63b3ed; border-radius:6px; color:#ebf8ff; font-size:14px; font-weight:bold;"


def build_config(cls, attack, delay, quest, no_consumable, no_bg, quest_pos, accept_drop, accept_drop_pos, pattern_index=None):
    """Build config dict for run_ability_from_gui."""
    if cls and cls != "Custom":
        class_name, attack = cls, ""
    else:
        if not attack or not all(c in "123456" for c in attack):
            return None
        class_name = ""
    valid_pos = quest and quest_pos and len(quest_pos) in (4, 6)
    return {
        "class_name": class_name,
        "attack": attack,
        "delay": round(delay, 1),
        "quest_turnin": quest,
        "quest_pos": quest_pos if valid_pos else None,
        "accept_drop": accept_drop and accept_drop_pos and len(accept_drop_pos) == 2,
        "accept_drop_pos": accept_drop_pos if (accept_drop and accept_drop_pos and len(accept_drop_pos) == 2) else None,
        "no_consumable": no_consumable,
        "no_background": no_bg,
        "pattern_index": pattern_index,
    }


def _run_ability_worker(config, q):
    """Thread target: run ability combo, log to queue."""
    run_ability_from_gui(config, q)


def read_log_queue():
    global log_queue, log_lines
    if log_queue:
        try:
            while True:
                line = log_queue.get_nowait()
                log_lines.append(line.rstrip())
        except queue.Empty:
            pass


class MainPage(QWidget):
    def __init__(self):
        super().__init__()
        self.quest_pos = None
        self._quest_q = None
        self._quest_t = None
        self._quest_a = None
        self.accept_drop_pos = None
        layout = QVBoxLayout(self)

        # Class
        layout.addWidget(QLabel("Class"))
        self.class_combo = QComboBox()
        self.class_combo.addItems(CLASS_OPTIONS)
        self.class_combo.setCurrentText("legion revenant")
        self.class_combo.currentTextChanged.connect(self._on_class_change)
        layout.addWidget(self.class_combo)

        # Pattern (for classes with multiple patterns, e.g. Timeless Chronomancer)
        pattern_container = QWidget()
        pattern_layout = QVBoxLayout(pattern_container)
        pattern_layout.setContentsMargins(0, 0, 0, 0)
        pattern_row = QHBoxLayout()
        pattern_row.addWidget(QLabel("Pattern"))
        self.pattern_combo = QComboBox()
        self.pattern_combo.setToolTip("Select combo pattern. Switch mid-fight to change combo without stopping.")
        self.pattern_combo.currentIndexChanged.connect(self._on_pattern_change)
        pattern_row.addWidget(self.pattern_combo)
        pattern_layout.addLayout(pattern_row)
        self.consumable_hint = QLabel("")
        self.consumable_hint.setStyleSheet("color: gray; font-size: 11px;")
        self.consumable_hint.setWordWrap(True)
        pattern_layout.addWidget(self.consumable_hint)
        layout.addWidget(pattern_container)
        self.pattern_container = pattern_container

        # Custom attack
        attack_row = QHBoxLayout()
        attack_row.addWidget(QLabel("Attack"))
        self.attack_edit = QLineEdit("12345")
        self.attack_edit.setPlaceholderText("e.g. 12345")
        attack_row.addWidget(self.attack_edit)
        layout.addLayout(attack_row)

        # Delay
        delay_row = QHBoxLayout()
        delay_row.addWidget(QLabel("Delay (s)"))
        self.delay_spin = QDoubleSpinBox()
        self.delay_spin.setRange(0.1, 2)
        self.delay_spin.setSingleStep(0.1)
        self.delay_spin.setValue(1.0)
        delay_row.addWidget(self.delay_spin)
        layout.addLayout(delay_row)

        # Active combo display (OTP-style)
        combo_container = QWidget()
        combo_layout = QVBoxLayout(combo_container)
        combo_layout.setSpacing(8)
        self.combo_display = QLabel("")
        self.combo_display.setStyleSheet("color: #0d7377; font-size: 16px; font-family: monospace; font-weight: 600;")
        self.combo_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        combo_layout.addWidget(self.combo_display)
        skill_row = QHBoxLayout()
        skill_row.setSpacing(6)
        self.skill_boxes: list[QLabel] = []
        for i in range(1, 7):
            lb = QLabel(str(i))
            lb.setFixedSize(40, 40)
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet(_SKILL_BOX_INACTIVE)
            self.skill_boxes.append(lb)
            skill_row.addWidget(lb)
        combo_layout.addLayout(skill_row)
        layout.addWidget(combo_container)

        # Options
        opts = QGroupBox("Options")
        opts_layout = QVBoxLayout(opts)
        self.quest_cb = QCheckBox("Quest turn-in")
        opts_layout.addWidget(self.quest_cb)
        rec_row = QHBoxLayout()
        rec_row.addWidget(QPushButton("Record quest", clicked=self._record_quest))
        rec_row.addWidget(QPushButton("Record turn-in", clicked=self._record_turnin))
        rec_row.addWidget(QPushButton("Record accept", clicked=self._record_accept))
        opts_layout.addLayout(rec_row)
        self.quest_status = QLabel("")
        self.quest_status.setStyleSheet("color: gray;")
        opts_layout.addWidget(self.quest_status)
        self.accept_drop_cb = QCheckBox("Accept drop (loot from monsters)")
        opts_layout.addWidget(self.accept_drop_cb)
        drop_row = QHBoxLayout()
        drop_row.addWidget(QPushButton("Record accept drop", clicked=self._record_accept_drop))
        opts_layout.addLayout(drop_row)
        self.accept_drop_status = QLabel("")
        self.accept_drop_status.setStyleSheet("color: gray;")
        opts_layout.addWidget(self.accept_drop_status)
        self.no_consumable_cb = QCheckBox("No consumable (key 6)")
        self.no_bg_cb = QCheckBox("Foreground mode")
        opts_layout.addWidget(self.no_consumable_cb)
        opts_layout.addWidget(self.no_bg_cb)
        layout.addWidget(opts)

        # Buttons
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("Start")
        self.start_btn.clicked.connect(self._start)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop)
        self.stop_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)
        layout.addLayout(btn_row)

        # Log
        layout.addWidget(QLabel("Log"))
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setFont(QFont("Menlo", 10))
        self.log.setMaximumHeight(120)
        layout.addWidget(self.log)

        self.attack_edit.setVisible(False)
        self.pattern_container.setVisible(False)
        self.attack_edit.textChanged.connect(self._update_combo_display)
        self._on_class_change()

    def _display_combo(self, combo: str, class_name: str | None = None) -> str:
        """Include auto (1) for targeting when combo doesn't start with it. Skip for Chrono ShadowHunter."""
        return _combo_with_auto(combo, class_name)

    def _update_skill_boxes(self, combo: str):
        """Highlight skill boxes 1-6 that appear in the combo."""
        active = set(c for c in combo if c in "123456")
        for i, lb in enumerate(self.skill_boxes):
            lb.setStyleSheet(_SKILL_BOX_ACTIVE if str(i + 1) in active else _SKILL_BOX_INACTIVE)

    def _update_combo_display(self):
        cls = self.class_combo.currentText()
        if cls == "Custom":
            combo = self.attack_edit.text().strip()
            if combo and all(c in "123456" for c in combo):
                delay = self.delay_spin.value()
                displayed = self._display_combo(combo, None)
                self.combo_display.setText(f"Combo: {displayed}  Delay: {delay}s")
                self._update_skill_boxes(displayed.replace(" ", ""))
            else:
                self.combo_display.setText("")
                self._update_skill_boxes("")
            return
        if cls in CLASS_PATTERNS:
            idx = self.pattern_combo.currentIndex()
            patterns = CLASS_PATTERNS[cls]
            if 0 <= idx < len(patterns):
                combo, delay_val = patterns[idx][0], patterns[idx][1]
                cooldowns = TCM_COOLDOWNS if cls == "timeless chronomancer" else CLASS_COOLDOWNS.get(cls, {})
                delay = delay_val if delay_val is not None else (_min_delay_for_combo(combo, cooldowns) if cooldowns else self.delay_spin.value())
                displayed = self._display_combo(combo, cls)
                self.combo_display.setText(f"Combo: {displayed}  Delay: {delay}s")
                self._update_skill_boxes(displayed.replace(" ", ""))
            else:
                self.combo_display.setText("")
                self._update_skill_boxes("")
        else:
            preset = CLASSES.get(cls)
            if preset:
                combo, delay_val = preset[0], preset[1]
                cooldowns = CLASS_COOLDOWNS.get(cls, {})
                delay = delay_val if delay_val is not None else (_min_delay_for_combo(combo, cooldowns) if cooldowns else self.delay_spin.value())
                displayed = self._display_combo(combo, cls)
                self.combo_display.setText(f"Combo: {displayed}  Delay: {delay}s")
                self._update_skill_boxes(displayed.replace(" ", ""))
            else:
                self.combo_display.setText("")
                self._update_skill_boxes("")

    def _update_live_config_if_running(self):
        """When running, update LIVE_CONFIG so combo switches mid-fight."""
        global ability_thread
        if ability_thread and ability_thread.is_alive():
            cls = self.class_combo.currentText()
            pattern_index = self.pattern_combo.currentIndex() if cls in CLASS_PATTERNS else None
            attack = self.attack_edit.text().strip() if cls == "Custom" else ""
            base_delay = self.delay_spin.value()
            combo, delay = resolve_combo_delay(cls, pattern_index, attack, base_delay)
            aqw_auto.LIVE_CONFIG = {"combo": combo, "delay": delay, "class_name": cls if cls != "Custom" else ""}

    def _on_class_change(self):
        cls = self.class_combo.currentText()
        is_custom = cls == "Custom"
        self.attack_edit.setVisible(is_custom)

        # Show pattern selector only for classes with multiple patterns
        has_patterns = cls in CLASS_PATTERNS
        self.pattern_container.setVisible(has_patterns)
        if has_patterns:
            self.pattern_combo.clear()
            self.pattern_combo.blockSignals(True)
            for p in CLASS_PATTERNS[cls]:
                name = p[2]
                self.pattern_combo.addItem(name)
            self.pattern_combo.blockSignals(False)
            self.pattern_combo.setCurrentIndex(0)
            self._on_pattern_change()

        if not is_custom:
            preset = CLASSES.get(cls, ("2345", 1.0))
            delay_val = preset[1]
            self.delay_spin.setValue(delay_val if delay_val is not None else 1.0)
            if cls in CLASS_PATTERNS or (delay_val is None and cls in CLASS_COOLDOWNS):
                self.delay_spin.setToolTip("Auto-computed from skill cooldowns")
            else:
                self.delay_spin.setToolTip("")
        self._update_combo_display()
        self._update_live_config_if_running()

    def _on_pattern_change(self):
        cls = self.class_combo.currentText()
        if cls not in CLASS_PATTERNS:
            self.consumable_hint.setText("")
            self.consumable_hint.setVisible(False)
            return
        idx = self.pattern_combo.currentIndex()
        patterns = CLASS_PATTERNS[cls]
        if 0 <= idx < len(patterns):
            p = patterns[idx]
            combo = p[0]
            consumable = p[3] if len(p) > 3 else ""
            if consumable:
                self.consumable_hint.setText(f"Equip (slot 6): {consumable}\nCombo: {self._display_combo(combo, cls)}")
                self.consumable_hint.setVisible(True)
            else:
                self.consumable_hint.setText(f"Combo: {self._display_combo(combo, cls)}")
                self.consumable_hint.setVisible(True)
        else:
            self.consumable_hint.setText("")
            self.consumable_hint.setVisible(False)
        self._update_combo_display()
        self._update_live_config_if_running()

    def _record_quest(self):
        if not pyautogui:
            QMessageBox.critical(self, "Error", "pyautogui required")
            return
        self.quest_status.setText("Move cursor to quest... (2 sec)")
        QTimer.singleShot(2000, lambda: self._do_record(0))

    def _record_turnin(self):
        if not pyautogui:
            QMessageBox.critical(self, "Error", "pyautogui required")
            return
        self.quest_status.setText("Move cursor to turn-in... (2 sec)")
        QTimer.singleShot(2000, lambda: self._do_record(1))

    def _record_accept(self):
        if not pyautogui:
            QMessageBox.critical(self, "Error", "pyautogui required")
            return
        self.quest_status.setText("Move cursor to Accept button... (2 sec)")
        QTimer.singleShot(2000, lambda: self._do_record(2))

    def _record_accept_drop(self):
        if not pyautogui:
            QMessageBox.critical(self, "Error", "pyautogui required")
            return
        self.accept_drop_status.setText("Move cursor to Accept (loot drop)... (2 sec)")
        QTimer.singleShot(2000, self._do_record_accept_drop)

    def _do_record_accept_drop(self):
        x, y = pyautogui.position()
        self.accept_drop_pos = (x, y)
        self.accept_drop_status.setText(f"Accept drop: ({x}, {y}) ✓")

    def _do_record(self, step):
        x, y = pyautogui.position()
        if step == 0:
            self._quest_q = (x, y)
            self._quest_t = None
            self._quest_a = None
            self.quest_status.setText(f"Quest: ({x}, {y}) — now record turn-in")
        elif step == 1:
            self._quest_t = (x, y)
            self._quest_a = None
            self.quest_status.setText(f"Quest: {self._quest_q}  Turn-in: ({x}, {y}) ✓ (or record accept)")
        else:
            self._quest_a = (x, y)
            self.quest_status.setText(f"Quest: {self._quest_q}  Turn-in: {self._quest_t}  Accept: ({x}, {y}) ✓")
        if self._quest_q and self._quest_t:
            self.quest_pos = (*self._quest_q, *self._quest_t)
            if self._quest_a:
                self.quest_pos = (*self.quest_pos, *self._quest_a)

    def _start(self):
        global ability_thread, log_queue, log_lines
        cls = self.class_combo.currentText()
        attack = self.attack_edit.text().strip()
        delay = self.delay_spin.value()
        if cls == "Custom" and (not attack or not all(c in "123456" for c in attack)):
            QMessageBox.critical(self, "Error", "Custom attack must be digits 1–6 only")
            return
        if self.quest_cb.isChecked() and not self.quest_pos:
            QMessageBox.critical(self, "Error", "Record quest and turn-in positions first")
            return
        if self.accept_drop_cb.isChecked() and not self.accept_drop_pos:
            QMessageBox.critical(self, "Error", "Record accept drop position first")
            return
        pattern_index = None
        if cls in CLASS_PATTERNS:
            pattern_index = self.pattern_combo.currentIndex()
        config = build_config(cls, attack, delay,
                             self.quest_cb.isChecked(), self.no_consumable_cb.isChecked(),
                             self.no_bg_cb.isChecked(), self.quest_pos,
                             self.accept_drop_cb.isChecked(), self.accept_drop_pos,
                             pattern_index)
        if config is None:
            QMessageBox.critical(self, "Error", "Invalid attack pattern")
            return
        log_lines = []
        log_queue = queue.Queue()
        ability_thread = threading.Thread(target=_run_ability_worker, args=(config, log_queue), daemon=True)
        ability_thread.start()
        self.log.clear()
        cls_part = f"--class {cls}" if cls != "Custom" else f"--attack {attack}"
        self.log.append(f"Started: {cls_part} --delay {config['delay']}")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        QTimer.singleShot(100, self._poll_log)

    def _poll_log(self):
        global ability_thread, log_queue, log_lines
        read_log_queue()
        if log_lines:
            self.log.append("\n".join(log_lines))
            log_lines.clear()
        if ability_thread and ability_thread.is_alive():
            QTimer.singleShot(100, self._poll_log)
        else:
            if ability_thread is not None:
                # Thread finished on its own (not stopped by user)
                ability_thread = None
                self.start_btn.setEnabled(True)
                self.stop_btn.setEnabled(False)
                self.log.append("Stopped.")

    def _stop(self):
        global ability_thread
        aqw_auto.running = False
        ability_thread = None
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.log.append("Stopped.")


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Dage Auto")
        self.setMinimumSize(360, 420)
        icon_path = _icon_path()
        if icon_path:
            self.setWindowIcon(QIcon(icon_path))
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.addWidget(MainPage())

        bottom_row = QHBoxLayout()
        version_label = QLabel(f"v{APP_VERSION}" if _UPDATER_AVAILABLE else "")
        version_label.setStyleSheet("color: gray; font-size: 10px;")
        bottom_row.addWidget(version_label)
        bottom_row.addStretch()
        if _UPDATER_AVAILABLE:
            self._check_btn = QPushButton("Check for Updates")
            self._check_btn.setFixedHeight(22)
            self._check_btn.setStyleSheet("font-size: 10px;")
            self._check_btn.clicked.connect(self._manual_update_check)
            bottom_row.addWidget(self._check_btn)
        layout.addLayout(bottom_row)

        if _UPDATER_AVAILABLE:
            self._manual_check = False
            updater.start_check(GITHUB_REPO, APP_VERSION)
            self._update_timer = QTimer(self)
            self._update_timer.timeout.connect(self._poll_update)
            self._update_timer.start(500)

        QTimer.singleShot(1500, self._check_accessibility)

    def _check_accessibility(self):
        if _is_accessibility_granted():
            return
        box = QMessageBox(self)
        box.setWindowTitle("Accessibility Permission Required")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(
            "Dage Auto needs Accessibility permission to control your game.<br><br>"
            "After an update, macOS requires you to re-grant this permission.<br><br>"
            "Click <b>Open Settings</b>, find <b>Dage Auto</b> in the list, "
            "remove it, then add it back."
        )
        open_btn = box.addButton("Open Settings", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is open_btn:
            _open_accessibility_settings()

    def _manual_update_check(self):
        self._manual_check = True
        self._check_btn.setEnabled(False)
        self._check_btn.setText("Checking...")
        updater.start_check(GITHUB_REPO, APP_VERSION)
        self._update_timer.start(500)

    def _poll_update(self):
        result = updater.poll()
        if result is None:
            return
        self._update_timer.stop()
        if hasattr(self, "_check_btn"):
            self._check_btn.setEnabled(True)
            self._check_btn.setText("Check for Updates")
        if not result.get("available"):
            if self._manual_check:
                error = result.get("error", "")
                msg = "You are on the latest version."
                if error:
                    msg += f"\n\nDebug: {error}"
                QMessageBox.information(self, "No Updates", msg)
            return
        latest = result["version"]
        asset_url = result.get("asset_url")
        page_url = result["url"]
        box = QMessageBox(self)
        box.setWindowTitle("Update Available")
        box.setText(
            f"A new version <b>{latest}</b> is available!<br>"
            f"You are running <b>v{APP_VERSION}</b>."
        )
        box.setIcon(QMessageBox.Icon.Information)
        if getattr(sys, "frozen", False) and asset_url:
            update_btn = box.addButton("Update Now", QMessageBox.ButtonRole.AcceptRole)
        else:
            update_btn = box.addButton("Download Update", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is not update_btn:
            return
        if getattr(sys, "frozen", False) and asset_url:
            self._start_in_app_update(asset_url, latest)
        else:
            webbrowser.open(page_url)

    def _start_in_app_update(self, asset_url: str, latest: str):
        app_path = os.path.normpath(os.path.join(sys.executable, "../../.."))
        updater.download_and_install(asset_url, app_path)
        self._progress = QProgressDialog(f"Downloading {latest}...", None, 0, 100, self)
        self._progress.setWindowTitle("Updating Dage Auto")
        self._progress.setCancelButton(None)
        self._progress.setMinimumDuration(0)
        self._progress.setAutoClose(False)
        self._progress.show()
        self._install_timer = QTimer(self)
        self._install_timer.timeout.connect(self._poll_install)
        self._install_timer.start(200)

    def _poll_install(self):
        self._progress.setValue(updater.download_progress())
        done, error = updater.download_finished()
        if not done:
            return
        self._install_timer.stop()
        self._progress.close()
        if error:
            QMessageBox.critical(self, "Update Failed", error)
            return
        QMessageBox.information(self, "Restarting", "Update downloaded! Dage Auto will restart.")
        QApplication.quit()


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    icon_path = _icon_path()
    if icon_path:
        app.setWindowIcon(QIcon(icon_path))
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
