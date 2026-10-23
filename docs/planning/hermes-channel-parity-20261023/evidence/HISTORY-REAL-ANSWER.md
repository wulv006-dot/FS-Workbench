# 原历史实测回答

原请求KL3-history-readonly-20261023-01；真实Hermes与DeepSeek的一次回答，未改写。日期措辞问题见独立验收，不作为新的正式业务规则。

本次验收只读取了 `fc.marketing.attribution` 的存档版与现行版，以及一条来源选择决策；没有触碰经营日报、订单、客户、记忆或技能，也没有任何写入。

**一、较早口径（历史，仅作证据）**
`fc.marketing.attribution@baseline-v15`，layer=archive、status=retired，原文出自 `docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md` 第7节（文件版本日期为 2026-10-21，sha256 9263e02e…）。原文写的是：“`google-FC27-PMAX-Coins-US` 属全局品牌广告，不按名称将全部费用和 ROAS 归 FC。”也就是说，按该口径，PMax-Coins-US 被定位为**全局品牌广告**，不因系列名就把它归到 FC；这一条现已退出当前读取，只保留作历史证据。

**二、2026-10-22 更正后的现行归属**
`fc.marketing.attribution@v15-pmax-20261022`，layer=current、status=effective、effective_at=2026-10-22，原文出自 `releases/fc-coins/fc-pricing-v2-20261022/source/business-baseline.md` 第7节（sha256 1c586eb4…），supersedes 指向 `@baseline-v15`。现行原文为：“2026-10-22用户更正：`google-FC27-PMAX-Coins-US`（PMax-Coins-US）归FC项目，主力贡献集中FC，但投放仍可跨游戏。”同时规定：按实际成交游戏筛出的 FC 订单及订单 USD 计入 FC 广告成交，其它游戏订单仍归实际游戏；Google 平台的归因转化、价值、费用与 ROAS 保留其跨游戏范围，在没有已核分摊方法时，不把整条指标套给 FC，也不把后台订单 USD 当作平台归因价值。项目归属、平台指标范围与成交游戏仍为三个不同字段。

**三、2026-10-23 的来源选择决策**
稳定 ID 为 `fs.decision.pmax-authority-20261023`，revision=2026-10-23，layer=decision、status=confirmed，来源为 `knowledge/decisions/pmax-authority-20261023.md`（sha256 1f826090…）。该决策记录了三点：
- 确认人：用户（条目 owner 记为“吴律；FC原模块维护者”），2026-10-23 施工会话中明确确认“FC维护源和服务器基准则已明确它归FC项目，并区分跨游戏平台指标，这是最新的版本”。
- 替代对象：通用业务手册第7节较早的“全局品牌”表述，退出本条当前读取，保留为历史证据；并明确“不因文件也标v15而继续并列有效”。
- 选择理由：该原文与服务器运行基准的已核版本对应，且已区分跨游戏平台指标，是最新版本；决策只更正知识指向与版本状态，不改定价公式、参数、教学、自动化或调度。文档未记载更多经营动机，故不作推断。

**四、时间精度**
文件版本日期：历史原文为 2026-10-21；现行原文所在文件为 2026-10-22。决定日期：2026-10-22 为更正日，2026-10-23 为用户确认与来源决策日。三条条目均标 `time_precision: date_only`，**精确生效时刻未记载、未知**，不得补推。

**五、release 与读取哈希**
release = `knowledge-layering-20261023-1`（catalog_sha256 ba2a0ad4…）。历史读取 selection_sha256 = `302afd89c324784be8f97a43ce49b3151dbf3befd008d5be17f76faa17d1d567`；当前及决策读取 selection_sha256 = `16a910e820e892bb3fb03eae4c794714060f1cad512e77cc90a944f842011fc7`。
