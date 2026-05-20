from __future__ import annotations

import unittest

from svn_tui.ui.status_actions import (
    BATCH_STATUS_ACTIONS,
    DIRECTORY_STATUS_ACTIONS,
    SINGLE_STATUS_ACTIONS,
    STATUS_ACTION_KEY_STYLE,
    status_action_for_key,
    status_action_for_option,
)


class StatusActionTests(unittest.TestCase):
    def test_single_menu_labels_include_hotkey_prefixes(self) -> None:
        labels = [action.menu_label for action in SINGLE_STATUS_ACTIONS]

        self.assertEqual(
            labels,
            [
                "l/L   Log",
                "b/B   Blame",
                "d/D   Diff Base",
                "h/H   Diff Head",
                "y/Y   Copy",
                "u     Update",
                "r     Revert",
            ],
        )

    def test_batch_menu_only_contains_batch_safe_actions(self) -> None:
        labels = [action.menu_label for action in BATCH_STATUS_ACTIONS]

        self.assertEqual(
            labels,
            [
                "u     Update",
                "c     Commit",
                "r     Revert",
                "y/Y   Copy",
                "U     Update this Directory",
                "R     Revert this Directory",
            ],
        )

    def test_directory_menu_only_contains_directory_actions(self) -> None:
        labels = [action.menu_label for action in DIRECTORY_STATUS_ACTIONS]

        self.assertEqual(
            labels,
            [
                "U     Update this Directory",
                "R     Revert this Directory",
            ],
        )

    def test_menu_text_highlights_shortcut_only(self) -> None:
        text = SINGLE_STATUS_ACTIONS[0].menu_text

        self.assertEqual(text.plain, "l/L   Log")
        self.assertEqual(len(text.spans), 1)
        self.assertEqual(text.spans[0].start, 0)
        self.assertEqual(text.spans[0].end, 3)
        self.assertEqual(text.spans[0].style, STATUS_ACTION_KEY_STYLE)

    def test_hotkey_lookup_is_case_sensitive(self) -> None:
        self.assertEqual(status_action_for_key("L", SINGLE_STATUS_ACTIONS).option_id, "log")
        self.assertEqual(status_action_for_key("l", SINGLE_STATUS_ACTIONS).option_id, "log")
        self.assertEqual(status_action_for_key("Y", SINGLE_STATUS_ACTIONS).option_id, "copy")
        self.assertEqual(status_action_for_key("y", SINGLE_STATUS_ACTIONS).option_id, "copy")
        self.assertEqual(status_action_for_key("Y", BATCH_STATUS_ACTIONS).option_id, "copy")
        self.assertEqual(status_action_for_key("y", BATCH_STATUS_ACTIONS).option_id, "copy")
        self.assertEqual(
            status_action_for_key("u", BATCH_STATUS_ACTIONS).option_id,
            "update",
        )
        self.assertEqual(
            status_action_for_key("U", BATCH_STATUS_ACTIONS).option_id,
            "update_directory",
        )
        self.assertEqual(
            status_action_for_key("r", BATCH_STATUS_ACTIONS).option_id,
            "revert",
        )
        self.assertEqual(
            status_action_for_key("R", BATCH_STATUS_ACTIONS).option_id,
            "revert_directory",
        )

    def test_option_lookup_returns_action(self) -> None:
        self.assertEqual(status_action_for_option("update", BATCH_STATUS_ACTIONS).key, "u")


if __name__ == "__main__":
    unittest.main()
