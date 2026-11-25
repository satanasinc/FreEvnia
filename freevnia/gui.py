#!/usr/bin/env python3
"""Small Qt window to control PBP / PIP on the Philips Evnia 49M2C8900L.

Uses freevnia.usbddc (DDC/CI over USB through the VIA Billboard 2109:8884).
The monitor routes its USB (KVM) to the LEFT/main picture: if the main source is not this PC,
the program loses access until you switch back with the remote.
"""
import sys
import threading

import usb.core
from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QApplication, QButtonGroup, QColorDialog, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QMessageBox, QPushButton, QSlider, QVBoxLayout, QWidget,
                               QComboBox, QTabWidget)

from . import ambiglow as amb
from . import settings as st
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
            return "on" if p.get_vcp(dev, 0xE6, retries=10)["cur"] == 0 else "full"
        except Exception:
            return "err"


RUNNER = None                    # the animated effect currently drawn by FreEvnia (a thread)


def stop_runner():
    """Stop the animated effect. Must be called WITHOUT holding LOCK (the thread needs it to finish its frame)."""
    global RUNNER
    r, RUNNER = RUNNER, None
    if r is not None:
        r.stop()
        r.join(timeout=2)


def ambi(action, rgb=None, brightness=100):
    """Run one Ambiglow action under the USB lock (the LEDs are a separate USB device)."""
    stop_runner()
    with LOCK:
        dev = amb.find_device()
        if action == "color":
            amb.solid(dev, rgb, "all", brightness)
        elif action == "off":
            amb.off(dev)
        elif action == "release":
            amb.release(dev, device())


def apply(mode, loc, size, main="dp1", sub="usbc"):
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        p.apply_mode(dev, p.MODES[mode], p.SRC_MAIN[main], p.SRC_SUB[sub], size, loc)


class Signals(QObject):
    result = Signal(str, object)
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


class JobR(QRunnable):
    """Run fn off the UI thread and emit result(tag, value) (or failed)."""
    def __init__(self, fn, signals, tag):
        super().__init__()
        self.fn, self.sig, self.tag = fn, signals, tag

    def run(self):
        try:
            self.sig.result.emit(self.tag, self.fn())
        except Exception as e:
            self.sig.failed.emit(str(e))


def read_settings():
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        return st.read_all(dev), st.time_since_pixel_refresh(dev)


def write_setting(key, value):
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        s = st.BY_KEY[key]
        st.write(dev, s, value)
        import time
        time.sleep(0.4)
        return key, st.read(dev, s)


def do_pixel_refresh():
    with LOCK:
        dev = device()
        if dev is None:
            raise RuntimeError("No access to the monitor")
        st.pixel_refresh(dev)
    return None


def read_osd():
    with LOCK:
        dev = device()
        if dev is None:
            return "n/a"
        return amb.ddc_settings(dev)


def write_osd(**kw):
    """Change the monitor's own Ambiglow setting and make the LEDs show it.

    Follow video / follow audio / off are drawn by the monitor: FreEvnia lets go of the LEDs (clears its colour
    buffer and rewrites the mode). The other modes are drawn by FreEvnia (static once, the rest in a thread).
    What to draw comes from what was asked (current values + the change), not from a read-back, because the
    monitor sometimes answers a read with an older reply."""
    global RUNNER
    stop_runner()
    with LOCK:
        ddc = device()
        if ddc is None:
            raise RuntimeError("No access to the monitor (its USB hub is on another computer)")
        vals = amb.ddc_settings(ddc)
        vals.update({k: v for k, v in kw.items() if v is not None})
        amb.ddc_apply(ddc, **kw)
        led = amb.find_device()
        if vals["mode"] not in amb.SOFTWARE_MODES:
            amb.release(led, ddc)
        elif vals["mode"] == amb.DDC_STATIC:
            amb.draw(led, vals["mode"], vals["color"], vals["position"], vals["brightness"], vals["speed"])
    RUNNER = amb.make_runner(amb.find_device(), vals, lock=LOCK)
    if RUNNER is not None:
        RUNNER.start()
    return vals


class Window(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FreEvnia - PBP / PIP")
        self.sig = Signals()
        self.sig.state.connect(self.on_state)
        self.sig.result.connect(self.on_result)
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
        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        page1, page2, page3 = QWidget(), QWidget(), QWidget()
        l1, l2, l3 = QVBoxLayout(page1), QVBoxLayout(page2), QVBoxLayout(page3)
        self.tabs.addTab(page1, "PBP / PIP")
        self.tabs.addTab(page2, "Ambiglow")
        self.tabs.addTab(page3, "Settings")
        self.tabs.currentChanged.connect(self.on_tab)

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
        l1.addWidget(box)

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
        l1.addWidget(fbox)

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
        l1.addWidget(pbox)

        abox = QGroupBox("Ambiglow")
        al = QVBoxLayout(abox)
        crow = QHBoxLayout()
        self.ambi_btns = []
        for name in ("white", "warm", "red", "orange", "yellow", "green", "cyan", "blue", "purple", "pink"):
            r, g, b = amb.COLORS[name]
            sw = QPushButton()
            sw.setFixedSize(30, 30)
            sw.setToolTip(name)
            sw.setStyleSheet(f"background-color: rgb({r},{g},{b}); border: 1px solid gray;")
            sw.clicked.connect(lambda _=False, c=amb.COLORS[name]: self.set_ambi(c))
            crow.addWidget(sw)
            self.ambi_btns.append(sw)
        al.addLayout(crow)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Brightness"))
        self.ambi_level = QSlider(Qt.Horizontal)
        self.ambi_level.setRange(5, 100)
        self.ambi_level.setValue(100)
        self.ambi_level.sliderReleased.connect(lambda: self.set_ambi(self.ambi_rgb))
        brow.addWidget(self.ambi_level)
        al.addLayout(brow)
        arow = QHBoxLayout()
        for text, fn in (("Other colour…", self.pick_ambi), ("Off", lambda: self.ambi_run("off")),
                         ("Back to monitor OSD", lambda: self.ambi_run("release"))):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, f=fn: f())
            arow.addWidget(b)
            self.ambi_btns.append(b)
        al.addLayout(arow)
        aval = QLabel("Fixed colours are drawn by FreEvnia. \"Back to monitor OSD\" gives the LEDs back to the "
                      "monitor's own setting above.")
        aval.setWordWrap(True)
        aval.setStyleSheet("color: gray; font-size: 11px;")
        al.addWidget(aval)
        self.osd_label = QLabel("Monitor OSD setting: …")
        l2.addWidget(self.osd_label)
        self.build_osd_group(l2)
        l2.addWidget(abox)
        l2.addStretch(1)
        self.ambi_rgb = amb.COLORS["white"]

        nota = QLabel("The monitor sends its USB (KVM) to the left/main picture.\n"
                      "If the main source is not this PC, control is lost until you switch back with the remote.")
        nota.setStyleSheet("color: gray; font-size: 11px;")
        l1.addWidget(nota)
        l1.addStretch(1)
        self.build_settings(l3)

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

    def closeEvent(self, event):
        # An animated effect would freeze on its last frame: give the LEDs back before leaving.
        if RUNNER is not None:
            stop_runner()
            try:
                with LOCK:
                    amb.release(amb.find_device(), device())
            except Exception:
                pass
        event.accept()

    def build_osd_group(self, layout):
        gb = QGroupBox("Monitor's own Ambiglow setting (what the OSD stores)")
        gl = QGridLayout(gb)
        self.osd_combo = {}
        for r, (field, (code, table)) in enumerate(amb.DDC_FIELDS.items()):
            gl.addWidget(QLabel(field.capitalize()), r, 0)
            cb = QComboBox()
            for v, name in table.items():
                cb.addItem(name, v)
            cb.setEnabled(False)
            cb.activated.connect(lambda _i, f=field, c=cb: self.change_osd(f, c.currentData()))
            gl.addWidget(cb, r, 1)
            self.osd_combo[field] = cb
        note = QLabel("Off is done by the monitor itself. Follow video only works when chosen with the monitor's OSD "
                      "buttons. FreEvnia draws follow audio (it listens to what the PC plays; speed = sensitivity) "
                      "and the other effects while this window stays open.")
        note.setWordWrap(True)
        note.setStyleSheet("color: gray; font-size: 11px;")
        gl.addWidget(note, len(amb.DDC_FIELDS), 0, 1, 2)
        layout.addWidget(gb)
        QTimer.singleShot(300, lambda: self.pool.start(JobR(read_osd, self.sig, "osd")))

    def change_osd(self, field, value):
        self.status.setText("Sending to the monitor…")
        self.pool.start(JobR(lambda: write_osd(**{field: value}), self.sig, "osd-written"))

    def build_settings(self, layout):
        self.set_combo = {}
        for group, title in (("general", "General"), ("image", "Image and audio"), ("game", "Gaming"),
                             ("panel", "OLED panel care")):
            gb = QGroupBox(title)
            gl = QGridLayout(gb)
            for r, s in enumerate(x for x in st.SETTINGS if x.group == group):
                lab = QLabel(s.label)
                cb = QComboBox()
                for v, name in s.values.items():
                    cb.addItem(name, v)
                cb.setEnabled(False)
                if s.note:
                    cb.setToolTip(s.note)
                    lab.setToolTip(s.note)
                cb.activated.connect(lambda _i, k=s.key, c=cb: self.change_setting(k, c.currentData()))
                gl.addWidget(lab, r, 0)
                gl.addWidget(cb, r, 1)
                self.set_combo[s.key] = cb
            layout.addWidget(gb)
        self.refresh_label = QLabel("Time since the last pixel refresh: …")
        layout.addWidget(self.refresh_label)
        self.refresh_btn = QPushButton("Run pixel refresh…")
        self.refresh_btn.clicked.connect(self.confirm_pixel_refresh)
        layout.addWidget(self.refresh_btn)
        hint = QLabel("Pixel refresh is an OLED maintenance cycle: the panel is unusable while it runs.")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addStretch(1)

    def on_tab(self, i):
        if i == 1:
            self.pool.start(JobR(read_osd, self.sig, "osd"))
        elif i == 2:
            self.pool.start(JobR(read_settings, self.sig, "settings"))

    def change_setting(self, key, value):
        self.status.setText("Sending to the monitor…")
        self.pool.start(JobR(lambda: write_setting(key, value), self.sig, "setting-written"))

    def confirm_pixel_refresh(self):
        r = QMessageBox.warning(
            self, "Pixel refresh",
            "This starts the OLED pixel-refresh cycle. The panel cannot be used while it runs.\n\nContinue?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if r == QMessageBox.Yes:
            self.pool.start(Job(do_pixel_refresh, self.sig, ok_text="Pixel refresh started"))

    def on_result(self, tag, value):
        if tag == "settings":
            vals, since = value
            for key, cb in self.set_combo.items():
                v = vals.get(key)
                i = cb.findData(v) if v is not None else -1
                cb.setEnabled(i >= 0)
                if i >= 0:
                    cb.setCurrentIndex(i)
            self.refresh_label.setText("Time since the last pixel refresh: "
                                       + (f"{since[0]} h {since[1]} min" if since else "unknown"))
        elif tag == "setting-written":
            key, v = value
            s = st.BY_KEY[key]
            self.status.setText(f"✔ {s.label}: {st.label(s, v)}")
            cb = self.set_combo[key]
            if cb.findData(v) >= 0:
                cb.setCurrentIndex(cb.findData(v))
        elif tag in ("osd", "osd-written"):
            if value == "n/a":
                text = "Ambiglow settings not reachable (the monitor's USB cable is on another computer)."
                for cb in self.osd_combo.values():
                    cb.setEnabled(False)
            else:
                text = "Monitor Ambiglow setting: " + amb.ddc_describe(value)
                for field, cb in self.osd_combo.items():
                    i = cb.findData(value[field])
                    cb.setEnabled(True)
                    if i >= 0:
                        cb.setCurrentIndex(i)
                if tag == "osd-written":
                    self.status.setText("✔ " + text)
                    if value["mode"] == 1:
                        self.status.setText("✔ " + text + " — the monitor draws Follow video only when you pick it "
                                            "with its own OSD buttons")
            self.osd_label.setText(text)

    def ambi_run(self, action, rgb=None):
        lvl = self.ambi_level.value()
        text = {"color": "Ambiglow colour set", "off": "Ambiglow off", "release": "Ambiglow back to the OSD"}[action]
        self.pool.start(Job(lambda: ambi(action, rgb, lvl), self.sig, ok_text=text))
        QTimer.singleShot(800, lambda: self.pool.start(JobR(read_osd, self.sig, "osd")))

    def set_ambi(self, rgb):
        self.ambi_rgb = rgb
        self.ambi_run("color", rgb)

    def pick_ambi(self):
        c = QColorDialog.getColor(QColor(*self.ambi_rgb), self, "Ambiglow colour")
        if c.isValid():
            self.set_ambi((c.red(), c.green(), c.blue()))

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
