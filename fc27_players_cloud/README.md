# FC27 Players现行维护入口

2026-11-10新Coins合同：PS、Xbox、PC各自使用真实平台的Coins美元基价与八日优惠；自动财务基准为购买并实际交付100K，无5K赠送。版本`fc27_dual20_d9_d2_platform_100k_v4`、平台范围`fc27_three_platform_v1`。1000K及以上的额外赠送记作让利，不扩大硬线档位；历史已发生的105K交付、成本和原回执保留当时事实。

球员市场金币数量与美元售价是两层数据：PS/Xbox互通市场数量可作有来源的共同市场参考，不能把PS美元rate、平均优惠、毛利或执行确认复制给Xbox。每个平台的实际商品需按自己的aid（PS21587、Xbox21585、PC21589）、Coins美元rate、数量/加成及本商品折扣核算；缺Xbox美元价不得PS补位。Coins平均优惠只用于对应平台Coins财务核算，不给球员商品重复加折扣。

Players维护走`player_web/existing_action_service.py`→`球员维护工具/admin_adapter.py:AdminAdapter.sync_prices`，按原模型/商品ID调用Admin原`recalcFc27Price`并前后读取实际产品。未核完整公式的结果仅称`completed_readback/formula_verified=false`，不能当成三平台公式已验。2026-11-10只读现场配置release为`2026.11.07-cloud.21`，服务当时inactive，未为验收唤醒；该时点不是长期停用决定。真实容器、bind覆盖与后续版本须在各次发布时核对，不能整包覆盖当前源。

Coins自然跟随入口是[当前player_sync_job.py](../releases/fc-coins/fc-pricing-v3-20261026/source/player_sync_job.py)。新回执要求上述v4及平台契约、严格PS/XBOX/PC金额、原operation/原SHA和Order/Admin确认；旧原操作只按原console/pc历史路径解释，不升格为新执行。原category POST一次、未决原ID对账、既有权限和共享价格锁保持，不恢复已退役抽样或创建额外业务操作。

代码、测试、CI、部署及自然轮分别见[三平台计划](../docs/planning/fc-three-platform-20261110/PLAN.md)。新scope本地实现不表示后台黑盒重算公式已验证；当前仍需原合法只读结果及下一原自然任务补证。Players自身cloud21发布沿[原窄publisher](../releases/fc-players/single-card-normal-20261107/README.md)，本次不因Coins改造唤醒或重发已有球员任务。
