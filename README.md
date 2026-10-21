# TypeRelay 2.1

Type text from your local computer into a remote desktop using simulated keystrokes. TypeRelay is a small Windows application with a Chinese Tkinter interface and explicit modes for commands and file editing.

The simplified home screen uses a soft blue-purple gradient header and rounded cards, with settings at the top right.

[中文说明](README_zh.md) · [MIT license](LICENSE)

**Desktop verification and a screenshot of this interface are pending manual review.** Remote desktop forwarding depends on the client, target editor, keyboard layout, and input method; validate a short sample in your own environment first.

## Install and run

Requires **Windows, Python 3.8 or later, and Tkinter**. The only third-party runtime dependency is `keyboard==0.13.5`.

```powershell
git clone https://github.com/tuiangeuaoglea/typerelay.git
cd typerelay
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe typerelay.py
```

## Use

1. Paste your text into the editor and select **指令** (command, including MobaXterm) or **文件** (file editing).
2. Open **设置** (settings) if you need to change the countdown or character interval. Defaults are **5 seconds** and **50 ms**; accepted ranges are 1–60 seconds and 10–500 ms. Increase the interval to 80–100 ms if the remote client drops characters.
3. Set the target input method to English / half-width. For file editing, disable the target editor's automatic indentation and completion when possible.
4. Click **开始输入 →** to start the countdown, then switch to the target window and place the caret. Text is not sent immediately; TypeRelay locks the local foreground window when the countdown ends.
5. Keep that window focused while text is sent. **Esc**, **停止**, or a change of foreground window stops the run. A stopped run does not resume automatically; inspect any partial input before retrying.
6. Check the text in the target. In command mode, press Enter yourself when ready. In file mode, save the file yourself.

| Mode | Line breaks and whitespace | Completion |
| --- | --- | --- |
| Command — default | CRLF, CR, and LF become spaces; each Tab becomes four spaces | No Enter is sent |
| File editing | Line breaks, blank lines, leading/trailing whitespace, and final newline are preserved | No automatic file save |

The large editor shows original character and line counts. Switching modes does not rewrite the text. Text and settings are frozen for each run; countdown, progress, completion, stop, and failure have separate states. The stop button appears while a run is active.

**设置** is collapsed by default. It contains the countdown and character interval; the footer shows a compact summary of these values. File mode also enables:

- **Tab 转为 4 个空格**: enabled by default; disable it to send real Tab keys.
- **清除目标编辑器的自动缩进**: disabled by default. It requires the target's Shift+Home to select to the absolute beginning of the line. Test it in a temporary file before using it with an editor whose Home behavior is uncertain.

Collapsing settings preserves their values. The two file-specific options are disabled in command mode.

## Behavior and limits

- ASCII symbols use main-keyboard scan codes and explicit Shift combinations. Non-ASCII characters use Windows Unicode `SendInput`; some remote clients do not forward these events.
- The target's keyboard layout, IME, automatic indentation, bracket pairing, and completion can alter the result. TypeRelay does not change system or remote input-method settings.
- Focus protection checks the **local foreground root window HWND and PID**. It cannot detect a change of remote application or editing area inside the same remote desktop window.
- The application does not save text history, upload the input, automatically read the clipboard, or automatically execute commands. It has no tray mode or global start hotkey.
- A progress count describes characters sent locally, not confirmation that the remote target received them.

## Tests and Python API

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

Offline tests replace native input with mocks. Passing them does not establish remote forwarding or target-editor compatibility.

For a manual desktop check, launch these two local windows in separate consoles:

```powershell
.\.venv\Scripts\python.exe tools/local_check.py relay
.\.venv\Scripts\python.exe tools/local_check.py editor --mode file
```

The relay window contains a synthetic sample. Select file mode, set the target input method to English / half-width, start the countdown, then switch to the temporary editor and click its text box. After input stops, click its verification button. The editor compares only its own text box with the expected sample; neither test window connects to an intranet. To check command mode, use `editor --mode command` and select command mode in the relay window. These steps are provided for manual validation; they have not been recorded as passed desktop tests.

Existing `type_text(text)` calls remain supported and default to command mode. `TypingOptions`, `prepare_text()`, and `type_text()` also support explicit file-mode options and injectable checkpoint, wait, input, and progress callbacks. Countdown and foreground-window protection are managed by the desktop application; direct engine callers must supply their own checkpoint when needed.

## License

MIT — see [LICENSE](LICENSE).
