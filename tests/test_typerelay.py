"""Offline regression tests. GUI creation, native input, and hooks are blocked."""

import contextlib
import ctypes
from ctypes import wintypes
from dataclasses import FrozenInstanceError
import importlib.util
import io
from pathlib import Path
import queue
import sys
import threading
import tkinter
import types
import unittest
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "typerelay.py"
SYMBOL_PAIRS = (
    ("-", "_", 0x0C), ("=", "+", 0x0D), ("[", "{", 0x1A),
    ("]", "}", 0x1B), ("\\", "|", 0x2B), (";", ":", 0x27),
    ("'", '"', 0x28), ("`", "~", 0x29), (",", "<", 0x33),
    (".", ">", 0x34), ("/", "?", 0x35),
)


class EditorModel:
    """A plain editor with Enter autoindent and absolute Shift+Home selection."""

    def __init__(self, text="", caret=None, autoindent=False):
        self.text = text
        self.caret = len(text) if caret is None else caret
        self.anchor = None
        self.autoindent = autoindent

    def insert(self, value):
        if self.anchor is not None:
            start, end = sorted((self.anchor, self.caret))
            self.text = self.text[:start] + self.text[end:]
            self.caret = start
            self.anchor = None
        self.text = self.text[:self.caret] + value + self.text[self.caret:]
        self.caret += len(value)

    def key(self, name):
        if name == "enter":
            prefix = self.text[self.text.rfind("\n", 0, self.caret) + 1:self.caret]
            indent = prefix[:len(prefix) - len(prefix.lstrip(" \t"))]
            self.insert("\n" + (indent if self.autoindent else ""))
        elif name == "shift+home":
            self.anchor = self.caret
            self.caret = self.text.rfind("\n", 0, self.caret) + 1
        elif name == "space":
            self.insert(" ")
        elif name == "tab":
            self.insert("\t")
        elif name == "backspace":
            if self.anchor is not None:
                self.insert("")
            elif self.caret:
                self.text = self.text[:self.caret - 1] + self.text[self.caret:]
                self.caret -= 1
        else:
            raise AssertionError(f"Unexpected editor key: {name}")


class TypeRelayTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.unicode_events = []
        self.fake_keyboard = types.ModuleType("keyboard")

        def recorder(operation, result=None):
            def record(key):
                self.events.append((operation, key))
                return result
            return mock.Mock(side_effect=record)

        for operation in ("send", "press", "release", "press_and_release"):
            setattr(self.fake_keyboard, operation, recorder(operation))
        self.fake_keyboard.key_to_scan_codes = recorder("init", (42,))
        self.send_input = mock.Mock(side_effect=self.capture_unicode)
        self.fake_user32 = types.SimpleNamespace(
            SendInput=self.send_input,
            GetForegroundWindow=mock.Mock(return_value=100),
            GetAncestor=mock.Mock(return_value=100),
            GetWindowThreadProcessId=mock.Mock(),
            GetAsyncKeyState=mock.Mock(return_value=0),
        )
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(mock.patch.object(ctypes, "WinDLL", return_value=self.fake_user32))
        self.stack.enter_context(mock.patch.object(ctypes, "get_last_error", return_value=5))
        self.stack.enter_context(mock.patch.object(tkinter, "Tk", side_effect=AssertionError("GUI forbidden")))
        name = "typerelay_modes_under_test"
        spec = importlib.util.spec_from_file_location(name, SOURCE)
        self.module = importlib.util.module_from_spec(spec)
        self.stack.enter_context(mock.patch.dict(sys.modules, {name: self.module, "keyboard": self.fake_keyboard}))
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(self.module)
        self.stack.enter_context(mock.patch.object(self.module.time, "sleep"))

    def capture_unicode(self, count, inputs, size):
        self.assertEqual(size, ctypes.sizeof(self.module._INPUT))
        for item in ctypes.cast(inputs, ctypes.POINTER(self.module._INPUT))[:count]:
            self.unicode_events.append((item.type, item.ki.wVk, item.ki.wScan, item.ki.dwFlags))
        return count

    def options(self, **kwargs):
        return self.module.TypingOptions(**kwargs)

    def stream(self, text, options, **kwargs):
        sent = []
        count = self.module.type_text(text, options, wait=lambda _: None,
                                     send_key=lambda key: sent.append(("key", key)),
                                     send_char=lambda char: sent.append(("char", char)), **kwargs)
        return sent, count

    def headless_app(self):
        app = object.__new__(self.module.App)
        app.root = mock.Mock()
        app.status = mock.Mock()
        app.events = queue.Queue()
        app.cancel = threading.Event()
        app.focus = types.SimpleNamespace(escape_pressed=mock.Mock(return_value=False),
                                         foreground=mock.Mock(return_value=(100, 200)),
                                         capture=mock.Mock(return_value=(100, 200)))
        app.busy = False
        app.timer = None
        app.poll_timer = None
        app._stats_timer = None
        app.closing = False
        app.state_name = "ready"
        app.sent_count = 0
        app.total_count = 0
        app.advanced_open = False
        app.mode = mock.Mock(get=mock.Mock(return_value=self.module.FILE_MODE))
        app.interval_var = mock.Mock(get=mock.Mock(return_value="50"))
        app.countdown_var = mock.Mock(get=mock.Mock(return_value="2"))
        app.expand_tabs = mock.Mock(get=mock.Mock(return_value=False))
        app.autoindent = mock.Mock(get=mock.Mock(return_value=False))
        app.text_area = mock.Mock()
        app.mode_hint = mock.Mock()
        app.mode_buttons = [mock.Mock(), mock.Mock()]
        for name in ("tabs_check", "indent_check", "countdown_box", "interval_box",
                     "start_button", "clear_button", "stop_button", "state_badge",
                     "countdown_display", "progressbar", "progress_label", "stats_label",
                     "empty_hint", "advanced_frame", "advanced_button"):
            setattr(app, name, mock.Mock())
        return app

    def drain(self, app):
        result = []
        while not app.events.empty():
            result.append(app.events.get_nowait())
        return result

    def test_command_mode_full_stream_flattens_without_enter_or_tab(self):
        source = "\r\n  python3 -c 'print(\"中_>?.\")'\t\r\nnext\r"
        expected = "   python3 -c 'print(\"中_>?.\")'     next "
        sent, count = self.stream(source, self.options(clear_autoindent=True, expand_tabs=False))
        self.assertEqual(sent, [("char", char) for char in expected])
        self.assertEqual(count, len(expected))

    def test_file_mode_full_stream_preserves_lines_indentation_unicode_and_end(self):
        source = "\r\n\tdef f():\r    return '中_>?.'  \n\n"
        expected = "\n\tdef f():\n    return '中_>?.'  \n\n"
        sent, count = self.stream(source, self.options(mode=self.module.FILE_MODE, expand_tabs=False))
        self.assertEqual(sent, [("key", "enter") if c == "\n" else
                                ("key", "tab") if c == "\t" else ("char", c)
                                for c in expected])
        self.assertEqual(count, len(expected))

    def test_file_tab_conversion_is_explicit_four_spaces_not_tabstop(self):
        for expand, expected in ((True, "a    b\n    c"), (False, "a\tb\n\tc")):
            with self.subTest(expand=expand):
                options = self.options(mode=self.module.FILE_MODE, expand_tabs=expand)
                self.assertEqual(self.module.prepare_text("a\tb\r\n\tc", options), expected)

    def test_whitespace_only_content_and_boundaries_are_not_stripped(self):
        for source in (" ", "\t", "\n", "\n  \n", "  x  ", "\r\n\r"):
            with self.subTest(source=repr(source)):
                options = self.options(mode=self.module.FILE_MODE, expand_tabs=False)
                expected = source.replace("\r\n", "\n").replace("\r", "\n")
                self.assertEqual(self.module.prepare_text(source, options), expected)

    def test_get_text_excludes_only_tk_synthetic_final_newline(self):
        app = self.headless_app()
        app.text_area.get.return_value = "\n    patch\n\n"
        self.assertEqual(app.get_text(), "\n    patch\n\n")
        app.text_area.get.assert_called_once_with("1.0", "end-1c")

    def test_invalid_controls_rejected_before_any_send(self):
        for char in ("\0", "\b", "\x1b", "\x7f", "\v", "\f"):
            for mode in (self.module.COMMAND_MODE, self.module.FILE_MODE):
                with self.subTest(control=ord(char), mode=mode):
                    with self.assertRaises(ValueError):
                        self.stream("safe" + char, self.options(mode=mode))
        self.assertEqual(self.events, [])

    def test_invalid_mode_and_delay_rejected_before_send(self):
        for kwargs in ({"mode": "unknown"}, {"interval": 0}, {"interval": 0.501},
                       {"interval": float("nan")}, {"interval": float("inf")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.stream("abc", self.options(**kwargs))

    def test_file_cleanup_off_emits_only_source_keys(self):
        sent, _ = self.stream("a\nb\n", self.options(mode=self.module.FILE_MODE))
        self.assertEqual(sent, [("char", "a"), ("key", "enter"),
                                ("char", "b"), ("key", "enter")])

    def test_autoindent_cleanup_preserves_source_with_or_without_editor_indent(self):
        source = "    if ready:\n        work()\n\n    end()\n"
        for editor_indent in (False, True):
            with self.subTest(editor_autoindent=editor_indent):
                editor = EditorModel(autoindent=editor_indent)
                self.module.type_text(source, self.options(mode=self.module.FILE_MODE, clear_autoindent=True),
                                      send_char=editor.insert, send_key=editor.key, wait=lambda _: None)
                self.assertEqual(editor.text, source)

    def test_autoindent_cleanup_keeps_existing_suffix_and_does_not_join_blank_line(self):
        for editor_indent in (False, True):
            with self.subTest(editor_autoindent=editor_indent):
                editor = EditorModel("    prefixSUFFIX", len("    prefix"), editor_indent)
                self.module.type_text("\n    patch\n", self.options(mode=self.module.FILE_MODE, clear_autoindent=True),
                                      send_char=editor.insert, send_key=editor.key, wait=lambda _: None)
                self.assertEqual(editor.text, "    prefix\n    patch\nSUFFIX")

    def test_cleanup_disabled_does_not_claim_to_fix_target_autoindent(self):
        editor = EditorModel(autoindent=True)
        self.module.type_text("    first\n    second", self.options(mode=self.module.FILE_MODE),
                              send_char=editor.insert, send_key=editor.key, wait=lambda _: None)
        self.assertEqual(editor.text, "    first\n        second")

    def test_cancel_before_first_character_sends_nothing(self):
        def stop():
            raise self.module.TypingStopped("stopped")
        with self.assertRaises(self.module.TypingStopped):
            self.stream("abc", self.options(), checkpoint=stop)
        self.assertEqual(self.events, [])

    def test_cancel_during_stream_does_not_send_remaining_characters(self):
        sent = []
        cancelled = threading.Event()
        def send(char):
            sent.append(char)
            cancelled.set()
        def check():
            if cancelled.is_set():
                raise self.module.TypingStopped("stopped")
        with self.assertRaises(self.module.TypingStopped):
            self.module.type_text("abc", self.options(), checkpoint=check, wait=lambda _: None,
                                  send_char=send, send_key=lambda _: self.fail("Unexpected key"))
        self.assertEqual(sent, ["a"])

    def test_cancel_during_autoindent_pause_sends_no_selection_or_deletion(self):
        sent = []
        cancelled = threading.Event()
        def check():
            if cancelled.is_set():
                raise self.module.TypingStopped("stopped")
        def wait(seconds):
            if seconds >= .15:
                cancelled.set()
        with self.assertRaises(self.module.TypingStopped):
            self.module.type_text("\nrest", self.options(mode=self.module.FILE_MODE, clear_autoindent=True),
                                  checkpoint=check, wait=wait, send_key=sent.append,
                                  send_char=lambda _: self.fail("Unexpected character"))
        self.assertEqual(sent, ["enter"])

    def test_checkpoint_blocks_cancel_escape_or_foreground_change(self):
        for reason in ("cancel", "escape", "hwnd", "pid"):
            with self.subTest(reason=reason):
                app = self.headless_app()
                if reason == "cancel": app.cancel.set()
                if reason == "escape": app.focus.escape_pressed.return_value = True
                if reason == "hwnd": app.focus.foreground.return_value = (101, 200)
                if reason == "pid": app.focus.foreground.return_value = (100, 201)
                with self.assertRaises(self.module.TypingStopped):
                    app.checkpoint((100, 200))
        self.assertEqual(self.events, [])

    def test_focus_capture_rejects_own_window_or_missing_identity(self):
        focus = self.module.WindowsFocus()
        for target in ((0, 100), (100, 0), (100, self.module.os.getpid())):
            with self.subTest(target=target), mock.patch.object(focus, "foreground", return_value=target):
                with self.assertRaises(self.module.TypingStopped):
                    focus.capture()
        with mock.patch.object(focus, "foreground", return_value=(100, 200)):
            self.assertEqual(focus.capture(), (100, 200))

    def test_mode_and_options_are_snapshotted_at_start(self):
        app = self.headless_app()
        app.text_area.get.return_value = "\n\tcode\n"
        app.countdown = mock.Mock()
        app.start()
        seconds, text, options = app.countdown.call_args.args
        self.assertEqual((seconds, text, options.mode, options.expand_tabs),
                         (2, "\n\tcode\n", self.module.FILE_MODE, False))
        app.mode.get.return_value = self.module.COMMAND_MODE
        app.expand_tabs.get.return_value = True
        app.text_area.get.return_value = "replacement"
        self.assertEqual(options.mode, self.module.FILE_MODE)
        self.assertEqual(text, "\n\tcode\n")
        with self.assertRaises(FrozenInstanceError):
            options.mode = self.module.COMMAND_MODE
        for control in (*app.mode_buttons, app.text_area, app.start_button,
                        app.countdown_box, app.interval_box):
            control.config.assert_called_with(state=tkinter.DISABLED)

    def test_busy_start_does_not_queue_second_job(self):
        app = self.headless_app()
        app.busy = True
        app.countdown = mock.Mock()
        app.start()
        app.text_area.get.assert_not_called()
        app.countdown.assert_not_called()

    def test_countdown_delivers_same_snapshot_to_worker(self):
        app = self.headless_app()
        options = self.options(mode=self.module.FILE_MODE, expand_tabs=False)
        with mock.patch.object(self.module.threading, "Thread") as worker_thread:
            app.countdown(1, "\n\tcode", options)
            callback = app.root.after.call_args.args
            app.mode.get.return_value = self.module.COMMAND_MODE
            callback[1](*callback[2:])
        worker_thread.assert_called_once_with(target=app.worker,
                                             args=("\n\tcode", options, (100, 200)), daemon=True)
        worker_thread.return_value.start.assert_called_once()

    def test_stop_during_countdown_cancels_callback_and_sends_nothing(self):
        app = self.headless_app()
        app.busy = True
        app.timer = "pending"
        app.stop()
        app.root.after_cancel.assert_called_once_with("pending")
        self.assertTrue(app.cancel.is_set())
        self.assertFalse(app.busy)
        self.assertIsNone(app.timer)
        self.assertEqual(self.events, [])

    def test_worker_uses_queue_only_and_preserves_options_identity(self):
        app = self.headless_app()
        options = self.options(mode=self.module.FILE_MODE)
        def fake_type(text, received_options, *, checkpoint, wait, progress):
            self.assertIs(received_options, options)
            checkpoint()
            progress(10, 11)
            return 11
        with mock.patch.object(self.module, "type_text", side_effect=fake_type):
            app.worker("a" * 11, options, (100, 200))
        messages = self.drain(app)
        self.assertEqual([kind for kind, _ in messages], ["progress", "done"])
        self.assertEqual(messages[0], ("progress", (10, 11)))
        self.assertEqual(messages[-1][1]["state"], "completed")
        self.assertIsInstance(messages[-1][1]["message"], str)
        self.assertTrue(messages[-1][1]["message"])
        app.root.assert_not_called()
        self.assertEqual(app.root.mock_calls, [])
        self.assertEqual(app.status.mock_calls, [])
        self.assertEqual(app.mode.mock_calls, [])

    def test_worker_reports_failure_without_echoing_exception_payload(self):
        app = self.headless_app()
        with mock.patch.object(self.module, "type_text", side_effect=RuntimeError("PRIVATE_INPUT_SECRET")):
            app.worker("PRIVATE_INPUT_SECRET", self.options(), (100, 200))
        messages = self.drain(app)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0][0], "done")
        self.assertEqual(messages[0][1]["state"], "error")
        self.assertIn("RuntimeError", messages[0][1]["message"])
        self.assertNotIn("PRIVATE_INPUT_SECRET", messages[0][1]["message"])
        self.assertEqual(app.root.mock_calls + app.status.mock_calls, [])

    def test_worker_cancel_and_focus_loss_emit_stop_without_native_input(self):
        for reason in ("cancel", "focus"):
            with self.subTest(reason=reason):
                app = self.headless_app()
                if reason == "cancel": app.cancel.set()
                else: app.focus.foreground.return_value = (101, 200)
                app.worker("abc", self.options(), (100, 200))
                messages = self.drain(app)
                self.assertEqual(len(messages), 1)
                self.assertEqual(messages[0][0], "done")
                self.assertEqual(messages[0][1]["state"], "stopped")
                self.assertNotIn("已发送", messages[0][1]["message"])
                self.assertEqual(app.root.mock_calls + app.status.mock_calls, [])
        self.assertEqual(self.events, [])
        self.send_input.assert_not_called()

    def test_worker_wait_is_interruptible_without_waiting_entire_interval(self):
        app = self.headless_app()
        def cancel_after_first_wait(seconds):
            self.assertLessEqual(seconds, .02)
            app.cancel.set()
            return True
        app.cancel.wait = mock.Mock(side_effect=cancel_after_first_wait)
        with mock.patch.object(self.module.time, "monotonic", return_value=10.0):
            app.worker("abc", self.options(interval=.5), (100, 200))
        self.assertEqual(self.events, [("send", "a")])
        app.cancel.wait.assert_called_once()
        result = self.drain(app)[-1][1]
        self.assertEqual(result["state"], "stopped")
        self.assertNotIn("已发送", result["message"])

    def test_all_main_keyboard_symbol_pairs(self):
        for base, shifted, scan in SYMBOL_PAIRS:
            with self.subTest(base=base):
                self.events.clear()
                self.module._send_char_safe(base)
                self.assertEqual(self.events, [("init", "left shift"), ("send", scan)])
                self.events.clear()
                self.module._send_char_safe(shifted)
                self.assertEqual(self.events, [("init", "left shift"), ("press", "left shift"),
                                               ("press_and_release", scan), ("release", "left shift")])

    def test_plain_letters_digits_space_and_uppercase(self):
        for char, key in (("a", "a"), ("7", "7"), (" ", "space")):
            with self.subTest(char=char):
                self.events.clear()
                self.module._send_char_safe(char)
                self.assertEqual(self.events, [("send", key)])
        self.events.clear()
        self.module._send_char_safe("A")
        self.assertEqual(self.events, [("press", "left shift"), ("press_and_release", "a"),
                                      ("release", "left shift")])

    def test_shift_released_if_base_key_fails(self):
        self.fake_keyboard.press_and_release.side_effect = RuntimeError("offline failure")
        with self.assertRaises(RuntimeError): self.module._send_char_safe("_")
        self.fake_keyboard.release.assert_called_once_with("left shift")

    def test_cancel_between_shift_down_and_character_releases_shift_without_character(self):
        calls = 0
        def check():
            nonlocal calls
            calls += 1
            if calls == 2: raise self.module.TypingStopped("stopped")
        with self.assertRaises(self.module.TypingStopped):
            self.module._send_char_safe("?", check)
        self.fake_keyboard.press.assert_called_once_with("left shift")
        self.fake_keyboard.release.assert_called_once_with("left shift")
        self.fake_keyboard.press_and_release.assert_not_called()

    @unittest.skipUnless(sys.platform == "win32" and ctypes.sizeof(ctypes.c_void_p) == 8, "Windows x64 layout")
    def test_unicode_input_layout_has_full_native_union(self):
        self.assertEqual(ctypes.sizeof(self.module._INPUT), 40)

    def test_unicode_bmp_uses_utf16_keydown_and_keyup(self):
        self.module._send_char_safe("中")
        self.assertEqual(self.unicode_events, [(1, 0, 0x4E2D, 4), (1, 0, 0x4E2D, 6)])
        self.assertEqual(self.send_input.argtypes,
                         (wintypes.UINT, ctypes.POINTER(self.module._INPUT), ctypes.c_int))
        self.assertIs(self.send_input.restype, wintypes.UINT)
        self.assertEqual(self.events, [])

    def test_unicode_supplementary_preserves_surrogate_pair(self):
        self.module._send_unicode("\U0001F600")
        self.assertEqual(self.unicode_events, [(1, 0, 0xD83D, 4), (1, 0, 0xD83D, 6),
                                              (1, 0, 0xDE00, 4), (1, 0, 0xDE00, 6)])

    def test_incomplete_unicode_send_fails(self):
        self.send_input.side_effect = None
        self.send_input.return_value = 1
        with self.assertRaises(OSError) as caught: self.module._send_unicode("中")
        self.assertEqual(caught.exception.errno, 5)


if __name__ == "__main__":
    unittest.main()
