from __future__ import annotations

from pathlib import Path

from textual.app import App
from textual.binding import Binding

from svn_tui.ui.screens.status import StatusScreen
from svn_tui.ui.styles import APP_CSS


class SvnTui(App[None]):
    CSS = APP_CSS
    BINDINGS = [
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, target: Path) -> None:
        super().__init__()
        self.target = target

    def on_mount(self) -> None:
        self.push_screen(StatusScreen(self.target))
