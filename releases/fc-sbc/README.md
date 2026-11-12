# FC27 SBC与Packs现行维护入口

新Coins基准（用户2026-11-10确认）：PS、Xbox、PC分别使用对应平台真实Coins美元rate，购买并实际交付100K、无5K赠送；八日优惠和双20各平台独立。财务版本`fc27_dual20_d9_d2_platform_100k_v4`，平台契约`fc27_three_platform_v1`。1000K及以上额外赠送作为让利，不进入自动硬门槛，不追改历史赠送/实际成本。

SBC/Packs维护在同一`fc27-sbc-tool.service`中，现役入口`/opt/fc27-sbc-tool/webapp.py`，同目录`pricing.py`、`repricer.py`、`workbook.py`、`uploader.py`。Packs是repricer的类目分支，不等于捆绑包服务。2026-11-10已核live webapp SHA`4289996cc5ff3e739f8bcb14c3ef452b7cc6853708444d6e819ee825bc369c0a`；现有`security-20261015/source/webapp.py`不是该现役完整版本，不得从旧包覆盖。

已核逐aid路径：`pricing.fetch_coin_prices`分别取PS21587、Xbox21585、PC21589的Admin unit_price，`Settings.rate_for`/`GoodsRow.target`及`webapp.do_reprice`按实际行aid/商品ID计算和写入。SBC使用自己的固定费与加成；Packs固定费为0，自己的显式人工覆盖保留。换算必须保留真实单位：Order b2c或Admin单位价为USD/1K时除1000得到USD/枚；100K整包美元价应除100000，不能共价或把含赠送实际交付单价误作购买基价；商品自己的折扣与Coins八日实际优惠不重复扣减。

已核代码存在逐平台能力，但上传/跨平台克隆完整链、后台实际公式和新三平台金额读回尚未完整验。对这些部分不能写“已三平台验收”。完整现役源码读取曾被自动审批拒绝，已停止原样导出；本次没有用旧security副本改运行代码，保持原能力。后续只沿获准脱敏源或原合法业务只读入口补证。

原发布器见[security publisher](security-20261015/publisher/release_navigation.py)，现役另有`/opt/fs-release-stage/fc27-sbc-order-projection-20261110/`工件；旧CAS不复用。当前三平台本地改造与最终验收统一见[本轮计划](../../docs/planning/fc-three-platform-20261110/PLAN.md)。[10/15安全修复](security-20261015/README.md)、[11/8标签修复](tag-index-20261108/README.md)保留各自当时事实，不恢复旧自动开关或覆盖后续现场代码。
