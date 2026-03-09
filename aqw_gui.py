#!/usr/bin/env python3
"""
Dage Auto - Desktop GUI for Adventure Quest Worlds automation.
"""

import os
import queue
import sys
import threading
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
from aqw_auto import CLASSES, run_ability_from_gui

try:
    from PySide6.QtWidgets import (
        QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
        QLabel, QComboBox, QLineEdit, QDoubleSpinBox, QCheckBox, QPushButton,
        QGroupBox, QTextEdit, QMessageBox,
    )
    from PySide6.QtCore import QTimer
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


def build_config(cls, attack, delay, quest, no_consumable, no_bg, escape_self_target, escape_after_key, quest_pos, accept_drop, accept_drop_pos):
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
        "escape_self_target": escape_self_target,
        "escape_after_key": escape_after_key,
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
        self.escape_self_target_cb = QCheckBox("Escape after self-target skills")
        self.escape_self_target_cb.setToolTip("Press Escape after buff/heal skills that target self (archmage, legion revenant, archpaladin)")
        opts_layout.addWidget(self.no_consumable_cb)
        opts_layout.addWidget(self.no_bg_cb)
        opts_layout.addWidget(self.escape_self_target_cb)
        escape_hint = QLabel("(Self-target can be disabled in game: Advanced Options)")
        escape_hint.setStyleSheet("color: gray; font-size: 11px;")
        opts_layout.addWidget(escape_hint)
        escape_key_row = QHBoxLayout()
        escape_key_row.addWidget(QLabel("Escape after key (Custom):"))
        self.escape_after_combo = QComboBox()
        self.escape_after_combo.addItems(["None", "3", "4", "5"])
        escape_key_row.addWidget(self.escape_after_combo)
        opts_layout.addLayout(escape_key_row)
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
        self._on_class_change()

    def _on_class_change(self):
        is_custom = self.class_combo.currentText() == "Custom"
        self.attack_edit.setVisible(is_custom)
        self.escape_after_combo.setEnabled(is_custom)
        if not is_custom:
            preset = CLASSES.get(self.class_combo.currentText(), ("2345", 1.0))
            self.delay_spin.setValue(preset[1])

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
        escape_after = None if self.escape_after_combo.currentText() == "None" else self.escape_after_combo.currentText()
        config = build_config(cls, attack, delay,
                             self.quest_cb.isChecked(), self.no_consumable_cb.isChecked(),
                             self.no_bg_cb.isChecked(), self.escape_self_target_cb.isChecked(),
                             escape_after, self.quest_pos,
                             self.accept_drop_cb.isChecked(), self.accept_drop_pos)
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
            ability_thread = None
            self.start_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
            self.log.append("Stopped.")

    def _stop(self):
        global ability_thread
        aqw_auto.running = False
        if ability_thread and ability_thread.is_alive():
            ability_thread.join(timeout=2)
        ability_thread = None


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
