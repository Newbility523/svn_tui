# 架构与业务链路

`svn-tui` 是一个 Textual 应用。当前业务分为两个主界面：工作副本状态界面和仓库日志界面。重构后的目标是让界面、工具、样式、配置各自独立，后续新增界面时不需要继续扩张入口脚本。

## 分层结构

```text
main.py
  -> svn_tui/cli.py
     -> svn_tui/app.py
        -> svn_tui/ui/screens/*
           -> svn_tui/ui/widgets.py
           -> svn_tui/ui/formatters.py
           -> svn_tui/services/*
              -> svn_tui/models.py
              -> svn_tui/config.py
```

各层职责：

- `main.py`：兼容入口，只调用 `svn_tui.cli.main()`。
- `pyproject.toml`：项目打包配置，提供安装后的 `svn-tui` 命令入口。
- `tools/svn_fixture.py`：应用外的本地体验测试工具，用于生成 SVN fixture 仓库和工作副本状态。
- `svn_tui/__main__.py`：包入口，支持 `python3 -m svn_tui`。
- `svn_tui/cli.py`：解析目标路径和初始界面参数，创建并运行 App。
- `svn_tui/app.py`：Textual App 外壳，只保留全局行为、全局快捷键和首屏选择。
- `svn_tui/config.py`：集中管理预览阈值、列宽、日志条数、滚动间隔和主题配置。
- `svn_tui/models.py`：保存 SVN 状态、日志、日志路径等业务数据结构。
- `svn_tui/services/`：工具层，负责 SVN 命令、diff/blame、日志读取、文件预览索引。
- `svn_tui/ui/screens/`：界面层，每个 Screen 对应一个完整界面。
- `svn_tui/ui/widgets.py`：可复用组件，包括状态行、日志行、路径行、预览视图、弹出菜单项。
- `svn_tui/ui/formatters.py`：界面文本格式化、列宽计算、路径截断、中文 cell 宽度处理。
- `svn_tui/ui/styles.py`：Textual CSS，集中维护布局和样式。
- `svn_tui/ui/search.py`：列表搜索和搜索文本提取逻辑。
- `svn_tui/utils/`：跨层小工具，当前包含路径和大小格式化。

## 状态界面链路

1. CLI 接收目标路径和初始界面，启动 `SvnTui`。
2. App 首屏进入 `StatusScreen`。
3. 如果 status 目标是文件，App 会先把目标改为该文件的父目录。
4. `StatusScreen` 创建 `SvnClient`，异步调用 `SvnClient.status()`。
5. `SvnClient.status()` 先确认工作副本根目录，再执行 `svn st <target>`。
6. `parse_svn_status_line()` 把命令输出解析为 `SvnStatusEntry`。
7. `StatusRow` 负责将 `SvnStatusEntry` 渲染为可勾选列表行。
8. 当前行变化后，右侧 `PreviewView` 延迟 200ms 加载预览，避免快速移动时频繁读文件。
9. 预览服务按文件大小决定完整索引、后台补全索引或只显示前缀内容。
10. 用户勾选条目后按 `Z` 打开批量菜单，再通过 `Commit` 输入提交说明，`SvnClient.commit()` 执行 `svn commit -m <message> -- <paths>`。
11. 提交完成后重新加载状态列表。

## Diff 和 Blame 链路

交互式 diff 和 blame 不嵌入 Textual。Textual 与 Neovim 都会控制同一个终端，直接嵌套会互相抢 TTY。

- `Enter` / `d`：暂停 Textual，执行真实 `nvim -d base-file working-file`。
- 状态菜单的 `Diff Head`：暂停 Textual，执行 `nvim -d head-file working-file`，其中 `head-file` 来自 `svn cat -r HEAD`。
- 未版本控制或无法读取 BASE 的文件：退化为 `nvim <file>`。
- `b`：执行 `svn blame`，把结果写入临时文件，再用只读 `nvim -R` 打开。

## 状态操作菜单链路

1. 状态界面按 `z` 打开当前高亮条目的操作菜单。
2. 状态界面按 `Z` 打开勾选条目的操作菜单；未勾选任何条目时显示目录级操作，勾选一个条目时等同于 `z`，勾选多个条目时显示批量操作和目录级操作。
3. 菜单打开时，菜单快捷键优先触发菜单项，不触发底层 Status 快捷键。
4. 单条目 `Log` 为目标条目创建新的 `SvnClient` 并进入 `LogScreen`。
5. 单条目 `Blame`、`Diff Base`、`Diff Head` 暂停 Textual 后交给 Neovim。
6. `Copy` 复制目标条目的完整本地路径；批量复制时每行一个路径。
7. 小写 `u/r` 针对选中条目执行 `svn update` / `svn revert`，大写 `U/R` 在批量菜单底部针对当前 Status 目录执行目录级操作。
8. `Commit` 只出现在批量菜单中，打开提交信息弹窗并提交勾选条目。
9. 更新和还原操作完成后刷新状态列表。

## 日志界面链路

1. 状态界面按 `l` 进入 `LogScreen`，或 CLI 直接以 `log` 作为首屏进入。
2. `LogScreen` 立即切屏，并显示加载状态。
3. `SvnClient.ensure_repository_metadata()` 读取仓库根 URL 和目标 URL。
4. `SvnClient.recent_logs()` 执行 `svn log --xml -v -l <limit> <target-url>`。
5. `parse_svn_log_xml()` 解析为 `SvnLogEntry` 和 `SvnLogPathEntry`。
6. 左侧显示 revision、author、date、summary；中部显示完整 message；下方显示 changed paths。
7. 选择 changed path 后，`SvnClient.diff_for_log_path()` 执行 `svn diff -c <revision> <url>`。
8. 右侧 `TextPreviewView` 渲染历史 diff。

## 多界面扩展方式

新增一个界面时建议遵循以下规则：

1. 在 `svn_tui/ui/screens/` 新建 Screen，例如 `branch.py`。
2. 只在 Screen 中编排界面状态和用户交互，不直接写复杂 SVN 命令。
3. SVN 或文件操作放到 `svn_tui/services/`。
4. 新的业务数据结构放到 `svn_tui/models.py`，或在模型膨胀后拆成 `models/` 包。
5. 可复用列表行、预览、菜单等组件放到 `svn_tui/ui/widgets.py` 或拆到 `svn_tui/ui/widgets/`。
6. 文本列宽、状态颜色、路径截断等展示规则放到 `svn_tui/ui/formatters.py`。
7. 新增配置只放到 `svn_tui/config.py`。
8. 样式只放到 `svn_tui/ui/styles.py`，不要把大段 CSS 放回 Screen 类里。
9. 在 `README.md` 或本文件补充入口、快捷键和业务链路。

## 宽字符对齐

状态列表和日志路径列表按终端 cell 宽度对齐，不按 Python 字符数对齐。中文、日文、韩文等宽字符通常占 2 个 cell，直接使用 `len()` 会导致后续列错位。

当前处理集中在 `svn_tui/ui/formatters.py`：

- `display_width()`：封装 Rich `cell_len()`。
- `fit_cell()`：按 cell 宽度补齐或截断。
- `fit_path_label()`：按 cell 宽度处理路径列。
- `scroll_path_label()`：长路径滚动时也按 cell 宽度计算周期。

后续新增表格或固定列时，应复用这些工具。
