# Player 只读目录开发记录

`player_catalog.py` 是独立适配模块，未接入报价 socket、Discord、FS 控制台，也未部署。它复用现有 SBC AdminClient 的只读模型/商品接口，限定 gid 1327、Players 叶子 cid 9627、美国站 site 266。不得把后台客户端的其他方法透传给 bot。

## 接口与配置

`PlayerCatalog(client, verified_prices=None, tag_client=None, allowed_tag_ids=())`：

- `search(query, limit=25, page=1)` 使用后端 `title_like` 子串搜索（不是容错拼写搜索），输入去首尾空格后 2–80 字符，拒绝 SQL LIKE 通配符，单页最多 25 条，最多 10 页；结果为 `items/page/has_more`。UI 应先搜索再选卡，不加载全部球员到下拉菜单。
- `featured(featured_model_ids)` 按 FS 配置的模型 ID 顺序读取，最多 25 条；失效或跨类目 ID 拒绝整组。模型 ID 是稳定选择键，名称、rating、位置、卡版本、Signature 等以模型标题展示；返回的 `futbin_player_id` 来自 `more.extend.player_id`，不能当作 EasySBC ID。
- `tags()` 只返回 `allowed_tag_ids` 中、当前有效且属于该游戏/类目的标签；`browse_tag(tag_id, limit=25, page=1)` 从后台模型原始页的 `tid` 本地过滤，每次最多读 25 条、最多 200 页。`has_more` 代表后台原始页还有数据，某一页没有匹配也可能后续有；不要把它解释为精确匹配数量。模型列表并未核实服务端标签筛选，故不向后台猜传过滤参数。
- `tag_client` 要实现 `list_tags(gid=1327, cid=9627)`。现有 `/opt/fc27-player-tool/releases/2026.11.07-cloud.21/球员维护工具/admin_client.py` 通过只读 `GoodsTag/index` 实现，按 gid/cid 本地过滤；SBC 客户端同名方法走 `tagSelect`，当前账号返回 401，不能用于本功能。已有 Player 工具保持停机；连接其客户端需要在服务进程中安全接入共享登录态，不能把 token 暴露给 Discord。引用路径、客户端加载和进程权限由整合阶段验证，不要直接启停该工具。
- `options('players:<model_id>')` 和 `quote(product_id, goods_id)` 默认拒绝价格，只有 `verified_prices={model_id: [platform_aid, ...]}` 显式列出的组合可报价。报价时重读模型及具体商品，检查站点、类目、平台、状态、标题一致、数量、价格和空销售属性等；返回当前 `Goods.price`，USD 四舍五入两位。禁止在没有逐卡、逐平台网站比对的情况下加入配置；核验只是时点证据，发布前应重验。价格页链接仅到 Players 总页，不承诺预选卡片或平台。

## 网站比对（2026-11-08，只读时点）

公开 [Players 页面](https://www.mmoexp.com/Fc-27/Players.html) 的 PS5 默认卡片，`data-id` 对应后台商品，`data-attr` 为空；以下四项名称、评分、位置、卡版本及 ID 一致，网站显示价与后台 `price` 四舍五入一致：

| 模型 ID | 商品 ID | 球员与卡片 | 网站 USD | 后台 price |
|---|---|---|---:|---:|
| 45490827 | 187277461 | Tabitha Chawinga / 89 / LW++ / UWCL RTTK | 226.92 | 226.9245 |
| 45490779 | 187277173 | Romelu Lukaku / 87 / ST++ / UCL RTTK | 10.14 | 10.14486 |
| 45490783 | 187277197 | Marcos Llorente Moreno / 88 / RB++ / UCL RTTK | 82.32 | 82.31575 |
| 45490797 | 187277281 | Yui Hasegawa / 89 / CDM++ / UWCL RTTK | 53.39 | 53.394 |

这四项后台均为 `sku_switch=0`、`attr_switch=1`、`num=1`、`more.saleprop=[]`、`more.skuTableSet=[]`；官网加购 `data-attr` 空，支持这些样本没有用户选择的销售属性，不证明所有球员均如此。PS5 aid 21587；Xbox 21585 和 PC 21589 尚未逐项核价。可经复核后配置 `{45490827:[21587],45490779:[21587],45490783:[21587],45490797:[21587]}`；默认不启用任何条目。

同日将本地模块通过 SSH 标准输入送入一次性 Python 进程，只读调用真实 AdminClient，Haaland 搜索返回 3 个不同模型；四项报价分别返回上表金额。用现有 Player 标签客户端及共享登录态在进程内只读验证，白名单中的 Champions League、Popular 可读取，Champions League 原始第一页过滤出 25 项。没有部署代码或启动 Player 工具。此验证以 root 运行，正式服务的账号权限及加载方式尚待检查。

## 整合工作

FS 控制台需保存 `featured_model_ids` 和 `allowed_tag_ids`；后台读取时进行长度、ID、类目及有效性校验。实现限定操作的 bridge 和异步 UI，私密展示卡版本与平台，再读实时价；价格异常显示不可用，不展示旧价或猜价。标签按原始页分页可能出现空页，UI 必须允许继续。加入对应鉴权、速率控制、错误脱敏及重启/多账号验证；暂不接入 EasySBC 事件或声称可调用其 slash 命令。
