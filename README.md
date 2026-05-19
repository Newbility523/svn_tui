# svn-tui

一个基于 [Textual](https://textual.textualize.io/) 的 SVN TUI 客户端原型。

当前目标是快速查看指定工作副本路径下的 `svn st` 结果，逐个检查文件变更，用 `nvim -d` 打开 diff，并提交勾选的文件；同时可以直接查看仓库最近日志与对应 diff。

## Requirements

- Python 3.13+
- SVN 命令行工具
- Neovim

安装 Python 依赖：

```bash
python -m pip install -r requirements.txt
```

## Usage

```bash
python main.py /path/to/svn/working-copy
```

如果不传路径，默认使用当前目录：

```bash
python main.py
```

列表中的路径相对传入的打开路径显示。例如打开 `a/b/c` 时，文件 `a/b/c/d.py` 会显示为 `d.py`。

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
- 日志界面支持在当前日志行右侧弹出操作菜单，并复制 revision / author / message 到剪贴板。
- SVN 状态读取使用异步子进程，避免阻塞 TUI 主循环。
- 预览使用 debounce，停止移动 200ms 后才加载。
- 预览使用单后台任务、可取消索引和虚拟滚动。
- 大文件先显示前缀内容；中等文件会后台补全索引，超大文件跳过全量索引。

## Shortcuts

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
| `r` | 刷新 `svn st` |
| `Ctrl-e` / `Ctrl-y` | 预览向下 / 向上滚动一行 |
| `Ctrl-d` / `Ctrl-u` | 预览向下 / 向上滚动半页 |
| `Shift-Right` / `Shift-Left` | 预览横向滚动 |
| `q` | 退出 |

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
