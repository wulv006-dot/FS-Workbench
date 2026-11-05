# ES身份补充：实现与边界

本候选让已归档订单与客户追踪保存、检查buyer证据；**未按buyer重新计算客户人数、生命周期或全年价值，未切换去重主键**。原customer_id、邮箱追踪池和旧快照保持原口径。

## 实际调用链

日更原任务：新/缺日订单入库 → 原ES文件完整性验证 → read_pinned_identities读取已冻结原始行 → Store.enrich_order_identities按订单哈希匹配现有订单 → 原revision事务 → 原快照发布。日常只关联本批新增/缺日，周一仍沿原90日修订范围；不新增服务、仓库或定时器，不每日扫描全部日期。

ES缺site时，仅给时间范围内唯一匹配的现有站点订单补字段。多site/多记录同订单号标ambiguous；未匹配不新增虚构订单。原buyer与新证据不一致时保留原buyer、标conflict并记录候选冲突值，不静默覆盖。UID不连接多个buyer。Admin状态刷新保留已核ES身份；旧snapshot仍读当时revision。

原追踪private_es_day → candidate_rows保留原ES字段，再以Admin订单号、站点、游戏、付款状态、客户邮箱确切校验，成功后才标matched to Admin。同订单多SKU允许一行缺buyer，两个有效不同buyer才排除冲突。追踪池仍按既有email归集；私有详情可见证据，tracking_tool匿名输出与pool_evidence仅提供覆盖单数、观察到的buyer数及冲突状态，无原ID。

## 真实只读覆盖

2026-11-05读取现有文件，0次源采集、0次数据库写入：

| 既有归档 | 行数 | buyer有效 | UID有效 | 字段类型 | 抽查Store命中 |
|---|---:|---:|---:|---|---|
| 11/04完整日 | 972 | 972 | 565 | 两列均str | 0/200，该日尚未通过原周更入库 |
| 11/03完整日 | 1,181 | 0 | 0 | 无两列 | 0/200，该日尚未入库 |
| 11/01完整日 | 1,187 | 0 | 0 | 无两列 | 192/200，命中均唯一站点，8条未命中 |

新导出能返回历史字段，不代表旧文件已拥有新列。11/04可在日更入库后复用现成文件；缺字段的历史须按需回补，不填0。buyer/UID保持原字符串，0、空、null/none、N/A等占位无效，不转浮点或数字。共享ES公开dataset仍不包含原ID。

## 验证和后续

新增用例先复现Store无补充入口、追踪刷新丢ES身份；183 Python3.9隔离环境用户分析298项、客户生命周期22项，共320项通过。覆盖幂等、旧快照隔离、多站点歧义、buyer冲突保留、多SKU缺字段及匿名工具无ID。最终包SHA：6a6b6ea7ef0461c26bad6836c7dbbd04b25b6365bfd7492455733dc14c8bbe1c。

尚未生产写入身份或创建第二生产stage。main的user_store包含未上线版本索引；后续必须沿现役Store精确补丁发布，不引入未部署的user_version_index.advance，实际载荷另验。全年buyer精确查询仍待接口/权限接点，本补丁不伪称解决跨邮箱历史覆盖。业务原件只在私有.agent_runtime/buyer-tracking-incremental-20261105，不进入Git。
