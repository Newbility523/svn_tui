from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text


STATUS_ACTION_KEY_STYLE = "bold cyan"
STATUS_ACTION_KEY_WIDTH = 5


@dataclass(frozen=True)
class StatusAction:
    option_id: str
    key: str
    label: str
    alternate_keys: tuple[str, ...] = ()

    @property
    def menu_label(self) -> str:
        key_label = "/".join((self.key, *self.alternate_keys))
        return f"{key_label:<{STATUS_ACTION_KEY_WIDTH}} {self.label}"

    @property
    def menu_text(self) -> Text:
        key_label = "/".join((self.key, *self.alternate_keys))
        text = Text()
        text.append(key_label, style=STATUS_ACTION_KEY_STYLE)
        text.append(" " * (STATUS_ACTION_KEY_WIDTH - len(key_label) + 1))
        text.append(self.label)
        return text

    @property
    def keys(self) -> tuple[str, ...]:
        return (self.key, *self.alternate_keys)


SINGLE_STATUS_ACTIONS = [
    StatusAction("log", "l", "Log", ("L",)),
    StatusAction("blame", "b", "Blame", ("B",)),
    StatusAction("diff_base", "d", "Diff Base", ("D",)),
    StatusAction("diff_head", "h", "Diff Head", ("H",)),
    StatusAction("copy", "y", "Copy", ("Y",)),
    StatusAction("update", "u", "Update"),
    StatusAction("revert", "r", "Revert"),
]


DIRECTORY_STATUS_ACTIONS = [
    StatusAction("update_directory", "U", "Update this Directory"),
    StatusAction("revert_directory", "R", "Revert this Directory"),
]


BATCH_STATUS_ACTIONS = [
    StatusAction("update", "u", "Update"),
    StatusAction("commit", "c", "Commit"),
    StatusAction("revert", "r", "Revert"),
    StatusAction("copy", "y", "Copy", ("Y",)),
    *DIRECTORY_STATUS_ACTIONS,
]


STATUS_ACTIONS = SINGLE_STATUS_ACTIONS


def status_action_for_key(
    key: str,
    actions: list[StatusAction] | None = None,
) -> StatusAction | None:
    for action in actions or STATUS_ACTIONS:
        if key in action.keys:
            return action
    return None


def status_action_for_option(
    option_id: str,
    actions: list[StatusAction] | None = None,
) -> StatusAction | None:
    for action in actions or STATUS_ACTIONS:
        if action.option_id == option_id:
            return action
    return None
