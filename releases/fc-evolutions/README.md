# FC27 Evolution现行维护入口

2026-11-10用户确认PS、Xbox、PC独立报价、平均优惠与核算；Coins财务基准为购买并交付100K、无5K赠送，版本`fc27_dual20_d9_d2_platform_100k_v4`、范围`fc27_three_platform_v1`。1000K及以上额外赠送作为让利，不列为自动硬门槛。历史原操作的赠送及实际成本按当时记录解释，不重写。

187现役服务为`fc27-evolutions.service`，真实源码`/opt/fc27-evolutions/source/evolutions.py`，2026-11-10只读SHA`02931d6dbd00a7ce7c6dcf349f77999d6257111f444a8075a8433ae6ee0d14cd`。本目录只提供维护入口，尚未把完整现役源归库；[fs_mcp_connector/evolutions.py](../../fs_mcp_connector/evolutions.py)是只读消费连接器，不能代替服务源码发布。

已核`Backend.rates`按Order gid1322各area独立取PS/XBOX/PC b2c美元/1K，拒重复或缺平台；`plan`按各商品aid使用本平台rate与本平台fixed override，`target`按金币数量/1000×该rate×加成。写前比较原商品字段，`confirm_price`读取该商品的price、unit_price与discount核对目标。没有已证PS美元价复制给Xbox的分支，保留此独立能力；不因共享市场数量参考绑最终售价。

Coins100K无赠的本平台购买基价继续作为美元rate；Evolution的商品数量、显式固定价、加成和商品折扣维持自身业务公式，不把Coins八日优惠重复施加。缺Xbox rate必须明确缺项，不能PS补位。

当前证明层级是现役代码摘录/哈希与独立平台路径；差异rate的完整运行验算、源码归库和现场全部读回未完成，不能据本说明宣称已上线新合同。完整源导出受到自动审批拒绝，未绕过或从旧副本覆盖。后续发布需先核该服务自己的原维护/发布证据，不用连接器publisher替代；本轮统一状态见[三平台计划](../../docs/planning/fc-three-platform-20261110/PLAN.md)。
