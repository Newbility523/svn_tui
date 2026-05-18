# svn-tui

一个基于 [Textual](https://textual.textualize.io/) 的 SVN TUI 客户端原型。

当前目标是快速查看指定工作副本路径下的 `svn st` 结果，逐个检查文件变更，用 `nvim -d` 打开 diff，并提交勾选的文件。

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
| `r` | 刷新 `svn st` |
| `Ctrl-e` / `Ctrl-y` | 预览向下 / 向上滚动一行 |
| `Ctrl-d` / `Ctrl-u` | 预览向下 / 向上滚动半页 |
| `Shift-Right` / `Shift-Left` | 预览横向滚动 |
| `q` | 退出 |

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
