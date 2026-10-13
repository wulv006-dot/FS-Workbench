# Admin 读取入口核对

2026-10-13，用户补充 Admin“订单统计”“统计管理”均有可检索经营数据。使用现有合法 Admin 读取器原认证流程，GET `/admin/index/index` 实际 HTTP200/code1；仅导出菜单路由，未导出账户、凭据或业务原始明细。

| 正式菜单 | 本次实际返回的相对路径 | 当前能力证据 |
|---|---|---|
| 订单管理 | order/order | 当前菜单存在；FCDetails当前已复用订单支付明细与未完成池 |
| 统计管理 | stats | 当前目录存在，不能把不同子项口径当成相同 |
| 订单统计（Es） | statics/orderEs | 当前菜单存在；已有经营原生聚合合同含付款人数、新客、退款、支付成功、发货完成率等 |
| 会员统计 | stats/memberStats | 当前菜单存在；本任务未重新核字段/期间/FC分组支持，不声称已接通 |
| 订单处理效率分析 | stats/orderLog | 当前菜单存在；本任务尚未核事件/时长/分母，不能声称已有P50/P90 |
| 产品销量排行榜 | stats/productSalesByEs | 当前菜单存在；2026-10-04既有正式接口/分页/目录分类合同供复用，金额币种/代表SKU限制保持 |
| 订单统计 | statics/order | 当前菜单存在；独立于orderEs，待核实际字段与范围 |

第一次只创建SessionManager而未调用其原ensure流程时token为空，仅说明该新对象尚未初始化，不能被写成Admin生产会话失效。后续按现有正式读流程已成功得到上述菜单；没有绕登录或新建凭据。

历史资料 `docs/planning/fc27-product-facts-p2-20261004/NATIVE-RANKING-DISCOVERY.md` 和已有 supplement_fields.py 仅作接口合同线索，本日菜单存在性与字段实际读取分别验收。旧资料Order主源表述属于历史，本任务仍Admin主源、Order参考利润/明细补源。
