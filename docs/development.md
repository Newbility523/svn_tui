# 开发与验证指南

本文档记录本项目的本地开发、验证和提交流程。

## 环境准备

依赖：

- Python 3.13+
- SVN 命令行工具
- Neovim

安装 Python 依赖和 `svn-tui` 命令入口：

```bash
python3 -m pip install -r requirements.txt
```

如果使用虚拟环境：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

## 本地运行

运行当前目录：

```bash
svn-tui
```

运行指定 SVN 工作副本：

```bash
svn-tui /path/to/svn/working-copy
```

显式选择初始界面：

```bash
svn-tui status /path/to/item
svn-tui log /path/to/item
svn-tui --screen log /path/to/item
```

也可以使用包入口或源码入口：

```bash
python3 -m svn_tui status /path/to/item
python3 main.py status /path/to/item
```

只检查 CLI 入口：

```bash
svn-tui --help
```

## 验证命令

提交前至少运行：

```bash
python3 -m unittest discover
python3 -m compileall main.py svn_tui tools tests
svn-tui --help
```

如果使用项目虚拟环境：

```bash
.venv/bin/python -m unittest discover
.venv/bin/python -m compileall main.py svn_tui tools tests
.venv/bin/svn-tui --help
```

## Ranger / tmux 联动验证

普通 ranger 映射会在当前终端启动外部 TUI，退出 `svn-tui` 后应自然回到 ranger。tmux 环境下可以使用 `tmux popup` 做临时浮窗。

建议在安装了 ranger 的类 Unix 环境中按以下方式验收：

```bash
ranger /path/to/svn/working-copy
```

在 ranger 中选中文件或目录后，分别触发 README 中的 status / log 映射，确认能进入目标界面；在 `svn-tui` 中按 `q` 退出后，确认终端回到 ranger 且可继续移动光标。tmux popup 映射还需要确认 popup 关闭后焦点回到原 ranger pane。

## SVN Fixture 体验测试

`tools/svn_fixture.py` 可以创建本地 SVN 仓库、两份 working copy 和一组可切换工作状态。默认目录是 `.dev/svn-fixture/`，可随时删除或通过脚本重建。

初始化或恢复到最初干净环境：

```bash
python3 tools/svn_fixture.py init
python3 tools/svn_fixture.py reset
```

列出可用状态并切换：

```bash
python3 tools/svn_fixture.py list
python3 tools/svn_fixture.py state mixed
python3 tools/svn_fixture.py state conflict
python3 tools/svn_fixture.py state large-preview
```

直接打开 `svn-tui`：

```bash
python3 tools/svn_fixture.py open status
python3 tools/svn_fixture.py open log
```

状态说明：

- `clean` / `log-rich`：干净 working copy，仓库里有多条提交记录用于日志界面。
- `commit-ready`：少量修改、添加和删除，适合测试提交弹窗和勾选流程。
- `mixed`：包含 modified、added、copied、deleted、missing、unversioned 和 ignore property 变更。
- `large-preview`：包含大文件、超长行、二进制文件和 versioned diff 预览样本。
- `conflict`：通过第二份 working copy 制造真实 SVN 文本冲突。

涉及中文路径、列宽或截断逻辑时，建议额外做一个 smoke test：

```bash
.venv/bin/python - <<'PY'
from rich.cells import cell_len
from svn_tui.ui.formatters import fit_path_label

for width in range(1, 50):
    label = fit_path_label("目录/中文文件.py", width, False, 0)
    assert cell_len(label) == width, (width, repr(label), cell_len(label))

print("unicode width ok")
PY
```

## 代码组织规则

新增代码优先遵循现有分层：

- CLI 和启动逻辑放到 `svn_tui/cli.py`、`svn_tui/app.py`。
- 全局配置放到 `svn_tui/config.py`。
- 业务数据结构放到 `svn_tui/models.py`。
- SVN 命令、文件读取、预览索引等工具逻辑放到 `svn_tui/services/`。
- Textual Screen 放到 `svn_tui/ui/screens/`。
- 可复用 UI 组件放到 `svn_tui/ui/widgets.py`。
- 展示文本、列宽、样式名、路径截断放到 `svn_tui/ui/formatters.py`。
- Textual CSS 放到 `svn_tui/ui/styles.py`。
- 通用小工具放到 `svn_tui/utils/`。

Screen 可以依赖 services，services 不应依赖 Screen 或 Widget。这样可以避免新增界面时把工具层和界面层重新耦合在一起。

## 新增界面流程

1. 在 `svn_tui/ui/screens/` 新建 Screen。
2. 在 `svn_tui/services/` 添加该界面需要的 SVN 或文件操作。
3. 使用 `models.py` 中的数据结构承载业务数据。
4. 复用 `widgets.py` 中的列表行、预览视图或菜单组件。
5. 需要固定列展示时，使用 `formatters.py` 中的 cell 宽度工具。
6. 在 `app.py` 或已有 Screen 中添加进入新界面的 action。
7. 更新 README 和 `docs/architecture.md`。

## 提交前检查

提交前建议确认：

```bash
git status --short
git diff --stat
python3 -m compileall main.py svn_tui tools tests
svn-tui --help
```

如果当前机器没有 `python` 命令，使用 `python3` 或 `.venv/bin/python`。

## 已知限制

- 状态菜单的目录级更新 / 还原操作直接作用于当前 Status 目录，使用前应确认工作副本范围。
- 交互式 diff 和 blame 依赖外部 Neovim。
- 二进制文件不会做文本预览。
- 超大文件只做前缀预览，避免 TUI 卡顿。
- 宽字符对齐依赖终端自身对 East Asian Width 的渲染；应用侧已按 Rich cell 宽度计算。
