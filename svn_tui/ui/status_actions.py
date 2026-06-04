from __future__ import annotations

from dataclasses import dataclass

from rich.text import Text

from svn_tui.models import SvnStatusEntry


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


ADD_STATUS_ACTION = StatusAction("add", "a", "Add")
IGNORE_STATUS_ACTION = StatusAction("ignore", "i", "Ignore")
RESOLVE_WORKING_STATUS_ACTION = StatusAction("resolve", "s", "Resolve Working")


DIRECTORY_STATUS_ACTIONS = [
    StatusAction("update_directory", "U", "Update this Directory"),
    StatusAction("revert_directory", "R", "Revert this Directory"),
    StatusAction("cleanup_directory", "C", "Clean Up this Directory"),
    StatusAction("remove_unversioned_directory", "X", "Remove Unversioned..."),
]


BATCH_STATUS_ACTIONS = [
    StatusAction("update", "u", "Update"),
    StatusAction("commit", "c", "Commit"),
    StatusAction("revert", "r", "Revert"),
    StatusAction("copy", "y", "Copy", ("Y",)),
    *DIRECTORY_STATUS_ACTIONS,
]


STATUS_ACTIONS = SINGLE_STATUS_ACTIONS


def single_status_actions_for_entry(entry: SvnStatusEntry) -> list[StatusAction]:
    is_unversioned = entry.text_status in {"?", "I"}
    is_addable = entry.text_status == "?"
    has_conflict = entry.text_status == "C" or entry.prop_status == "C"
    is_directory = entry.path.is_dir()
    actions: list[StatusAction] = []
    if is_addable:
        actions.append(ADD_STATUS_ACTION)
        actions.append(IGNORE_STATUS_ACTION)
    for action in SINGLE_STATUS_ACTIONS:
        if action.option_id == "log" and is_unversioned:
            continue
        if action.option_id == "blame" and (
            is_unversioned or is_directory or entry.text_status in {"D", "!"}
        ):
            continue
        if action.option_id in {"diff_base", "diff_head"} and (
            is_unversioned or is_directory
        ):
            continue
        if action.option_id == "copy" and has_conflict:
            actions.append(RESOLVE_WORKING_STATUS_ACTION)
        if action.option_id == "update" and is_unversioned:
            continue
        if action.option_id == "revert" and is_unversioned:
            continue
        actions.append(action)
    return actions


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
