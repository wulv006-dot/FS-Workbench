# FC27 捆绑包现行维护入口

2026-11-10用户确认的新口径：PS、Xbox、PC按各自真实Coins美元单价独立报价。Coins硬线基准是购买并实际交付100K，无额外5K赠送；财务版本`fc27_dual20_d9_d2_platform_100k_v4`，报价范围`fc27_three_platform_v1`。1000K及以上额外赠送属于让利，不加入自动定价硬门槛，也不改变本工具的捆绑包公式。

维护源为[src/pack_bundles_server.py](src/pack_bundles_server.py)及[页面](web/index.html)。187对应`/opt/fc27-pack-bundles/pack_bundles_server.py`与`/var/www/dashboard/modules/sports/bundles/index.html`；原API为`/dashboard/fc27-bundles-api/`。2026-11-10核对的生产基线分别为`67ac2b9010b70ff7153b4e1de1562a19055d9bf2b9ff2de8a4c3fba720baf1f1`、`50f292ce140923951ecfb5f31d47bb9b35b1a0ef10c94d5e299efdbd66398261`。以下新实现已本地完成，正式CI、发布和真实入口状态以[本轮计划](../docs/planning/fc-three-platform-20261110/PLAN.md)及其验收为准，不能据README当作已上线。

每个平台使用自己的Order gid1322、对应area的`b2c`美元/1K；公开页来源按本平台`package_usd/base_k`核算，不能拿PS美元rate补缺Xbox。100K当前无赠；大档赠送不作为降低本工具Coins基价的分母。PS/Xbox同卡的互通市场金币数量可共用真实市场参考，必须在`market_references`标明实际观测平台和共同市场，不伪称Xbox独立观测。金额侧各自计算、舍入、记录`rate_platform`和`pricing_basis`，不再把Xbox写价指向PS结果。

原公式保持：球员实际价=市场金币数/1000×本平台Coins美元rate×加成；划线价=实际价/原划线因子；包售价=各球员划线价总和×原包销售因子；包原价=包售价/原原价因子。各商品自己的折扣及写后读回保持，不重复施加Coins八日优惠。某平台美元rate/必要数量缺失，只明确该平台不可写，不由其他平台补价；完整平台继续按原授权运行。

手动请求在202接受前取得原线程锁及跨进程`write-admission.lock`，持到原结果日志完成；自动和直接dispatch使用同一文件锁。原publisher同锁串行完成源码替换、服务重载和只读加载版本核验；锁忙的新请求明确409且未启动。没有新队列或自动重放。首次从尚无文件锁的旧进程升级，必须先完成已有写入排空与原结果核对，不能凭`active`或单次`last_refresh`直接重启。原`needs_review`/超时不清除，不把后来现价相同解释成历史请求成功。

相关检查：`python -m unittest discover -s fc27_pack_bundles_20261013/tests`；UI两项需Node，跨进程发布同锁需183/Linux实际执行。发布沿[原FC adapter](../releases/fc-coins/fc-pricing-v3-20261026/deploy/fc_v3_release_adapter.py)新精确scope；`deploy/go_live_write.sh`是历史业务写价脚本，不能用作代码publisher。

[2026-10历史交付与验收](../docs/planning/fc27-pack-bundles-20261013/README.md)保留原当时价格、赠送和共价事实，不作为新执行口径。
