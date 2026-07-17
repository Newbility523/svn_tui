from __future__ import annotations

import unittest

from svn_tui.ui.navigation import (
    format_navigation_bar,
    screen_navigation_style,
    screen_stack_labels,
)


class StatusScreen:
    pass


class LogScreen:
    pass


class ShelfManagerScreen:
    pass


class UnknownScreen:
    pass


class NavigationTests(unittest.TestCase):
    def test_screen_stack_labels_follow_screen_order(self) -> None:
        labels = screen_stack_labels([StatusScreen(), LogScreen()])

        self.assertEqual(labels, ["Status", "Log"])

    def test_known_screens_have_distinct_background_styles(self) -> None:
        status_style = screen_navigation_style("Status")
        log_style = screen_navigation_style("Log")
        shelf_style = screen_navigation_style("ShelfManager")

        self.assertNotEqual(status_style, log_style)
        self.assertIn("on dark_green", status_style)
        self.assertIn("on dark_blue", log_style)
        self.assertIn("on dark_magenta", shelf_style)

    def test_format_navigation_bar_renders_colored_segments_in_order(self) -> None:
        rendered = format_navigation_bar(["Status", "Log"])

        self.assertEqual(rendered.plain, " Status  Log ")
        self.assertEqual(len(rendered.spans), 2)
        self.assertEqual(
            str(rendered.spans[0].style),
            screen_navigation_style("Status"),
        )
        self.assertEqual(
            str(rendered.spans[1].style),
            screen_navigation_style("Log"),
        )

    def test_unknown_screen_uses_default_style(self) -> None:
        self.assertEqual(
            screen_navigation_style("UnknownScreen"),
            "bold white on grey23",
        )


if __name__ == "__main__":
    unittest.main()
