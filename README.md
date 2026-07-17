# svn-tui

一个基于 [Textual](https://textual.textualize.io/) 的 SVN TUI 客户端原型，用于在终端里查看 SVN 工作副本状态、检查变更、提交文件，并浏览仓库最近日志。

当前目标是快速查看指定工作副本路径下的 `svn st` 结果，逐个检查文件变更，用 `nvim -d` 打开 diff，并提交勾选的文件；同时可以直接查看仓库最近日志与对应 diff。项目已拆分为可扩展的包结构，便于后续增加更多独立界面。

## Requirements

- Python 3.13+
- SVN 命令行工具
- Neovim

安装 Python 依赖和 `svn-tui` 命令入口：

```bash
python3 -m pip install -r requirements.txt
```

## Quick Start

默认打开状态界面：

```bash
svn-tui /path/to/svn/working-copy
```

也可以使用包入口或源码入口：

```bash
python3 -m svn_tui /path/to/svn/working-copy
python3 main.py /path/to/svn/working-copy
```

如果不传路径，默认使用当前目录：

```bash
svn-tui
```

显式选择初始界面：

```bash
svn-tui status /path/to/item
svn-tui log /path/to/item
svn-tui --screen log /path/to/item
```

`status` 接收文件路径时，会自动改用该文件所在目录作为目标，便于从文件管理器选中文件后查看同目录状态。`log` 接收文件路径时会保留文件目标，用于直接查看该文件的历史日志。

列表中的路径相对传入的打开路径显示。例如打开 `a/b/c` 时，文件 `a/b/c/d.py` 会显示为 `d.py`。

## Ranger Integration

`svn-tui` 不能嵌入 ranger 进程内部。推荐做法是在 ranger 快捷键中启动外部 TUI，退出 `svn-tui` 后自然回到 ranger。

示例 `~/.config/ranger/rc.conf`：

```text
map zs shell svn-tui status %f
map zl shell svn-tui log %f
```

如果使用当前仓库而不是安装后的包入口，可以写成：

```text
map zs shell python3 /path/to/svn_tui/main.py status %f
map zl shell python3 /path/to/svn_tui/main.py log %f
```

在 tmux 里使用 ranger 时，也可以把 `svn-tui` 放进 popup：

```text
map zS shell tmux popup -d "#{pane_current_path}" -w 90% -h 90% -E "svn-tui status %f"
map zL shell tmux popup -d "#{pane_current_path}" -w 90% -h 90% -E "svn-tui log %f"
```

`tmux popup` 会在当前 pane 上方打开一个临时 TUI，退出 `svn-tui` 后 popup 关闭并回到 ranger。

## SVN Fixture Tool

体验测试时可以用本地 fixture 工具一键生成 SVN 仓库、提交历史和工作副本状态：

```bash
python3 tools/svn_fixture.py
```

直接运行会打开交互菜单，可以用方向键或 `j` / `k` 选择操作，按 `Enter` 执行。也可以显式运行命令：

```bash
python3 tools/svn_fixture.py init
python3 tools/svn_fixture.py state mixed
svn-tui status .dev/svn-fixture/wc
```

常用命令：

```bash
python3 tools/svn_fixture.py list
python3 tools/svn_fixture.py reset
python3 tools/svn_fixture.py state commit-ready
python3 tools/svn_fixture.py state conflict
python3 tools/svn_fixture.py state large-preview
python3 tools/svn_fixture.py state shelf-ready
python3 tools/svn_fixture.py open status
python3 tools/svn_fixture.py open log
```

每次 `state <name>` 都会先重建 fixture 到基准提交历史，再制造指定工作状态，避免多次体验测试后本地 repo 累积额外 revision。默认数据放在 `.dev/svn-fixture/`，该目录已被 Git 忽略。

## Documentation

- [架构与业务链路](docs/architecture.md)
- [开发与验证指南](docs/development.md)
- [TODO](docs/todo.md)

## Project Structure

项目已按后续多界面扩展拆成包结构：

- `main.py`：兼容入口，只调用包内 CLI。
- `tools/svn_fixture.py`：本地 SVN 体验测试 fixture 工具。
- `svn_tui/__main__.py`：支持 `python3 -m svn_tui` 入口。
- `svn_tui/cli.py`：命令行参数解析和启动。
- `svn_tui/app.py`：Textual App 外壳和全局快捷键。
- `svn_tui/config.py`：预览、列表列宽、日志数量、滚动间隔、主题等全局配置。
- `svn_tui/models.py`：SVN 状态、日志、日志路径等业务数据结构。
- `svn_tui/shelf_models.py`：working copy identity、Shelf 和 Shelf Version 数据结构。
- `svn_tui/services/`：SVN 命令调用和文件预览索引等工具层，不依赖具体界面。
- `svn_tui/services/shelves.py`：Shelf 持久化、Checkpoint、Shelve、Unshelve、导出和清理服务。
- `svn_tui/ui/styles.py`：Textual CSS 布局和样式。
- `svn_tui/ui/widgets.py`：可复用 UI 组件和列表行渲染。
- `svn_tui/ui/dialogs.py`：提交信息、帮助等弹窗。
- `svn_tui/ui/screens/`：不同界面 Screen，目前包含状态、日志和 Shelf Manager 界面。
- `svn_tui/ui/formatters.py`、`svn_tui/ui/search.py`：界面展示格式化和列表搜索逻辑。
- `svn_tui/utils/`：路径、大小格式化等跨层小工具。

新增界面时优先在 `svn_tui/ui/screens/` 添加 Screen，并复用 `services/`、`models.py`、`ui/widgets.py` 和 `ui/formatters.py`。样式只放在 `svn_tui/ui/styles.py`，配置只放在 `svn_tui/config.py`。

## Business Flow

主链路：

1. CLI 解析目标工作副本路径，启动 `SvnTui`。
2. App 进入 `StatusScreen`，通过 `SvnClient.status()` 异步执行 `svn st`。
3. 状态列表将 `SvnStatusEntry` 渲染为可勾选行，右侧按当前行延迟加载只读预览。
4. 用户勾选文件后输入提交说明，`SvnCommandDialog` 执行 `svn commit` 并展示实时输出，完成后刷新状态。
5. 用户打开 diff / blame 时暂停 Textual，交给真实 `nvim` 处理交互。
6. 用户进入 `LogScreen` 后，`SvnClient.recent_logs()` 读取仓库日志，选中 revision/path 后再异步加载 `svn diff`。

## Features

- 显示 `svn st` 结果。
- 按状态和文件类型给列表项着色。
- 显示文件扩展名和大小。
- 用空格将条目标记进提交列表。
- 通过批量操作菜单输入提交信息并提交勾选的文件。
- 用 `nvim -d` 检查变更。
- 右侧提供 inline diff 预览；未版本控制或无法生成 diff 的条目保留文件预览。
- 主列表底部保留最近一次 SVN 操作的完整输出，便于回看 update / commit / revert 等命令结果。
- SVN commit 和目录级 cleanup 操作使用可滚动的命令运行弹窗，支持运行中取消和完成后回看输出。
- 主界面按 `l` 打开最近日志全屏界面。
- 状态列表按 `z` 打开当前条目的操作菜单，按 `Z` 打开勾选条目或当前目录的操作菜单。
- 提供应用本地 Shelf，可以为勾选的已版本控制文本修改保存多个 Checkpoint、保存后清理工作区，并恢复任意版本。
- 日志界面直接按仓库 URL 读取最近日志，不依赖工作副本先 `svn update`。
- CLI 支持直接打开 status 或 log 初始界面，方便 ranger 等外部工具调用。
- 日志界面支持查看 revision 列表、提交说明、变更路径列表，以及单文件历史 diff 预览。
- 日志列表中的 revision 直接显示数字，不添加 `r` 前缀。
- 日志界面支持在当前日志行右侧弹出操作菜单，并复制 revision / author / message 到剪贴板。
- SVN 状态读取使用异步子进程，避免阻塞 TUI 主循环。
- 预览使用 debounce，停止移动 200ms 后才加载。
- 预览使用单后台任务、可取消索引和虚拟滚动。
- 大文件先显示前缀内容；中等文件会后台补全索引，超大文件跳过全量索引。
- 列表列宽按终端 cell 宽度计算，中文路径和中文扩展名不会破坏后续列对齐。

## Shortcuts

底部 Footer 由 Textual 根据当前界面可用的 bindings 自动渲染。App 只保留真正全局的快捷键；Status 和 Log 界面分别声明自己的界面快捷键。

### Global Shortcuts

| Key | Action |
| --- | --- |
| `q` | 退出 |

### Status Shortcuts

| Key | Action |
| --- | --- |
| `?` | 打开帮助弹窗 |
| `j` / `k` | 上下移动状态列表 |
| `Ctrl-f` / `Ctrl-b` | 状态列表翻页 |
| `gg` / `G` | 跳到状态列表顶部 / 底部 |
| `Space` | 勾选 / 取消勾选当前条目 |
| `v` | 进入范围多选模式 |
| `Space` | 在范围多选模式中反选范围内每个条目 |
| `Ctrl-Enter` | 在提交弹窗中确认提交 |
| `Esc` | 退出范围多选模式，或在弹窗中取消 / 关闭 |
| `Enter` / `d` | 打开当前条目的 `nvim -d` |
| `b` | 用只读 `nvim` 打开当前条目的 `svn blame` |
| `l` | 打开最近日志界面 |
| `z` | 打开当前条目的操作菜单 |
| `Z` | 打开勾选条目的操作菜单；没有勾选时显示目录级操作 |
| `/` | 显示并聚焦状态列表下方的搜索栏 |
| `n` / `N` | 跳到下一个 / 上一个搜索匹配 |
| `r` | 刷新 `svn st` |
| `f` | 在 All / Checked / Conflicts / Unversioned 状态筛选之间切换 |
| `Ctrl-e` / `Ctrl-y` | 预览向下 / 向上滚动一行 |
| `Ctrl-d` / `Ctrl-u` | 预览向下 / 向上滚动半页 |
| `Shift-Right` / `Shift-Left` | 预览横向滚动 |

### Status Popup Menu

状态列表按 `z` 后会在当前条目旁打开操作菜单。菜单打开时，菜单快捷键优先于 Status 界面快捷键：

- `l/L   Log`：打开当前条目的日志界面。
- `b/B   Blame`：用只读 `nvim` 打开当前条目的 `svn blame`。
- `d/D   Diff Base`：用 `nvim -d` 对比 `BASE` 与工作副本。
- `h/H   Diff Head`：用 `nvim -d` 对比 `HEAD` 与工作副本。
- `y/Y   Copy`：复制当前条目的完整本地路径。
- `u     Update`：执行 `svn update -- <path>`，完成后刷新状态列表。
- `r     Revert`：执行 `svn revert -- <path>`，完成后刷新状态列表。

按 `Z` 会对勾选条目打开操作菜单。未勾选任何条目时只显示目录级操作；只要勾选了条目，就显示批量操作和目录级操作：

- `u     Update`：批量执行 `svn update -- <paths>`。
- `c     Commit`：打开提交信息弹窗，确认后用命令运行弹窗提交勾选条目。
- `r     Revert`：批量执行 `svn revert -- <paths>`。
- `y/Y   Copy`：复制所有勾选条目的完整本地路径，每行一个。
- `U     Update this Directory`：对当前 Status 目录执行 `svn update -- <directory>`。
- `R     Revert this Directory`：对当前 Status 目录执行 `svn revert -- <directory>`。
- `C     Clean Up this Directory`：打开命令运行弹窗并执行 `svn cleanup -- <directory>`。
- `X     Remove Unversioned...`：确认后打开命令运行弹窗并执行 `svn cleanup --remove-unversioned -- <directory>`。
- `S     Open Shelves`：打开独立 Shelf Manager；该入口本身不会修改工作副本。

菜单内 `j` / `k` 移动，`Enter` 触发当前菜单项，`Esc` 关闭菜单。

## Shelves

Shelf 是 `svn-tui` 管理的本地修改版本容器，不会提交到 SVN 仓库，也不会写入 `.svn`。每个 Shelf 可以包含多个版本；每个版本的 `patch.diff` 是用于预览、导出和恢复文本修改的载体，Patch 本身不是独立的 Shelf。

使用流程：

1. 在 Status 界面用 `Space` 勾选一个或多个 `M` 状态的普通文本文件。
2. 按 `Z` 打开批量菜单，再按 `S` 进入 Shelf Manager。
3. 按 `n` 创建 Shelf。名称可以留空，默认生成 `shelf-YYYYMMDD-HHMMSS`；不支持重命名。
4. 后续可对当前 Shelf 保存 Checkpoint、Shelve 勾选修改，或恢复任意历史版本。

Shelf Manager 快捷键：

| Key | Action |
| --- | --- |
| `Ctrl-l` | 返回 Status |
| `Tab` | 在 Shelves 和 Versions 列表之间切换 |
| `n` | 新建 Shelf 并保存第一个 Checkpoint |
| `c` | 向当前 Shelf 保存 Checkpoint，工作区不变 |
| `s` | 保存新版本并在确认后还原勾选路径 |
| `u` | 恢复当前选中的 Shelf Version |
| `e` | 导出当前版本的 `.diff` 文件 |
| `d` | 确认后删除当前版本 |
| `D` | 确认后删除整个 Shelf |
| `o` | 在系统文件管理器中打开 Shelf 目录 |
| `y` | 复制当前 Patch 或 Shelf 路径 |
| `r` | 刷新 Shelf 列表 |

默认存储位置由操作系统的应用数据目录决定，例如 macOS 为 `~/Library/Application Support/svn-tui/shelves/`，Linux 通常为 `~/.local/share/svn-tui/shelves/`，Windows 为 `%LOCALAPPDATA%\svn-tui\shelves\`。Shelf 按 working copy 根路径、仓库 UUID、仓库 URL 和目标相对路径生成的 fingerprint 隔离。

当前第一版只接受已纳入 SVN、状态为 `M` 的普通文本文件。未版本文件、二进制文件、冲突、删除、移动和复制等复杂树变化会在保存前被拒绝，不会修改工作副本。`Shelve Selected` 先持久化 Patch 再执行 revert；`Unshelve` 只处理版本记录的路径，覆盖这些路径上的现有修改前会要求确认。

### SVN Command Dialog

提交和目录级 cleanup 操作会打开 SVN 命令运行弹窗。弹窗上方显示将要执行的命令，下方滚动显示 stdout/stderr 合并后的实时输出。运行中按 `Esc` 会先进入取消确认；命令结束或取消后，按 `Esc` 关闭弹窗。关闭后状态列表会刷新，完整输出也会同步到底部 Output 面板。

## Log View

日志界面为全屏三栏布局：

- 左上：最近日志列表
- 中左：当前日志的完整 message
- 左下：当前日志的变更路径列表
- 右侧：当前路径的历史 diff 预览

进入日志界面后会先立即切屏，再异步加载日志内容。

### Log Shortcuts

| Key | Action |
| --- | --- |
| `Ctrl-l` | 返回主界面 |
| `Tab` | 在左上日志列表和左下变更路径列表之间切换焦点 |
| `j` / `k` | 在当前聚焦列表中上下移动 |
| `Ctrl-f` / `Ctrl-b` | 当前聚焦列表翻页 |
| `/` | 显示并聚焦当前列表下方的搜索栏 |
| `n` / `N` | 跳到下一个 / 上一个搜索匹配 |
| `p` | 在日志列表当前项旁打开操作浮窗 |
| `L` | 在浮窗的 `copy >` 项上进入右侧子菜单 |
| `Enter` | 触发当前浮窗项；在 copy 子菜单中复制字段 |
| `Esc` | 关闭浮窗；若当前在 copy 子菜单，则先只关闭子菜单 |
| `Ctrl-e` / `Ctrl-y` | diff 预览向下 / 向上滚动一行 |
| `Ctrl-d` / `Ctrl-u` | diff 预览向下 / 向上滚动半页 |
| `Shift-Right` / `Shift-Left` | diff 预览横向滚动 |

### Log Popup Menu

日志列表按 `p` 后会在当前日志行右侧弹出操作菜单：

- `copy >`

其中：

- 操作菜单会显示在当前日志行右侧；`copy >` 子菜单会显示在操作菜单右侧。
- 在 `copy >` 上按 `L` 或 `Enter` 进入子菜单。
- `copy >` 可进一步复制：
  - `revision`
  - `author`
  - `message`

## Search

Status 和 Log 界面的搜索栏嵌在列表下方，不使用弹窗。

- 按 `/` 显示并聚焦当前列表的搜索栏。
- 输入搜索词后按 `Enter` 跳到下一个匹配。
- 当前聚焦列表会在底部显示浅色提示：`Searching: / to search`。
- 搜索词非空时，底部会显示 `Searching: query [current/total] Jump by n/N`。
- `Jump by n/N` 用加粗样式提示后续跳转方式。
- `n` / `N` 只按当前聚焦列表的搜索词继续向下 / 向上跳转。

Status 界面按 `f` 可以在 All、Checked、Conflicts、Unversioned 之间切换筛选。筛选只影响当前列表展示，已勾选路径会保留；详情栏会显示当前筛选和可见条目数量。

## Preview

预览区不直接嵌入 Neovim。Textual 和 Neovim 都是终端 UI，直接嵌套会竞争同一个 TTY。

当前做法：

- 版本控制文件优先显示 `svn diff -- <path>` 的 inline diff。
- Textual 自己渲染只读预览。
- 小于等于 1 MiB 的文件会一次建立完整行 offset 索引。
- 1 MiB 到 2 MiB 的文件会先索引前 1200 行，再后台继续补全索引。
- 超过 2 MiB 的文件只显示前缀预览并跳过全量索引。
- 可见行通过 Rich `Syntax` 按需渲染。
- 已渲染行使用 LRU 缓存，避免滚动大文件时缓存无限增长。

交互式 diff 仍然通过暂停 Textual 并启动真实 Neovim：

```bash
nvim -d base-file working-file
```

## Notes

- 提交命令使用参数数组执行，带空格的文件路径会作为单独路径参数传递。
- 对未版本控制或无法取得 BASE 的文件，会直接使用 `nvim <file>` 打开。
- 二进制文件不会预览。
- 超长行会截断显示。
- 日志变更路径列表中的 `Type` 使用 `F` / `D` 区分文件和目录。
- 终端字体或环境如果对 East Asian Width 处理异常，中文列宽仍可能受终端自身渲染影响；应用侧使用 Rich cell 宽度计算做对齐。

## Development

常用验证命令：

```bash
python3 -m compileall main.py svn_tui tools tests
svn-tui --help
```

完整开发说明见 [开发与验证指南](docs/development.md)。
