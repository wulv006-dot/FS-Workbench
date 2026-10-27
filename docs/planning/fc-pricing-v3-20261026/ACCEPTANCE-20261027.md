# FC27 V3 真实验收记录｜2026-10-27 自然周期接续

当前双20、无预算代码已上线，真实首轮、英国折扣退出和原编号类别联动已完成。两个新合同自然周期已分别完成为INFEASIBLE、未写价、无技术重试；更多连续周期和长期经营效果尚未验收，不能将本记录称为P0–P4全部完成。后续候选、修复及隔离故障注入见[NATURAL-AND-FAULT-ACCEPTANCE](NATURAL-AND-FAULT-ACCEPTANCE.md)。

## 当前版本与计划

- 当前代码：`7ca8b90ccec88ae8026267fb4b5495741b074cb2`，[PR540](https://github.com/wulv006-dot/FS-Workbench/pull/540)。正式CI run40426795918/job121934454028，230项FC V3检查通过。竞品卡片、Hermes全文换行及实际页面验收见[页面核验](MARKET-UI-ACCEPTANCE-20261027.md)。PR538多商品行购买/赠送K修复已部署并回接原缓存。局部价格组缺口不再冻结无关样本，真实PC30笔对应的两个曝光观察已接回原学习缓存，见[学习覆盖验收](LEARNING-COVERAGE-ACCEPTANCE-20261027.md)。PR534的原快照旧策略回放、Hermes只读桥和登录后的实际入口已核，见[回放验收](LEGACY-REPLAY-ACCEPTANCE-20261027.md)。PR532页面遗留00:20已对齐实际02:20，真实展示保持。PR530历史补齐逻辑保持，实际源码SHA以当前SOURCE-MAP为准。PR529修复已核历史PlayStation原生标签，PR530沿原Admin/ES补齐指定历史缺日；真实结果见[历史覆盖核验](HISTORICAL-COVERAGE-20261027.md)。PR526页面重复原因去重及真实展示验收保留。实际91/91目标SHA匹配，见[SOURCE-MAP](SOURCE-MAP.json)。PR520–523分别修复积压缓存吞吐、默认地区层底价舍入、业务无解分类及每轮快照保存，完整发布链见[接续核验](NATURAL-AND-FAULT-ACCEPTANCE.md)。
- 双20/冲量/无预算：[PR515](https://github.com/wulv006-dot/FS-Workbench/pull/515)，merge89086d090809d70dd8899f3e57a6a466f18d2ac3；正式196项FC及87项知识检查通过。
- 英国专项与完整指南：[PR516](https://github.com/wulv006-dot/FS-Workbench/pull/516)，merge3fa60c797259a82c59925ac52899afd20f0a028f；202项检查通过。原编号类别联动兼容：[PR517](https://github.com/wulv006-dot/FS-Workbench/pull/517)，merge5120b4e70aa6a0ed6e69e136bcec032374ade249；206项检查通过。
- 原计划`15010688-bf97-5dd8-a33e-b4ae3c360403`：revision2/ACTIVE，`fc27_dual20_v1`、`budget_policy=none`，有效daily_budget/total_budget字段已移除，迁移前记录保留。政策revision41、ON/auto、120分钟、三平台、最低毛利20%。
- 原截止仍为2026-10-27 22:30北京时间；没有延长试验。首轮真实程序写价完成03:10:25；05:12:35与07:14:52两个自然轮均正常完成为INFEASIBLE、未写价、attempt0，当时下轮09:14:52。08:20:58收到已登录Chrome页面暂停请求，用户确认非本人主动暂停并授权恢复；08:26:23恢复原计划后下一轮为10:26:23，间隔仍120分钟。代码发布未重置间隔。

## 首轮真实程序执行

操作`637a2036-7a51-5b9c-a5e0-0da23f333939`，run`9c68a9eb-afe0-54a7-bfbd-bd797d29de2a`，耐久任务`manual:ac81d571-7b5b-5dac-be49-9edb9a66781e`。2026-10-27 03:10:25北京时间COMPLETED，后台CONFIRMED、ALL confirmed、缓存cleared、全球和沙特/英国三平台公开verified，完整双20证明通过。执行审计SHA：`c19c885903476b79be50d3a174678e392842573436737b4a224a3341a3452c22`。

该轮由操作者触发当前程序，原机械审计`automatic=false`真实保留，不冒称定时自然触发。预算预占0条。派生任务`f65259cd-7a21-534d-9bef-15c150fa84a6`原因旧automatic条件在请求前拒绝；核实NOT_SENT及无派发账本后，同一编号接续，于04:03:33 confirmed/category_all，955模型，类别请求accepted，sample_count0，未抽查球员售价。旧失败原文件完整留在`/var/lib/fc27-cloud/rollback/v3-player-preflight-f65259cd-7a21-534d-9bef-15c150fa84a6/`。

以下均为当时100K购买、额外5K赠送的USD公开价格，不能作未来报价依据：

| 地区 | PS | Xbox | PC | 系数 |
| --- | --- | --- | --- | --- |
| 全球 | 8.72 | 8.72 | 8.80 | 1/1/1 |
| Saudi Arabia | 7.90 | 7.90 | 8.80 | 0.9055/0.9055/1 |
| 英国取消前 | 7.94 | 7.94 | 8.01 | 0.91/0.91/0.91 |
| 英国取消后04:07 | 8.72 | 8.72 | 8.80 | 1/1/1 |

同轮Lootbar Console9.18/105K、ItemD2R8.77/100K；全球执行有效价8.304762/100K交付，相对Lootbar低5.01%。Arab-UT普通8.13/100K，沙特有效价7.523810/100K交付，低7.46%。PC未达到5–10%竞争区间，整轮准确标记`MARGIN_FLOOR_FALLBACK_20`，不能宣称全部竞争目标达标。Arab-UT PC普通报价仍缺失，未复制PS。

## 英国临时优惠退出

唯一操作`e51f61e9-39d8-5588-9c64-d54343fd212e`，任务`uk-retirement:adeb3227-0ee4-5d48-bfb0-b7b2e8bc5156`，04:07:37 COMPLETED。精确Scope site266/lang_region39/gid1327/top_cid1/sid7645/goods0/cid0/aid0，原ID1、factor0.9100、status1→0。采用停用保留原行与回退证据，已撤销折扣效果，非物理删除历史记录。只发一次现有地区写入，传输声明SHA`4e5d6461c3d9260404596a3b70e1d5bf6485922ad0414cc35aae2b5773106625`。

停用前后完整双20均通过；缓存cleared、全球verified、Saudi21及UK39各三平台verified。英国三平台最终均继承全球，沙特原系数与价格不变；其他英国优惠、币种、其他游戏不在本次修改范围。

## 发布、知识与使用入口

| 发布编号 | 已核目标 | 用途/清单SHA |
| --- | --- | --- |
| nav-20261026T190500Z | 31/31 | 双20/无预算；c966303622b6593fbc2eec1c9c935019bce6c25e5bd289c2cad537a1a4989593 |
| nav-20261026T190700Z | 17/17 | 教材-4；3021fd3c806fb2510e4e623ab80fa73f83ccbcde0b3f3b5486c145dd8795106e |
| nav-20261026T195100Z | 23/23 | 英国及类别联动；7f6a14ba780e0eeacd4ce95127f8fe0c8159c5b12a395ad01d31f0cc33c8b89c |
| nav-20261026T201700Z | 2/2 | 队列错误退避与专项显示；7f46586d412fdc98d34dc3128ff46593b6dcacc5c7950df003a5bf1c69e24aa7 |

全部沿现有publisher、锁、CAS、备份和健康检查。备份位于`/var/backups/fs-navigation-20261006/<发布编号>/`；回退仅恢复适用V3文件，不倒退generation、业务账本、财务政策或恢复退役旧调度。

教材`fc-pricing-v3-20261026-4`，实际wulv/FS/fs选择13条、25990字符，完整基准SHA与目录匹配。每日只读/不逐轮审核/退役旧采集条款在真实装配中存在，未额外调用第二次模型。当天每日模型已完成，但依据补丁前历史快照，页面明确标历史；这不证明模型已独立掌握新双20规则。

界面实查：当前冲额、ACTIVE、120分钟、07:12下轮、最新公开8.72/8.72/8.80，无预算输入，五策略说明及[完整使用指南](USER-GUIDE.md)入口可读。[工作台](https://47.85.224.112/dashboard/fc27-coins.html)；[Notion业务规则](https://app.notion.com/p/3ff9a8a79c4e81bc8a4feb15aab87a5a)同一同步编号已更新预算、英国和退役真实状态。

## 共享会话恢复后的真实入口核验

05:50–05:51原8767共享会话入口曾HTTP503，具体captcha_ocr_failed:captcha_http_502；原四次只读失败完整保留。05:55:45该入口已沿自身流程恢复HTTP200，没有盲重启、改账号或导出令牌。

恢复后原只读任务`99a13d4c-10ed-442c-81e2-ea1cf60e4231`于05:57:56完成，ready/error为空、业务结果INFEASIBLE。Lootbar、ItemD2R、Arab-UT所需覆盖ready、无缺项，Arab普通报价available，成本、优惠、汇率和地区上下文已进入完整pricing_snapshot，输入SHA为`c55644a524fd74839f3602140131810742bc813dc6bcdc6759836a3c486d4d14`。唯一snapshot_ready事件1条，回执execution_authorized=false、无可执行动作。生产operations仍3条、分配仍3条，计划ACTIVE、下轮07:12:35不变。

真实页面已显示同一最新快照和INFEASIBLE，不再展示03:09旧候选；PR526把重复的逐候选原因归并为三项不同原因，原明细保留。此轮证明HTTPS取数、完整无解记录与页面恢复，不是新的写价成功。Arab-UT PC普通报价仍未提供、地区竞争带及当前共同写入顺序限制真实保留；详细时点及原失败见[接续核验](NATURAL-AND-FAULT-ACCEPTANCE.md)。

## 真实数据与未验范围

- 原七日匿名历史2352笔，平台2351笔；最近新窗口10/20–26的Coins预测Console1828、PC490笔，以每6小时真实订单速率、净AOV和含赠交付K建基数。弹性拟合及不确定性模块已实际接入，当前合格价格窗样本未成熟，仍使用先验2及0.5/1/2/4假设情景，不叫当前已拟合或真实增益。
- 历史实际后台任务已运行：7日2344笔/$142359.73、14日4911笔/$312918.40、28日11429笔/$739940.81、上月5278笔/$311408.47。这些为原输入，保持不覆盖。新月度任务f7f2d789已通过原生缺日补齐形成5308笔/$314630.74、平台5308笔全部可核；仍为部分总体，不冒称完整经营结果。不同窗口/产品覆盖口径分别保留，详见历史覆盖核验。
- 已覆盖同单CNY收入减历史实际采购成本可重建采购毛利；缺历史USD换算、原优惠条款、原公开价窗口及退款修订时，旧策略因果增益和完整历史反事实仍不可验。
- 04:36真实同快照在新计划默认参数及现有授权资源下，日常20/拉新9/积压25/促销4个候选通过完整双20；冲额无合法共同中间路径，准确返回INFEASIBLE。它们是历史只读候选，未启用或写价。容量来自已记录吞吐估计，档案截止和覆盖见接续核验。
- 每日影子已真实运行，隔离oneshot/只读库/PrivateNetwork/无writer，使用原日保存时段数据。跨日持续运行和长期经营收益尚未取得自然周期证据。
- Watchdog/恢复回归含原ID、UNKNOWN不重发、去重、服务冷启动、只读影子隔离及队列错误退避；现场已对账NOT_SENT、原失败和发布健康等待。未做破坏性生产浏览器故障注入，也未声称全部故障路径都在线注入通过。
- 05:10首个新合同自然周期已实际完成，无新写入、无技术重试，按正常周期继续；随后更多周期无重复写入/旧策略回摆/无限重启和下次跨日影子仍待真实时点逐轮核证。现场隔离影子损坏输入、恢复、重复消费及并发锁测试已通过，未向生产浏览器注入破坏性故障。

私有原样证据保留在本任务`.agent_runtime/fc-pricing-v3-20261026/`：first-dual20-acceptance.json、uk-retirement-acceptance.json、legacy-retirement-acceptance.json、current-source-7ca8b90.json及原发布日志。完整订单、会话和后台载荷未上传Git或Notion。
