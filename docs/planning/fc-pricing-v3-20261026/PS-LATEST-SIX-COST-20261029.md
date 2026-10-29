# FC27 PS 最近六条有效发货成本（2026-10-29）

用户确认：PS 与 Xbox 共用 PS 最近六条有效订单发货的最高采购单价；PC 原成本规则、采集和执行间隔保持。

PS 直接限定 Order `gid=1322`、`aid=21942`、`cid=1`、`genre=1`；初始从本次此刻向前一小时，不足六条自动扩为两小时，之后继续扩窗，沿原有效成本八日边界。每个窗口完整读主发货表，按交易时间、数字订单 ID 从新到旧排序、去重，再取六条中的最高 CNY/K。时间窗和选中来源随六条证据保存；样本不足、重复 ID 冲突、筛选不符或分页上限不能冒充完整。

后台交易时间表头没有排序控件，因此程序完整读取窄窗口后本地排序。原页面全页 `hasDataRows` 会计入汇总表，PS 判空改用主发货表行数；PC 仍使用原七日、十五页和最新有效单规则。PS/Xbox 共用同一成本、来源 ID、交易时间及六条样本。

规范化和财务消费者均检查新合同 `ps_latest_six_valid_order_delivery_max_v1`，拒绝旧单条成本 payload。Hermes financial 副本同步，`pricing_simulation.FINANCIAL_SHA` 同步新源码。原历史快照与旧操作不改写，本次代码不写价、不重置计划或间隔。

## 发布范围

精确五个 existing 目标：`collect_p2pah_cost.py`、`snapshot_layer.py`、FC/Hermes 两份 `fc_pricing_v3/financial.py`、Hermes `pricing_simulation.py`。将 collector 纳入原 V3 映射（99 总目标），仅选择 `fc-pricing-v3-ps-latest-six-cost-20261029` 五目标 delta，NEW=0。继续使用原 publisher 的 CAS、原锁、备份、停读者/恢复和回读；不整包覆盖其他活动源。

## 当前验证边界

- 离线定向覆盖顺序、唯一 ID、样本不足扩窗、高价第七条排除、Xbox 不能覆盖、PC 原值/缺项、边界含 end、旧 payload 和坏边界拒绝。
- 真实只读参数核验：PS 21942、订单发货 1，后台秒级 start 生效；一小时窗口 20/0 两页、4.594 秒；两小时窗口 20/11/0 三页、9.433 秒。仅为采集证据，不是上线、自然周期或新售价验收。
- 完整正式 CI、合并、受控发布和下一自然周期分别验收，不由此文提前宣称。
