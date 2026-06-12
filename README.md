# TypeRelay

**Type locally, appear remotely.** A lightweight Windows tool that types copied text into a remote desktop keystroke by keystroke.

![Python](https://img.shields.io/badge/python-3.8+-blue)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

## The Problem

Working inside a cloud desktop (RDP, VMware Horizon, Citrix, etc.) with **clipboard sharing disabled**? You copy text locally, switch to the remote desktop, hit Ctrl+V — and nothing useful comes out. That's because the remote clipboard is isolated from your local one.

## The Solution

TypeRelay bypasses the clipboard entirely. It **simulates actual keystrokes** through the keyboard input channel, which works everywhere — your remote desktop just sees a keyboard typing.

```
┌─ Your PC ─────────────────┐     ┌─ Remote Desktop ──────────┐
│ 1. Paste text into        │     │                            │
│    TypeRelay window       │     │                            │
│ 2. Set countdown, click   │     │                            │
│    "Start Typing"         │     │                            │
│ 3. Countdown runs...      │ ──→ │ 4. Switch here, place      │
│                           │     │    cursor in target field  │
│ 5. Text is typed          │ ──→ │ 6. Text appears!           │
│    keystroke by keystroke │     │                            │
└───────────────────────────┘     └────────────────────────────┘
```

## Features

- **Countdown timer** — gives you time to switch windows and place the cursor
- **Shift-combo symbols** — explicitly presses Shift+base_key for `(){}[]!@#`, bypassing keyboard layout mismatches
- **Adjustable speed** — 1–30 second countdown, configurable keystroke interval
- **Always on top** — window stays visible while you switch to the remote desktop
- **Zero bloat** — 300 lines of Python, single dependency

## Installation

```bash
# Clone the repo
git clone https://github.com/tuiangeuaoglea/typerelay.git
cd typerelay

# Install dependency
pip install -r requirements.txt

# Run
python typerelay.py
```

**Requirements:** Python 3.8+, Windows

## Usage

1. Copy text on your local machine
2. Paste it into the TypeRelay text area
3. Set countdown seconds (default: 3)
4. Click **Start Typing**
5. Switch to your remote desktop, click into the target input field
6. Wait for the countdown → text gets typed automatically

### Quick Launch (Windows)

Create a desktop shortcut that launches without a console window:

```batch
@echo off
cd /d C:\path\to\typerelay
start "" pythonw typerelay.py
```

## How It Works

| Character type | Method | Reliability |
|---|---|---|
| Letters & digits | `keyboard.send()` | ✅ Always works |
| Symbols `(){}[]!@#$` | Explicit `Shift + base_key` | ✅ Bypasses layout issues |
| CJK / Unicode | `SendInput(KEYEVENTF_UNICODE)` | ⚠️ RDP may not forward |

The shift-combo trick is the key insight: Chinese keyboards share the same **physical** key positions as US keyboards. Pressing `Shift+9` on a Chinese keyboard sends the same scan code as on a US keyboard, so the remote desktop receives `(` regardless of the local layout.

## Limitations

- **CJK characters** may not work over RDP — `KEYEVENTF_UNICODE` injection is dropped by some remote desktop clients
- **Newlines** are converted to spaces (prevents accidental Enter key submissions)
- Windows only (uses `ctypes` Win32 API for Unicode injection)

## Contributing

Pull requests are welcome! Ideas for improvement:

- [ ] System tray mode
- [ ] Global hotkey trigger
- [ ] Clipboard polling (auto-type on copy)
- [ ] Cross-platform support (Linux/Mac via `uinput`/`CGEvent`)

## License

MIT — see [LICENSE](LICENSE) for details.

---

[中文文档](README_zh.md)
