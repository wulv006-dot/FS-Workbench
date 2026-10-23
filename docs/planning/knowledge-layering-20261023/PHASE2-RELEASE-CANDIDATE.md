# 二期发布前核对：2026-10-23 增量

本候选沿 PR382，不另开分支或发布器。固定组合基准为 `a4580dd27d99dd03652a08ffb5740e9209a6de64`，合并点 `711af3b0da2b48ee93848771e3d443af1919d61b`。后续 main 变化不自动混入本候选；真正合并前按现行 HOTFIX 检查当时组合，不能用本文件代替正式 CI。

## 本次补齐

- 原生 Desktop 的 prompt_turn 通过方法签名决定传哪些参数，并以 stored session key 作为 task_id。构造包装保留原方法签名，专用只读实例在原生 turn 前验证真实任务；省略 task_id 时固定为批准任务，不等 provider 已返回才发现身份不符。普通会话沿原任务身份、工具、记忆和技能。
- 与上述基准的 user_tools 联检：period_cohort/current/period_end 枚举和描述沿最新维护源动态读取，原查询参数原样传给现有 /users；不覆盖已更新的用户分析代码。
- 原发布器增加本 scope 的短时元数据/目录比较，和原 unchangedRequired 哈希检查配合，发现技能新增/删除、父目录/文件权限及链接变化即返回漂移。此检查只运行于发布检查，不产生技能冻结文件、不改学习开关。
- 服务器完整只读盘点覆盖四目标、615 个静态文件、243 个父目录、四个相关目录树与服务/计时器。原始路径/元数据留本地受控证据；不是永久基线，也不是已取得发布锁。原动态数据库、凭据正文和历史对话不复制。

## 尚未批准及真实缺口

生产仍用旧镜像，未合并、切换或建立新会话；本次模型请求为零。用户选择“一个专用的新 Desktop 空会话”，不等于创建授权。

官方 session.create 的 runtime ID、stored ID 均现场生成，idempotency_key 是 TTL 内存缓存，不能充当永久去重账本。创建后会自动预热 agent，空草稿又不立即落 sessions 行；不能宣称随便从该 RPC 创建后写策略就会重建已预热 agent。session.save 只是导出，不解决空草稿持久化。

后续已实测另一条现有原生能力：在实际修正版镜像、关闭网络及生产 profile 只读条件下，调用原生 SessionDB.create_session，在临时数据库建立指定 ID 的 desktop/default 空记录；get_session 与 list_sessions_rich 均读回同一行，消息及 system prompt 为空。因此可先固定一个计划 ID 与策略哈希，批准后仅用该原生 API 创建一条空记录，再通过正常 Desktop resume 打开。测试数据库已随临时容器销毁，生产会话没有创建；不得把该记录当作已存在的生产会话。此 API 是 upsert，执行前必须拒绝已有同 ID，重复/未知先核原操作和真实记录，不盲重放。真实 UI resume 与完整 provider 初始化仍待批准后验收。

具体上线卡集中列出预选 ID、四载荷、原生空会话创建、服务切换及只读验收范围；若真实恢复或绑定机制未通过，按原发布日志回退本批载荷，保留消息与原会话，不扩大到其他会话。正式包必须带确定的 session/profile/task、策略及清单哈希，任何未知操作先查原回执。完整 provider/费用硬限制及真实模型质量仍未验，不能把 89 项离线或镜像源读回称实际模型通过。

## 影响与保护

生产切换只涉及 fs-hermes-desktop.service 与关联 hermes-dingtalk.service，短暂影响 Desktop/飞书原生入口。不停止 fs-hermes-fc、业务 range、Nginx、定价、采集、用户分析及已有计时器。共享 in-flight 队列、学习、扫描与原生 turn lease 必须自然排空；遇活动记录直接退出，不取消在途，不清 lease，不靠锁等待凑空闲。

发布及回滚沿原 ID/journal、前值备份和 CAS，保留消息、数据库、队列、记忆、技能、知识和审计。原 source/角色/权限/FC 业务规则保持；不写 Notion、不增加或改写老D调度。旧验收文件保留为各自时点快照，本增量以最终交付卡和带 SHA 的证据为准。
