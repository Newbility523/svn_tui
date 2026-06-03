from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static, TextArea

from svn_tui.ui.formatters import format_help_text


class CommitMessageDialog(ModalScreen[str | None]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("ctrl+enter", "submit", "Commit"),
    ]

    def __init__(self, file_count: int) -> None:
        super().__init__()
        self.file_count = file_count

    def compose(self) -> ComposeResult:
        with Vertical(id="commit-dialog"):
            yield Label(f"Commit Message ({self.file_count} files)", id="commit-title")
            yield TextArea(
                "",
                id="commit-message",
                show_line_numbers=False,
                placeholder="Enter commit message",
            )
            with Horizontal(id="commit-actions"):
                yield Button("Esc Cancel", id="commit-cancel")
                yield Button("Ctrl+Enter Commit", variant="success", id="commit-confirm")

    def on_mount(self) -> None:
        self.query_one("#commit-message", TextArea).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        message = self.query_one("#commit-message", TextArea).text.strip()
        self.dismiss(message)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "commit-cancel":
            self.action_cancel()
            return
        if event.button.id == "commit-confirm":
            self.action_submit()


class ConfirmActionDialog(ModalScreen[bool]):
    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("n", "cancel", "Cancel", show=False),
        Binding("y", "confirm", "Confirm"),
    ]

    def __init__(
        self,
        title: str,
        message: str,
        *,
        confirm_label: str = "Confirm",
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.message = message
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="confirm-dialog"):
            yield Label(self.dialog_title, id="confirm-title")
            yield Static(self.message, id="confirm-message")
            with Horizontal(id="confirm-actions"):
                yield Button("Esc Cancel", id="confirm-cancel")
                yield Button(f"y {self.confirm_label}", variant="error", id="confirm-ok")

    def on_mount(self) -> None:
        self.query_one("#confirm-cancel", Button).focus()

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_confirm(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "confirm-cancel":
            self.action_cancel()
            return
        if event.button.id == "confirm-ok":
            self.action_confirm()


class HelpDialog(ModalScreen[None]):
    BINDINGS = [
        Binding("escape", "close", "Close"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="help-dialog"):
            yield Label("Help", id="help-title")
            yield Static(format_help_text(), id="help-content")

    def action_close(self) -> None:
        self.dismiss(None)
