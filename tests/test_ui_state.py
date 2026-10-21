"""Headless UI regressions; native input and Tk window creation stay blocked."""

import types
import unittest
from unittest import mock

import test_typerelay as harness


class UIStateTests(unittest.TestCase):
    setUp = harness.TypeRelayTests.setUp
    capture_unicode = harness.TypeRelayTests.capture_unicode
    headless_app = harness.TypeRelayTests.headless_app
    options = harness.TypeRelayTests.options

    def test_statistics_count_original_characters_and_normalized_lines(self):
        cases = (
            ("", (0, 0)),
            ("abc", (3, 1)),
            ("\n", (1, 2)),
            ("\r\n", (2, 2)),
            ("a\r\nb\rc\n", (7, 4)),
            ("\t中\U0001f600  ", (5, 1)),
            ("\n  first\n\n", (10, 4)),
        )
        for source, expected in cases:
            with self.subTest(source=repr(source)):
                self.assertEqual(self.module.text_statistics(source), expected)

    def test_prepared_snapshot_is_idempotent_for_both_modes_and_tab_options(self):
        sources = ("", "\r\n\t  def f():\r    return '中_?'  \n\n", " \t\r\n ")
        for mode in (self.module.COMMAND_MODE, self.module.FILE_MODE):
            for expand_tabs in (False, True):
                options = self.options(mode=mode, expand_tabs=expand_tabs)
                for source in sources:
                    with self.subTest(mode=mode, expand_tabs=expand_tabs, source=repr(source)):
                        prepared = self.module.prepare_text(source, options)
                        self.assertEqual(self.module.prepare_text(prepared, options), prepared)

    def test_start_resets_progress_to_prepared_character_count(self):
        app = self.headless_app()
        app.text_area.get.return_value = "\r\n\tcode\n"
        app.mode.get.return_value = self.module.COMMAND_MODE
        app.sent_count, app.total_count = 20, 20
        app.update_progress = mock.Mock()
        app.set_busy = mock.Mock()
        app.countdown = mock.Mock()
        app.start()
        prepared = "     code "
        app.update_progress.assert_called_once_with(0, len(prepared))
        self.assertEqual(app.countdown.call_args.args[1], prepared)
        app.text_area.delete.assert_not_called()
        app.text_area.insert.assert_not_called()

    def test_start_cancels_pending_statistics_callback_before_new_run(self):
        app = self.headless_app()
        app.text_area.get.return_value = "abc"
        app._stats_timer = "pending-statistics"
        app.countdown = mock.Mock()
        app.start()
        app.root.after_cancel.assert_called_once_with("pending-statistics")
        self.assertIsNone(app._stats_timer)
        self.assertTrue(app.busy)
        self.assertEqual((app.sent_count, app.total_count), (0, 3))

    def test_finish_only_completed_run_fills_progress(self):
        for state in ("completed", "stopped", "error"):
            with self.subTest(state=state):
                app = self.headless_app()
                app.sent_count, app.total_count = 3, 17
                app.set_busy = mock.Mock()
                app.set_state = mock.Mock()
                app.finish("PRIVATE_MESSAGE", state)
                app.set_busy.assert_called_once_with(False)
                app.set_state.assert_called_once_with(state, "PRIVATE_MESSAGE")
                self.assertEqual(app.total_count, 17)
                self.assertEqual(app.sent_count, 17 if state == "completed" else 3)

    def test_update_progress_keeps_numeric_counts_without_touching_editor(self):
        app = self.headless_app()
        app.update_progress(7, 23)
        self.assertEqual((app.sent_count, app.total_count), (7, 23))
        calls = app.progressbar.config.call_args_list + app.progressbar.configure.call_args_list
        self.assertTrue(any(call.kwargs.get("maximum") == 23 and call.kwargs.get("value") == 7
                            for call in calls))
        self.assertEqual(app.text_area.mock_calls, [])

    def test_statistics_refresh_uses_original_text_without_rewriting_it(self):
        app = self.headless_app()
        app.text_area.get.return_value = "a\r\nb\rc\n"
        app.set_state = mock.Mock()
        app.refresh_stats()
        calls = app.stats_label.config.call_args_list + app.stats_label.configure.call_args_list
        displayed = " ".join(str(call.kwargs.get("text", "")) for call in calls)
        self.assertIn("7", displayed)
        self.assertIn("4", displayed)
        app.empty_hint.place_forget.assert_called()
        app.text_area.delete.assert_not_called()
        app.text_area.insert.assert_not_called()

    def test_statistics_refresh_shows_empty_hint_without_clearing_busy_result(self):
        app = self.headless_app()
        app.text_area.get.return_value = ""
        app.busy = True
        app.state_name = "typing"
        app.sent_count, app.total_count = 7, 23
        app.set_state = mock.Mock()
        app.update_progress = mock.Mock()
        app.refresh_stats()
        app.empty_hint.place.assert_called()
        app.set_state.assert_not_called()
        app.update_progress.assert_not_called()
        self.assertEqual((app.sent_count, app.total_count), (7, 23))

    def test_advanced_toggle_preserves_source_mode_and_options(self):
        app = self.headless_app()
        app.toggle_advanced()
        self.assertTrue(app.advanced_open)
        app.advanced_frame.grid.assert_called_once()
        app.toggle_advanced()
        self.assertFalse(app.advanced_open)
        app.advanced_frame.grid_remove.assert_called_once()
        for variable in (app.mode, app.expand_tabs, app.autoindent):
            variable.set.assert_not_called()
        self.assertEqual(app.text_area.mock_calls, [])

    def test_advanced_toggle_is_frozen_during_countdown_or_typing(self):
        app = self.headless_app()
        app.busy = True
        app.toggle_advanced()
        self.assertFalse(app.advanced_open)
        self.assertEqual(app.advanced_frame.mock_calls + app.advanced_button.mock_calls, [])

    def test_poll_dispatches_numeric_progress_and_explicit_result_state(self):
        app = self.headless_app()
        app.update_progress = mock.Mock()
        app.finish = mock.Mock()
        app.events.put(("progress", (7, 23)))
        app.events.put(("done", {"state": "stopped", "message": "已停止"}))
        app.poll()
        app.update_progress.assert_called_once_with(7, 23)
        app.finish.assert_called_once_with("已停止", state="stopped")
        app.root.after.assert_called_once_with(50, app.poll)
        self.assertEqual(app.status.mock_calls, [])

    def test_closed_poll_does_not_touch_tk_or_dispatch_stale_events(self):
        app = self.headless_app()
        app.closing = True
        app.update_progress = mock.Mock()
        app.finish = mock.Mock()
        app.events.put(("progress", (5, 10)))
        app.events.put(("done", {"state": "completed", "message": "done"}))
        app.poll()
        app.update_progress.assert_not_called()
        app.finish.assert_not_called()
        self.assertEqual(app.root.mock_calls + app.status.mock_calls, [])

    def test_close_cancels_countdown_poll_and_statistics_callbacks(self):
        app = self.headless_app()
        app.timer = "countdown-timer"
        app.poll_timer = "poll-timer"
        app._stats_timer = "statistics-timer"
        app.close()
        self.assertTrue(app.closing)
        self.assertTrue(app.cancel.is_set())
        self.assertEqual(app.root.after_cancel.call_args_list, [
            mock.call("countdown-timer"), mock.call("poll-timer"), mock.call("statistics-timer")])
        app.root.destroy.assert_called_once_with()
        self.assertEqual(self.events, [])
        self.send_input.assert_not_called()

    def test_stop_countdown_marks_stopped_without_sending_or_filling_progress(self):
        app = self.headless_app()
        app.busy, app.timer = True, "pending"
        app.sent_count, app.total_count = 0, 30
        app.set_state = mock.Mock()
        app.set_busy = mock.Mock()
        app.stop()
        app.set_state.assert_called_once_with("stopped", mock.ANY)
        self.assertEqual((app.sent_count, app.total_count), (0, 30))
        self.assertTrue(app.cancel.is_set())
        self.assertEqual(self.events, [])
        self.send_input.assert_not_called()

    def test_missing_target_at_countdown_end_marks_stopped_without_worker(self):
        app = self.headless_app()
        app.focus.capture.side_effect = self.module.TypingStopped("尚未切到目标窗口")
        app.finish = mock.Mock()
        with mock.patch.object(self.module.threading, "Thread") as worker:
            app.countdown(0, "abc", self.options())
        app.finish.assert_called_once_with("尚未切到目标窗口", state="stopped")
        worker.assert_not_called()
        self.assertEqual(self.events, [])

    def test_gradient_button_keyboard_activation_respects_disabled_state(self):
        for key in ("Return", "space"):
            for state in ("normal", "disabled"):
                with self.subTest(key=key, state=state):
                    button = types.SimpleNamespace(cget=mock.Mock(return_value=state), command=mock.Mock())
                    result = self.module.GradientButton._activate(button, types.SimpleNamespace(keysym=key))
                    self.assertEqual(result, "break")
                    self.assertEqual(button.command.call_count, 1 if state == "normal" else 0)

    def test_gradient_button_mouse_activation_requires_enabled_press_and_inside_release(self):
        button = types.SimpleNamespace(
            cget=mock.Mock(return_value="disabled"), command=mock.Mock(), focus_set=mock.Mock(),
            pressed=False, winfo_width=lambda: 180, winfo_height=lambda: 50)

        def appearance(**changes):
            for name, value in changes.items():
                setattr(button, name, value)

        button._appearance = mock.Mock(side_effect=appearance)
        button._activate = lambda event: self.module.GradientButton._activate(button, event)
        inside = types.SimpleNamespace(x=20, y=20)
        self.module.GradientButton._press(button, inside)
        self.module.GradientButton._release(button, inside)
        button.focus_set.assert_not_called()
        button.command.assert_not_called()

        button.cget.return_value = "normal"
        self.module.GradientButton._press(button, inside)
        self.module.GradientButton._release(button, types.SimpleNamespace(x=-1, y=20))
        button.command.assert_not_called()
        self.assertFalse(button.pressed)
        self.module.GradientButton._press(button, inside)
        self.module.GradientButton._release(button, inside)
        button.command.assert_called_once_with()
        self.assertFalse(button.pressed)

    def test_hero_subtitle_tracks_scaled_title_font_without_changing_focus(self):
        app = self.headless_app()
        app.hero = mock.Mock()
        app._hero_title_font = mock.Mock()
        app._hero_body_font = mock.Mock()
        app._hero_title_font.metrics.return_value = 64
        event = types.SimpleNamespace(width=780, height=140)
        with mock.patch.object(self.module, "_draw_gradient"):
            app._draw_hero(event)
        title, subtitle = app.hero.create_text.call_args_list
        self.assertGreaterEqual(subtitle.args[1], title.args[1] + 64)
        self.assertIs(title.kwargs["font"], app._hero_title_font)
        self.assertIs(subtitle.kwargs["font"], app._hero_body_font)
        app.root.focus_set.assert_not_called()
        app.root.focus_force.assert_not_called()
        app.hero.focus_set.assert_not_called()

    def test_idle_hides_optional_status_and_busy_restores_stop(self):
        app = self.headless_app()
        app.set_busy(False)
        app.set_state("ready", "ready")
        app.update_progress(0, 0)
        for widget in (app.stop_button, app.countdown_display, app.progressbar, app.progress_label):
            widget.grid_remove.assert_called()
        app.set_busy(True)
        app.set_state("countdown", "switch target", countdown=5)
        app.update_progress(0, 12)
        for widget in (app.stop_button, app.countdown_display, app.progressbar, app.progress_label):
            widget.grid.assert_called()
        self.assertEqual((app.sent_count, app.total_count), (0, 12))


if __name__ == "__main__":
    unittest.main()
