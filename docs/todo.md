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
- [x] 增加 SVN 命令运行弹窗，用于 commit 和目录级 cleanup，并支持实时输出和取消确认。
- [x] 增加 SVN 体验测试 fixture 工具，支持一键初始化、交互式菜单、状态切换和重置。
- [ ] 支持用户配置文件，外置 SVN/Neovim 路径、日志数量、预览阈值、主题和快捷键。

## 带 Checkpoint 的 Shelves

目标：提供 `svn-tui` 自己管理的本地 shelves，让用户可以把当前 SVN working copy 的本地修改按主题保存为多个版本，并在需要时恢复、导出或清理。该功能不写入 SVN 仓库，也不直接写入 `.svn` 内部目录。

### 产品术语

- `Shelf`：一组本地修改的主题容器，例如 `fix-login-flow`。
- `Save Checkpoint`：保存当前勾选修改为 shelf 的一个新版本，但保留 working copy 当前修改。
- `Shelve Selected`：保存当前勾选修改为 shelf 的一个新版本，然后只还原/清空这些勾选路径。
- `Unshelve Version`：从某个 shelf version 恢复修改到当前 working copy；语义是把该 version 记录的路径恢复成保存时的内容。
- `Patch`：某个 shelf version 的文本 diff 载体，可用于导出或恢复文本修改。

### 设计原则

- 默认按 working copy 隔离 shelves，避免两个 checkout 互相误恢复。
- 不直接写 `.svn`，避免依赖 SVN/TortoiseSVN 内部私有格式。
- 允许识别同仓库同路径的 compatible shelves，但默认不混在当前 working copy 列表里。
- `Save Checkpoint` 和 `Shelve Selected` 都创建版本；区别只在保存后是否清空勾选路径。
- `Shelve Selected` 只处理用户勾选的路径，不隐式处理整个 status 目录。
- `Unshelve Version` 可以选择任意版本，包括由 `Shelve Selected` 创建的版本。
- `Unshelve Version` 只处理该 version 记录的路径；其它本地修改不受影响。
- 初版只支持已版本控制文件的文本修改；未版本文件、二进制文件和复杂树变更进入后续阶段。

### 默认存储方案

默认保存到应用本地数据目录：

```text
%LOCALAPPDATA%\svn-tui\shelves\<wc-fingerprint>\
  <shelf-name>\
    shelf.json
    v001\
      patch.diff
      meta.json
    v002\
      patch.diff
      meta.json
```

默认位置由 `platformdirs` 按系统选择：

```text
macOS:   ~/Library/Application Support/svn-tui/shelves/<wc-fingerprint>/
Linux:   ~/.local/share/svn-tui/shelves/<wc-fingerprint>/
Windows: %LOCALAPPDATA%\svn-tui\shelves\<wc-fingerprint>\
```

`wc-fingerprint` 建议由以下信息生成：

- working copy root 绝对路径。
- SVN repository UUID。
- repository root URL。
- target URL / target relative path。

`meta.json` 至少记录：

- shelf 名称、版本号、版本类型（checkpoint/shelve）。
- 创建时间、用户备注、working copy root。
- repo UUID、repo root URL、target relative path、base revision。
- 保存时包含的路径列表和 SVN 状态摘要。
- patch 文件路径，以及未来扩展的文件副本索引。

### 交互入口

状态界面操作菜单增加 `Open Shelves` 入口。该入口只打开管理界面，不会保存、还原或修改 working copy：

```text
Z / Actions
  Open Shelves
```

进入独立的 `ShelfManagerScreen` 后，建议提供三栏信息：

```text
Shelves
  fix-login-flow        v4   Shelved      5 files   2026-06-10 16:20
  cleanup-before-merge  v2   Checkpoint   2 files   2026-06-09 18:12

Versions
  v4  Shelve       5 files   saved and reverted
  v3  Checkpoint   5 files   kept in working copy
  v2  Checkpoint   4 files
  v1  Checkpoint   3 files
```

核心操作：

- `New Shelf`：名称可选；留空时按本地时间自动生成
  `shelf-YYYYMMDD-HHMMSS`，同一秒重名时追加 `-02`、`-03`；创建后保存第一个版本。
- `Save Checkpoint`：对当前 shelf 保存新版本，工作区不变。
- `Shelve Selected`：对当前 shelf 保存新版本，然后只还原当前勾选路径。
- `Unshelve Version`：选择 shelf version，先还原该 version 记录的路径，再应用该 version 的 patch；不处理 version 之外的其它本地修改。
- `Export Patch`：把选中 version 导出为 `.patch` / `.diff`。
- `Delete Version`：删除单个版本。
- `Delete Shelf`：删除整个 shelf，需二次确认。
- `Open Folder` / `Copy Path`：方便用户定位本地存储。

### 第一阶段范围

- [x] 新增 shelf 存储服务，负责 app data 路径、working copy fingerprint、目录结构和 JSON 元数据读写。
- [x] 新增 `svn diff` patch 生成服务，支持保存当前勾选路径的已版本控制文本修改。
- [x] 新增 `New Shelf` 操作：允许输入名称或留空自动生成名称，并立即保存第一个 checkpoint。
- [x] 新增 `Save Checkpoint` 操作：保存 patch 和 metadata，不修改 working copy。
- [x] 新增 `Shelve Selected` 操作：保存 patch 和 metadata 后，只对当前勾选路径执行安全还原。
- [x] 新增 `Unshelve Version` 操作：选择版本后，只针对该 version 记录的路径执行 revert + apply patch。
- [x] 新增独立 `ShelfManagerScreen`，能列出当前 working copy 的 shelves 和 versions。
- [x] 在状态菜单中增加 `Open Shelves` 入口，该入口只打开管理界面。
- [x] 增加确认弹窗，覆盖 `Shelve Selected` 清空勾选修改、`Unshelve Version` 覆盖当前修改、删除版本/删除 shelf。
- [x] 更新 README 和架构文档，说明 shelves 与 patches 的区别。
- [x] 增加 fixture 状态和测试，覆盖 save checkpoint、shelve selected、unshelve version 的基本链路。

### 后续阶段

- [ ] 支持未版本文件保存：为未版本文件保存副本并在 unshelve 时恢复。
- [ ] 支持二进制文件保存：保存完整副本，而不是只依赖文本 patch。
- [ ] 支持删除、移动、复制等复杂树变更的更完整恢复。
- [ ] 支持显示 compatible shelves：同 repo UUID + target relpath，但来自其它 working copy。
- [ ] 支持从其它 working copy 导入 compatible shelf。
- [ ] 支持清理过期 shelves 或限制保留版本数量。
- [ ] 支持用户配置 shelves 存储位置。

### 风险与约束

- `svn diff` 不能完整表达所有工作区状态，初版需要明确只保证文本 diff 主路径。
- `Shelve Selected` 的清空动作必须非常谨慎，只还原本次保存涉及的勾选路径。
- `Unshelve Version` 如果发现该 version 记录的路径当前已有本地修改，必须提示这些路径上的当前修改会被丢弃；用户确认后再执行，不确认则不做任何修改。
- `Unshelve Version` 不检查也不处理该 version 路径之外的其它本地修改。
- patch 应用失败时需要保留错误输出，并指引用户手动处理。
- compatible shelves 不能默认自动混用，否则两个 checkout 之间容易误恢复。

### 待确认

- [x] 初版只支持“已版本控制文本修改”，把未版本文件和二进制文件放到后续阶段。
- [x] `Shelve Selected` 清空工作区时，只还原勾选路径，不处理整个当前 status 目录。
- [x] 状态菜单入口命名为 `Open Shelves`，只负责打开管理界面，不直接保存或还原。
- [x] `Shelf Manager` 做成独立 Screen，类似 `LogScreen` 的完整页面，而不是嵌在 log 或弹窗里。
- [x] 新建 shelf 不强制输入名称；留空时自动生成
  `shelf-YYYYMMDD-HHMMSS`，重名时追加数字后缀；不支持重命名。
- [x] `Unshelve Version` 以选中 version 为准；如果 version 路径当前已有本地修改，确认后丢弃这些路径上的当前修改并应用 version，不碰其它路径。

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
