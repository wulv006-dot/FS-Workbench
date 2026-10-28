# 当前合同与教材10候选

2026-10-29。用户最新授权的平均20%红线窗口是 Asia/Shanghai 日期D的D-9至D-2，含首尾8完整日；当D=2026-10-29时为10/20–27。合并8日同群体净实付与ES实际优惠USD总额后计算留存，不按单日率等权；成本/竞品/FX仍为当轮。

生产financial=`fc27_dual20_d9_d2_v2`、mix.history_window_contract=`d9_d2_eight_closed_days_v1`，锚点策略`sprint_5_10_lower_quote_floor20_v3`不变。核心、旧快照只读验证、同ID迁移及ES实数覆盖由P1/root负责，本候选不执行迁移/下载/模型/价格操作。

## 精确文档与知识范围

只更新5份当前规范：BUSINESS-BASELINE、HERMES-OPERATING-CONTRACT、DUAL20-NO-BUDGET-CHANGE、SIMPLIFIED-OPERATING-CONTRACT、USER-GUIDE。当前财务相关七日文字改成8日滞后窗口；orders_per_block七日168小时、UI历史7/14/28日、看板/日报/学习窗口和计划期限保持。

当前baseline和HERMES合同还明确：归档取消07硬停、按原分项状态与预算接续，瞬态退避、明确错误仅停止对应项；消费者保留可用证据、披露缺失/原因/重试/终态，不依赖整轮归档或准备线程结束；全局快照/统计锁不跨网络等待拖住其他可用入口，原Order串行、写价所有权、CAS/UNKNOWN仍保留。缺项报告规则不豁免真实改价财务证明。报告07:49/50截止未擅改。

`knowledge/index.json`升candidate release10，保25条索引、14条current和原13默认entry IDs。必要原builder/release/prepare pins同时更新；原冻结publisher不变，旧source/knowledge副本、knowledge/history和已发布8/9均不改。

## 默认13条冲突检查（候选离线选择，不冒称生产10已加载）

| 默认entry ID | 核对结论 |
| --- | --- |
| fs.data.sources | Admin优先/Order补缺；选定内容与9逐字相同，不含旧七日财务规则 |
| fs.data.currency | USD/CNY来源与换算原则相同；不推广历史窗口到本轮FX |
| fs.customer.identity | 客户身份原则相同，无财务窗口变更 |
| fs.finance.procurement | 实际采购与同群体成本原则相同，不改报告或看板分母 |
| fc.pricing.constraints | 原current错误指向V2双10/昨日止七日。现同ID改指当前HERMES“财务、竞品和地区”段，revision为fc27_dual20_d9_d2_v2，只选双20/D-9..D-2八日，不默认装载旧约束 |
| fc.marketing.attribution | Aion2分销等已核归因与9逐字相同，不改财务窗口之外口径 |
| fs.procurement.inputs | 采购输入/费用原则与9逐字相同 |
| fs.pricing.parameter-identity | 参数与资源身份原则与9逐字相同 |
| fs.product.identity | 商品身份原则与9逐字相同 |
| fs.customer.lifecycle | 生命周期与人数口径与9逐字相同，不把观察窗口改8日 |
| fs.learning.methods | 方法与训练边界与9逐字相同，七日168小时示例保持 |
| fs.project.execution | HOTFIX执行、锁和原ID要求与9逐字相同 |
| fc.pricing.v3 | 当前合同revision为fc-v3-lag1-eight-day-20261029；新8日财务、归档全天/明确缺项与锁规则，原双模式/较低锚点/权限边界保持 |

选定内容实际只有fc.pricing.constraints与fc.pricing.v3两条变化，其他11条逐字相同。13条均无“最近七日财务窗口”或当前≥10%硬线冲突。完整baseline的source SHA变化需更新10个引用pin，但不是10个选定业务段全部变更。dashboard合同仍不新增进默认13条。

## 真实源/目标库存与原流程

被替换current条目原先引用的V2 MARGIN-REDLINES.md仍由原`fc.pricing.decision-v15`历史决定引用，文件和冻结SHA保留。因此实际非candidate唯一源仍14份，无人为补空源：artifact14 source + index =15 immutable NEW；runtime完整baseline + policy=2 existing，共17targets。

相对于教材9只有baseline、HERMES两份源文档内容变化，V2旧规则文件不变。新baseline SHA `2914912d667ece60ad3ac5a06585f9edfd4e82af95d6dc827a32ac5a62f7332a`；新HERMES SHA `64a9f67bcb5f82d932bdcdd00c4350fbc4e5e64d33738751e22ae133bfbb106b`。

原prepare10旧CAS：baseline=`6f418d35c37d8fadd44b78fb4e1090afce3c90901cc3912fbde2d0afc56058e8`；policy=`d504f83bfd02b8ade1379358344e45c881bacbad0959ee1e10385e7208c7d3ce`。发布前仍须按原流程重核真实CAS/保护，不复用过期manifest。

## 验证与未执行

知识87本地通过，原byte-pin插件工作字节已完整恢复；13默认条目的真实selector、source SHA和语义差异已离线检查，历史V2源及其他未改源保持原hash。共用分支上未提交，root统一审阅、提交和正式CI；真实Git-blob build_stage需在统一commit后重建，不能拿HEAD9包冒充候选10。

尚未制作正式catalog SHA/manifest，未stage/prepare/apply、未更改生产policy、未触Notion、未建模型任务。root runtime证据：`p2_knowledge10_default13_review.json`、`p2_knowledge10_87.stderr`及`p2_knowledge10_candidate_sources.json`。
