"""Headless regressions for window visibility, rendering and custom scrolling."""

import ctypes
import struct
import types
import unittest
from unittest import mock
import zlib

import test_typerelay as harness


class RenderingTests(unittest.TestCase):
    setUp = harness.TypeRelayTests.setUp
    capture_unicode = harness.TypeRelayTests.capture_unicode

    def decode_png(self, data):
        """Read the generated PNG independently of Tk or the platform decoder."""
        self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
        position, image_data, dimensions = 8, [], None
        while position < len(data):
            length = struct.unpack_from(">I", data, position)[0]
            kind = data[position + 4:position + 8]
            payload = data[position + 8:position + 8 + length]
            checksum = struct.unpack_from(">I", data, position + 8 + length)[0]
            self.assertEqual(checksum, zlib.crc32(kind + payload) & 0xFFFFFFFF)
            if kind == b"IHDR":
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", payload)
                self.assertEqual((depth, color, compression, filtering, interlace), (8, 6, 0, 0, 0))
                dimensions = (width, height)
            elif kind == b"IDAT":
                image_data.append(payload)
            elif kind == b"IEND":
                break
            position += length + 12
        self.assertIsNotNone(dimensions)
        width, height = dimensions
        scanlines = zlib.decompress(b"".join(image_data))
        stride = width * 4 + 1
        self.assertEqual(len(scanlines), stride * height)
        rows = []
        for y in range(height):
            row = scanlines[y * stride:(y + 1) * stride]
            self.assertEqual(row[0], 0)
            rows.append([tuple(row[1 + x * 4:5 + x * 4]) for x in range(width)])
        return dimensions, rows

    def test_app_defaults_to_topmost_without_activating_or_raising_it(self):
        root = mock.Mock()
        with mock.patch.object(self.module.tk, "StringVar"), \
                mock.patch.object(self.module.tk, "BooleanVar"), \
                mock.patch.object(self.module, "WindowsFocus"), \
                mock.patch.object(self.module.App, "_build_styles"), \
                mock.patch.object(self.module.App, "_build_ui"), \
                mock.patch.object(self.module.App, "update_mode"), \
                mock.patch.object(self.module.App, "refresh_stats"), \
                mock.patch.object(self.module.App, "set_state"):
            self.module.App(root=root)
        root.attributes.assert_called_once_with("-topmost", True)
        root.focus_set.assert_not_called()
        root.focus_force.assert_not_called()
        root.lift.assert_not_called()

    def test_round_gradient_is_valid_rgba_png_with_antialiased_corner_alpha(self):
        dimensions, rows = self.decode_png(self.module.rounded_gradient_png(
            40, 20, "#000000", "#FFFFFF", 6))
        self.assertEqual(dimensions, (40, 20))
        self.assertEqual(rows[0][0][3], 0)
        self.assertEqual(rows[10][20][3], 255)
        self.assertTrue(any(0 < pixel[3] < 255 for row in rows for pixel in row))
        middle = rows[10]
        self.assertLess(middle[0][0], 10)
        self.assertGreater(middle[-1][0], 245)
        self.assertTrue(all(left[0] <= right[0] for left, right in zip(middle, middle[1:])))

    def test_border_does_not_replace_solid_card_interior(self):
        _, rows = self.decode_png(self.module.rounded_gradient_png(
            36, 20, "#FFFFFF", "#FFFFFF", 6, border="#000000", border_width=1))
        self.assertEqual(rows[10][18], (255, 255, 255, 255))
        self.assertLess(rows[0][18][0], rows[3][18][0])
        self.assertEqual(rows[0][0][3], 0)

    def test_gradient_canvas_keeps_photo_reference_and_uses_one_image_item(self):
        canvas = types.SimpleNamespace(create_image=mock.Mock(return_value=27))
        photo = mock.sentinel.photo
        with mock.patch.object(self.module.tk, "PhotoImage", return_value=photo) as factory:
            item = self.module._draw_gradient(canvas, 40, 20, "#7562EC", "#487FF0", radius=6)
        self.assertEqual(item, 27)
        self.assertIs(canvas._surface_image, photo)
        canvas.create_image.assert_called_once_with(0, 0, image=photo, anchor="nw", tags="paint")
        self.assertIs(factory.call_args.kwargs["master"], canvas)
        dimensions, _ = self.decode_png(factory.call_args.kwargs["data"])
        self.assertEqual(dimensions, (40, 20))

    def test_focused_button_render_colors_are_valid_and_disabled_button_has_no_focus_border(self):
        for state in ("normal", "disabled"):
            with self.subTest(state=state):
                button = types.SimpleNamespace(delete=mock.Mock(), winfo_width=lambda: 180,
                    winfo_height=lambda: 50, cget=mock.Mock(return_value=state),
                    focused=True, pressed=False, hovered=False, caption="开始输入", create_text=mock.Mock())
                rendered = []

                def render(canvas, width, height, start, end, **options):
                    png = self.module.rounded_gradient_png(width, height, start, end, **options)
                    rendered.append(self.decode_png(png))

                with mock.patch.object(self.module, "_draw_gradient", side_effect=render) as draw:
                    self.module.GradientButton._draw(button)
                self.assertEqual(rendered[0][0], (180, 50))
                self.assertEqual(draw.call_args.kwargs["border"], "#FFFFFF" if state == "normal" else None)
                button.create_text.assert_called_once()

    def test_small_render_surfaces_stay_valid_with_large_corner_radius(self):
        for width, height in ((1, 1), (2, 3)):
            with self.subTest(width=width, height=height):
                dimensions, rows = self.decode_png(self.module.rounded_gradient_png(
                    width, height, "#7562EC", "#487FF0", 22))
                self.assertEqual(dimensions, (width, height))
                self.assertEqual(len(rows), height)

    def test_png_corner_row_reuse_preserves_every_row_and_vertical_symmetry(self):
        for width, height, radius, border_width in ((9, 1, 0, 0), (19, 7, 3.2, 1.5),
                                                   (17, 8, 9, 3), (5, 3, 0, 4), (1, 7, 3, .5)):
            with self.subTest(width=width, height=height, radius=radius, border_width=border_width):
                dimensions, rows = self.decode_png(self.module.rounded_gradient_png(
                    width, height, "#7562EC", "#487FF0", radius,
                    border="#FFFFFF", border_width=border_width))
                self.assertEqual(dimensions, (width, height))
                self.assertEqual(rows, list(reversed(rows)))

    def test_scrollbar_geometry_clamps_positions_and_supports_short_tracks(self):
        for first, last, track in ((0, .2, 200), (.8, 1, 200), (.5, .51, 200),
                                   (-.2, .2, 200), (.9, 1.2, 200), (0, 1, 10), (0, 1, 0)):
            with self.subTest(first=first, last=last, track=track):
                start, length = self.module.scrollbar_geometry(first, last, track)
                self.assertGreaterEqual(start, 0)
                self.assertGreaterEqual(length, 0)
                self.assertLessEqual(start + length, max(0, track))
        first_start, thumb = self.module.scrollbar_geometry(0, .2, 200)
        last_start, last_thumb = self.module.scrollbar_geometry(.8, 1, 200)
        self.assertEqual(first_start, 0)
        self.assertAlmostEqual(thumb, last_thumb)
        self.assertAlmostEqual(last_start + last_thumb, 200)

    def scrollbar(self, orient="vertical"):
        scrollbar = types.SimpleNamespace(first=0., last=.25, orient=orient,
            command=mock.Mock(), grid=mock.Mock(), grid_remove=mock.Mock(),
            _draw=mock.Mock(), winfo_width=lambda: 200 if orient == "horizontal" else 10,
            winfo_height=lambda: 200 if orient == "vertical" else 10)
        scrollbar._axis = lambda event: self.module.SlimScrollbar._axis(scrollbar, event)
        scrollbar._length = lambda: self.module.SlimScrollbar._length(scrollbar)
        return scrollbar

    def test_scrollbar_hides_when_not_needed_and_restores_on_overflow(self):
        scrollbar = self.scrollbar()
        for first, last in (("0", "1"), ("0", "0")):
            self.module.SlimScrollbar.set(scrollbar, first, last)
            scrollbar.grid_remove.assert_called()
        self.module.SlimScrollbar.set(scrollbar, "0", ".25")
        scrollbar.grid.assert_called()
        self.assertEqual((scrollbar.first, scrollbar.last), (0., .25))

    def test_scrollbar_drag_reaches_both_ends_without_focusing_the_application(self):
        for orient in ("horizontal", "vertical"):
            with self.subTest(orient=orient):
                scrollbar = self.scrollbar(orient)
                scrollbar.focus_set = mock.Mock()
                scrollbar.drag_offset = 5
                for coordinate, expected in ((-200, 0), (500, .75)):
                    event = types.SimpleNamespace(x=coordinate, y=coordinate)
                    self.module.SlimScrollbar._drag(scrollbar, event)
                    operation, fraction = scrollbar.command.call_args.args
                    self.assertEqual(operation, "moveto")
                    self.assertAlmostEqual(fraction, expected)
                scrollbar.focus_set.assert_not_called()

    def test_scrollbar_drag_preserves_pointer_offset_and_release_ends_drag(self):
        scrollbar = self.scrollbar()
        scrollbar.first, scrollbar.last = .25, .5
        self.module.SlimScrollbar._press(scrollbar, types.SimpleNamespace(x=5, y=60))
        self.assertAlmostEqual(scrollbar.drag_offset, 10)
        scrollbar.command.assert_not_called()
        self.module.SlimScrollbar._drag(scrollbar, types.SimpleNamespace(x=5, y=80))
        operation, fraction = scrollbar.command.call_args.args
        self.assertEqual(operation, "moveto")
        self.assertAlmostEqual(fraction, .35)
        self.module.SlimScrollbar._release(scrollbar, types.SimpleNamespace())
        self.assertIsNone(scrollbar.drag_offset)
        scrollbar.command.reset_mock()
        self.module.SlimScrollbar._drag(scrollbar, types.SimpleNamespace(x=5, y=100))
        scrollbar.command.assert_not_called()

    def test_scrollbar_click_outside_thumb_pages_without_starting_drag(self):
        scrollbar = self.scrollbar()
        scrollbar.first, scrollbar.last = .25, .5
        for coordinate, direction in ((10, -1), (150, 1)):
            with self.subTest(coordinate=coordinate):
                self.module.SlimScrollbar._press(scrollbar, types.SimpleNamespace(x=5, y=coordinate))
                scrollbar.command.assert_called_with("scroll", direction, "pages")
                self.assertIsNone(scrollbar.drag_offset)

    def test_shift_wheel_scrolls_horizontal_without_focusing_or_editing_text(self):
        app = harness.TypeRelayTests.headless_app(self)
        for delta, expected in ((120, -1), (-240, 2), (30, -1), (0, None)):
            with self.subTest(delta=delta):
                app.text_area.reset_mock()
                result = app._scroll_horizontal(types.SimpleNamespace(delta=delta))
                self.assertEqual(result, "break")
                if expected is None:
                    app.text_area.xview_scroll.assert_not_called()
                else:
                    app.text_area.xview_scroll.assert_called_once_with(expected, "units")
                app.text_area.focus_set.assert_not_called()
                app.text_area.insert.assert_not_called()
                app.text_area.delete.assert_not_called()
        app.root.focus_force.assert_not_called()
        app.root.lift.assert_not_called()

    def test_dpi_setup_prefers_per_monitor_context_and_does_not_create_tk(self):
        context = mock.Mock(return_value=1)
        api = types.SimpleNamespace(SetProcessDpiAwarenessContext=context)
        with mock.patch.object(self.module.ctypes, "WinDLL", return_value=api), \
                mock.patch.object(self.module.sys, "platform", "win32"):
            self.assertTrue(self.module.configure_dpi_awareness())
        self.assertEqual(context.call_count, 1)
        value = context.call_args.args[0]
        value = value.value if hasattr(value, "value") else value
        self.assertEqual(ctypes.c_ssize_t(value).value, -4)

    def test_dpi_setup_keeps_existing_awareness_when_windows_reports_access_denied(self):
        api = types.SimpleNamespace(SetProcessDpiAwarenessContext=mock.Mock(return_value=0))
        with mock.patch.object(self.module.ctypes, "WinDLL", return_value=api) as load, \
                mock.patch.object(self.module.ctypes, "get_last_error", return_value=5), \
                mock.patch.object(self.module.sys, "platform", "win32"):
            self.assertFalse(self.module.configure_dpi_awareness())
        self.assertEqual(load.call_count, 1)

    def test_dpi_setup_falls_back_safely_without_native_apis(self):
        with mock.patch.object(self.module.ctypes, "WinDLL", side_effect=OSError("Unavailable")), \
                mock.patch.object(self.module.sys, "platform", "win32"):
            self.assertFalse(self.module.configure_dpi_awareness())

    def test_dpi_setup_uses_shcore_when_context_api_is_unsupported(self):
        user32 = types.SimpleNamespace(SetProcessDpiAwarenessContext=mock.Mock(return_value=0))
        shcore = types.SimpleNamespace(SetProcessDpiAwareness=mock.Mock(return_value=0))
        with mock.patch.object(self.module.ctypes, "WinDLL", side_effect=[user32, shcore]), \
                mock.patch.object(self.module.ctypes, "get_last_error", return_value=87), \
                mock.patch.object(self.module.sys, "platform", "win32"):
            self.assertTrue(self.module.configure_dpi_awareness())
        shcore.SetProcessDpiAwareness.assert_called_once_with(2)

    def test_dpi_setup_uses_legacy_api_when_modern_apis_are_missing(self):
        user32 = types.SimpleNamespace(SetProcessDPIAware=mock.Mock(return_value=1))
        with mock.patch.object(self.module.ctypes, "WinDLL", side_effect=[user32, OSError("No shcore")]), \
                mock.patch.object(self.module.sys, "platform", "win32"):
            self.assertTrue(self.module.configure_dpi_awareness())
        user32.SetProcessDPIAware.assert_called_once_with()

    def test_dpi_setup_does_not_fail_if_libraries_expose_none_of_the_apis(self):
        with mock.patch.object(self.module.ctypes, "WinDLL", return_value=types.SimpleNamespace()), \
                mock.patch.object(self.module.sys, "platform", "win32"):
            self.assertFalse(self.module.configure_dpi_awareness())

    def test_dpi_configuration_precedes_creation_of_owned_root(self):
        events, root = [], mock.Mock()
        with mock.patch.object(self.module, "configure_dpi_awareness", side_effect=lambda: events.append("dpi")), \
                mock.patch.object(self.module.tk, "Tk", side_effect=lambda: events.append("tk") or root), \
                mock.patch.object(self.module.tk, "StringVar"), \
                mock.patch.object(self.module.tk, "BooleanVar"), \
                mock.patch.object(self.module, "WindowsFocus"), \
                mock.patch.object(self.module.App, "_build_styles"), \
                mock.patch.object(self.module.App, "_build_ui"), \
                mock.patch.object(self.module.App, "update_mode"), \
                mock.patch.object(self.module.App, "refresh_stats"), \
                mock.patch.object(self.module.App, "set_state"):
            self.module.App()
        self.assertEqual(events, ["dpi", "tk"])


if __name__ == "__main__":
    unittest.main()
