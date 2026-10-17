# FC、管理实际与游戏情报范围卡

2026-10-15；本目录是父任务委派的隔离候选，没有生产写入、Git 写入、重启、业务采集请求、模型调用或根 HANDOFF 修改。

已读项目 AGENTS、gitignore、OPEN-DECISIONS、最新 HANDOFF、父任务实时取得的治理三份和模块合同。原 E 仓无 remote，原有 untracked/dirty 源保持。FS 主线负责共享发布窗口与最终组合；FC/经营范围沿吴律责任分工，游戏其他 owner 未据本候选扩权。

活动基线为前端 `/var/lib/fs-navigation-formal-static/workspace-native-20261006-5d085f7c1aac/`、范围服务 `/opt/fs-exact-range-20261001/`。完整逐项映射、原 SHA 与候选 SHA 见 `changed-source-runtime-map.json`；只读现场元数据见 `live-metadata.json`，139 资产新读盘点另见 `../frontend-release/live-baseline.json`。

`fc-detail.js` 是 FC 前端的构建片段，服务器没有独立同名活动文件。现网消费位置是上述版本的 `business.js` 内联段（从 `// This fragment runs inside the existing business mount` 至 `function workspaceState` 前）；映射记录完整 business SHA 和该段 SHA。新片段已内联至候选 business.js，新 native 不增加无消费者的 fc-detail.js 静态资产。

FC 根因：历史支付明细与当前履约池共用 900 秒有效期，但同一历史视图读取结束后没有独立复查；同 key 阻止重读。单次 fetch 没有超时，920 秒总等待无法约束卡住的单次请求。FC 与 legacy 区间共用单 worker，等待队列又在 900 秒源读取预算外。源异常原先仅记录 failed，缺少安全原因码。现有记录不能证明用户截图那一次上游失败的精确异常。

候选修复：FC 独立一个 worker，原每分钟 3 次/最多 2 pending/源单次 900 秒保护保持；新队列最多一执行一排队，不能被 legacy 队列占住。单请求最多 20 秒、整体最多 920 秒；瞬态网络在预算内续读，鉴权失败停止。同视图只有一条在途请求，成功按 900 秒复查当前池，失败 60 秒后复查，可见恢复重查；显式更新视图接强制 FC 刷新。排队与读取区分，等待超时保留原快照，不把服务端在途任务改报成功或失败。旧 fc_daily 生成 action/header/按钮去除，新报告入口接 LV 决策大脑 `/dashboard/fs-home/brain/index.html?report_kind=daily#reports`；旧报告仅只读归档。独立 FC 队列使最大潜在 Admin 只读并发比原多一个，原上游重试及权限不变。

管理台：周实际原来在模板中直接写死“未接入”，并没有周范围查询。新候选按原 2026-10 五段，与当前有效实际日期取交集，最多两并发复用原 summary 请求；完整周、部分周、未来周、失败分别标示。二级指标中，主站客单价由同范围 Admin 主站营收÷订单数精确计算；复购/发货完成率仅消费可证实主站字段，缺失不推算；利润率为 Order 全站参考，不作主站目标达成率。Order 过期不连带抹去新鲜 Admin 实际。金额仍美元，利润仍 Admin 主站销售额×Order 全站利润率的预估，非实结。

管理本日失败已只读证明：10/15 00:58:43 scheduled 任务在 24ms 内结束，15 项目均 catalog_unavailable；同秒 range stopped，00:58:47 才 started。保留旧成功（10/14 09:30、实际截至10/13）及当日失败。父任务已经另做 catalog 有界重试，**不采用本目录 candidate/management_daily.py 的独立重试候选**；不删除/覆盖原失败 journal，不盲重跑模型。boss_daily 未修改。

DY 原版可验证基准是用户提供的 `E:/WorkBuddy/经营管理台.zip`，SHA `3a0bec8c76203254161a7cb2fc0314e40cc0f515c29b5dc0e358360b096e318c`。17 页目标/负责人/周目标与原 ZIP 比较通过；candidate/targets.json 与现网 `2985f9a48902b577cfe6955b95c82f191a2f34d1bc10302aad8c5d4581ce8102` 原字节一致。没有取得 DY 上游目标测算表或审批记录。原 FC 周营收合计 $830,000、12,897 单，与月目标 $831,000、12,913 单的 $1,000/16 单差异保留，没有改业务参数。

游戏台根因：真实情报缺明确时间/时区时被跳过 game.events，卡片随后笼统显示无活跃节点；旧 phaseboard 还会盖住新 timeline。候选把全部已验证情报摘要与官方证据接入每游戏卡片/详情，只有明确日期、时分和偏移者进入小时倒计时；尚无采集/来源缺口/可读但无校验节点分开显示，原 phaseboard 仅历史模式展示。只读真实公开基准有 15 事件，成功版本读取为10/14 09:00；10/15 本轮 model_failed，原成功版保留，不冒称本轮成功。模型和 UTC+9 后端修复由父任务负责。

本机验证：14 项 FC 后端、2 项专用队列、原 FC 查询/响应断言、FC 生命周期、管理合同/阈值、管理实际周段/AOV/缺值与过期隔离、真实 15 事件前端消费均通过。Python 为本机 3.14；没有把这些检查写为 Python 3.9/Linux、真实角色或线上点击验收。新 native 已由父任务要求冻结在 `../frontend-release/stage/`，本目录不擅自再变冻结资产。最终发布、Linux publisher、组合浏览器、真实角色与自然周期均由主线另验。
