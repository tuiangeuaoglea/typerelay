#!/usr/bin/env python3
"""
TypeRelay 2 — explicit command and file-editor typing modes.

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
import os
import queue
import math
import struct
import zlib
from functools import lru_cache
from dataclasses import dataclass
import tkinter as tk
from tkinter import ttk
from tkinter import font as tkfont

# Fix Windows terminal GBK encoding garbled output
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

import keyboard

# ── Configuration ──────────────────────────────────────────────────
DEFAULT_COUNTDOWN = 5
CHAR_INTERVAL = 0.05            # seconds; remote clients may need a slower interval

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
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUTUNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


def _send_unicode(ch: str):
    """Send a single Unicode codepoint via KEYEVENTF_UNICODE.

    Only used for characters with codepoint > 127 (e.g. CJK).
    May not work over RDP — the remote desktop client can drop these events.
    """
    encoded = ch.encode("utf-16-le")
    events = []
    for offset in range(0, len(encoded), 2):
        unit = int.from_bytes(encoded[offset:offset + 2], "little")
        for flags in (KEYEVENTF_UNICODE, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP):
            events.append(_INPUT(
                type=INPUT_KEYBOARD,
                ki=_KEYBDINPUT(wVk=0, wScan=unit, dwFlags=flags,
                               time=0, dwExtraInfo=0),
            ))
    arr = (_INPUT * len(events))(*events)
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    send_input = user32.SendInput
    send_input.argtypes = (wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int)
    send_input.restype = wintypes.UINT
    sent = send_input(len(events), arr, ctypes.sizeof(_INPUT))
    if sent != len(events):
        raise OSError(ctypes.get_last_error(),
                      f"Unicode input incomplete ({sent}/{len(events)} events)")


# ── Shift-symbol map: symbols that require Shift on a US-layout keyboard ─
_SHIFT_MAP = {
    '~': '`', '!': '1', '@': '2', '#': '3', '$': '4', '%': '5',
    '^': '6', '&': '7', '*': '8', '(': '9', ')': '0',
    '_': '-', '+': '=', '{': '[', '}': ']',
    '|': '\\', ':': ';', '"': "'", '<': ',', '>': '.', '?': '/',
}
for _ch in range(ord('A'), ord('Z') + 1):
    _SHIFT_MAP[chr(_ch)] = chr(_ch).lower()


# Use physical main-keyboard keys. Name lookup can prefer numpad minus/divide;
# Shift+numpad-minus still produces '-' instead of the requested underscore.
_BASE_SCANS = {
    '-': 0x0C, '=': 0x0D, '[': 0x1A, ']': 0x1B,
    '\\': 0x2B, ';': 0x27, "'": 0x28, '`': 0x29,
    ',': 0x33, '.': 0x34, '/': 0x35,
}


def _base_key(ch: str):
    if ch in _BASE_SCANS:
        # Raw scan codes bypass name resolution, so initialize keyboard's
        # scan-to-VK table even when the first character is punctuation.
        keyboard.key_to_scan_codes('left shift')
        return _BASE_SCANS[ch]
    return ch


def _send_char_safe(ch: str, checkpoint=lambda: None):
    """Send a single character safely.

    Strategy:
      - Non-ASCII (codepoint > 127): Unicode injection via SendInput
      - ASCII symbol requiring Shift: explicit Shift + base key combo
        (this bypasses keyboard-layout mismatches, e.g. Chinese keyboards)
      - Plain ASCII letter/digit: delegated to keyboard.send()
    """
    checkpoint()
    cp = ord(ch)
    if cp > 127:
        _send_unicode(ch)
    elif ch in _SHIFT_MAP:
        base = _base_key(_SHIFT_MAP[ch])
        keyboard.press('left shift')
        try:
            time.sleep(0.005)
            checkpoint()
            keyboard.press_and_release(base)
            time.sleep(0.005)
        finally:
            keyboard.release('left shift')
    else:
        keyboard.send('space' if ch == ' ' else _base_key(ch))


VERSION = "2.1.1"
COMMAND_MODE = "command"
FILE_MODE = "file"


@dataclass(frozen=True)
class TypingOptions:
    mode: str = COMMAND_MODE
    interval: float = CHAR_INTERVAL
    expand_tabs: bool = True
    clear_autoindent: bool = False


class TypingStopped(Exception):
    pass


def prepare_text(text, options):
    """Normalize line endings, never strip indentation or boundary blank lines."""
    if options.mode not in (COMMAND_MODE, FILE_MODE):
        raise ValueError("未知输入模式")
    if not 0.01 <= options.interval <= 0.5:
        raise ValueError("输入间隔必须为 10–500 毫秒")
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    if any(ord(ch) < 32 and ch not in '\n\t' or ord(ch) == 127 for ch in text):
        raise ValueError("文本含有换行、Tab 之外的控制字符，请先移除")
    if options.mode == COMMAND_MODE:
        text = text.replace('\n', ' ').replace('\t', '    ')
    elif options.expand_tabs:
        text = text.replace('\t', '    ')
    return text


class WindowsFocus:
    """Check foreground root HWND/PID; no hooks, clipboard, or input capture."""
    def __init__(self):
        self.api = ctypes.WinDLL('user32', use_last_error=True)
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.GetWindowThreadProcessId.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.DWORD))
        self.api.GetAsyncKeyState.argtypes = (ctypes.c_int,)
        self.api.GetAsyncKeyState.restype = ctypes.c_short

    def foreground(self):
        hwnd = self.api.GetForegroundWindow()
        hwnd = self.api.GetAncestor(hwnd, 2) if hwnd else 0
        pid = wintypes.DWORD()
        self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return hwnd, pid.value

    def escape_pressed(self):
        return bool(self.api.GetAsyncKeyState(0x1B) & 0x8001)

    def capture(self):
        target = self.foreground()
        if not target[0] or not target[1] or target[1] == os.getpid():
            raise TypingStopped("尚未切到目标窗口，未发送任何文本")
        return target


def type_text(text, options=None, *, checkpoint=lambda: None,
              wait=time.sleep, send_key=None, send_char=None, progress=lambda n, total: None):
    """Send a prepared snapshot. A checkpoint precedes each key operation."""
    options = options or TypingOptions()
    text = prepare_text(text, options)
    send_key = send_key or keyboard.send
    send_char = send_char or (lambda ch: _send_char_safe(ch, checkpoint))

    def key(name):
        checkpoint()
        send_key(name)
        wait(options.interval)

    for index, ch in enumerate(text, 1):
        checkpoint()
        if ch == '\n':
            key('enter')
            if options.clear_autoindent:
                # Select only the generated prefix before the new-line caret.
                # A placeholder avoids Backspace joining lines when none exists.
                wait(max(0.15, options.interval))
                key('shift+home')
                key('space')
                key('backspace')
        elif ch == '\t':
            key('tab')
        else:
            send_char(ch)
            wait(options.interval)
        if index % 10 == 0 or index == len(text):
            progress(index, len(text))
    checkpoint()
    return len(text)


def text_statistics(text):
    """Count source characters and logical lines without changing the source."""
    normalized = text.replace('\r\n', '\n').replace('\r', '\n')
    return len(text), normalized.count('\n') + 1 if text else 0


COLORS = {
    'bg': '#F5F6FC', 'surface': '#FFFFFF', 'ink': '#252B45',
    'muted': '#7A819A', 'border': '#E5E7F2', 'accent': '#6557DD',
    'soft': '#F0EDFF', 'green': '#177454', 'red': '#B42338',
}
STATE_LABELS = {
    'ready': ('就绪', COLORS['muted']),
    'countdown': ('等待开始', COLORS['accent']),
    'typing': ('输入中', COLORS['accent']),
    'stopping': ('正在停止', '#946200'),
    'completed': ('已完成', COLORS['green']),
    'stopped': ('已停止', '#946200'),
    'error': ('请检查', COLORS['red']),
}


def configure_dpi_awareness():
    """Opt in before creating Tk; retain awareness chosen by the host/manifest."""
    if sys.platform != 'win32':
        return False
    try:
        user32 = ctypes.WinDLL('user32', use_last_error=True)
        try:
            modern = user32.SetProcessDpiAwarenessContext
            modern.argtypes = (ctypes.c_void_p,)
            modern.restype = wintypes.BOOL
            if modern(ctypes.c_void_p(-4)):
                return True
            if ctypes.get_last_error() == 5:  # The host has already selected awareness.
                return False
        except AttributeError:
            pass
        try:
            shcore = ctypes.WinDLL('shcore', use_last_error=True)
            per_monitor = shcore.SetProcessDpiAwareness
            per_monitor.argtypes = (ctypes.c_int,)
            per_monitor.restype = ctypes.c_long
            result = per_monitor(2)
            if result == 0:
                return True
            if result in (-2147024891, 0x80070005):
                return False
        except (AttributeError, OSError):
            pass
        legacy = user32.SetProcessDPIAware
        legacy.argtypes = ()
        legacy.restype = wintypes.BOOL
        return bool(legacy())
    except (AttributeError, OSError):
        return False


def _round_coverage(x, y, width, height, radius, inset=0):
    """One-pixel analytic antialiasing of a rounded rectangle's signed distance."""
    half_width, half_height = width / 2 - inset, height / 2 - inset
    if half_width <= 0 or half_height <= 0:
        return 0.0
    radius = max(0, min(radius - inset, half_width, half_height))
    qx = abs(x + 0.5 - width / 2) - (half_width - radius)
    qy = abs(y + 0.5 - height / 2) - (half_height - radius)
    distance = math.hypot(max(qx, 0), max(qy, 0)) + min(max(qx, qy), 0) - radius
    return max(0.0, min(1.0, 0.5 - distance))


@lru_cache(maxsize=24)
def rounded_gradient_png(width, height, start, end, radius, border=None, border_width=1):
    """RGBA PNG at the widget's pixel size, with antialiased edges and no add-ons."""
    width, height = max(1, int(width)), max(1, int(height))
    radius = max(0, min(radius, width / 2, height / 2))
    first = tuple(int(start[i:i + 2], 16) for i in (1, 3, 5))
    last = tuple(int(end[i:i + 2], 16) for i in (1, 3, 5))
    border_rgb = tuple(int(border[i:i + 2], 16) for i in (1, 3, 5)) if border else None
    pixels = [tuple(round(a + (b - a) * x / max(1, width - 1)) for a, b in zip(first, last))
              for x in range(width)]

    def row(y):
        data = bytearray(b'\x00')  # PNG filter: None.
        for x, rgb in enumerate(pixels):
            outer = _round_coverage(x, y, width, height, radius)
            if border_rgb and outer:
                inner = _round_coverage(x, y, width, height, radius, inset=border_width)
                ratio = min(1.0, inner / outer)
                rgb = tuple(round(b + (c - b) * ratio) for b, c in zip(border_rgb, rgb))
            data.extend((*rgb, round(outer * 255)))
        return bytes(data)

    # Only corner rows differ; reuse the straight middle instead of rerendering it.
    edge_rows = min(math.ceil(max(radius, border_width if border else 0)), height // 2)
    top = [row(y) for y in range(edge_rows)]
    center_height = height - edge_rows * 2
    raw = b''.join(top) + (row(edge_rows) * center_height if center_height else b'') + b''.join(reversed(top))

    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!IIBBBBB', width, height, 8, 6, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(raw, 3)) + chunk(b'IEND', b''))


def _draw_gradient(canvas, width, height, start, end, radius=18, border=None, border_width=1):
    # Keep the PhotoImage referenced for as long as the canvas displays it.
    canvas._surface_image = tk.PhotoImage(master=canvas, data=rounded_gradient_png(
        width, height, start, end, radius, border, border_width))
    return canvas.create_image(0, 0, image=canvas._surface_image, anchor='nw', tags='paint')


def scrollbar_geometry(first, last, track_length, min_thumb=24):
    track_length = max(0, track_length)
    span = max(0.0, min(1.0, last - first))
    length = min(track_length, max(min_thumb, span * track_length))
    position = max(0.0, min(1.0, first / (1 - span))) if span < 1 else 0
    return position * (track_length - length), length


class SlimScrollbar(tk.Canvas):
    """Arrow-free scrollbar; appears only when the associated view overflows."""
    def __init__(self, parent, orient, command):
        options = {'width': 10, 'height': 1} if orient == 'vertical' else {'height': 10, 'width': 1}
        super().__init__(parent, bg='white', highlightthickness=0, borderwidth=0,
                         takefocus=False, cursor='arrow', **options)
        self.orient, self.command = orient, command
        self.first, self.last = 0.0, 1.0
        self.drag_offset = None
        self.hovered = False
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda event: self._hover(True))
        self.bind('<Leave>', lambda event: self._hover(False))
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<B1-Motion>', self._drag)
        self.bind('<ButtonRelease-1>', self._release)

    def _axis(self, event):
        return event.y if self.orient == 'vertical' else event.x

    def _length(self):
        return self.winfo_height() if self.orient == 'vertical' else self.winfo_width()

    def set(self, first, last):
        self.first = max(0.0, min(1.0, float(first)))
        self.last = max(self.first, min(1.0, float(last)))
        if self.last <= self.first or self.last - self.first >= 1 - 1e-6:
            self.grid_remove()
        else:
            self.grid()
            self._draw()

    def _hover(self, hovered):
        self.hovered = hovered
        self._draw()

    def _draw(self, event=None):
        self.delete('all')
        position, length = scrollbar_geometry(self.first, self.last, self._length())
        if length <= 0:
            return
        color = '#9FA6C7' if self.hovered or self.drag_offset is not None else '#D1D5E6'
        thickness = 6 if self.hovered or self.drag_offset is not None else 4
        width, height = (thickness, max(1, round(length))) if self.orient == 'vertical' else (max(1, round(length)), thickness)
        self._surface_image = tk.PhotoImage(master=self, data=rounded_gradient_png(width, height, color, color, thickness / 2))
        x, y = (2, round(position)) if self.orient == 'vertical' else (round(position), 2)
        self.create_image(x, y, image=self._surface_image, anchor='nw')

    def _press(self, event):
        position, length = scrollbar_geometry(self.first, self.last, self._length())
        axis = self._axis(event)
        if position <= axis <= position + length:
            self.drag_offset = axis - position
        else:
            self.drag_offset = None
            self.command('scroll', -1 if axis < position else 1, 'pages')
        self._draw()

    def _drag(self, event):
        if self.drag_offset is None:
            return
        _, length = scrollbar_geometry(self.first, self.last, self._length())
        travel = self._length() - length
        if travel <= 0:
            return
        span = self.last - self.first
        fraction = max(0.0, min(1 - span, (self._axis(event) - self.drag_offset) / travel * (1 - span)))
        self.command('moveto', fraction)

    def _release(self, event):
        self.drag_offset = None
        self._draw()


class GradientButton(tk.Canvas):
    """Keyboard-accessible native-Tk action button with focus and disabled states."""
    def __init__(self, parent, text, command):
        super().__init__(parent, height=50, width=180, highlightthickness=0,
                         borderwidth=0, bg=COLORS['bg'], takefocus=True, cursor='hand2')
        self.caption, self.command = text, command
        self.hovered = False
        self.pressed = False
        self.focused = False
        self.bind('<Configure>', self._draw)
        self.bind('<Enter>', lambda event: self._appearance(hovered=True))
        self.bind('<Leave>', lambda event: self._appearance(hovered=False, pressed=False))
        self.bind('<FocusIn>', lambda event: self._appearance(focused=True))
        self.bind('<FocusOut>', lambda event: self._appearance(focused=False, pressed=False))
        self.bind('<ButtonPress-1>', self._press)
        self.bind('<ButtonRelease-1>', self._release)
        self.bind('<Return>', self._activate)
        self.bind('<space>', self._activate)

    def configure(self, cnf=None, **kwargs):
        result = super().configure(cnf, **kwargs)
        if 'state' in kwargs:
            super().configure(takefocus=kwargs['state'] != 'disabled')
            self._draw()
        return result

    config = configure

    def _appearance(self, **changes):
        for name, value in changes.items():
            setattr(self, name, value)
        self._draw()

    def _press(self, event):
        if self.cget('state') != 'disabled':
            self.focus_set()
            self._appearance(pressed=True)

    def _release(self, event):
        activate = self.pressed and 0 <= event.x < self.winfo_width() and 0 <= event.y < self.winfo_height()
        self._appearance(pressed=False)
        if activate:
            self._activate(event)

    def _activate(self, event=None):
        if self.cget('state') != 'disabled':
            self.command()
        return 'break'

    def _draw(self, event=None):
        self.delete('all')
        width, height = self.winfo_width(), self.winfo_height()
        disabled = self.cget('state') == 'disabled'
        colors = ('#DCD9F0', '#DAE1F3') if disabled else (
            ('#5B4BC8', '#3969D8') if self.pressed else
            ('#8371F7', '#578DF9') if self.hovered else ('#7562EC', '#487FF0'))
        _draw_gradient(self, width, height, *colors, radius=15,
                       border='#FFFFFF' if self.focused and not disabled else None, border_width=2)
        self.create_text(width / 2, height / 2, text=self.caption, fill='#8B87A6' if disabled else 'white',
                         font=('Microsoft YaHei UI', 11, 'bold'))


class EditorCard(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg=COLORS['bg'], highlightthickness=0, height=160, width=1)
        self.inner = tk.Frame(self, bg='white')
        self.body = self.create_window(14, 12, window=self.inner, anchor='nw')
        self.bind('<Configure>', self._resize)

    def _resize(self, event):
        self.delete('paint')
        _draw_gradient(self, event.width, event.height, '#FFFFFF', '#FFFFFF',
                       radius=22, border=COLORS['border'])
        self.tag_lower('paint')
        self.itemconfigure(self.body, width=max(1, event.width - 28), height=max(1, event.height - 24))


class App:
    def __init__(self, root=None):
        if root is None:
            configure_dpi_awareness()
        self.root = root if root is not None else tk.Tk()
        self.root.title(f"TypeRelay {VERSION}")
        self.root.attributes('-topmost', True)
        self.root.geometry('960x720')
        self.root.minsize(780, 600)
        self.events = queue.Queue()
        self.cancel = threading.Event()
        self.focus = WindowsFocus()
        self.busy = False
        self.timer = None
        self.closing = False
        self.state_name = 'ready'
        self.sent_count = 0
        self.total_count = 0
        self.advanced_open = False
        self.poll_timer = None
        self._stats_timer = None
        self.mode = tk.StringVar(value=COMMAND_MODE)
        self.expand_tabs = tk.BooleanVar(value=True)
        self.autoindent = tk.BooleanVar(value=False)
        self.countdown_var = tk.StringVar(value=str(DEFAULT_COUNTDOWN))
        self.interval_var = tk.StringVar(value=str(round(CHAR_INTERVAL * 1000)))
        self._build_styles()
        self._build_ui()
        self.update_mode()
        self.refresh_stats()
        self.set_state('ready', '粘贴文本后，点击开始输入。')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.bind('<Configure>', self._on_resize)
        self.poll_timer = self.root.after(50, self.poll)

    def _build_styles(self):
        self.root.configure(bg=COLORS['bg'])
        self.root.option_add('*Font', ('Microsoft YaHei UI', 10))
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10), background=COLORS['bg'],
                        foreground=COLORS['ink'])
        style.configure('TButton', padding=(14, 9), background=COLORS['surface'],
                        bordercolor=COLORS['border'], lightcolor=COLORS['surface'],
                        darkcolor=COLORS['surface'], focuscolor=COLORS['accent'])
        style.map('TButton', background=[('disabled', '#EDF0F5'), ('pressed', '#E3E9F4'),
                                         ('active', '#EDF2FA')],
                  foreground=[('disabled', '#8C98AA')],
                  bordercolor=[('focus', COLORS['accent'])])
        style.configure('Primary.TButton', background=COLORS['accent'], foreground='white',
                        font=('Microsoft YaHei UI', 10, 'bold'), bordercolor=COLORS['accent'],
                        lightcolor=COLORS['accent'], darkcolor=COLORS['accent'], focuscolor='white')
        style.map('Primary.TButton', background=[('disabled', '#D8E0EF'), ('pressed', '#1948B5'),
                                                 ('active', '#366BE8')],
                  foreground=[('disabled', '#7E8EA9'), ('!disabled', 'white')])
        style.configure('Stop.TButton', foreground=COLORS['red'])
        style.map('Stop.TButton', background=[('disabled', '#EDF0F5'), ('active', '#FFF0F1')],
                  foreground=[('disabled', '#8C98AA'), ('!disabled', COLORS['red'])])
        style.configure('Quiet.TButton', padding=(8, 4), background=COLORS['bg'],
                        borderwidth=0, foreground=COLORS['muted'])
        style.configure('Settings.TButton', padding=(14, 8), background='#F8F7FF',
                        borderwidth=0, bordercolor='#F8F7FF', foreground=COLORS['accent'])
        style.map('Settings.TButton', background=[('active', 'white'), ('disabled', '#ECEBF5')])
        style.configure('Clear.TButton', padding=(8, 3), background='white', borderwidth=0,
                        foreground=COLORS['muted'], font=('Microsoft YaHei UI', 9))
        style.layout('Segment.TRadiobutton', style.layout('Toolbutton'))
        style.configure('Segment.TRadiobutton', padding=(16, 6), background='white',
                        foreground=COLORS['muted'], borderwidth=1, bordercolor='white',
                        lightcolor='white', darkcolor='white', focuscolor=COLORS['accent'])
        style.map('Segment.TRadiobutton',
                  background=[('disabled', '#F4F3F8'), ('selected', COLORS['soft']), ('active', '#F7F5FF')],
                  foreground=[('disabled', '#8C98AA'), ('selected', COLORS['accent'])],
                  bordercolor=[('focus', COLORS['accent']), ('selected', COLORS['soft'])])
        style.configure('TSpinbox', padding=5, arrowsize=12, fieldbackground='white',
                        bordercolor=COLORS['border'], arrowcolor=COLORS['muted'])
        style.map('TSpinbox', bordercolor=[('focus', COLORS['accent'])],
                  fieldbackground=[('disabled', '#EDF0F5')])
        style.configure('TCheckbutton', focuscolor=COLORS['accent'])
        style.configure('Horizontal.TProgressbar', thickness=5, borderwidth=0,
                        troughcolor='#E4EAF3', background=COLORS['accent'])
        for state, (_, color) in STATE_LABELS.items():
            style.configure(state + '.TLabel', foreground=color, background=COLORS['bg'],
                            font=('Microsoft YaHei UI', 10, 'bold'))

    def _label(self, parent, text='', size=10, color=None, **kwargs):
        return tk.Label(parent, text=text, font=('Microsoft YaHei UI', size),
                        fg=color or COLORS['muted'], bg=parent.cget('bg'), **kwargs)

    def _build_ui(self):
        page = tk.Frame(self.root, bg=COLORS['bg'])
        page.pack(fill='both', expand=True, padx=28, pady=(24, 20))
        page.columnconfigure(0, weight=1)
        page.rowconfigure(2, weight=1)

        self._hero_title_font = tkfont.Font(root=self.root, family='Segoe UI', size=24, weight='bold')
        self._hero_body_font = tkfont.Font(root=self.root, family='Microsoft YaHei UI', size=10)
        hero_height = max(102, self._hero_title_font.metrics('linespace') + self._hero_body_font.metrics('linespace') + 44)
        self.hero = tk.Canvas(page, height=hero_height, bg=COLORS['bg'], highlightthickness=0)
        self.hero.grid(row=0, column=0, sticky='ew', pady=(0, 18))
        self.advanced_button = ttk.Button(self.hero, text='设置', command=self.toggle_advanced,
                                          style='Settings.TButton')
        self.hero.bind('<Configure>', self._draw_hero)

        self.advanced_frame = tk.Frame(page, bg=COLORS['bg'])
        self.advanced_frame.grid(row=1, column=0, sticky='ew', padx=8, pady=(0, 16))
        timing = tk.Frame(self.advanced_frame, bg=COLORS['bg'])
        timing.grid(row=0, column=0, columnspan=2, sticky='w', pady=(0, 10))
        self._label(timing, '倒计时', size=9).grid(row=0, column=0, padx=(0, 8))
        self.countdown_box = ttk.Spinbox(timing, from_=1, to=60, textvariable=self.countdown_var,
                                         width=4, justify='center', command=self._update_summary)
        self.countdown_box.grid(row=0, column=1)
        self._label(timing, '秒', size=9).grid(row=0, column=2, padx=(5, 24))
        self._label(timing, '逐字间隔', size=9).grid(row=0, column=3, padx=(0, 8))
        self.interval_box = ttk.Spinbox(timing, from_=10, to=500, increment=10,
                                        textvariable=self.interval_var, width=5, justify='center',
                                        command=self._update_summary)
        self.interval_box.grid(row=0, column=4)
        self._label(timing, 'ms', size=9).grid(row=0, column=5, padx=(5, 0))
        for variable in (self.countdown_var, self.interval_var):
            variable.trace_add('write', self._update_summary)
        self.tabs_check = ttk.Checkbutton(self.advanced_frame, text='Tab 转为 4 个空格', variable=self.expand_tabs)
        self.tabs_check.grid(row=1, column=0, sticky='w', padx=(0, 22))
        self.indent_check = ttk.Checkbutton(self.advanced_frame, text='清除目标自动缩进', variable=self.autoindent)
        self.indent_check.grid(row=1, column=1, sticky='w')
        self.advanced_hint = self._label(self.advanced_frame,
            '后两项仅文件模式可用。清除缩进要求目标 Shift+Home 选至行首；远程丢字可调到 80–100ms。',
            size=9, anchor='w', justify='left', wraplength=650)
        self.advanced_hint.grid(row=2, column=0, columnspan=2, sticky='ew', pady=(7, 0))
        self.advanced_frame.grid_remove()

        self.editor_card = EditorCard(page)
        self.editor_card.grid(row=2, column=0, sticky='nsew')
        editor = self.editor_card.inner
        editor.columnconfigure(0, weight=1)
        editor.rowconfigure(1, weight=1)
        editor_header = tk.Frame(editor, bg='white')
        editor_header.grid(row=0, column=0, sticky='ew', pady=(0, 10))
        self.mode_buttons = []
        for label, value in (('指令', COMMAND_MODE), ('文件', FILE_MODE)):
            button = ttk.Radiobutton(editor_header, text=label, variable=self.mode, value=value,
                                     style='Segment.TRadiobutton', command=self.update_mode, takefocus=True)
            button.pack(side='left', padx=(0, 4))
            self.mode_buttons.append(button)
        self.clear_button = ttk.Button(editor_header, text='清空', command=self.clear, style='Clear.TButton')
        self.clear_button.pack(side='right')
        self.stats_label = self._label(editor_header, size=9)
        self.stats_label.pack(side='right', padx=(8, 12))

        text_frame = tk.Frame(editor, bg='white')
        text_frame.grid(row=1, column=0, sticky='nsew')
        text_frame.columnconfigure(0, weight=1)
        text_frame.rowconfigure(0, weight=1)
        self.text_area = tk.Text(text_frame, font=('Consolas', 12), wrap='none', undo=True,
                                 bg='white', fg=COLORS['ink'], insertbackground=COLORS['accent'],
                                 selectbackground='#E8E3FF', selectforeground=COLORS['ink'],
                                 relief='flat', borderwidth=0, padx=8, pady=8,
                                 highlightthickness=1, highlightcolor=COLORS['accent'],
                                 highlightbackground='white', height=1, width=1)
        self.text_area.grid(row=0, column=0, sticky='nsew')
        vertical = SlimScrollbar(text_frame, orient='vertical', command=self.text_area.yview)
        vertical.grid(row=0, column=1, sticky='ns')
        horizontal = SlimScrollbar(text_frame, orient='horizontal', command=self.text_area.xview)
        horizontal.grid(row=1, column=0, sticky='ew')
        self.text_area.config(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.empty_hint = self._label(self.text_area, '粘贴你想输入的内容…', size=12,
                                      color='#A0A4BA', anchor='nw')
        self.empty_hint.bind('<Button-1>', lambda _: self.text_area.focus_set())
        self.text_area.bind('<<Modified>>', self._on_text_modified)
        self.text_area.bind('<Shift-MouseWheel>', self._scroll_horizontal)
        self.mode_hint = self._label(editor, size=9, anchor='w', justify='left', wraplength=650)
        self.mode_hint.grid(row=2, column=0, sticky='w', pady=(8, 0))

        actions = tk.Frame(page, bg=COLORS['bg'])
        actions.grid(row=3, column=0, sticky='ew', pady=(18, 12))
        actions.columnconfigure(0, weight=1)
        self.start_button = GradientButton(actions, text='开始输入  →', command=self.start)
        self.start_button.grid(row=0, column=0, sticky='ew')
        self.stop_button = ttk.Button(actions, text='停止 / Esc', command=self.stop,
                                      state='disabled', style='Stop.TButton')
        self.stop_button.grid(row=0, column=1, padx=(10, 0), sticky='ns')
        self.stop_button.grid_remove()

        status_area = tk.Frame(page, bg=COLORS['bg'])
        status_area.grid(row=4, column=0, sticky='ew')
        status_area.columnconfigure(2, weight=1)
        self.countdown_display = tk.Label(status_area, text='', font=('Consolas', 17, 'bold'),
                                           fg=COLORS['accent'], bg=COLORS['bg'])
        self.countdown_display.grid(row=0, column=0, sticky='w', padx=(0, 8))
        self.state_badge = ttk.Label(status_area, text='就绪', style='ready.TLabel')
        self.state_badge.grid(row=0, column=1, sticky='w', padx=(0, 9))
        self.status = self._label(status_area, size=9, anchor='w', justify='left', wraplength=600)
        self.status.grid(row=0, column=2, sticky='ew')
        self.status.bind('<Configure>', lambda event: self.status.config(wraplength=max(120, event.width - 2)))
        self.progress_label = self._label(status_area, size=9)
        self.progress_label.grid(row=1, column=0, columnspan=3, sticky='e', pady=(4, 3))
        self.progressbar = ttk.Progressbar(status_area, mode='determinate', maximum=1, value=0)
        self.progressbar.grid(row=2, column=0, columnspan=3, sticky='ew')
        self.settings_summary = self._label(status_area, size=9)
        self.settings_summary.grid(row=3, column=0, columnspan=2, sticky='w', pady=(9, 0))
        self._label(status_area, '目标输入法：英文 / 半角', size=9).grid(
            row=3, column=2, sticky='e', pady=(9, 0))
        self._update_summary()

    def _draw_hero(self, event):
        self.hero.delete('all')
        _draw_gradient(self.hero, event.width, event.height, '#EEE9FF', '#E8F2FF', radius=22)
        self.hero.create_text(24, 20, text='TypeRelay', anchor='nw',
                              font=self._hero_title_font, fill=COLORS['ink'])
        subtitle_y = 26 + self._hero_title_font.metrics('linespace')
        self.hero.create_text(26, subtitle_y, text='本机文本  →  目标窗口', anchor='nw',
                              font=self._hero_body_font, fill='#7A7C9D')
        self.hero.create_window(event.width - 26, event.height / 2,
                                window=self.advanced_button, anchor='e')

    def _update_summary(self, *args):
        if hasattr(self, 'settings_summary'):
            self.settings_summary.config(text=f'{self.countdown_var.get()} 秒准备  ·  {self.interval_var.get()} ms / 字符')
    def _on_resize(self, event):
        if event.widget == self.root:
            width = max(300, event.width - 54)
            self.mode_hint.config(wraplength=width)
            self.advanced_hint.config(wraplength=width - 16)

    def _on_text_modified(self, event=None):
        if self.text_area.edit_modified():
            self.text_area.edit_modified(False)
            if self._stats_timer is not None:
                self.root.after_cancel(self._stats_timer)
            self._stats_timer = self.root.after(60, self.refresh_stats)

    def _scroll_horizontal(self, event):
        if event.delta:
            steps = max(1, abs(int(event.delta / 120)))
            self.text_area.xview_scroll(-steps if event.delta > 0 else steps, 'units')
        return 'break'

    def refresh_stats(self, event=None):
        self._stats_timer = None
        text = self.get_text()
        characters, lines = text_statistics(text)
        self.stats_label.config(text=f'{characters:,} 字符 · {lines:,} 行')
        if text:
            self.empty_hint.place_forget()
        else:
            self.empty_hint.place(x=16, y=11)
        if not self.busy:
            self.update_progress(0, 0)
            self.set_state('ready', '开始输入后，切到目标窗口。' if text
                           else '粘贴文本后，点击开始输入。')

    def toggle_advanced(self):
        if self.busy:
            return
        self.advanced_open = not self.advanced_open
        if self.advanced_open:
            self.advanced_frame.grid()
        else:
            self.advanced_frame.grid_remove()
        self.advanced_button.config(text='收起设置' if self.advanced_open else '设置')

    def set_state(self, state, message, countdown=None):
        self.state_name = state
        label, color = STATE_LABELS[state]
        self.state_badge.config(text=label, style=state + '.TLabel')
        self.status.config(text=message, fg=color)
        display = str(countdown).zfill(2) if countdown is not None else ''
        self.countdown_display.config(text=display, fg=color)
        if countdown is None:
            self.countdown_display.grid_remove()
        else:
            self.countdown_display.grid()

    def update_progress(self, sent, total):
        self.sent_count = max(0, min(sent, total))
        self.total_count = max(0, total)
        self.progressbar.config(maximum=max(1, self.total_count), value=self.sent_count)
        self.progress_label.config(text=(f'{self.sent_count:,} / {self.total_count:,} 字符'
                                        if self.total_count else ''))
        for widget in (self.progressbar, self.progress_label):
            if self.total_count:
                widget.grid()
            else:
                widget.grid_remove()

    def get_text(self):
        return self.text_area.get('1.0', 'end-1c')

    def update_mode(self):
        file_mode = self.mode.get() == FILE_MODE
        self.mode_hint.config(text=(
            '保留换行与缩进。请先关闭目标自动缩进、自动补全。'
            if file_mode else
            '换行转为空格 · 不发送回车，输入后由你核对并执行。'))
        for control in (self.tabs_check, self.indent_check):
            control.config(state=tk.NORMAL if file_mode and not self.busy else tk.DISABLED)

    def set_busy(self, busy):
        self.busy = busy
        state = tk.DISABLED if busy else tk.NORMAL
        for control in (*self.mode_buttons, self.countdown_box, self.interval_box,
                        self.start_button, self.clear_button, self.text_area, self.advanced_button):
            control.config(state=state)
        self.stop_button.config(state=tk.NORMAL if busy else tk.DISABLED)
        if busy:
            self.stop_button.grid()
        else:
            self.stop_button.grid_remove()
        self.update_mode()

    def start(self):
        if self.busy:
            return
        text = self.get_text()
        if not text:
            self.set_state('error', '请先粘贴要输入的文本。')
            return
        try:
            try:
                seconds = int(self.countdown_var.get())
            except ValueError:
                raise ValueError('倒计时必须为 1–60 秒的整数') from None
            if not 1 <= seconds <= 60:
                raise ValueError('倒计时必须为 1–60 秒')
            try:
                interval = float(self.interval_var.get()) / 1000
            except ValueError:
                raise ValueError('逐字间隔必须为 10–500 毫秒') from None
            options = TypingOptions(self.mode.get(), interval,
                                    self.expand_tabs.get(), self.autoindent.get())
            prepared = prepare_text(text, options)
        except ValueError as error:
            self.set_state('error', str(error))
            return
        self.cancel.clear()
        self.focus.escape_pressed()  # Discard stale Escape history before this run.
        if self._stats_timer is not None:
            self.root.after_cancel(self._stats_timer)
            self._stats_timer = None
        self.update_progress(0, len(prepared))
        self.set_busy(True)
        self.countdown(seconds, prepared, options)

    def countdown(self, seconds, text, options):
        self.timer = None
        if self.cancel.is_set() or self.focus.escape_pressed():
            self.finish('已停止，未发送文本。', state='stopped')
        elif seconds:
            name = '文件编辑' if options.mode == FILE_MODE else 'MobaXterm 指令'
            self.set_state('countdown', f'{name} · 请切到目标窗口，放好光标。', countdown=seconds)
            self.timer = self.root.after(1000, self.countdown, seconds - 1, text, options)
        else:
            try:
                target = self.focus.capture()
            except TypingStopped as error:
                self.finish(str(error), state='stopped')
                return
            self.set_state('typing', '正在输入；按 Esc 或切离目标窗口可停止。')
            threading.Thread(target=self.worker, args=(text, options, target), daemon=True).start()

    def checkpoint(self, target):
        if self.cancel.is_set() or self.focus.escape_pressed():
            raise TypingStopped('已停止，目标内可能已有部分文本；请先检查后再重试')
        if self.focus.foreground() != target:
            raise TypingStopped('目标窗口失焦，已停止；请检查已输入的部分文本')

    def worker(self, text, options, target):
        def check():
            self.checkpoint(target)

        def wait(seconds):
            # Small interruptible waits bound Stop/Escape response time.
            deadline = time.monotonic() + seconds
            while True:
                check()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return
                self.cancel.wait(min(0.02, remaining))
        try:
            count = type_text(text, options, checkpoint=check, wait=wait,
                              progress=lambda n, total: self.events.put(('progress', (n, total))))
            message = ('输入结束，请在目标内核对后手动按回车。' if options.mode == COMMAND_MODE
                       else '输入结束，请在目标内核对换行与缩进；未自动保存。')
            self.events.put(('done', {'state': 'completed', 'message': message}))
        except TypingStopped as error:
            self.events.put(('done', {'state': 'stopped', 'message': str(error)}))
        except Exception as error:
            # Do not echo text/exception payloads that may contain typed secrets.
            self.events.put(('done', {'state': 'error', 'message':
                f'输入失败（{type(error).__name__}），已停止；请检查目标内的部分文本。'}))

    def poll(self):
        if self.closing:
            return
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == 'done':
                self.finish(payload['message'], state=payload['state'])
            else:
                self.update_progress(*payload)
        if not self.closing:
            self.poll_timer = self.root.after(50, self.poll)

    def finish(self, message, state='completed'):
        self.set_busy(False)
        if state == 'completed':
            self.update_progress(self.total_count, self.total_count)
        self.set_state(state, message)

    def stop(self):
        self.cancel.set()
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
            self.finish('已停止，未发送文本。', state='stopped')
        elif self.busy:
            self.set_state('stopping', '正在停止，请检查目标内已输入的部分文本。')

    def clear(self):
        if not self.busy:
            self.text_area.delete('1.0', 'end')
            self.refresh_stats()

    def close(self):
        self.closing = True
        self.cancel.set()
        for timer in (self.timer, self.poll_timer, self._stats_timer):
            if timer is not None:
                self.root.after_cancel(timer)
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == '__main__':
    App().run()


