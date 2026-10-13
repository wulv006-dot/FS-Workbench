# 游戏监控台与经营管理台：源码候选

本目录接入老板提供的两个工作台，作为 FS 独立工作区。仅包含界面、公开图片、原包目标与负责人配置，以及 AI 输入/输出白名单纯函数；不包含现场基线、部署产物、凭据、运行数据或 Advisor 后端。

| 入口 | 主标题 | 副标题 |
| --- | --- | --- |
| `/dashboard/game-monitor/` | 游戏监控台 | 全球新游上线 · 版本赛季 · 开服节点一屏追踪 |
| `/dashboard/management/` | 经营管理台 | 三组进度 · 健康度责任到人 · 目标沙盘与经营决策 |

## 来源与业务口径

- `source/game-monitor/` 来自用户提供的“游戏监控台.zip”，由本轮接入代码修正会话处理、静态快照提示、倒计时与 AI 手动解读交互。包内游戏信息是导入快照，来源链接与事件日期不代表本轮联网核验结果；没有新增自动采集或定时刷新承诺。
- `source/management/` 来自用户提供的“经营管理台.zip”。依用户明确选择，`targets.json` 保留原包目标、分组、负责人；实际值经 FS 准确区间读取。旧实际不再展示，沙盘保留的旧预测明确标为原包规划假设。目标属于原包计划，负责人字段不改变系统权限。
- 经营目录使用既有 metadata-only catalog；数值查询使用 `/dashboard/fs-home/range.json?mode=summary&profile=...&start=...&end=...`，核对项目、日期及 `admin-main-order-labelled-supplement-v1` 合同。目录更新时间不能当作经营数据采集时间。
- 实际数据遵守当前 FS Admin 主源、Order 补缺及显式来源标签。销售额、订单及利润率的来源/站点范围/读取时间分别保留。预估利润为可用销售额乘同区间 Order 利润率，明确标为估算，不冒充后台实结利润。
- 缺值保留为空，不能补零；日期、项目或口径不一致拒绝消费。历史缓存与当前区间的过期状态分别展示，等待和失败不能展示为成功。切换项目、日期或登录身份取消旧请求与旧结果。
- 沙盘只产生当前账号的浏览器本地草案，可导出审阅；不向服务器发布目标，不写业务数据。原包非本轮日期的计划不当作新期间实绩或已批准新目标。

## 权限与 AI 边界

工作区沿用 FS 登录与既有服务端会话保护；角色按钮只是交互提示，不替代后端鉴权。会话失效或身份变化会清理界面中的已渲染数据。AI 解读仅管理员显式点击触发，前端保留请求意图、原任务编号及同任务 GET 查询，未知结果不自动重新 POST。

`backend/boss_insights.py` 仅提供以下纯函数：

- `project_context(body)`：严格校验并投影 `{scope, request_id, context}`，只返回 `{scope, context}`，紧缩 UTF-8 不超过 16 KiB。
- `build_messages(body)`：从同一白名单请求生成模型消息，不接受额外指令、原备注或客户资料。
- `validate_response(raw, projected)`：复用既有 `fc_daily_model.MODEL`，核验模型、回执、完成状态及用量；成功返回 `status/text/model/receipt/tokens/source_kind`。

游戏解读只发送少量公开游戏名、事件标题、日期和 HTTPS 来源链接，输出标为 `imported_snapshot`。经营解读只允许项目 key、期间、销售额、订单、预估利润、目标销售额及缺项，输出标为 `fs_summary`；原包负责人姓名不发送给模型。模型输出是短中文定性建议，不执行操作、不作为联网检索结果，也不生成或写入售价。

本目录没有 provider、密钥读取、独立模型数据库、自动调度或新增额度。管理员鉴权、权威经营汇总重读、request_id/context 去重、调用前 pending、unknown 保留、共享每日模型额度及任务回执由独立 Advisor PR 接入现有后端；未完成该依赖不能声称本目录已经具备可用的服务端 AI。前端仅调用约定任务入口并轮询原任务；不绕过现有到额停止规则。

## 自动检查范围

复用 `tools/pr_fast.py` 的 `fs-boss-workspaces` 分组，不新增 workflow：

1. `tests/game-monitor.cjs`：资源存在性、内联语法、快照提示、输入最小化、身份切换、任务查询/恢复与失败状态。
2. `tests/management_test.cjs`：来源与区间合同、缺值、指标与目标计算。
3. `tests/management_polling.cjs`：有界同区间查询、取消、最多两个并发请求及原 AI 任务恢复。
4. `tests/management_sandbox.cjs`：目标再分配、失败回退、输入校验及账号隔离草案。
5. `backend/test_boss_insights.py`：20 项纯 schema/响应校验测试。测试从邻接的 `../fc-daily-20261013/source/fc_daily_model.py` 导入模型常量；不调用模型或读取凭据。

检查失败、空测试或必需测试 skip 均不能通过。HTML/CSS 基础结构与 Python/JavaScript 语法检查遵循现有 dispatcher。以上属于离线检查，不代表真实浏览器、Linux、nginx、当前角色权限或模型调用验收。

本轮 Windows 本地结果：候选结构/语法检查通过；通过 dispatcher 的同一 `node/units` 入口运行，四个 Node 检查和二十个纯函数用例全部通过，零失败、零 skip。完整 `pr-fast` 的既有改名自检尝试创建含换行的文件名，Windows 返回 `Errno 22`，因此完整检查仍未通过；没有修改或跳过这项自检，Linux CI 结果待实际执行。

## 发布与独立证据

`build_release.py`、publisher、现场 baseline 和发布测试没有复制进本 PR；它们依赖本轮现场受保护文件与精确 SHA，继续由主任务以既有受控发布器单独处理。旧游戏监控入口退役涉及 nginx 路由切换；原目录、数据与历史版本保留供追溯和回滚，本目录没有删除它们的程序。

独立本地发布证据：136 个不可变文件、4 个可变路径的冻结候选 `workspace-native-20261006-3618d84549f1`，合同 SHA-256 `8a11f04e5c7a194f2ea28532c5dc83dcc4ea5bc802f60bcb910ce76bef28a60b`，17 项临时根目录发布/回滚/CAS/故障恢复测试通过。该候选未含后续 Advisor 资产；Windows 测试侧模拟了 POSIX 元数据、符号链接、目录同步及服务命令，不能充当真实 Linux 发布验收。后续变更须针对受影响载荷重新核验，不能借用本条宣称已上线。

协作规则以 `docs/ops/HOTFIX.md` 为准。共享入口由吴律主导，原球类/RPG 业务归属保持；本源码候选不修改账号、业务参数、采集计划、模型额度或发布授权。
