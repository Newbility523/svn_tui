# TODO

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

- [ ] CLI 支持显式选择初始界面。
  - 例：`python3 main.py status /path/to/item`
  - 例：`python3 main.py log /path/to/item`
  - 或：`python3 main.py --screen status /path/to/item`
- [ ] `SvnTui` 支持接收初始 Screen 类型，而不是固定进入 `StatusScreen`。
- [ ] `LogScreen` 支持从 CLI 直接作为首屏打开。
- [ ] 增加一个稳定的命令入口名称，方便 ranger 配置调用。
  - 后续可以考虑 `python -m svn_tui` 或 console script。
- [ ] 编写 ranger 集成示例配置。
  - status：把 ranger 当前选中文件或目录传给状态界面。
  - log：把 ranger 当前选中文件或目录传给日志界面。
- [ ] 编写 tmux popup 集成示例配置。
- [ ] 文档说明 Textual 不能真正嵌入 ranger，只能通过外部 TUI 或 tmux popup 方式联动。
- [ ] 验证从 ranger 进入 `svn-tui` 后退出能正常返回 ranger。

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
- 文档包含普通终端调用、ranger 配置示例、tmux popup 配置示例。
