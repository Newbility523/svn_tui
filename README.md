# svn-tui

一个基于 [Textual](https://textual.textualize.io/) 的 SVN TUI 客户端原型，用于在终端里查看 SVN 工作副本状态、检查变更、提交文件，并浏览仓库最近日志。

当前目标是快速查看指定工作副本路径下的 `svn st` 结果，逐个检查文件变更，用 `nvim -d` 打开 diff，并提交勾选的文件；同时可以直接查看仓库最近日志与对应 diff。项目已拆分为可扩展的包结构，便于后续增加更多独立界面。

## Requirements

- Python 3.13+
- SVN 命令行工具
- Neovim

安装 Python 依赖：

```bash
python3 -m pip install -r requirements.txt
```

## Quick Start

```bash
python3 main.py /path/to/svn/working-copy
```

如果不传路径，默认使用当前目录：

```bash
python3 main.py
```

列表中的路径相对传入的打开路径显示。例如打开 `a/b/c` 时，文件 `a/b/c/d.py` 会显示为 `d.py`。

## Documentation

- [架构与业务链路](docs/architecture.md)
- [开发与验证指南](docs/development.md)
- [TODO](docs/todo.md)

## Project Structure

项目已按后续多界面扩展拆成包结构：

- `main.py`：兼容入口，只调用包内 CLI。
- `svn_tui/cli.py`：命令行参数解析和启动。
- `svn_tui/app.py`：Textual App 外壳和全局快捷键。
- `svn_tui/config.py`：预览、列表列宽、日志数量、滚动间隔、主题等全局配置。
- `svn_tui/models.py`：SVN 状态、日志、日志路径等业务数据结构。
- `svn_tui/services/`：SVN 命令调用和文件预览索引等工具层，不依赖具体界面。
- `svn_tui/ui/styles.py`：Textual CSS 布局和样式。
- `svn_tui/ui/widgets.py`：可复用 UI 组件和列表行渲染。
- `svn_tui/ui/dialogs.py`：提交信息、帮助等弹窗。
- `svn_tui/ui/screens/`：不同界面 Screen，目前包含状态界面和日志界面。
- `svn_tui/ui/formatters.py`、`svn_tui/ui/search.py`：界面展示格式化和列表搜索逻辑。
- `svn_tui/utils/`：路径、大小格式化等跨层小工具。

新增界面时优先在 `svn_tui/ui/screens/` 添加 Screen，并复用 `services/`、`models.py`、`ui/widgets.py` 和 `ui/formatters.py`。样式只放在 `svn_tui/ui/styles.py`，配置只放在 `svn_tui/config.py`。

## Business Flow

主链路：

1. CLI 解析目标工作副本路径，启动 `SvnTui`。
2. App 进入 `StatusScreen`，通过 `SvnClient.status()` 异步执行 `svn st`。
3. 状态列表将 `SvnStatusEntry` 渲染为可勾选行，右侧按当前行延迟加载只读预览。
4. 用户勾选文件后输入提交说明，`SvnClient.commit()` 执行 `svn commit`，完成后刷新状态。
5. 用户打开 diff / blame 时暂停 Textual，交给真实 `nvim` 处理交互。
6. 用户进入 `LogScreen` 后，`SvnClient.recent_logs()` 读取仓库日志，选中 revision/path 后再异步加载 `svn diff`。

## Features

- 显示 `svn st` 结果。
- 按状态和文件类型给列表项着色。
- 显示文件扩展名和大小。
- 用空格将条目标记进提交列表。
- 输入提交信息后提交勾选的文件。
- 用 `nvim -d` 检查变更。
- 右侧提供文件预览。
- 主界面按 `l` 打开最近日志全屏界面。
- 日志界面直接按仓库 URL 读取最近日志，不依赖工作副本先 `svn update`。
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
| `c` | 打开提交信息弹窗 |
| `Ctrl-Enter` | 在提交弹窗中确认提交 |
| `Esc` | 退出范围多选模式，或在弹窗中取消 / 关闭 |
| `Enter` / `d` | 打开当前条目的 `nvim -d` |
| `b` | 用只读 `nvim` 打开当前条目的 `svn blame` |
| `l` | 打开最近日志界面 |
| `/` | 显示并聚焦状态列表下方的搜索栏 |
| `n` / `N` | 跳到下一个 / 上一个搜索匹配 |
| `r` | 刷新 `svn st` |
| `Ctrl-e` / `Ctrl-y` | 预览向下 / 向上滚动一行 |
| `Ctrl-d` / `Ctrl-u` | 预览向下 / 向上滚动半页 |
| `Shift-Right` / `Shift-Left` | 预览横向滚动 |

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

- `revert to this`
- `revert changes from`
- `copy >`

其中：

- 操作菜单会显示在当前日志行右侧；`copy >` 子菜单会显示在操作菜单右侧。
- `revert to this` 和 `revert changes from` 当前只展示触发提示，尚未真正执行 SVN 回退。
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

## Preview

预览区不直接嵌入 Neovim。Textual 和 Neovim 都是终端 UI，直接嵌套会竞争同一个 TTY。

当前做法：

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
python3 -m compileall main.py svn_tui
python3 main.py --help
```

完整开发说明见 [开发与验证指南](docs/development.md)。
