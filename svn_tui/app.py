from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding
from textual.screen import Screen

from svn_tui.services.svn import SvnClient
from svn_tui.ui.screens.log import LogScreen
from svn_tui.ui.screens.status import StatusScreen
from svn_tui.ui.styles import APP_CSS

InitialScreen = str


class SvnTui(App[None]):
    CSS = APP_CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, target: Path, initial_screen: InitialScreen = "status") -> None:
        super().__init__()
        self.initial_screen = initial_screen
        self.target = initial_screen_target(target, initial_screen)

    def get_default_screen(self) -> Screen[None]:
        if self.initial_screen == "log":
            return LogScreen(SvnClient(self.target))
        return StatusScreen(self.target)


def initial_screen_target(target: Path, initial_screen: InitialScreen) -> Path:
    if initial_screen == "status" and target.expanduser().is_file():
        return target.expanduser().parent
    return target
