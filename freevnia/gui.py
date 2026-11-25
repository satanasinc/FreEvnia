#!/usr/bin/env python3
"""Small Qt window to control PBP / PIP on the Philips Evnia 49M2C8900L.

Uses freevnia.usbddc (DDC/CI over USB through the VIA Billboard 2109:8884).
The monitor routes its USB (KVM) to the LEFT/main picture: if the main source is not this PC,
the program loses access until you switch back with the remote.
"""
import sys
import threading

import usb.core
from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (QApplication, QButtonGroup, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget)

from . import usbddc as p

LOCK = threading.Lock()          # one USB access at a time (polling and commands)
POS = {"ul": 3, "ur": 1, "ll": 4, "lr": 2}   # upper-left, upper-right, lower-left, lower-right (verified)
SIZES = {"Small": 1, "Medium": 2, "Large": 3}
MAIN_OPTS = (("dp1", "DisplayPort (this PC)"), ("hdmi1", "HDMI 1"), ("hdmi2", "HDMI 2"), ("usbc", "USB-C"))
SUB_OPTS = (("usbc", "USB-C"), ("hdmi1", "HDMI 1"), ("hdmi2", "HDMI 2"))


def device():
    return usb.core.find(idVendor=p.VID, idProduct=p.PID)


def read_state():
    """None = no access; 'full' = full screen; 'on' = PBP/PIP active; 'err' = read failure."""
    with LOCK:
        dev = device()
        if dev is None:
            return None
        try:
            return "on" if p.get_vcp(dev, 0xE6)["cur"] == 0 else "full"
        except Exception:
            return "err"


def apply(mode, loc, size, main="dp1", sub="usbc"):
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        p.apply_mode(dev, p.MODES[mode], p.SRC_MAIN[main], p.SRC_SUB[sub], size, loc)


class Signals(QObject):
    state = Signal(object)
    done = Signal(str)
    failed = Signal(str)


class Job(QRunnable):
    def __init__(self, fn, signals, ok_text=None):
        super().__init__()
        self.fn, self.sig, self.ok_text = fn, signals, ok_text

    def run(self):
        try:
            r = self.fn()
            if self.ok_text is None:
                self.sig.state.emit(r)
            else:
                self.sig.done.emit(self.ok_text)
        except Exception as e:
            self.sig.failed.emit(str(e))


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FreEvnia - PBP / PIP")
        self.sig = Signals()
        self.sig.state.connect(self.on_state)
        self.sig.done.connect(self.on_done)
        self.sig.failed.connect(self.on_failed)
        self.pool = QThreadPool.globalInstance()
        self.mode = None             # last mode applied from here (the monitor does not let us read it back)
        self.loc, self.size = POS["ur"], SIZES["Medium"]
        self.main, self.sub = "dp1", "usbc"
        self.busy = False

        root = QVBoxLayout(self)
        self.status = QLabel("Checking the monitor…")
        self.status.setWordWrap(True)
        root.addWidget(self.status)

        box = QGroupBox("Mode")
        row = QHBoxLayout(box)
        self.mode_group = QButtonGroup(self)
        self.mode_btn = {}
        for key, text in (("off", "Full screen"), ("pbp1", "PBP\n(side by side)"), ("pip", "PIP\n(small window)")):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setMinimumHeight(56)
            b.clicked.connect(lambda _=False, k=key: self.set_mode(k))
            self.mode_group.addButton(b)
            self.mode_btn[key] = b
            row.addWidget(b)
        self.mode_group.setExclusive(True)
        root.addWidget(box)

        fbox = QGroupBox("Sources")
        fl = QVBoxLayout(fbox)
        self.main_btn, self.sub_btn = {}, {}
        for titulo, opciones, store, slot in (
                ("Main (left):", MAIN_OPTS, self.main_btn, self.set_main),
                ("Second picture:", SUB_OPTS, self.sub_btn, self.set_sub)):
            fr = QHBoxLayout()
            lab = QLabel(titulo)
            lab.setMinimumWidth(130)
            fr.addWidget(lab)
            grp = QButtonGroup(self)
            for key, text in opciones:
                b = QPushButton(text)
                b.setCheckable(True)
                b.clicked.connect(lambda _=False, k=key, s=slot: s(k))
                grp.addButton(b)
                store[key] = b
                fr.addWidget(b)
            fl.addLayout(fr)
        self.main_btn[self.main].setChecked(True)
        self.sub_btn[self.sub].setChecked(True)
        root.addWidget(fbox)

        pbox = QGroupBox("PIP window")
        pl = QVBoxLayout(pbox)
        grid = QGridLayout()
        self.pos_group = QButtonGroup(self)
        self.pos_btn = {}
        for key, text, r, c in (("ul", "↖  Upper left", 0, 0), ("ur", "↗  Upper right", 0, 1),
                                ("ll", "↙  Lower left", 1, 0), ("lr", "↘  Lower right", 1, 1)):
            b = QPushButton(text)
            b.setCheckable(True)
            b.setMinimumHeight(40)
            b.clicked.connect(lambda _=False, k=key: self.set_pos(k))
            self.pos_group.addButton(b)
            self.pos_btn[key] = b
            grid.addWidget(b, r, c)
        self.pos_btn["ur"].setChecked(True)
        pl.addLayout(grid)
        srow = QHBoxLayout()
        self.size_group = QButtonGroup(self)
        self.size_btn = {}
        for text, val in SIZES.items():
            b = QPushButton(text)
            b.setCheckable(True)
            b.clicked.connect(lambda _=False, v=val: self.set_size(v))
            self.size_group.addButton(b)
            self.size_btn[val] = b
            srow.addWidget(b)
        self.size_btn[SIZES["Medium"]].setChecked(True)
        pl.addLayout(srow)
        root.addWidget(pbox)

        nota = QLabel("The monitor sends its USB (KVM) to the left/main picture.\n"
                      "If the main source is not this PC, control is lost until you switch back with the remote.")
        nota.setStyleSheet("color: gray; font-size: 11px;")
        root.addWidget(nota)

        self.controls = (list(self.mode_btn.values()) + list(self.pos_btn.values()) + list(self.size_btn.values())
                         + list(self.main_btn.values()) + list(self.sub_btn.values()))
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(3000)
        self.poll()

    # --- actions -------------------------------------------------------
    def run_apply(self, mode, text):
        self.busy = True
        self.status.setText("Sending to the monitor…")
        loc, size, main, sub = self.loc, self.size, self.main, self.sub
        self.pool.start(Job(lambda: apply(mode, loc, size, main, sub), self.sig, ok_text=text))

    def set_main(self, key):
        if key == self.main:
            return
        if key != "dp1":
            r = QMessageBox.warning(
                self, "Change the main source",
                "If the main source is not this PC, the monitor's USB goes with it and this program "
                "will lose control.\n\nYou will have to switch back with the remote.\n\nContinue?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if r != QMessageBox.Yes:
                self.main_btn[self.main].setChecked(True)
                return
        self.main = key
        if self.sub == key or (key == "usbc" and self.sub == "usbc"):      # the same source cannot be in both pictures
            self.sub = next(k for k, _ in SUB_OPTS if k != key)
            self.sub_btn[self.sub].setChecked(True)
        self.run_apply(self.mode or "off", "Main source changed")

    def set_sub(self, key):
        if key == self.main:
            self.sub_btn[self.sub].setChecked(True)
            self.status.setText("The second picture cannot use the same source as the main one.")
            return
        self.sub = key
        if self.mode in ("pbp1", "pip"):
            self.run_apply(self.mode, "Second picture changed")

    def set_mode(self, key):
        self.mode = key
        self.run_apply(key, {"off": "Full screen", "pbp1": "PBP on", "pip": "PIP on"}[key])

    def set_pos(self, key):
        self.loc = POS[key]
        if self.mode == "pip":
            self.run_apply("pip", "PIP moved")

    def set_size(self, val):
        self.size = val
        if self.mode == "pip":
            self.run_apply("pip", "PIP size changed")

    def poll(self):
        if not self.busy:
            self.pool.start(Job(read_state, self.sig))

    # --- replies -----------------------------------------------------
    def enable(self, on):
        for w in self.controls:
            w.setEnabled(on)

    def on_state(self, st):
        self.busy = False
        if st is None:
            self.status.setText("⚠ No access to the monitor: its USB hub is on another computer.\n"
                                "Put this PC on the left/main picture with the remote.")
            self.enable(False)
            return
        self.enable(True)
        if st == "err":
            self.status.setText("Could not read the monitor state.")
        elif st == "full":
            self.status.setText("Monitor connected · full screen")
            if self.mode != "off":
                self.mode = "off"
            self.mode_btn["off"].setChecked(True)
        else:
            extra = "" if self.mode in ("pbp1", "pip") else " (set from the remote)"
            self.status.setText("Monitor connected · PBP/PIP active" + extra)
            if self.mode in ("pbp1", "pip"):
                self.mode_btn[self.mode].setChecked(True)
            else:
                self.mode_group.setExclusive(False)
                for b in self.mode_btn.values():
                    b.setChecked(False)
                self.mode_group.setExclusive(True)

    def on_done(self, text):
        self.busy = False
        self.status.setText("✔ " + text)
        QTimer.singleShot(1500, self.poll)

    def on_failed(self, msg):
        self.busy = False
        self.status.setText("✖ " + msg)


def main():
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    if "--grab" in sys.argv:      # testing only: save a screenshot of the window and exit
        out = sys.argv[sys.argv.index("--grab") + 1]
        QTimer.singleShot(1500, lambda: (w.grab().save(out), app.quit()))
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
