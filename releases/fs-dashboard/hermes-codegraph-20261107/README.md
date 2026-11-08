# Hermes CodeGraph 接入与 187 源码盘点

2026-11-07。用户授权安装、183 隔离验证、Hermes 开发环境接入及 187 首轮只读分类；未授权本轮搬迁、删除生产源码。执行规则沿用 `docs/ops/HOTFIX.md`。

## 运行方式

固定使用 `colbymchenry/codegraph` **v1.6.2** 的 Linux x64 发行包，SHA-256 为 `ef0af416092128fb1ccc723786000b7edf4a6971fe604acd08bf966e4f37b828`。在 183 的独立目录、1 CPU/2 GiB 额度下验证版本、真实 MCP 查询及文件创建/修改/删除自动同步；既有 RPG 服务状态与 MainPID 保持。

当前 Hermes 没有可选 MCP SDK，因此通过已有原生插件机制接入官方 CLI，不替换或升级现有 Python 依赖。`fs_codegraph` 提供：

- `codegraph_projects`：列出已批准的分析工作区、来源与采集时间，以及首轮盘点报告路径。
- `codegraph_explore`：先自动同步本地索引，再查询源码与调用关系；同步失败即返回错误，不提供旧图冒充当前结果。

查询限定在 `/profile/cache/fs-codegraph/sources/` 与已有本地开发检出 `/profile/cache/workspaces/FS-Workbench`。不接受调用者提供命令、URL或生产目录路径；使用参数数组和 `--` 分隔查询，不经 shell。生产目录只由盘点程序读取，查询使用分析副本。新工具不会索引数据库、日志、凭据或运行配置。

初始工作区为 `hermes-runtime`、`fc-coins`、`hermes-desktop`、`fs-data` 和 `fs-ui`。前四项是带时间及逐文件哈希的生产代码快照；最后一项是服务器已有开发检出的共享 UI 代码。服务器没有 Git CLI，报告读取 HEAD/refs 元数据并对比检出文件内容，明确不能把内容相同当成已提交或已部署。

## 安装与验收

1. 从官方 GitHub 发行版下载 Linux x64 包和校验表，在 183 验证；沿已有连接器把同一包传入 Hermes 持久 profile 的 `tools/codegraph/1.6.2/`。187 宿主 Python 缺少 HTTPS 支持，安装器不要求升级宿主库。
2. `deploy.py` 接收本目录插件及 `inventory_187.py` 的 JSON 载荷；校验包后在 Hermes 容器运行。源码与工具模板入库，实际载荷、配置备份、索引和业务盘点只保留在私有运行目录。
3. `inventory_187.py` 建立服务/定时器、容器与源码目录关联，并对选定源码做哈希比对。`fs_codegraph` 的源码快照排除配置、可能的硬编码凭据、大型压缩构建文件及运行数据；覆盖范围与遗漏写入报告。
4. 插件安装到持久 profile 的 `plugins/fs-codegraph/`。经 Hermes 的 `dashboard_set_agent_plugin_enabled` 原生准入和热加载启用，保留原有工具与配置。原生 Python 工具按 Hermes 机制在新会话中可用，旧会话不冒称已获得新工具。
5. 原生 `PluginManager` 和 `ToolRegistry.dispatch` 实际调用两个新工具，核验源码返回和路径逃逸拒绝；再核对生产源码哈希、容器运行状态和原有 FS 工具仍在。无需触发付费模型请求。

安装回执：`/profile/cache/fs-codegraph/install-20261107.json`。验收回执：同目录 `acceptance-20261107.json`。源码分类：`inventory-187.json`。这些文件不入 Git。

### 首轮结果

安装与原生工具调用已验证。保留的选定源码为 313 个生产源码文件及 27 个共享 UI 文件；CodeGraph 按自身支持格式与默认规则实际索引 312 个文件、7,542 个符号和 23,957 条关系，五个索引均没有读取/解析失败。未进入代码图的文件仍可按原文件读取。313 个生产源码文件写后独立哈希核对无变化。Desktop 与 FC 容器持续运行，没有重启或业务文件搬删。

盘点包含 67 个服务/定时器、212 个 `/opt` 目录；28 个目录存在服务或运行容器的直接引用。服务列表同时保留 ActiveState、SubState 和 timer 关联，其余目录标作 `unverified_keep`，不是废弃清单。静态图缺边、文件日期旧或未发现直接引用，都不足以授权清理。

## 回退与恢复

- 原始 profile 配置备份为分析目录的 `config.before-20261107.yaml`，仅保留在服务器且模式为 0600。不得把备份或令牌导出到仓库。
- 停用时沿 Hermes 原生 `dashboard_set_agent_plugin_enabled('fs-codegraph', enabled=False)`，只撤销此插件与工具集，不用旧整份配置覆盖后续改动。已打开会话按 Hermes 原有停用语义收敛，新会话不再启用此工具；若要求立即撤销旧会话中的 Python handler，另按当前任务状态安排受控操作。
- 只有确认没有活跃 CodeGraph 进程后，才处理其分析缓存；生产源码不在清理范围。保留安装、准入和验收回执。
- 安装若中断，先读取原安装回执和当前配置。仅下载阶段、且无配置备份及插件目录时可补齐包后继续；其他阶段须核对原状态，不能盲重放。
- 快照不是完整部署备份。生产源码变化后须重新核对来源、刷新带版本的分析副本，不能把旧快照当成实时生产版本或直接用它回滚运行系统。

## 验证命令

Linux 执行 `python -m unittest test_plugin test_inventory`；11 个用例覆盖参数边界、路径逃逸、shell 插值、同步失败、快照凭据排除及旧 systemd/无 Git 兼容。
仓库 `pr-fast` 的 `hermes-codegraph` 分组运行相同用例；Windows 的符号链接及 POSIX 路径跳过只用于本机检查，不代替 Linux 的零跳过验收。
