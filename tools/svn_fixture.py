from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

MARKER_FILE = ".svn-fixture-root"
DEFAULT_ROOT = Path(".dev") / "svn-fixture"


@dataclass(frozen=True)
class FixturePaths:
    root: Path
    repo: Path
    wc: Path
    actor_wc: Path
    seed_wc: Path

    @classmethod
    def from_root(cls, root: Path) -> FixturePaths:
        resolved = root.expanduser().resolve()
        return cls(
            root=resolved,
            repo=resolved / "repo",
            wc=resolved / "wc",
            actor_wc=resolved / "actor-wc",
            seed_wc=resolved / "seed-wc",
        )

    @property
    def marker(self) -> Path:
        return self.root / MARKER_FILE

    @property
    def repo_url(self) -> str:
        return self.repo.resolve().as_uri()


@dataclass(frozen=True)
class FixtureContext:
    paths: FixturePaths
    svn: str
    svnadmin: str


@dataclass(frozen=True)
class State:
    name: str
    description: str
    apply: Callable[[FixtureContext], None]


@dataclass(frozen=True)
class MenuItem:
    label: str
    description: str
    args: tuple[str, ...]


class FixtureError(RuntimeError):
    pass


def run(
    args: Sequence[str | Path],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    text_args = [str(arg) for arg in args]
    completed = subprocess.run(
        text_args,
        cwd=str(cwd) if cwd is not None else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and completed.returncode != 0:
        details = "\n".join(
            part
            for part in (completed.stdout.strip(), completed.stderr.strip())
            if part
        )
        message = (
            f"Command failed with exit code {completed.returncode}: "
            f"{format_command(text_args)}"
        )
        if details:
            message = f"{message}\n{details}"
        raise FixtureError(message)
    return completed


def svn(ctx: FixtureContext, command: str, *args: str | Path) -> list[str | Path]:
    return [
        ctx.svn,
        command,
        "--non-interactive",
        "--no-auth-cache",
        "--username",
        "svn-fixture",
        *args,
    ]


def svn_commit(ctx: FixtureContext, message: str, cwd: Path) -> None:
    run(svn(ctx, "commit", "-m", message), cwd=cwd)


def format_command(args: Sequence[str]) -> str:
    return " ".join(args)


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.replace("\r\n", "\n").replace("\r", "\n"), encoding="utf-8")


def append_text(path: Path, content: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    write_text(path, existing + content)


def write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


def remove_fixture_root(paths: FixturePaths) -> None:
    if not paths.root.exists():
        return
    if not paths.root.is_dir():
        raise FixtureError(f"Fixture root is not a directory: {paths.root}")
    if not paths.marker.exists():
        raise FixtureError(
            f"Refusing to delete {paths.root}; missing {MARKER_FILE} marker."
        )
    remove_tree(paths.root)


def remove_tree(path: Path) -> None:
    shutil.rmtree(path, onexc=handle_remove_readonly)


def handle_remove_readonly(
    function: Callable[[str], object],
    path: str,
    _error: BaseException,
) -> None:
    os.chmod(path, 0o700)
    function(path)


def create_fixture_root(paths: FixturePaths) -> None:
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.marker.write_text("managed by tools/svn_fixture.py\n", encoding="utf-8")


def rebuild_fixture(ctx: FixtureContext) -> None:
    paths = ctx.paths
    remove_fixture_root(paths)
    create_fixture_root(paths)
    run([ctx.svnadmin, "create", paths.repo])
    run(svn(ctx, "checkout", paths.repo_url, paths.seed_wc))
    build_repository_history(ctx)
    if paths.seed_wc.exists():
        remove_tree(paths.seed_wc)
    run(svn(ctx, "checkout", paths.repo_url, paths.wc))
    run(svn(ctx, "checkout", paths.repo_url, paths.actor_wc))


def build_repository_history(ctx: FixtureContext) -> None:
    wc = ctx.paths.seed_wc
    write_text(
        wc / "README.txt",
        "SVN fixture project\n\nUse this repository to test svn-tui screens.\n",
    )
    write_text(
        wc / "src" / "app.py",
        "def main():\n    return 'hello fixture'\n\n",
    )
    write_text(
        wc / "docs" / "guide.md",
        "# Fixture Guide\n\nThis file changes across revisions.\n",
    )
    write_text(
        wc / "docs" / "old-plan.md",
        "# Old Plan\n\nThis document will be deleted in fixture history.\n",
    )
    write_text(wc / "assets" / "logo.txt", "fixture-logo\n")
    write_text(wc / "space name" / "file with space.txt", "paths with spaces\n")
    write_text(wc / "unicode" / "\u4e2d\u6587\u6587\u4ef6.txt", "wide path label\n")
    write_text(wc / "conflict.txt", "shared line\nbase ending\n")
    write_text(wc / "preview" / "story.txt", "A short preview baseline.\n")
    run(svn(ctx, "add", "--force", "."), cwd=wc)
    svn_commit(ctx, "r1 seed fixture project", wc)

    append_text(
        wc / "src" / "app.py",
        "def status_label(status):\n    return f'status={status}'\n",
    )
    write_text(
        wc / "src" / "helpers.py",
        "def normalize_path(value):\n    return value.replace('\\\\', '/')\n",
    )
    append_text(wc / "docs" / "guide.md", "\nAdded setup notes for the status screen.\n")
    run(svn(ctx, "add", "--force", "."), cwd=wc)
    svn_commit(ctx, "r2 add status helpers", wc)

    run(svn(ctx, "delete", "docs/old-plan.md"), cwd=wc)
    write_text(
        wc / "features" / "status-menu.md",
        "# Status Menu\n\nDynamic actions depend on SVN status.\n",
    )
    append_text(
        wc / "README.txt",
        "\nRevision three adds dynamic status-menu material.\n",
    )
    run(svn(ctx, "add", "--force", "."), cwd=wc)
    svn_commit(ctx, "r3 document dynamic status menu", wc)

    run(svn(ctx, "move", "src/helpers.py", "src/svn_helpers.py"), cwd=wc)
    append_text(
        wc / "src" / "svn_helpers.py",
        "\ndef display_path(value):\n    return normalize_path(value)\n",
    )
    write_bytes(wc / "preview" / "image.bin", bytes(range(128)))
    run(svn(ctx, "add", "--force", "."), cwd=wc)
    svn_commit(ctx, "r4 rename helpers and add binary sample", wc)

    append_text(
        wc / "docs" / "guide.md",
        "\nLog view now has several revisions to browse.\n",
    )
    append_text(
        wc / "space name" / "file with space.txt",
        "second line for path-with-space previews\n",
    )
    write_text(
        wc / "preview" / "long-lines.txt",
        "x" * 240 + "\n" + "another long line " + "y" * 180 + "\n",
    )
    run(svn(ctx, "add", "--force", "."), cwd=wc)
    svn_commit(ctx, "r5 enrich log and preview data", wc)


def apply_clean(ctx: FixtureContext) -> None:
    return None


def apply_log_rich(ctx: FixtureContext) -> None:
    return None


def apply_commit_ready(ctx: FixtureContext) -> None:
    wc = ctx.paths.wc
    append_text(
        wc / "src" / "app.py",
        "\ndef pending_commit_label():\n    return 'ready to commit'\n",
    )
    write_text(
        wc / "docs" / "release-notes.md",
        "# Release Notes\n\n- Added a pending commit fixture state.\n",
    )
    run(svn(ctx, "add", "docs/release-notes.md"), cwd=wc)
    run(svn(ctx, "delete", "features/status-menu.md"), cwd=wc)


def apply_mixed(ctx: FixtureContext) -> None:
    wc = ctx.paths.wc
    append_text(
        wc / "src" / "app.py",
        "\ndef local_only_change():\n    return 'modified in mixed state'\n",
    )
    write_text(wc / "src" / "new_feature.py", "def new_feature():\n    return True\n")
    run(svn(ctx, "add", "src/new_feature.py"), cwd=wc)
    run(svn(ctx, "copy", "src/app.py", "src/app_copy.py"), cwd=wc)
    run(svn(ctx, "delete", "docs/guide.md"), cwd=wc)
    (wc / "assets" / "logo.txt").unlink()
    write_text(wc / "unversioned-note.txt", "This file is not added to SVN.\n")
    write_text(wc / "ignored.tmp", "This file is ignored by svn:ignore.\n")
    run(svn(ctx, "propset", "svn:ignore", "ignored.tmp", "."), cwd=wc)


def apply_large_preview(ctx: FixtureContext) -> None:
    wc = ctx.paths.wc
    append_text(
        wc / "preview" / "story.txt",
        "\n".join(f"changed preview line {index}" for index in range(1, 180))
        + "\n",
    )
    write_text(wc / "preview" / "large-unversioned.txt", ("large preview line\n" * 140000))
    write_text(wc / "preview" / "long-unversioned.txt", "z" * 5000 + "\n")
    write_bytes(wc / "preview" / "binary-unversioned.bin", bytes(range(256)) * 24)


def apply_shelf_ready(ctx: FixtureContext) -> None:
    wc = ctx.paths.wc
    append_text(
        wc / "src" / "app.py",
        "\ndef shelf_fixture_change():\n    return 'app checkpoint'\n",
    )
    append_text(
        wc / "docs" / "guide.md",
        "\nLocal Shelf fixture notes that should survive a checkpoint.\n",
    )
    write_text(
        wc / "shelf-unversioned.txt",
        "Unsupported in the first Shelf version.\n",
    )


def apply_conflict(ctx: FixtureContext) -> None:
    wc = ctx.paths.wc
    actor_wc = ctx.paths.actor_wc
    write_text(
        wc / "conflict.txt",
        "shared line\nlocal edit from fixture working copy\n",
    )
    write_text(
        actor_wc / "conflict.txt",
        "shared line\nremote edit from actor working copy\n",
    )
    svn_commit(ctx, "fixture actor creates conflict source", actor_wc)
    run(svn(ctx, "update", "--accept", "postpone"), cwd=wc, check=False)


STATES: dict[str, State] = {
    "clean": State("clean", "Clean working copy with a rich commit history.", apply_clean),
    "log-rich": State("log-rich", "Clean working copy focused on log and diff browsing.", apply_log_rich),
    "commit-ready": State(
        "commit-ready",
        "Small modified, added, and deleted set suitable for commit flow testing.",
        apply_commit_ready,
    ),
    "mixed": State(
        "mixed",
        "Modified, added, copied, deleted, missing, unversioned, and ignored files.",
        apply_mixed,
    ),
    "large-preview": State(
        "large-preview",
        "Large text, long-line, binary, and modified preview samples.",
        apply_large_preview,
    ),
    "shelf-ready": State(
        "shelf-ready",
        "Two modified text files for checkpoint, shelve, and unshelve testing.",
        apply_shelf_ready,
    ),
    "conflict": State(
        "conflict",
        "A real SVN text conflict created from a second working copy.",
        apply_conflict,
    ),
}


def show_status(ctx: FixtureContext) -> None:
    print()
    print(f"Fixture root: {ctx.paths.root}")
    print(f"Repository:   {ctx.paths.repo_url}")
    print(f"Working copy: {ctx.paths.wc}")
    print()
    print("svn status:")
    completed = run(svn(ctx, "status", ctx.paths.wc), check=False)
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=sys.stderr)


def command_init(ctx: FixtureContext, _args: argparse.Namespace) -> None:
    rebuild_fixture(ctx)
    show_status(ctx)


def command_reset(ctx: FixtureContext, _args: argparse.Namespace) -> None:
    rebuild_fixture(ctx)
    show_status(ctx)


def command_state(ctx: FixtureContext, args: argparse.Namespace) -> None:
    rebuild_fixture(ctx)
    STATES[args.name].apply(ctx)
    show_status(ctx)


def command_list(_ctx: FixtureContext, _args: argparse.Namespace) -> None:
    print("Available fixture states:")
    for state in STATES.values():
        print(f"  {state.name:<14} {state.description}")


def command_path(ctx: FixtureContext, _args: argparse.Namespace) -> None:
    print(ctx.paths.wc)


def command_open(ctx: FixtureContext, args: argparse.Namespace) -> None:
    if not ctx.paths.wc.exists():
        rebuild_fixture(ctx)
    run([sys.executable, "-m", "svn_tui", args.screen, ctx.paths.wc], check=False)


def build_menu_items() -> list[MenuItem]:
    items = [
        MenuItem("init", "Rebuild repository and clean working copies.", ("init",)),
        MenuItem("list", "List available working-copy states.", ("list",)),
        MenuItem("reset", "Reset fixture to the initial clean environment.", ("reset",)),
        MenuItem("path", "Print the main fixture working-copy path.", ("path",)),
    ]
    items.extend(
        MenuItem(
            f"state {state.name}",
            state.description,
            ("state", state.name),
        )
        for state in STATES.values()
    )
    items.extend(
        [
            MenuItem("open status", "Open svn-tui status against the fixture.", ("open", "status")),
            MenuItem("open log", "Open svn-tui log against the fixture.", ("open", "log")),
        ]
    )
    return items


def build_menu_namespace(item: MenuItem) -> argparse.Namespace:
    command = item.args[0]
    namespace = argparse.Namespace(command=command)
    if command == "state":
        namespace.name = item.args[1]
    elif command == "open":
        namespace.screen = item.args[1]
    return namespace


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


def render_menu(items: Sequence[MenuItem], selected: int, ctx: FixtureContext) -> None:
    clear_screen()
    print("SVN fixture tool")
    print(f"Root: {ctx.paths.root}")
    print()
    print("Use Up/Down or j/k to choose. Enter runs. Esc/q quits.")
    print()
    for index, item in enumerate(items):
        marker = ">" if index == selected else " "
        print(f"{marker} {item.label:<20} {item.description}")


def terminal_is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def read_key() -> str:
    if os.name == "nt":
        return read_windows_key()
    return read_posix_key()


def read_windows_key() -> str:
    import msvcrt

    key = msvcrt.getwch()
    if key in ("\x00", "\xe0"):
        key = msvcrt.getwch()
        if key == "H":
            return "up"
        if key == "P":
            return "down"
        return ""
    if key == "\r":
        return "enter"
    if key == "\x1b":
        return "escape"
    return key.lower()


def read_posix_key() -> str:
    import select
    import termios
    import tty

    file_descriptor = sys.stdin.fileno()
    old_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setraw(file_descriptor)
        key = sys.stdin.read(1)
        if key == "\x1b":
            if select.select([sys.stdin], [], [], 0.05)[0]:
                second = sys.stdin.read(1)
                third = sys.stdin.read(1) if select.select([sys.stdin], [], [], 0.05)[0] else ""
                if second == "[" and third == "A":
                    return "up"
                if second == "[" and third == "B":
                    return "down"
            return "escape"
        if key in ("\r", "\n"):
            return "enter"
        return key.lower()
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, old_settings)


def run_interactive_menu(ctx: FixtureContext) -> int:
    items = build_menu_items()
    selected = 0
    while True:
        render_menu(items, selected, ctx)
        key = read_key()
        if key in ("q", "escape"):
            clear_screen()
            return 0
        if key in ("up", "k"):
            selected = (selected - 1) % len(items)
        elif key in ("down", "j"):
            selected = (selected + 1) % len(items)
        elif key == "enter":
            item = items[selected]
            clear_screen()
            print(f"Running: python tools/svn_fixture.py {' '.join(item.args)}")
            return dispatch_command(ctx, build_menu_namespace(item))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and switch local SVN fixture states for svn-tui UX testing."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_ROOT,
        help="fixture root directory; default: .dev/svn-fixture",
    )
    parser.add_argument("--svn", default="svn", help="svn executable; default: svn")
    parser.add_argument(
        "--svnadmin", default="svnadmin", help="svnadmin executable; default: svnadmin"
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("init", help="rebuild the fixture repository and clean working copies")
    subparsers.add_parser("reset", help="reset fixture to the initial clean environment")
    subparsers.add_parser("list", help="list available working-copy states")
    subparsers.add_parser("path", help="print the main fixture working-copy path")

    state_parser = subparsers.add_parser("state", help="reset and apply a named state")
    state_parser.add_argument("name", choices=sorted(STATES))

    open_parser = subparsers.add_parser("open", help="open svn-tui against the fixture")
    open_parser.add_argument("screen", choices=("status", "log"))

    return parser


def make_context(args: argparse.Namespace) -> FixtureContext:
    return FixtureContext(
        paths=FixturePaths.from_root(args.root),
        svn=args.svn,
        svnadmin=args.svnadmin,
    )


def dispatch_command(ctx: FixtureContext, args: argparse.Namespace) -> int:
    commands: dict[str, Callable[[FixtureContext, argparse.Namespace], None]] = {
        "init": command_init,
        "reset": command_reset,
        "list": command_list,
        "path": command_path,
        "state": command_state,
        "open": command_open,
    }
    try:
        commands[args.command](ctx, args)
    except FixtureError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except FileNotFoundError as error:
        print(f"error: command not found: {error.filename}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parsed_argv = list(sys.argv[1:] if argv is None else argv)
    args = parser.parse_args(parsed_argv)
    ctx = make_context(args)
    if args.command is None:
        if not terminal_is_interactive():
            parser.print_help()
            print(
                "\nRun without a command in an interactive terminal to open the menu.",
                file=sys.stderr,
            )
            return 2
        try:
            return run_interactive_menu(ctx)
        except KeyboardInterrupt:
            clear_screen()
            return 130
    return dispatch_command(ctx, args)


if __name__ == "__main__":
    raise SystemExit(main())
