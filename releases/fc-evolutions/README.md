# FC27 Evolution现行维护入口

2026-11-10用户确认PS、Xbox、PC独立报价、平均优惠与核算；Coins财务基准为购买并交付100K、无5K赠送，版本`fc27_dual20_d9_d2_platform_100k_v4`、范围`fc27_three_platform_v1`。1000K及以上额外赠送作为让利，不列为自动硬门槛。历史原操作的赠送及实际成本按当时记录解释，不重写。

187现役服务为`fc27-evolutions.service`，真实源码`/opt/fc27-evolutions/source/evolutions.py`，本轮发布前只读SHA`02931d6dbd00a7ce7c6dcf349f77999d6257111f444a8075a8433ae6ee0d14cd`。已从主PC本地完全同SHA维护源归库并适配正式Admin Session，当前维护源及精确发布步骤见[Admin会话与历史状态适配](admin-session-20261110/PUBLISH.md)。实际上线以新发布回执及源码读回为准；[fs_mcp_connector/evolutions.py](../../fs_mcp_connector/evolutions.py)仅为只读连接器。

已核`Backend.rates`按Order gid1322各area独立取PS/XBOX/PC b2c美元/1K，拒重复或缺平台；`plan`按各商品aid使用本平台rate与本平台fixed override，`target`按金币数量/1000×该rate×加成。写前比较原商品字段，`confirm_price`读取该商品的price、unit_price与discount核对目标。没有已证PS美元价复制给Xbox的分支，保留此独立能力；不因共享市场数量参考绑最终售价。

Coins100K无赠的本平台购买基价继续作为美元rate；Evolution的商品数量、显式固定价、加成和商品折扣维持自身业务公式，不把Coins八日优惠重复施加。缺Xbox rate必须明确缺项，不能PS补位。

原预览失败已沿原任务确认AdminAuthRequired，改为复用8912/8911正式Session，不更换身份、凭据或权限。历史UNKNOWN有后续有效真实Admin现态覆盖后退出当前阻断，保留原未知回执；缺覆盖、在途或新UNKNOWN仍核原ID，不重发旧目标、不恢复过期阻断。后台新写继续原新鲜核价、CAS、锁和单次POST。

两次服务器源码导出被自动审批拒绝后未重做；本轮使用已存在的本地完全同SHA源码。Linux回归、正式CI、部署、实际拉取及原自然调度分层记录于[三平台验收](../../docs/planning/fc-three-platform-20261110/ACCEPTANCE.md)，不以归库或单测冒充上线。原配置、商品、数据库和调度保持，不用连接器publisher替代服务原publisher。
