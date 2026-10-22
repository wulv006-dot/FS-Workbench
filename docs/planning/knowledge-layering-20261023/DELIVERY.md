# 知识分层本批交付与实际验收

本批批准范围已完成：Git版本、服务器发布、实际部署代码的隔离装配、Notion摘要与日期复盘均有读回。变更标识：`KL-da8aceb9b3da63529d7b5393`。本文件记录时点结果，后续现场状态仍须核活动源，不拿本次记录覆盖并行任务。

## 状态分开报告

| 项目 | 状态与证据 |
|---|---|
| 方案、代码及离线 | 完成；本模块24项通过。初次Windows完整pr-fast的换行文件名失败保留，正式Linux CI补足 |
| 正式CI与合并 | [PR367](https://github.com/wulv006-dot/FS-Workbench/pull/367)合并`ba05ef552a78fd5b9a3d513bc7cc5a559a6fd11e`，[CI724](https://github.com/wulv006-dot/FS-Workbench/actions/runs/39824735055)通过；[PR370](https://github.com/wulv006-dot/FS-Workbench/pull/370)合并`eafd47c7b7b25080a09cfa2404340ce59f8b820a`，[CI726](https://github.com/wulv006-dot/FS-Workbench/actions/runs/39827327307)通过 |
| 已部署 | 原publisher发布10文件；10目标、50保护对象及worker/range健康读回通过；父目录UID/GID/模式未改 |
| 实际加载 | 用已部署代码，在自清理隔离临时根选择模块→freeze→loaded_learning→effective_learning，6个正式ID、revision与内容SHA可还原；旧快照、原任务绑定与原改价默认路径保持 |
| 实际模型运用 | 本批未调用模型（0）；隔离装配不是模型掌握/迁移/经营效果证据 |
| Notion写后读回 | 两个原页各新增一个当前区、项目下新增一个日期复盘；原正文逐字包含、84个原链接保留，日期复盘五问/版本/证据通过 |
| 统一收尾 | 原账本四步均completed；重复next两次均completed且mutation_allowed=false，没有重复发布或创建日期页 |
| 未完成 | 普通FS/飞书新路由、真实模型运用及长期效果、老D精确job/自然采用、旧块无损折叠 |

## 唯一权威及版本

PMax-Coins-US归FC、实际FC成交计入FC、跨游戏平台指标保留范围，采用用户确认的FC维护源；索引只引用原文，不改原FC公式、利润底线、参数、教学、开关或调度。取数、币种、身份等仍用原业务基准。方法、技能、经验审核和原自动化继续运行，没有因固定任务版本而冻结成长能力。

Git固定源码提交`aae8e7549e3eb8ca2d420a2f15019522c6b1ae64`是本次不可变发布物的来源；仓库candidate索引是发布输入。服务器版本`knowledge-layering-20261023-1`，索引SHA256 `ba2a0ad4b38028cf08a0b73e6d1529a2ba255a29bd5cbc483b5f8f8c9ee095ba`。精确文件SHA及阶段结果见[RELEASED.json](../../../knowledge/RELEASED.json)，原映射见[SOURCE-MAP](SOURCE-MAP.json)。

## 发布、失败及回滚

沿既有publisher/CAS/锁/准入fence/备份，未另建发布器。旧父目录检查不兼容已存在UID0/GID9876/0750：PR370仅精确复用原用户分析合同，边界测试和inspect通过；没有改权限、ACL或凭据。

首次apply遇采集锁，核原ID证明10目标仍前值、备份不存在、服务正常后记retryable；自然释放后原ID成功，没有清锁、取消采集或换ID重放。原失败证据保留。

发布ID：`nav-20261022T174000Z`；manifest SHA256：`9a10341094914ccf4b1c18e552bfe0a9e7456a678eb1da196c279c50f70fef95`；备份：`/var/backups/fs-navigation-20261006/nav-20261022T174000Z`。ID时间不是实际执行时间。原回滚机制见[DEPLOYMENT](DEPLOYMENT.md)；未做真实回滚演练。后续用户分析PR371已按其回执保护本批全部10对象；未来回滚必须核新的活动哈希/并行修改，不覆盖其他任务。

## Notion与维护衔接

- [项目当前状态](https://app.notion.com/p/3fc9a8a79c4e81578ed1c5fa218837ea)
- [正式知识摘要入口](https://app.notion.com/p/3ff9a8a79c4e81bc8a4feb15aab87a5a)
- [本次独立日期复盘](https://app.notion.com/p/4019a8a79c4e81b187f2fdf09806fa9e)
- [迁移映射及原文保护](NOTION-MAPPING.md)；[每日模板/老D分工](MAINTENANCE.md)；[统一收尾](CLOSEOUT.md)

仅使用原生顶部插入和日期子页创建，保留原人工段落、教学、失败和维护约定，未移动旧块、改共享范围或新建定时。老D仍负责原凌晨汇总；按同change_id/revision去重。精确job与自然采用未验，不能据模板存在宣称切换完成。

用户分析任务已确认按最新版AGENTS→知识索引→HOTFIX→CLOSEOUT执行，并在发布中保护新文件；已协调共享服务窗口。知识跟进任务的消息入口返回AbsolutePathBuf参数错误，未确认收到，不能将其记成已采用。
