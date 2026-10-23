# 二期：FS原生知识接线候选与实测

代码已补齐，仍未部署。除了离线检查，已在**真实Hermes容器的独立进程**执行官方插件注册、工具筛选/缓存、原生dispatcher及middleware、已发布知识读取、异常拒绝与原生准入锁验证。数量、逐文件哈希及实际边界见[结果](PHASE2-RESULT.json)。不把这些结果称为真实用户会话、模型效果或生产验收。

本批仍未commit/push/创建或合并PR，未切换当前调用方/配置/镜像，未停启服务，未接飞书会话，未调用计费模型，未修改FC策略、全局记忆、Notion或任何调度。早先57项交付和失败证据均已保留；本页替代其“发布scope未实现、Windows自检未解决”等未完成状态。

## 当前事实与范围

基线main为`26aab959c467ac78661f906d52f744e46265b9c7`，分支`codex/knowledge-native-fs-20261023`，继续使用原phase2-candidate隔离工作区。该基线不是之后持续变化的main；正式Git步骤仍须按最终组合重评CI。

| 对象 | 已核事实 |
|---|---|
| 正式知识 | 已发布`knowledge-layering-20261023-1`，索引SHA `ba2a0ad4b38028cf08a0b73e6d1529a2ba255a29bd5cbc483b5f8f8c9ee095ba`；现有catalog加载器复用 |
| FS实际入口 | `/api/ws`及`/api/pty`最终进入原生`tui_gateway/server.py::_make_agent`；真实平台为desktop/tui，不能用cli/api_server标签代替 |
| 原生工厂 | 当前文件SHA `5e51f2b4ad33af95044be68a001d0ae66948d8c116fe8ff28a8e70b378ca3be1`；确定性补丁在真实原文件上解析通过 |
| 原镜像 | 只读核为`sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544`，本批未构建或切换镜像 |
| 原插件 | 活动入口SHA `233b4dd08f1554e1438fdcf98037d7d0f2be6370798dcd1e1f4117be2df0cd2f`；候选必须精确保留原六个工具和用户分析，仅追加两行知识注册 |
| 服务关系 | 飞书网关PartOf Desktop；拟定原生服务操作会短暂影响两者，因此必须明示，不能称完全无停顿 |
| 共享技能 | 本任务没有写共享profile技能或冻结要求。另一FC分析任务独占自己的data-storytelling教学范围，与本批离线插件/工厂候选分开 |

## 最小接线

1. 原插件新增独立`fs_knowledge`两读工具及短索引。使用原生平台门控元数据：默认工具集排除该组，非desktop/tui显式减去该组。符合策略的FS构造时才加入，原工具、禁用项及正常memory/技能能力保留。
2. 官方公开插件接口没有构造agent的准入钩子，单独pre_tool_call还存在上游异常放行。因此增加**候选镜像构建时的一处原生工厂接点**：一个import和将原AIAgent调用交给构造器，原参数全部保留。精确原文件哈希不符即拒绝，不在线猴补或任意替换核心。
3. 构造器使用原生session/platform和公共profile身份函数，读取实际SessionDB的上下文存在标志，避免未固定的旧会话静默采用新版本。未有assistant/tool/system历史且无旧system prompt的首次用户输入可进入新会话；已有pin继续固定版本。策略默认disabled，精确新session仍待指定。
4. 会话pin及每次知识使用保存release/catalog SHA、source commit、模块、条目revision/content/selection哈希与原生session/task。原write_file在跨进程文件锁内完成原检查和原子写入，不覆盖前值，不另建知识数据库。提示只是短索引，正文按模块/ID加载；候选、跨模块、历史与冲突继续由原catalog处理。
5. 专用测试实例只给两读工具，skip_memory、skip_background_review、skip_context_files为true。在每次run及原生批量工具分派前核工具集合/原task，任何额外工具、身份或集合篡改均拒绝。即使原生提示钩子整体异常，也不能绕过该实例的构造及分派边界。普通会话不套此白名单。
6. 正常已接入FS实例在run期间持有原admission.lock共享锁，与原发布独占锁衔接；不改FC程序的价格、成本、利润、开关、周期及UNKNOWN合同。

## 发布、前值与恢复

[native_release.py](../../../releases/fs-dashboard/knowledge-layering-20261023/deploy/native_release.py)是现有publisher的**scope适配层**。复用已存在的user-analytics目录父权限规则及冻结publisher `1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de`，不另造写文件/备份/日志/回滚引擎。

四个主机载荷：原插件入口、新knowledge.py、原策略native段、Desktop service中唯一镜像字面值替换。init去掉两行注册后必须等于现场前值SHA；策略所有非native字段必须等于现场；unit只允许原镜像→经过源文件读回的不可变新镜像。完整映射见[PHASE2-SOURCE-MAP](PHASE2-SOURCE-MAP.json)。

[统一准备入口](../../../tools/prepare_native_knowledge_release.py)沿原change_id的operation_id生成独立三文件构建上下文、验证原生补丁、构建隔离镜像并读回两个实际文件哈希，输出releaseReady=false候选。它不切镜像或操作服务。本轮未执行Docker构建；该路径目前仅离线失败注入验证。输出已存在或构建结果未知时保留原状态，不换路径盲重跑。

scope同时保留原发布锁、collector/provider锁、原队列/学习/用户分析排空检查，另对真实原生state.db持有BEGIN IMMEDIATE并拒绝任何lease行（含过期未核对行），不清行或取消调用。仅允许Desktop及其原网关的stop/start与必要daemon-reload；绝不调用旧scope的worker/range重启或stop_then_unlock_database。源文件写入、CAS、全前值备份及恢复仍在原publisher内执行。

启动后的错误需要先重新取得原生DB锁并核无在途任务，才能按原journal恢复。出现并发/超时/停止结果不明，保留unknown-needs-reconcile及前值，不盲恢复、重启或重放。进程被强杀等中断仍须按原发布ID、journal和实际SHA对账后再操作，不声称具有跨任意故障的零中断保证。消息、session、DB、队列、知识版本和审批/使用回执始终保留。

## 验收层级

| 层级 | 状态与证据 |
|---|---|
| 代码与离线 | 原工具、知识模块/版本、只读分派、跨进程、scope、失败恢复、重复操作及Windows完整pr-fast已通过；结果文件列精确数量 |
| 真实原生隔离 | 9项通过，实际Python3.14.7/官方PluginContext、schema cache、dispatcher/middleware、已发布6条知识和原SessionDB准入API；临时目录内落回执 |
| 真实失败修复 | 第一轮真实注册因max_chars=12000超过原生4000上限而失败；已修正并增加短索引有效JSON/长度回归，失败原件保留 |
| 正式CI/合并 | 未执行；本轮不授权Git写入 |
| 镜像构建/部署 | 未执行；当前主镜像和服务均未切换 |
| 实际用户入口与真实模型 | 未执行。隔离检查有意不运行原生provider构造/模型，不冒充真实会话或学习效果 |
| 飞书/Notion/凌晨维护 | 本批不做接入、写入或调度变更；由原维护任务按同change_id衔接 |

真实隔离检查完整覆盖的是明确的运行边界，不是完整AIAgent初始化和用户UI端到端。下一阶段只剩需要实际环境与具体授权的：最终base正式CI/合并、Linux Docker镜像构建及原生服务发布、选择真实新FS session/profile并读回工具/输入/版本，以及明确预算后的一次真实模型验收。当前未得到这些新增动作授权，统一收尾四步骤保持pending；不把预览清单当批准。

Windows问题的根因是自检在工作树物化含换行文件名。现在仍用实际Git diff和全部原断言，改用临时Git blob/tree/commit对象构造历史，Windows可执行且没有删/跳过路径用例。临时对象不进入本仓提交历史。旧完整失败日志保留。
