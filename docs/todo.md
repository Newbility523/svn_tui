# TODO

## 工程完善清单

### 高优先级

- [x] 为 `svn revert` 增加确认弹窗，覆盖单文件、批量文件和目录级操作。
- [x] 让状态菜单按 SVN 状态动态展示可用操作，例如 `svn add`、ignore、resolve 等。
  - [x] 隐藏单条目菜单中明显不可用的操作。
  - [x] 为未版本控制文件增加 `svn add` 操作。
  - [x] 为冲突文件增加 resolve 入口。
  - [x] 为 ignore 规则增加安全入口。
- [x] 处理日志界面的回退占位功能：隐藏未实现项，或实现带确认的回退流程。

### 工程质量

- [x] 增加 `pyproject.toml` 和 `svn-tui` console script 入口。
- [x] 增加 CI，运行 `unittest`、`compileall` 和 CLI help 验证。
- [x] 扩展服务层测试，覆盖状态解析、日志 XML 解析、预览边界和 SVN 命令失败。

### 体验增强

- [x] 增加状态界面的 inline diff 预览。
- [x] 增加状态筛选模式，例如只看已勾选、只看冲突、只看未版本控制文件。
- [x] 增加固定输出面板，展示 `svn update`、`svn commit`、`svn revert` 的完整输出。
- [x] 增加 SVN 体验测试 fixture 工具，支持一键初始化、状态切换和重置。
- [ ] 支持用户配置文件，外置 SVN/Neovim 路径、日志数量、预览阈值、主题和快捷键。

## Ranger 联动模式

目标：支持从 ranger 选中文件或目录后启动 `svn-tui` 的 status 或 log 界面，处理完成后退出并自然回到 ranger。

### 交互模式

推荐模式：

1. 用户在 ranger 中选中文件或目录。
2. ranger 快捷键调用 `svn-tui` 外部命令，并把当前路径传入。
3. `svn-tui` 占用当前终端全屏显示指定界面。
4. 用户完成查看、提交、diff 或 log 操作。
5. 用户退出 `svn-tui` 后返回 ranger。

可选模式：

- 在 tmux 环境下通过 `tmux popup` 启动 `svn-tui`，视觉上表现为从 ranger 弹出 SVN 面板。

### 待办拆分

- [x] CLI 支持显式选择初始界面。
  - 例：`python3 main.py status /path/to/item`
  - 例：`python3 main.py log /path/to/item`
  - 或：`python3 main.py --screen status /path/to/item`
- [x] `SvnTui` 支持接收初始 Screen 类型，而不是固定进入 `StatusScreen`。
- [x] `LogScreen` 支持从 CLI 直接作为首屏打开。
- [x] 增加一个稳定的命令入口名称，方便 ranger 配置调用。
  - 当前支持安装后的 `svn-tui` 命令，源码调试时也可用 `python3 -m svn_tui`。
- [x] 编写 ranger 集成示例配置。
  - status：把 ranger 当前选中文件或目录传给状态界面。
  - log：把 ranger 当前选中文件或目录传给日志界面。
- [x] 编写 tmux popup 集成示例配置。
- [x] 文档说明 Textual 不能真正嵌入 ranger，只能通过外部 TUI 方式联动。
- [ ] 验证从 ranger 进入 `svn-tui` 后退出能正常返回 ranger。
  - 当前 Windows 验证环境未安装 `ranger` / `tmux`，已补充手动验收步骤，待在可用终端环境中实际确认。

### 设计约束

- 不在 ranger 进程内嵌入 Textual。
- ranger、Textual、Neovim 都会控制同一个 TTY，必须避免多个全屏 TUI 同时抢占终端。
- `svn-tui` 退出码应保持正常，便于 ranger 判断命令是否成功结束。
- ranger 传入文件时，应以该文件作为目标；传入目录时，应以目录作为目标。

### 验收标准

- 从 ranger 选中文件后可以打开 status 界面。
- 从 ranger 选中目录后可以打开 status 界面。
- 从 ranger 选中文件或目录后可以直接打开 log 界面。
- 在 `svn-tui` 中按退出键后返回 ranger。
- status/log 界面的现有快捷键和预览行为不受影响。
- 文档包含普通终端调用、ranger 配置示例和 tmux popup 配置示例。
