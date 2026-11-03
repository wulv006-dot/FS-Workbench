# FS 本地代码图

用于跨模块定位、查调用者和相关测试。按需运行，不是开工或 CI 门禁；业务事实仍须回看当前源码、调用方、发布器及适用合同。

## 范围和版本

`graphify-scope.json` 是唯一范围配置，提供 OWNERS 17个模块的导航，并补用户/Hermes、活动、Admin、经营、流量等共享源码。它不等于17个生产模块全覆盖。日期旧不代表退役：FC V3 的源码仍在 `releases/fc-coins/fc-pricing-v3-20261026/`。历史快照和采集证据不进入日常图，也不删除；必要的候选维护源码须明确标级。

每组有 `evidence_level`：`publisher_mapping` 表示发布器直接确认了关键映射；`partial_mapping` 表示仅有部分、历史或候选映射；`maintained_source` 表示按维护模块/测试/回填纳入，现役映射待核。三者均不证明现场版本。当前FC V3为第一类；fc-ops、用户/Hermes、经营渠道、shared-admin为第二类；其它为第三类。特别是 tiered-data 和 shared-admin 的旧 SOURCE-MAP 仍写候选/未部署，不将其包装成当前回执。

配置描述当前仓库维护范围，不证明187/183现场已部署同一提交。`SOURCE-MAP.json` 的时间与状态按原记录理解。当前无法确定的源码先查原发布器，再补范围；不要用“最新目录名”代替依据。

官方包为 **graphifyy 0.9.100**，CLI 名为 `graphify`。本次核对的上游 v8 源码提交是 `32e5efe935e6844ef39a5e33409e4efe848f2172`；安装的 PyPI 发布包不宣称逐文件等于该提交（该提交还含发布后的缓存变更）。使用 Python >=3.10 的独立环境；本次实测 Windows Python 3.14.7。

## 使用

首次协作者在自己的 FS 检出中用 `python -m venv .agent_runtime/graphify-venv` 建立独立环境，再用该环境的解释器执行 `python -m pip install "graphifyy[sql]==0.9.100"`，自行生成本地缓存。Windows解释器在 `Scripts/python.exe`，Linux在 `bin/python`。无需 `graphify install`、MCP服务、提交hook或watcher。私库代码始终留本地。

以下 `python` 必须是装有该包的独立解释器：

```powershell
python tools/fs_graphify.py self-test
python tools/fs_graphify.py plan
python tools/fs_graphify.py build
python tools/fs_graphify.py query "备份调用链" --seed "daily_backup_status()" --budget 1200
python tools/fs_graphify.py affected "精确节点ID"
# 修改所选源码或更新Git检出后：
python tools/fs_graphify.py update
```

状态默认写在 `.agent_runtime/graphify/`；`--state <任务独立目录>` 可换位置。`plan.json` 是预览，成功建图的 `scope.json` 记录构建commit、工作树是否有跟踪文件改动、范围内改动路径、配置hash、逐文件hash、证据等级、HTML缺口、节点数及耗时。源码只从Git跟踪的所选路径复制，未跟踪新文件须先正常加入版本跟踪再更新图。`update` 复用官方增量缓存；明确从范围移除文件时清除相应副本并重建，普通调用保留官方缩图保护。

`query`/`affected`会比较源commit、范围配置和所选文件hash。旧图会明确警告；此时回看当前源码，更新后再将图用于当前结论。图查询仍可用于对照旧快照，不伪装成当前事实。

查询先用代码中的实际名称，重名时用完整节点 ID 或源码路径。输出中的路径相对原仓库，可直接回看；不要修改状态目录里的代码副本。大型图可用官方 `cluster-only <state>/index --no-label --no-viz` 生成报告；`export html --graph <state>/index/graphify-out/graph.json` 生成交互图，超过5000节点使用聚合视图。默认无需打开全图。

## 三个已选验收问题

1. **哪个 HTTP 文件实际被 FC 发布器使用？** 核 `releases/fc-coins/fc-pricing-v3-20261026/deploy/target_map.py`：`conversation_http.py` 指向 `/opt/fs-exact-range-20261001/conversation_http.py`。日常图选择 V3 的 source，排除旧 Hermes 同名 source；这证明仓库发布关系，不证明现场hash。
2. **用户库谁写、备份从哪里来？** 从 `user_store.py` 的 `Store.replace_window`、`Store.backup` 与 `user_jobs.py` 的 `daily_backup_status`、`backup` 查起，再看 `user_source` 和对应 tests。图能找这些符号和同文件调用；动态传入的 `store.backup()` 可能没有跨文件连边，必须回看原源码，不能由缺边推断无调用。
3. **改动后是否更新调用者和测试？** 在独立工作树给已跟踪源文件和测试加临时函数，经真实增量CLI检查新节点、调用关系与 affected 反向查询，再还原源码和图。本次结果存本机验收记录，业务回归并未因此执行。

## 静态图的空白

HTML内嵌JS、CSS、systemd/nginx语义、动态加载/子进程、运行时权限与会话、生产数据库内容不由本图证明。SQL只解析结构，不连生产数据库。没有符号的配置脚本/空包初始化文件可能没有节点。调用关系是导航线索，缺失或重名解析仍要搜索原代码。每次改价、发布或真实写入继续沿用原有ID、CAS、回执和对账保护。

## 给协作者

先读适用的HOTFIX。拿到这组正式仓库文件后，按上节安装并自行建图，不复制其他人的缓存。跨模块或同名源码难定位时按需查询；使用图的任务修改所选源码后运行update。普通改动无需每次全仓建图，也没有新增审批、CI门禁或守护进程。

新增模块、迁移源码、修改发布入口的Agent/工程负责人，在同一变更里同步 `graphify-scope.json` 的roots、basis与evidence_level；依据写实际调用方、发布器或来源文档。候选升级为发布映射需有对应证据，不能因时间更新或测试通过升级。相关检查是现有工具的self-test和plan；范围改变后，有需要的使用者再更新本地图。

交接时给出所用commit、图是否过期及相关来源，后续Agent从AGENTS入口接续。提交仅含工具、范围与说明；venv、索引、缓存、本机绝对路径、凭据和业务数据不入Git。不向别人的电脑安装，不向187/183加服务。

## 技能去重

保留本地现有 `handoff`，交接只追加本轮增量并引用原证据。复用 Ponytail 的最小实现和已有测试技能/项目真实接口回归要求；不复制 mattpocock TDD 的逐接口确认步骤，不安装固定多代理设计流程。唯一补装的 `writing-for-agents` 来自 mattpocock/skills `4ae2317ddb22b046e26455e4f9c9b3aaaf62212d`，整理代理文档时按需读，不执行其 setup。详细来源：[handoff](https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/productivity/handoff/SKILL.md)、[writing-for-agents](https://github.com/mattpocock/skills/tree/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/productivity/writing-for-agents)、[tdd](https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/engineering/tdd/SKILL.md)、[codebase-design](https://github.com/mattpocock/skills/blob/4ae2317ddb22b046e26455e4f9c9b3aaaf62212d/skills/engineering/codebase-design/SKILL.md)。
