from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RichLog, Static, TextArea

from svn_tui.ui.formatters import format_help_text


CONFIRM_KEYS = "ctrl+enter,ctrl+j"
CONFIRM_KEY_LABEL = "Ctrl+Enter"
CANCEL_KEYS = "escape"
CANCEL_KEY_LABEL = "Esc"
ERROR_OUTPUT_STYLE = "bold red"


@dataclass(frozen=True)
class SvnCommandResult:
    command: str
    args: tuple[str, ...]
    output: str
    return_code: int | None
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        return not self.cancelled and self.return_code == 0


class CommitMessageDialog(ModalScreen[str | None]):
    BINDINGS = [
        Binding(CANCEL_KEYS, "cancel", "Cancel", key_display=CANCEL_KEY_LABEL),
        Binding(CONFIRM_KEYS, "submit", "Commit", key_display=CONFIRM_KEY_LABEL),
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
                yield Button(f"{CANCEL_KEY_LABEL} Cancel", id="commit-cancel")
                yield Button(
                    f"{CONFIRM_KEY_LABEL} Commit",
                    variant="success",
                    id="commit-confirm",
                )

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
        Binding(CANCEL_KEYS, "cancel", "Cancel", key_display=CANCEL_KEY_LABEL),
        Binding("n", "cancel", "Cancel", show=False),
        Binding(CONFIRM_KEYS, "confirm", "Confirm", key_display=CONFIRM_KEY_LABEL),
        Binding("y", "confirm", "Confirm", show=False),
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
                yield Button(f"{CANCEL_KEY_LABEL} Cancel", id="confirm-cancel")
                yield Button(
                    f"{CONFIRM_KEY_LABEL} {self.confirm_label}",
                    variant="error",
                    id="confirm-ok",
                )

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


class TextInputDialog(ModalScreen[str | None]):
    BINDINGS = [
        Binding(CANCEL_KEYS, "cancel", "Cancel", key_display=CANCEL_KEY_LABEL),
        Binding(CONFIRM_KEYS, "submit", "Confirm", key_display=CONFIRM_KEY_LABEL),
    ]

    def __init__(
        self,
        title: str,
        *,
        placeholder: str = "",
        confirm_label: str = "Confirm",
    ) -> None:
        super().__init__()
        self.dialog_title = title
        self.placeholder = placeholder
        self.confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="text-input-dialog"):
            yield Label(self.dialog_title, id="text-input-title")
            yield Input(
                id="text-input-value",
                placeholder=self.placeholder,
            )
            with Horizontal(id="text-input-actions"):
                yield Button(f"{CANCEL_KEY_LABEL} Cancel", id="text-input-cancel")
                yield Button(
                    f"{CONFIRM_KEY_LABEL} {self.confirm_label}",
                    variant="success",
                    id="text-input-confirm",
                )

    def on_mount(self) -> None:
        self.query_one("#text-input-value", Input).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_submit(self) -> None:
        value = self.query_one("#text-input-value", Input).value.strip()
        self.dismiss(value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "text-input-value":
            return
        event.stop()
        self.action_submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "text-input-cancel":
            self.action_cancel()
            return
        if event.button.id == "text-input-confirm":
            self.action_submit()


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


class SvnCommandDialog(ModalScreen[SvnCommandResult | None]):
    BINDINGS = [
        Binding(CANCEL_KEYS, "cancel_or_close", "Cancel", key_display=CANCEL_KEY_LABEL),
        Binding(CONFIRM_KEYS, "confirm", "Confirm", key_display=CONFIRM_KEY_LABEL),
        Binding("y", "confirm", "Confirm", show=False),
        Binding("n", "keep_running", "Keep running", show=False),
    ]

    def __init__(
        self,
        args: list[str],
        *,
        command: str | None = None,
        title: str = "SVN Command",
    ) -> None:
        super().__init__()
        self.args = tuple(args)
        self.command = command or self.format_command(self.args)
        self.dialog_title = title
        self.process: asyncio.subprocess.Process | None = None
        self.process_task: asyncio.Task[None] | None = None
        self.output_lines: list[str] = []
        self.running = True
        self.confirming_cancel = False
        self.result: SvnCommandResult | None = None

    def compose(self) -> ComposeResult:
        with Vertical(id="svn-command-dialog"):
            yield Label(self.dialog_title, id="svn-command-title")
            with Vertical(id="svn-command-top"):
                yield Label("Command", id="svn-command-command-title")
                yield Static(self.command, id="svn-command-command")
            with Vertical(id="svn-command-bottom"):
                yield Label("Output", id="svn-command-output-title")
                yield RichLog(id="svn-command-output", highlight=False, markup=False)
            with Horizontal(id="svn-command-actions"):
                yield Static("Running...", id="svn-command-status")
                yield Button("Keep Running", id="svn-command-keep-running")
                yield Button(
                    f"{CONFIRM_KEY_LABEL} Cancel Command",
                    id="svn-command-confirm-cancel",
                    variant="error",
                )
                yield Button(
                    f"{CANCEL_KEY_LABEL} Cancel",
                    id="svn-command-cancel",
                    variant="warning",
                )

    def on_mount(self) -> None:
        self.query_one("#svn-command-keep-running", Button).display = False
        self.query_one("#svn-command-confirm-cancel", Button).display = False
        self.query_one("#svn-command-output", RichLog).focus()
        self.process_task = asyncio.create_task(self.run_process())

    def on_unmount(self) -> None:
        if self.process_task is not None and not self.process_task.done():
            self.process_task.cancel()
        if self.running:
            self.terminate_process()

    @staticmethod
    def format_command(args: tuple[str, ...]) -> str:
        return " ".join(shlex.quote(arg) for arg in args)

    async def run_process(self) -> None:
        try:
            self.process = await asyncio.create_subprocess_exec(
                *self.args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            assert self.process.stdout is not None
            assert self.process.stderr is not None
            stream_tasks = [
                asyncio.create_task(
                    self.stream_process_output(self.process.stdout, error=False)
                ),
                asyncio.create_task(
                    self.stream_process_output(self.process.stderr, error=True)
                ),
            ]
            await asyncio.gather(*stream_tasks)
            return_code = await self.process.wait()
        except FileNotFoundError as exc:
            message = f"command not found: {exc.filename}"
            self.append_output(message, error=True)
            self.finish_command("Failed.", return_code=None)
            return
        except asyncio.CancelledError:
            self.terminate_process()
            raise

        if return_code == 0:
            self.finish_command("Finished.", return_code=return_code)
            return
        self.finish_command(f"Exited with code {return_code}.", return_code=return_code)

    async def stream_process_output(
        self,
        stream: asyncio.StreamReader,
        *,
        error: bool,
    ) -> None:
        while True:
            raw_line = await stream.readline()
            if not raw_line:
                return
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            self.append_output(line, error=error)

    @staticmethod
    def output_renderable(line: str, *, error: bool) -> str | Text:
        if error:
            return Text(line, style=ERROR_OUTPUT_STYLE)
        return line

    def append_output(self, line: str, *, error: bool = False) -> None:
        self.output_lines.append(line)
        self.query_one("#svn-command-output", RichLog).write(
            self.output_renderable(line, error=error)
        )

    def finish_command(
        self,
        status: str,
        *,
        return_code: int | None,
        cancelled: bool = False,
    ) -> None:
        if self.result is not None:
            return
        self.running = False
        self.confirming_cancel = False
        self.result = SvnCommandResult(
            command=self.command,
            args=self.args,
            output="\n".join(self.output_lines),
            return_code=return_code,
            cancelled=cancelled,
        )
        self.update_action_state(
            status,
            cancel_label=f"{CANCEL_KEY_LABEL} Close",
            confirming=False,
        )

    def terminate_process(self) -> None:
        if self.process is None or self.process.returncode is not None:
            return
        self.process.terminate()

    def action_cancel_or_close(self) -> None:
        if not self.running:
            self.dismiss(self.result)
            return
        if self.confirming_cancel:
            self.clear_cancel_confirmation()
            return
        self.show_cancel_confirmation()

    def action_confirm(self) -> None:
        if self.confirming_cancel:
            self.confirm_cancel_command()
            return
        if not self.running:
            self.dismiss(self.result)

    def action_keep_running(self) -> None:
        if self.confirming_cancel:
            self.clear_cancel_confirmation()

    def show_cancel_confirmation(self) -> None:
        self.confirming_cancel = True
        self.update_action_state(
            "Cancel running command?",
            cancel_label=f"{CANCEL_KEY_LABEL} Back",
            confirming=True,
        )

    def clear_cancel_confirmation(self) -> None:
        self.confirming_cancel = False
        self.update_action_state(
            "Running...",
            cancel_label=f"{CANCEL_KEY_LABEL} Cancel",
            confirming=False,
        )

    def confirm_cancel_command(self) -> None:
        self.terminate_process()
        self.append_output("Command cancelled.")
        self.finish_command("Cancelled.", return_code=None, cancelled=True)

    def update_action_state(
        self,
        status: str,
        *,
        cancel_label: str,
        confirming: bool,
    ) -> None:
        self.query_one("#svn-command-status", Static).update(status)
        self.query_one("#svn-command-cancel", Button).label = cancel_label
        self.query_one("#svn-command-keep-running", Button).display = confirming
        self.query_one("#svn-command-confirm-cancel", Button).display = confirming

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "svn-command-cancel":
            self.action_cancel_or_close()
            return
        if event.button.id == "svn-command-keep-running":
            self.action_keep_running()
            return
        if event.button.id == "svn-command-confirm-cancel":
            self.confirm_cancel_command()

    def on_key(self, event: events.Key) -> None:
        if event.key != "enter" or not self.confirming_cancel:
            return
        event.stop()
        self.confirm_cancel_command()
