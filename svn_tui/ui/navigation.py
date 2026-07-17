from __future__ import annotations

from collections.abc import Iterable

from rich.text import Text
from textual.screen import Screen
from textual.widgets import Static


SCREEN_NAVIGATION_STYLES = {
    "Status": "bold white on dark_green",
    "Log": "bold white on dark_blue",
    "ShelfManager": "bold white on dark_magenta",
}
DEFAULT_NAVIGATION_STYLE = "bold white on grey23"


def screen_stack_labels(screens: Iterable[object]) -> list[str]:
    return [screen_navigation_label(screen) for screen in screens]


def screen_navigation_label(screen: object) -> str:
    class_name = screen.__class__.__name__
    if class_name.endswith("Screen") and len(class_name) > len("Screen"):
        return class_name[: -len("Screen")]
    return class_name


def screen_navigation_style(label: str) -> str:
    return SCREEN_NAVIGATION_STYLES.get(label, DEFAULT_NAVIGATION_STYLE)


def format_navigation_bar(labels: Iterable[str]) -> Text:
    navigation = Text()
    for label in labels:
        navigation.append(f" {label} ", style=screen_navigation_style(label))
    return navigation


class NavigationBar(Static):
    def refresh_from_screens(self, screens: Iterable[Screen[object]]) -> None:
        self.update(format_navigation_bar(screen_stack_labels(screens)))
