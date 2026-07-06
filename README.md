```
████████╗██╗   ██╗██████╗ ███████╗██████╗ ███████╗██╗      █████╗ ██╗   ██╗
╚══██╔══╝╚██╗ ██╔╝██╔══██╗██╔════╝██╔══██╗██╔════╝██║     ██╔══██╗╚██╗ ██╔╝
   ██║    ╚████╔╝ ██████╔╝█████╗  ██████╔╝█████╗  ██║     ███████║ ╚████╔╝
   ██║     ╚██╔╝  ██╔═══╝ ██╔══╝  ██╔══██╗██╔══╝  ██║     ██╔══██║  ╚██╔╝
   ██║      ██║   ██║     ███████╗██║  ██║███████╗███████╗██║  ██║   ██║
   ╚═╝      ╚═╝   ╚═╝     ╚══════╝╚═╝  ╚═╝╚══════╝╚══════╝╚═╝  ╚═╝   ╚═╝
```

> **Type locally, appear remotely.** Bypass disabled clipboard sharing on any remote desktop.

[![Python](https://img.shields.io/badge/python-3.8+-blue?logo=python&logoColor=white)](https://www.python.org)
[![Platform](https://img.shields.io/badge/platform-Windows-0078D6?logo=windows)](https://github.com/tuiangeuaoglea/typerelay)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Lines](https://img.shields.io/badge/lines-~300-lightgrey)](typerelay.py)

---

## The Problem

You're working inside a cloud desktop — **RDP**, **VMware Horizon**, **Citrix**, **AWS WorkSpaces** — and clipboard sharing is disabled by your IT policy.

```
┌──────────────────┐         ┌──────────────────────┐
│    YOUR PC       │         │   REMOTE DESKTOP      │
│                  │         │                       │
│  📋 Copy text    │   🚫    │  Ctrl+V → (nothing)   │
│                  │  ────→  │                       │
│  (works fine)    │  BLOCK  │  (clipboard isolated)  │
└──────────────────┘         └──────────────────────┘
```

You end up **retyping everything by hand**. This is the daily reality for millions of people working on secured corporate environments.

---

## The Solution

TypeRelay bypasses the clipboard entirely. It **simulates real keystrokes** through the keyboard input channel — your remote desktop just sees someone typing.

```
┌──────────────────────┐         ┌──────────────────────┐
│       YOUR PC        │         │   REMOTE DESKTOP      │
│                      │         │                       │
│  📋 Paste text   ═══╗│         │                       │
│  ⏱  Countdown...   ║│         │                       │
│  ⌨  Simulate keys  ║│  ═══════│══════▶  Text appears!  │
│                      │  SCAN   │                       │
│   "Shift+9" = `(`    │  CODES  │   "Who's typing?!"    │
└──────────────────────┘         └──────────────────────┘
```

### The Key Trick: Shift-Combo Symbols

Chinese keyboards share the same **physical key positions** as US keyboards. Pressing `Shift+9` sends the same scan code everywhere — so `(` always arrives as `(`, regardless of your local keyboard layout. No layout mismatch, no garbled symbols.

---

## Quick Start

```bash
git clone https://github.com/tuiangeuaoglea/typerelay.git
cd typerelay
pip install -r requirements.txt
python typerelay.py
```

**That's it.** No configuration. No admin rights. No server. Just Python.

---

## Usage

```
┌─────────────────────────────────────────┐
│            TypeRelay                     │
│  ┌───────────────────────────────────┐  │
│  │  Paste your text here...           │  │
│  │                                    │  │
│  │                                    │  │
│  └───────────────────────────────────┘  │
│                                          │
│  Countdown: [3] seconds                 │
│                                          │
│  ┌──────────────────────────────────┐   │
│  │        ▶ START TYPING             │   │
│  └──────────────────────────────────┘   │
│  ☑ Always on top                        │
└─────────────────────────────────────────┘
```

1. **Copy** text on your local machine
2. **Paste** it into TypeRelay
3. Set **countdown** seconds (default: 3)
4. Click **Start Typing**
5. **Switch** to your remote desktop → click the target field
6. Countdown runs → **text types itself!**

### Desktop Shortcut

```batch
@echo off
cd /d C:\path\to\typerelay
start "" pythonw typerelay.py
```

---

## Features

| Feature | Why it matters |
|:--|:--|
| 🎯 **Countdown timer** | Gives you time to switch windows and place cursor |
| ⌨ **Shift-combo symbols** | `(){}[]!@#$` always render correctly — bypasses layout mismatch |
| ⚡ **Adjustable speed** | 1–30s countdown, configurable keystroke interval |
| 📌 **Always on top** | Window stays visible while you switch to remote desktop |
| 🪶 **Zero bloat** | ~300 lines of Python, one dependency (keyboard) |

---

## How It Works

| Character type | Method | Reliability |
|:--|:--|:--|
| Letters & digits | `keyboard.send()` | ✅ Always works |
| Symbols `(){}[]!@#$` | Explicit `Shift + base_key` | ✅ Bypasses layout issues |
| CJK / Unicode | `SendInput(KEYEVENTF_UNICODE)` | ⚠️ RDP may not forward |

---

## Comparison

| Tool | Platform | Method | Symbols OK? | Maintained |
|:--|:--|:--|:--|:--|
| **TypeRelay** | Windows | Scan-code simulation | ✅ Shift-combo | ✅ |
| `gonzobrains/RemoteTyper` | macOS | AppleScript | ❌ Varies | ❌ |
| `wfukuokaya/autotype` | macOS | CGEvent | ⚠️ Layout-dependent | ❌ |
| `peak-flow/TypeBridge` | Browser | Chrome Extension | ⚠️ Web RDP only | ❌ |
| AutoHotkey script | Windows | Macro scripting | ⚠️ Manual config | N/A |

**TypeRelay is the only purpose-built tool for the "clipboard blocked on remote desktop" problem on Windows.**

---

## Limitations

- **CJK characters** — may not work over RDP (Unicode injection dropped by some clients)
- **Newlines** → spaces (prevents accidental Enter key submissions)
- **Windows only** (uses `ctypes` Win32 API)

---

## Roadmap

- [ ] System tray mode — minimize to tray, trigger from context menu
- [ ] Global hotkey — `Ctrl+Shift+V` to fire instantly
- [ ] Clipboard polling — auto-detect and type on copy
- [ ] Cross-platform — Linux (`uinput`) and macOS (`CGEvent`)
- [ ] Snippet library — save frequently-used text blocks

PRs welcome!

---

## License

MIT — see [LICENSE](LICENSE) for details.
