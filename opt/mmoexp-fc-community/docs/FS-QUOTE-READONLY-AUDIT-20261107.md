> **最新口径更正：** 用户随后明确要求使用网站折后实际售价，划线价仅营销展示，不是真实原价。本报告中原价选型是首版历史，已被替代；适配器现使用 Goods.price / price_basis=sale，ManCity PS5=8.21 USD。字段观测数据仍有效。
# FS 商品只读核查（2026-11-07）

范围：187 上 FC27 商品类别、商品和模型只读查询；没有客户数据、凭据或商品写入。测试机器人使用独立受限适配器，不能开放后台代理的通用转发。

现场客户端 `/opt/fc27-sbc-tool/admin_client.py` 的 `AdminClient` 使用共享会话；默认 `http://127.0.0.1:8911`，不是源文件旧注释中的 8767。它的 `list_goods`、`get_goods`、`get_model`、`category_tree` 分别读取 `/admin/goods.Goods/index`、`/admin/goods.Goods/edit`、`/admin/goods.GoodsMould/edit`、`/admin/goods.GoodsCategory/categorySelect`。列表须分页；类别树须动态读取。现役 `get_model` 返回整个响应，实际模型在 `data.row`。

游戏 gid 1327，MMOEXP 真实站点 site_id 266；aid 21587、21585、21589 分别是 PS、Xbox、PC。`site_id=0` 是模板，并非该站点价格。SBC 父 9625 的现场子类含 9971、10203；Packs 父 9629 子类含 10255。Gallery 的套餐父类 10211 和 10063 分别含 10213、10067，不能按重名商品合并。

用户指定的“原价”是网站划线价。按主线程同一时间在官网 US/USD、PS 查看，并在 187 用商品详情 GET 回查：

| 类别 / 商品 | goods id | 商品 price | 商品 unit_price | 数量 / 折扣 | 官网观察 |
|---|---:|---:|---:|---:|---|
| Packs / ManCity11-PlayerBundle | 185327195 | 8.211 | 11.73 | 1 / 70% | 售价 $8.21，划线 $11.73 |
| SBC / Loïs Openda | 187292685 | 10.03141 | 10.03141 | 1 / 100% | $10.03，无划线 |
| Gallery / Your Coins / From 0 to 500 Tokens | 184515837 | 23.45 | 23.45 | 1 / 100% | $23.45，无划线 |
| Gallery / Coins Provided / From 0 to 500 Tokens | 178574883 | 36.65 | 36.65 | 1 / 100% | $36.65，无划线 |

这些是商品 Goods 行的实测；不能把其他合同或模型字段同名的 price 直接套用到此处。此样本的商品 `price` 是折后额、`unit_price` 对应划线额，故适配器仅处理数量为 1、简单 SKU、无属性选择、有效状态与价格关系一致的行；SBC 和 Gallery 限制为未折扣行，直到各自折扣原价得到页面实证。金额使用十进制四舍五入到 USD 两位。商品和模型状态以及站点和平台在最终报价时重新读取。仅在后台状态不代表网站实际履约能力；复杂选项和 Coins 等没有纳入报价。

官网类目入口：[SBC](https://www.mmoexp.com/Fc-27/Sbc.html)、[In-Game Packs](https://www.mmoexp.com/Fc-27/Packs/In-game-packs.html)、[Gallery Your Coins](https://www.mmoexp.com/Fc-27/Boosting/Gallery-your-coins.html)、[Gallery Coins Provided](https://www.mmoexp.com/Fc-27/Boosting/Gallery-grade-2.html)。后台行 slug 为空，不拼造商品深链。

链接是类目页，并不携带商品或平台选择：用户打开后仍需自行选择对应商品与平台，页面金额可能随更新时间改变。当前适配器不提供 Coins、Players、Evolutions、其他 Boosting 类目，或需要额外 SKU/属性选择的商品；SBC、Gallery 的折扣行也暂不提供。类别菜单存在不代表已有可报价商品，产品状态发生变化时实时查询可能返回不可用。

运行态：`/opt/fc27-sbc-tool/auto_flow.py` 带定时执行采集、上架和改价的完整流程；现场配置 enabled 和 delist_enabled 均为 true，最近记录为当天手动执行，不能把工具当成只读服务。`/opt/fc27-pack-bundles/pack_bundles_server.py` 内置每小时刷新线程，现场自动刷新最近一次为 21:35 成功，配置允许自动写价。机器人不能调用这些写流程。`sbc_index.py` 对照数据站的 GET `/api/sbc` 读取 set_id，后台模型 `data.row.more.extend` 保存 `set_id`；Players 模型 extend 的 `player_id` 为 Futbin ID。set_id 名称匹配可能歧义，缺失时不可猜测；未验证这两个标识是否始终正确。

本地 `quote_catalog.py` 使用 `QuoteCatalog(AdminClient())`，只调用前述只读方法；`tests/fixtures/fs_pack_sample.json` 是商品字段白名单，无客户信息与凭据。内存执行现场核验了四个 PS 报价、商品列表及三个平台选项；不等于已部署或自动通知。

