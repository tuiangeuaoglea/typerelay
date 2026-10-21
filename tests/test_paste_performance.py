"""Headless paste, viewport stability and paint reuse regressions."""

import types
import unittest
from unittest import mock

import test_typerelay as harness


class PastePerformanceTests(unittest.TestCase):
    setUp = harness.TypeRelayTests.setUp
    capture_unicode = harness.TypeRelayTests.capture_unicode

    def app(self):
        app = harness.TypeRelayTests.headless_app(self)
        app._paste_timer = None
        app._paste_was_empty = False
        app.text_area.compare.return_value = False
        app.text_area.get.return_value = "existing text"
        return app

    def assert_source_untouched(self, app):
        app.root.clipboard_get.assert_not_called()
        app.text_area.clipboard_get.assert_not_called()
        app.text_area.insert.assert_not_called()
        app.text_area.delete.assert_not_called()
        app.text_area.mark_set.assert_not_called()
        app.text_area.tag_remove.assert_not_called()

    def test_identical_scroll_callbacks_map_and_repaint_only_once(self):
        bar = types.SimpleNamespace(first=0., last=1., _shown=None,
            grid=mock.Mock(), grid_remove=mock.Mock(), _draw=mock.Mock())
        for repeat in range(100):
            self.module.SlimScrollbar.set(bar, "0", ".25")
        bar.grid.assert_called_once_with()
        bar._draw.assert_called_once_with()
        for repeat in range(100):
            self.module.SlimScrollbar.set(bar, "0", "1")
        bar.grid_remove.assert_called_once_with()
        self.assertEqual(bar._draw.call_count, 1)

    def test_scrollbar_reuses_thumb_image_when_only_position_changes(self):
        bar = types.SimpleNamespace(first=0., last=.25, _shown=True,
            orient="vertical", hovered=False, drag_offset=None, _image_key=None,
            _draw_key=None, _thumb_item=None, _length=lambda: 200,
            create_image=mock.Mock(return_value=8), itemconfigure=mock.Mock(), coords=mock.Mock())
        with mock.patch.object(self.module.tk, "PhotoImage", return_value=mock.sentinel.thumb) as photo:
            self.module.SlimScrollbar._draw(bar)
            self.module.SlimScrollbar._draw(bar)
            bar.first, bar.last = .25, .5
            self.module.SlimScrollbar._draw(bar)
        photo.assert_called_once()
        bar.create_image.assert_called_once()
        bar.itemconfigure.assert_not_called()
        bar.coords.assert_called_once_with(8, 2, 50)

    def test_photo_cache_reuses_same_surface_and_stays_bounded(self):
        canvas = types.SimpleNamespace(create_image=mock.Mock(), _photo_cache={})
        with mock.patch.object(self.module.tk, "PhotoImage", side_effect=lambda **kwargs: object()) as photo:
            for repeat in range(20):
                self.module._draw_gradient(canvas, 40, 20, "#FFFFFF", "#FFFFFF", radius=6)
            self.assertEqual(photo.call_count, 1)
            first = canvas._surface_image
            self.module._draw_gradient(canvas, 40, 20, "#FFFFFF", "#FFFFFF", radius=6)
            self.assertIs(canvas._surface_image, first)
            for width in range(41, 51):
                self.module._draw_gradient(canvas, width, 20, "#FFFFFF", "#FFFFFF", radius=6)
            self.assertLessEqual(len(canvas._photo_cache), 8)

    def test_secondary_button_is_pill_shaped_and_skips_unchanged_repaint(self):
        for state in ("normal", "disabled"):
            with self.subTest(state=state):
                button = types.SimpleNamespace(variant="secondary", _visual_key=None,
                    winfo_width=lambda: 104, winfo_height=lambda: 50,
                    cget=mock.Mock(return_value=state), focused=True, pressed=False,
                    hovered=False, caption="清空", delete=mock.Mock(), create_text=mock.Mock())

                def render(canvas, width, height, start, end, **options):
                    png = self.module.rounded_gradient_png(width, height, start, end, **options)
                    self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")

                with mock.patch.object(self.module, "_draw_gradient", side_effect=render) as draw:
                    self.module.GradientButton._draw(button)
                    self.module.GradientButton._draw(button)
                draw.assert_called_once()
                self.assertEqual(draw.call_args.kwargs["radius"], 25)
                if state == "disabled":
                    self.assertIsNone(draw.call_args.kwargs["border"])
                else:
                    self.assertIsNotNone(draw.call_args.kwargs["border"])
                button.delete.assert_called_once_with("all")
                button.create_text.assert_called_once()

    def test_mode_switch_changes_only_visual_wrap_and_preserves_source(self):
        app = self.app()
        for mode, wrap in ((self.module.COMMAND_MODE, "word"), (self.module.FILE_MODE, "none")):
            with self.subTest(mode=mode):
                app.mode.get.return_value = mode
                app.text_area.cget.return_value = "none" if wrap == "word" else "word"
                app.update_mode()
                app.text_area.config.assert_any_call(wrap=wrap)
        self.assert_source_untouched(app)

    def test_before_paste_hides_placeholder_and_keeps_default_tk_paste_binding(self):
        app = self.app()
        app.text_area.compare.return_value = True
        app.root.after_idle.return_value = "paste-idle"
        result = app._before_paste()
        self.assertIsNone(result)
        self.assertTrue(app._paste_was_empty)
        app.empty_hint.place_forget.assert_called_once_with()
        app.root.after_idle.assert_called_once_with(app._finish_paste)
        self.assertEqual(app._paste_timer, "paste-idle")
        self.assert_source_untouched(app)

    def test_paste_hooks_do_nothing_when_busy_or_closing(self):
        for busy, closing in ((True, False), (False, True)):
            with self.subTest(busy=busy, closing=closing):
                app = self.app()
                app.busy, app.closing = busy, closing
                app.refresh_stats = mock.Mock()
                app._before_paste()
                app._finish_paste()
                app.root.after_idle.assert_not_called()
                app.refresh_stats.assert_not_called()
                app.empty_hint.place_forget.assert_not_called()
                self.assert_source_untouched(app)

    def test_paste_finish_anchors_fresh_command_only_and_cancels_pending_statistics(self):
        for fresh, mode, should_anchor in ((True, self.module.COMMAND_MODE, True),
                                          (False, self.module.COMMAND_MODE, False),
                                          (True, self.module.FILE_MODE, False)):
            with self.subTest(fresh=fresh, mode=mode):
                app = self.app()
                app._paste_timer, app._stats_timer = "paste-idle", "pending-statistics"
                app._paste_was_empty = fresh
                app.mode.get.return_value = mode
                app.refresh_stats = mock.Mock()
                app._finish_paste()
                app.root.after_cancel.assert_called_once_with("pending-statistics")
                self.assertIsNone(app._stats_timer)
                self.assertIsNone(app._paste_timer)
                app.refresh_stats.assert_called_once_with()
                if should_anchor:
                    app.text_area.xview_moveto.assert_called_once_with(0)
                    app.text_area.yview_moveto.assert_called_once_with(0)
                else:
                    app.text_area.xview_moveto.assert_not_called()
                    app.text_area.yview_moveto.assert_not_called()
                self.assert_source_untouched(app)

    def test_modified_event_hides_placeholder_before_deferred_statistics(self):
        app = self.app()
        app.text_area.edit_modified.return_value = True
        calls = mock.Mock()
        calls.attach_mock(app.empty_hint.place_forget, "hide_placeholder")
        calls.attach_mock(app.root.after, "defer_statistics")
        app._on_text_modified()
        self.assertEqual(calls.mock_calls[0], mock.call.hide_placeholder())
        app.root.after.assert_called_once_with(60, app.refresh_stats)
        self.assert_source_untouched(app)

    def test_clear_cancels_paste_and_returns_focus_but_busy_clear_is_noop(self):
        app = self.app()
        app._paste_timer, app._stats_timer = "pending-paste", "pending-statistics"
        app.refresh_stats = mock.Mock()
        app.clear()
        app.root.after_cancel.assert_has_calls([mock.call("pending-paste"), mock.call("pending-statistics")], any_order=True)
        self.assertIsNone(app._paste_timer)
        self.assertIsNone(app._stats_timer)
        app.text_area.delete.assert_called_once_with("1.0", "end")
        app.text_area.focus_set.assert_called_once_with()
        busy_app = self.app()
        busy_app.busy = True
        busy_app.clear()
        self.assertEqual(busy_app.root.mock_calls, [])
        busy_app.text_area.delete.assert_not_called()
        busy_app.text_area.focus_set.assert_not_called()

    def test_start_cancels_pending_paste_finalize_before_snapshot(self):
        app = self.app()
        app._paste_timer = "pending-paste"
        app.countdown = mock.Mock()
        app.start()
        app.root.after_cancel.assert_called_once_with("pending-paste")
        self.assertIsNone(app._paste_timer)
        app.countdown.assert_called_once()

    def test_close_cancels_paste_finalize_with_other_callbacks(self):
        app = self.app()
        app.timer, app.poll_timer = "countdown", "poll"
        app._stats_timer, app._paste_timer = "statistics", "paste"
        app.close()
        self.assertTrue(app.closing)
        self.assertEqual(app.root.after_cancel.call_count, 4)
        app.root.after_cancel.assert_has_calls([mock.call(name) for name in ("countdown", "poll", "statistics", "paste")], any_order=True)
        app.root.destroy.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
