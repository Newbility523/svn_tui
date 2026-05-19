# 开发与验证指南

本文档记录本项目的本地开发、验证和提交流程。

## 环境准备

依赖：

- Python 3.13+
- SVN 命令行工具
- Neovim

安装 Python 依赖：

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
python3 main.py
```

运行指定 SVN 工作副本：

```bash
python3 main.py /path/to/svn/working-copy
```

只检查 CLI 入口：

```bash
python3 main.py --help
```

## 验证命令

当前项目还没有测试套件，提交前至少运行：

```bash
python3 -m compileall main.py svn_tui
python3 main.py --help
```

如果使用项目虚拟环境：

```bash
.venv/bin/python -m compileall main.py svn_tui
.venv/bin/python main.py --help
```

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
python3 -m compileall main.py svn_tui
python3 main.py --help
```

如果当前机器没有 `python` 命令，使用 `python3` 或 `.venv/bin/python`。

## 已知限制

- 回退相关菜单项目前只展示提示，尚未执行 SVN 回退。
- 交互式 diff 和 blame 依赖外部 Neovim。
- 二进制文件不会做文本预览。
- 超大文件只做前缀预览，避免 TUI 卡顿。
- 宽字符对齐依赖终端自身对 East Asian Width 的渲染；应用侧已按 Rich cell 宽度计算。
