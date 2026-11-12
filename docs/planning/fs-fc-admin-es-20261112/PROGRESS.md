# FS／FC27／Admin ES：启动对齐与共享合同交接

## 本轮停止点与授权

2026-11-12，吴律要求先完成启动对齐和共享数据合同，只核陈超报告后的关键变化；额度允许再做 D0，完成一个可交接小阶段后停止。本轮交付为 **U0 增量接收＋U1 文档合同冻结**，不是 U1 代码基础完成。D0 未实施。没有可读取的剩余额度证明，不声称额度已耗尽；按小阶段边界停止，避免把归档修订、身份和双入口兼容拆成未经验证的半个补丁。

本轮只写本目录的文档和精选只读证据；未修改运行源码、线上价格、调度、权限、知识 catalog 或数据库；未部署、未激活 FC V6、未创建生产任务、未发送外部消息。原自动化继续运行，期间系统自行执行的写价不是本轮操作。

唯一方案正文为 [MASTER.md](MASTER.md)，逐字节接收用户附件 `FS_FC27_Admin_ES_总施工方案_优化定稿_20261112.md`，版本 integrated-final-r4。输入 SHA256：`ce21f219aee28b4d9d9062e61dc80e6f4a1862141b3bf3bf5633b4a8073b8137`。正文中的发布、激活、转交草稿和历史“已授权”描述均不扩大本轮授权。附录 B 是原报告，不是本轮现场证据。

## 版本与并行工作保护

- 接收基线：陈超报告 main `7e48408ffcfe1a936da12a732666a91f6d97c212`，取证时段 16:47—17:07（UTC+8）。
- 本轮 fetch 后 base：`7042edaf90647cbd51ab7df3e35f7b4341f72b3f`，私有源 `wulv006-dot/FS-Workbench`。
- 工作树：`D:/codex/FC27/fs-fc-admin-es-u0-u1-20261112`；分支 `codex/fs-fc-admin-es-u0-u1-20261112`。交接提交用本文件的最新 Git 提交定位，最终回复提供固定 SHA。
- 原入口在 `codex/hermes-es-relay-20261107` / `3d07c69`，工作区干净；没有切换、合并或覆盖它。其他已有工作树保留。
- 当前任务工作树无 `.codegraph/`，按规则直接读精确源码；未引用旧工作树索引作为本轮版本证明，也未创建索引。
- 已读 HOTFIX、GRAPHIFY、OWNERS、SOURCE-MAP 及 main 新增 Agent skills 规则。旧 SOURCE-MAP 含历史状态；不作为生产一致证明。
- GitHub open PR 查询返回 11 项，未发现本双项目 U0/U1 或 D0 实现包；#589/#586 为旧 FC 草案，#953/#793/#714 等涉及共享规则。仅核元数据，不声明所有开放 PR 文件均无冲突；本轮不改这些交叉文件。

## 事实接收与报告后关键变化

| 项目 | 原证据与本轮增量 | 接收结果 | 结论／后续边界 |
|---|---|---|---|
| 19／21／24 列与真实三表头 | MASTER 第三部分 §0.1、附录 B §3.2；ES 两个 parser 自报告基线到本轮 base 无差分 | 直接复用 | 不重新导出全量；原工作簿未取得，不能称本轮 raw 实测 |
| 历史源 incomplete | [现有恢复记录](../fc-pricing-recovery-20261112/README.md)，PR #1017/#1019/#1020 已在 base 中 | 已被变化替代 | closed ALL archive 投影与 publisher exact reader scope 已有修复，不重复施工；18:08 读回/部署属于该任务记录，非本轮重部署 |
| 18:39 storefront／18:41 HTTP 429 | 同一恢复记录；本轮 22:47 monitor 返回 storefront=ok、最新采集 ready_for_quote | 已被变化替代 | 当时失败保留；不把 429 当当前持续故障，也不推断其根因已被本轮修复 |
| 原计划与后续自然结果 | [只读摘要](evidence/u0-live-summary.json)：plan `5cecacfd-19f7-584a-8845-16adbef9b13d` revision 3，六资源不变；22:46:13 最近轮 NO_CHANGE，60 分钟节拍；pending_operations=[]、issues=[] | 局部补证 | 接口证实后续正常结果；不等于原 15:36 队列项已取得终态 |
| 实际业务读回 | 同摘要：监控记录 execution `554f89ab-7675-5a10-a32e-6521a30e40c2`，21:39:40 自动写入；22:46 后台与三平台公开观察 matched | 局部补证 | 这是监控聚合回执，未独立读取该 operation 原始账本；不能认证全部 V6 写入分支 |
| 原 15:36 原队列项 | MASTER 第一部分 §3.4 原 ID `cycle:5cecacfd-19f7-584a-8845-16adbef9b13d:1794469016:r0` | 待取得 | FS coins.jobs 只接受 UUID；ops.job 只接受 32 位 ID，未用新 ID 替代或伪造转换。下轮沿原持久队列只读查询 |
| API／worker／会话 | monitor health：api/worker/browser/order_session=ok，timer=active，queue_depth=0，incomplete_executions=0 | 局部补证 | 为接口报告状态，不是独立进程加载 SHA 检验；通知送达没有新证据 |
| 组合部署保护 | 报告中 admin_summary/range_api/p2pah_auth 字节差异；随后邮件导出 #1016/#1018、Lucky Loot、RPG 等已合并 | 局部补证 | 本轮不触碰共享发布目标；部署时仍需现场字节 CAS 与三方差分，不能整包覆盖 |
| 原生复购、首访含义、归因模型 | 原报告 4.33% 与 13/280 不同集合／公式尚未闭合 | 直接复用 | 保留 raw 和未知；不重算为同一口径，不根据首访推首购 |
| 183、Hermes 生效知识、周月报告任务 | 原报告 staged 及未闭合范围 | 待取得 | 本阶段不依赖其验收；未恢复暂停任务，不以旧状态当当前事实 |

只读摘要保留各接口自己的 UTC 时点；表内展示为 UTC+8。两个请求不是原子快照。`monitor.latest_collection` 仍指向 10 月 26 日，故没有将它的竞品与成本当本轮有效输入。待更新知识、自然周期长期稳定、原故障终态分别记录，不以一个健康字段覆盖。

## 共享合同冻结：唯一正文与实施落点

合同标识：`fs-fc-admin-es-shared-20261112-r4`，状态 **design_frozen / runtime_not_implemented**。权威字段定义直接引用 MASTER 附录 A.1—A.13，不另复制第二套业务合同。冻结指本轮实现依据已固定，不改变现役业务规则、财务门槛或权限。原生未证实的字段保留 unknown，不以设计签名冒充可调用 API。

| 共享对象／接口 | 唯一合同位置 | 已核维护落点及适用边界 |
|---|---|---|
| OrderFact、客户桥接、商品行 | 附录 A.2/A.3 | `releases/fs-dashboard/user-analytics-20261022/source/user_store.py` 既有 identities/orders/revisions/snapshots；沿旧键和授权域，不换哈希。ES dataset 当前订单号哈希不能直接当此键 |
| MarketingAttribution | 附录 A.4/A.12；第三部分 §9.3 | `releases/fs-dashboard/cache-archive-retention-20261025/source/es_order_structure.py::xlsx_rows/make_dataset`；`session_es_order_structure.py` 有另一投影入口，Dockerfile.session 将它装为 es_order_structure，D0 必须核两个入口。尚未实现新 normalizer |
| QueryScope／原生与本地复购 | 附录 A.5/A.13 | D1 沿 `dashboard-refresh-20261025/source` 的活动查询链；requested/effective/unsupported/coverage 与授权域贯通后端、MCP、导出、缓存；暂未认证原生分子分母 |
| CostFact／四种 accounting_basis | 附录 A.6/A.7 | `dashboard-refresh-20261025/source/actual_profit.py::normalized` 目前按站点+原单号关联，累加不同 delivery_id，缺成本 null；重复或缺 delivery_id 会报错，不是静默去重。D2 在可信输入边界确定重复记录处理，保留现有防误计行为 |
| 完整 curve／quote／PricingProof | 附录 A.6/A.7；第二部分 §11.1 | F0/F2 沿 `releases/fc-coins/fc-pricing-v3-20261026/source/fc_pricing_v3/`；read_curve/compile_curve/quote_native/curve_key 的设计签名及返回域取 §11.1，现役可调用性未认证，不新增第二 writer |
| PriceExposure／归因后补／成本回补 | 附录 A.2/A.8；F5 | 原 business_source.py/daily.py 仅由主线一次接线；创建时间绑定已确认 curve，付款／发货时间独立，后补回原窗口 |
| 修订、缓存、可用性 | 附录 A.9/A.12/A.13 | 沿原发布 revision 和引用保护。24→21 不视为清空；24 显式空值修订保留；冲突不拼 last-non-null；闭合历史不套实时 TTL；营销缺失不降级 P0 |

归因 normalizer 的设计签名固定为 `normalize_order_attribution(row, headers, header_contract)`。真实列映射、raw／presence／empty／unrecognized、首访解析状态、来源修订与可见时间均按附录 A.4；不扩大必需列集合。模型、窗口、源时区未证实则不猜。`dimensions.channels` 原含义保留，新字段另用 marketing namespace。

共同验收样例唯一使用附录 A.10，不另改数字：全站 4 单／3 客／$180／1⁄3；FC 3 单／2 客／$150／50%；UID=0 的 B/C 不合并；Direct+旧 google 并存；成本重复 D1 不重计、不同 D2 累加；1000K+30K 两种分母都回到 $50。合同样例尚未转为本轮可执行测试，不能记为通过。

## D0 具体交接范围

已定位而未修改：`xlsx_rows` 为每行保留全部表头键，`make_dataset` 白名单重投影导致三个归因列丢失；主入口仅另保留 coupon 三项元数据，session 入口还有差异。当前不能直接把建议 helper 放进一个目录就宣称两条运行链兼容。

接续时按以下顺序完成一个 D0 包：

1. 先核本分支与最新 main 的相关差分、两个入口实际 import／原 publisher 目标；保留后来已有修复。无变更的报告字段不重盘。
2. 在原测试目录加入实际 19/21/24 表头的合成 XLSX→dataset 反例；覆盖缺列、有列空值、未知枚举、Direct+旧 google、Campaign+google、Referral/cardpay.com、首访未知、无客户身份仍保收入及 archive_profile≠effective_scope。
3. 复用一个 normalizer，接两条实际投影链；沿旧 JSON/Store 保留 namespace、字段存在性、来源修订和哈希身份。修订排序不能靠 mtime 或最后非空拼接。至少验 24→21、21→24、24 明确清空、同 revision 冲突、重复日片、退款迟到。
4. 再运行受影响旧回归；需要 Linux 行为时先核 183 独立环境和资源，再隔离验证。183 不是本轮已确认可用环境；不转到 187 生产测试。
5. 原私有工作簿只取必要样例作 raw→dataset 去敏对照；本机没有陈超 E 目录原文件，不用合成数据冒充实样。无须全量重导，不触发 ES 导出或新定价轮次。
6. 更新本文件、提交代码与测试后停止。部署、FC 激活、真实写价仍不在本轮授权内。共享知识正式发布、合并与生产动作另按实际授权。

## 验证与续工

本轮是文档交付，验证结果：

- 附件副本逐字节与 SHA 一致、A.1—A.13 全部保留、JSON 证据读回及仅三文件范围检查通过。
- `python tools/pr_fast.py .agent_runtime/u0-u1-paths.txt 7042edaf90647cbd51ab7df3e35f7b4341f72b3f HEAD` 通过，affected_groups=[]；这是工作区文档／JSON与检查器自检，不是业务测试或正式 CI。
- `python tools/knowledge_closeout.py plan --base 7042edaf90647cbd51ab7df3e35f7b4341f72b3f` 首次失败：Python 3.14 缺 tzdata。使用已有 `D:/codex/FC27/fs-data-connector-20261109/.venv/Lib/site-packages/tzdata/zoneinfo` 作为当前进程 PYTHONTZPATH 后通过；未安装依赖或更改生产环境。105 项中 98 通过、7 项按现有平台条件跳过，不能称零跳过验收。
- closeout 返回 affected_ids=[]、steps=[]、requires_restart=false、无 blocking_conflicts；没有知识发布或 Notion 写入步骤。运行日志在工作树 `.agent_runtime/u0-u1-closeout.log`，原 ledger 保持忽略，不提交生产日志。
- 最终 `git diff --cached --check` 和提交后工作区状态在提交时核验。

未修改业务代码，因此不重跑陈超同版本的 36 通过／1 跳过，也不将其写成 D0 已验。没有运行 183、正式 GitHub CI 或生产回归。附件只做内容接收，不保证其历史外链和相对链接当前可访问。

已执行但不作为成功检查：`pr_fast.py --help` 返回 FileNotFoundError（该脚本将首参当 paths 文件）；后续按实际入口传 NUL 分隔路径。系统 PATH 无 gh，开放 PR 改由 GitHub 只读连接器核对。普通 fetch 初次因 Git 元数据只读失败，获工具审批后成功；没有自动审核拒绝或绕过。

下一位从本工作树、本文件和 MASTER 附录 A 接续。优先完成 D0；U1 的同单事实实现与 F0 quote 仍未完成。原 15:36 cycle 终态、线上组合字节、原工作簿、183 与模型消费分别待验；这些缺项不阻止 D0 离线工作，但不允许把设计冻结写成全链路已交付。
