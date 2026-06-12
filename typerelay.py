#!/usr/bin/env python3
"""
TypeRelay — Type text from your local clipboard into a remote desktop, keystroke by keystroke.

Workflow:
  1. Copy text locally, paste it into the TypeRelay text box
  2. Set a countdown (seconds), then click "Start Typing"
  3. While the countdown runs, switch to the remote desktop and place your cursor
  4. After countdown hits zero, the text is typed out character by character

How it works:
  - ASCII characters & symbols: simulated via the `keyboard` library
    (explicit Shift+base_key combos, bypassing keyboard layout issues)
  - Non-ASCII (CJK, etc.): injected via Windows SendInput KEYEVENTF_UNICODE
    (RDP may not forward these — YMMV)

Dependencies: `keyboard` (pip install keyboard)
"""

import ctypes
from ctypes import wintypes
import sys
import time
import threading
import tkinter as tk
from tkinter import Text, Label, Frame, Button, Spinbox

# Fix Windows terminal GBK encoding garbled output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import keyboard

# ── Configuration ──────────────────────────────────────────────────
DEFAULT_COUNTDOWN = 3           # default countdown in seconds
CHAR_INTERVAL = 0.03            # delay between keystrokes (sec); too fast = dropped chars in remote desktop

# ── Windows SendInput (Unicode injection, for CJK / non-ASCII) ────
INPUT_KEYBOARD = 1
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_KEYUP = 0x0002


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class _INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("ki", _KEYBDINPUT),
    ]


def _send_unicode(ch: str):
    """Send a single Unicode codepoint via KEYEVENTF_UNICODE.

    Only used for characters with codepoint > 127 (e.g. CJK).
    May not work over RDP — the remote desktop client can drop these events.
    """
    cp = ord(ch)
    down = _INPUT(
        type=INPUT_KEYBOARD,
        ki=_KEYBDINPUT(wVk=0, wScan=cp, dwFlags=KEYEVENTF_UNICODE, time=0, dwExtraInfo=None),
    )
    up = _INPUT(
        type=INPUT_KEYBOARD,
        ki=_KEYBDINPUT(wVk=0, wScan=cp, dwFlags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, time=0, dwExtraInfo=None),
    )
    arr = (_INPUT * 2)(down, up)
    ctypes.windll.user32.SendInput(2, arr, ctypes.sizeof(_INPUT))


# ── Shift-symbol map: symbols that require Shift on a US-layout keyboard ─
_SHIFT_MAP = {
    '~': '`', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '{': '[', '}': ']',
    '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/',
}
for _ch in range(ord('A'), ord('Z') + 1):
    _SHIFT_MAP[chr(_ch)] = chr(_ch).lower()


def _send_char_safe(ch: str):
    """Send a single character safely.

    Strategy:
      - Non-ASCII (codepoint > 127): Unicode injection via SendInput
      - ASCII symbol requiring Shift: explicit Shift + base key combo
        (this bypasses keyboard-layout mismatches, e.g. Chinese keyboards)
      - Plain ASCII letter/digit: delegated to keyboard.send()
    """
    cp = ord(ch)
    if cp > 127:
        _send_unicode(ch)
    elif ch in _SHIFT_MAP:
        base = _SHIFT_MAP[ch]
        keyboard.press('shift')
        time.sleep(0.005)
        keyboard.press_and_release(base)
        time.sleep(0.005)
        keyboard.release('shift')
    else:
        keyboard.send(ch)


# ── Typing engine ───────────────────────────────────────────────────
def type_text(text: str):
    """Type `text` keystroke by keystroke. Runs on a background thread.

    Newlines are replaced with spaces for safety (remote terminals may
    interpret Enter differently).
    """
    text = text.replace("\n", " ")
    text = text.replace("\r", "")
    total = len(text)
    print(f"[start] typing {total} characters...", flush=True)

    for i, ch in enumerate(text):
        if ch == "\t":
            for _ in range(4):
                keyboard.send(" ")
                time.sleep(CHAR_INTERVAL)
        else:
            _send_char_safe(ch)
        time.sleep(CHAR_INTERVAL)

        if (i + 1) % 100 == 0:
            print(f"  typed {i + 1}/{total}", flush=True)

    print("[done] typing complete", flush=True)


# ── GUI ────────────────────────────────────────────────────────────
class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("TypeRelay")
        self.root.attributes("-topmost", True)
        self.root.resizable(True, True)
        self.root.minsize(520, 400)

        # ── Top hint ────────────────────────────────────────────
        Label(
            self.root,
            text="1. Paste text below → 2. Set countdown → 3. Click button → 4. Switch to remote desktop",
            font=("Microsoft YaHei UI", 9),
            fg="#555",
            pady=6,
        ).pack()

        # ── Text area ────────────────────────────────────────────
        self.text_area = Text(
            self.root,
            font=("Consolas", 11),
            wrap=tk.NONE,
            undo=True,
            padx=8,
            pady=8,
        )
        self.text_area.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 6))

        # Horizontal scrollbar
        h_scroll = tk.Scrollbar(self.root, orient=tk.HORIZONTAL, command=self.text_area.xview)
        h_scroll.pack(fill=tk.X, padx=10)
        self.text_area.config(xscrollcommand=h_scroll.set)

        # ── Countdown display ────────────────────────────────────
        self.countdown_label = Label(
            self.root,
            text="",
            font=("Consolas", 48, "bold"),
            fg="#4CAF50",
            pady=10,
        )
        self.countdown_label.pack()

        # ── Button bar ───────────────────────────────────────────
        btn_frame = Frame(self.root)
        btn_frame.pack(fill=tk.X, padx=10, pady=(4, 4))

        # Countdown seconds spinner
        Label(btn_frame, text="Countdown", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT)
        self.countdown_var = tk.IntVar(value=DEFAULT_COUNTDOWN)
        self.spinbox = Spinbox(
            btn_frame,
            from_=1,
            to=30,
            width=3,
            textvariable=self.countdown_var,
            font=("Microsoft YaHei UI", 11),
            justify=tk.CENTER,
        )
        self.spinbox.pack(side=tk.LEFT, padx=(4, 2))
        Label(btn_frame, text="sec", font=("Microsoft YaHei UI", 9)).pack(side=tk.LEFT, padx=(0, 16))

        self.type_btn = Button(
            btn_frame,
            text="Start Typing",
            font=("Microsoft YaHei UI", 11, "bold"),
            bg="#4CAF50",
            fg="white",
            activebackground="#45a049",
            padx=20,
            pady=6,
            command=self.on_button_click,
        )
        self.type_btn.pack(side=tk.LEFT, padx=(0, 10))

        self.clear_btn = Button(
            btn_frame,
            text="Clear",
            font=("Microsoft YaHei UI", 9),
            command=self.on_clear,
            padx=10,
        )
        self.clear_btn.pack(side=tk.LEFT)

        # Status label
        self.status_label = Label(
            btn_frame,
            text="",
            font=("Microsoft YaHei UI", 9),
            fg="#888",
        )
        self.status_label.pack(side=tk.RIGHT)

        # ── Bottom hint ──────────────────────────────────────────
        Label(
            self.root,
            text="Newlines → spaces | ASCII symbols via Shift combos | CJK via Unicode injection",
            font=("Microsoft YaHei UI", 8),
            fg="#aaa",
            pady=4,
        ).pack()

        # Center the window
        self.root.update_idletasks()
        self._center_window()

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._countdown_timer = None

    def _center_window(self):
        w = self.root.winfo_width()
        h = self.root.winfo_height()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        x = (sw - w) // 2
        y = (sh - h) // 2
        self.root.geometry(f"+{x}+{y}")

    def get_text(self):
        return self.text_area.get("1.0", tk.END).strip()

    def get_countdown(self):
        try:
            return max(1, min(30, self.countdown_var.get()))
        except Exception:
            return DEFAULT_COUNTDOWN

    def set_status(self, msg):
        self.status_label.config(text=msg)

    def set_countdown_display(self, text, color="#4CAF50"):
        self.countdown_label.config(text=text, fg=color)
        self.root.update_idletasks()

    def on_button_click(self):
        text = self.get_text()
        if not text:
            self.set_status("Paste some text first!")
            return
        cd = self.get_countdown()
        self._disable_controls()
        self._start_countdown(cd, text)

    def on_clear(self):
        self.text_area.delete("1.0", tk.END)
        self.set_status("")
        self.set_countdown_display("")

    def on_close(self):
        if self._countdown_timer is not None:
            self.root.after_cancel(self._countdown_timer)
        self.root.destroy()
        sys.exit(0)

    def _disable_controls(self):
        self.type_btn.config(state=tk.DISABLED)
        self.clear_btn.config(state=tk.DISABLED)
        self.spinbox.config(state=tk.DISABLED)

    def _enable_controls(self):
        self.type_btn.config(state=tk.NORMAL)
        self.clear_btn.config(state=tk.NORMAL)
        self.spinbox.config(state=tk.NORMAL)

    def _start_countdown(self, remaining, text):
        if remaining > 0:
            self.set_countdown_display(str(remaining))
            self.set_status(f"Countdown {remaining}s — switch to remote desktop now!")
            self._countdown_timer = self.root.after(
                1000, self._start_countdown, remaining - 1, text
            )
        else:
            self.set_countdown_display("GO!", "#FF5722")
            self.set_status("Typing...")
            self._countdown_timer = None
            self.root.after(200, lambda: threading.Thread(
                target=self._do_type, args=(text,), daemon=True
            ).start())

    def _do_type(self, text):
        try:
            type_text(text)
        except Exception as e:
            print(f"[error] typing failed: {e}", flush=True)
        self.root.after(0, self._restore_ui)

    def _restore_ui(self):
        self._enable_controls()
        self.set_countdown_display("")
        cd = self.get_countdown()
        self.set_status(f"Done! (countdown: {cd}s | interval: {CHAR_INTERVAL*1000:.0f}ms/char)")

    def run(self):
        self.root.mainloop()


# ── Entry point ─────────────────────────────────────────────────────
def main():
    print("=" * 50)
    print("  TypeRelay — type locally-copied text into remote desktop")
    print("=" * 50)
    print(f"  Default countdown: {DEFAULT_COUNTDOWN}s (adjustable 1–30)")
    print(f"  Keystroke interval: {CHAR_INTERVAL}s ({CHAR_INTERVAL*1000:.0f}ms)")
    print(f"  Newlines: replaced with spaces")
    print(f"  Method: ASCII keystroke simulation; CJK via Unicode injection")
    print()
    print("  Usage:")
    print("    1. Paste text into the window")
    print("    2. Set countdown seconds, click 'Start Typing'")
    print("    3. Switch to remote desktop, place cursor")
    print("    4. Text will be typed automatically after countdown")
    print()

    app = App()
    app.run()


if __name__ == "__main__":
    main()
