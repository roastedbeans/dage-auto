#!/usr/bin/env python3
"""
Dage Auto - Desktop GUI for Adventure Quest Worlds automation.
"""

import os
import queue
import sys
import threading
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


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
from aqw_auto import CLASSES, CLASS_PATTERNS, CLASS_COOLDOWNS, TCM_COOLDOWNS, _min_delay_for_combo, run_ability_from_gui

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
        self.pattern_combo.setToolTip("Select combo pattern (Timeless Chronomancer only)")
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

        # Active combo display
        self.combo_display = QLabel("")
        self.combo_display.setStyleSheet("color: #0d7377; font-size: 12px; font-family: monospace; font-weight: 500;")
        self.combo_display.setWordWrap(True)
        layout.addWidget(self.combo_display)

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

    def _update_combo_display(self):
        cls = self.class_combo.currentText()
        if cls == "Custom":
            combo = self.attack_edit.text().strip()
            if combo and all(c in "123456" for c in combo):
                delay = self.delay_spin.value()
                self.combo_display.setText(f"Combo: {combo}  Delay: {delay}s")
            else:
                self.combo_display.setText("")
            return
        if cls in CLASS_PATTERNS:
            idx = self.pattern_combo.currentIndex()
            patterns = CLASS_PATTERNS[cls]
            if 0 <= idx < len(patterns):
                combo, delay_val = patterns[idx][0], patterns[idx][1]
                cooldowns = TCM_COOLDOWNS if cls == "timeless chronomancer" else CLASS_COOLDOWNS.get(cls, {})
                delay = delay_val if delay_val is not None else (_min_delay_for_combo(combo, cooldowns) if cooldowns else self.delay_spin.value())
                self.combo_display.setText(f"Combo: {combo}  Delay: {delay}s")
            else:
                self.combo_display.setText("")
        else:
            preset = CLASSES.get(cls)
            if preset:
                combo, delay_val = preset[0], preset[1]
                cooldowns = CLASS_COOLDOWNS.get(cls, {})
                delay = delay_val if delay_val is not None else (_min_delay_for_combo(combo, cooldowns) if cooldowns else self.delay_spin.value())
                self.combo_display.setText(f"Combo: {combo}  Delay: {delay}s")
            else:
                self.combo_display.setText("")

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
                self.consumable_hint.setText(f"Equip (slot 6): {consumable}\nCombo: {combo}")
                self.consumable_hint.setVisible(True)
            else:
                self.consumable_hint.setText(f"Combo: {combo}")
                self.consumable_hint.setVisible(True)
        else:
            self.consumable_hint.setText("")
            self.consumable_hint.setVisible(False)
        self._update_combo_display()

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

        version_label = QLabel(f"v{APP_VERSION}" if _UPDATER_AVAILABLE else "")
        version_label.setStyleSheet("color: gray; font-size: 10px;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        layout.addWidget(version_label)

        if _UPDATER_AVAILABLE:
            updater.start_check(GITHUB_REPO, APP_VERSION)
            self._update_timer = QTimer(self)
            self._update_timer.timeout.connect(self._poll_update)
            self._update_timer.start(500)

    def _poll_update(self):
        result = updater.poll()
        if result is None:
            return
        self._update_timer.stop()
        if not result.get("available"):
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
