# svn-tui

一个基于 [Textual](https://textual.textualize.io/) 的 SVN TUI 客户端原型。

当前目标是快速查看指定工作副本路径下的 `svn st` 结果，逐个检查文件变更，并用 `nvim -d` 打开 diff。提交功能暂未实现。

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
- 用 `nvim -d` 检查变更。
- 右侧提供文件预览。
- 预览使用 debounce，停止移动 200ms 后才加载。
- 预览使用虚拟滚动：滚动条按完整文件高度计算，但只渲染可见行。

## Shortcuts

| Key | Action |
| --- | --- |
| `j` / `k` | 上下移动状态列表 |
| `Ctrl-f` / `Ctrl-b` | 状态列表翻页 |
| `gg` / `G` | 跳到状态列表顶部 / 底部 |
| `Space` | 勾选 / 取消勾选当前条目 |
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
- 预览先建立文件行 offset 索引。
- 右侧滚动条使用完整文件行数。
- 可见行通过 Rich `Syntax` 按需渲染。

交互式 diff 仍然通过暂停 Textual 并启动真实 Neovim：

```bash
nvim -d base-file working-file
```

## Notes

- 提交功能暂未实现。
- 对未版本控制或无法取得 BASE 的文件，会直接使用 `nvim <file>` 打开。
- 二进制文件不会预览。
- 超长行会截断显示。
