# Admin 写入迁移规范（浏览器模拟登录 → 数据中台 HMAC API）

> 适用范围：FS、球类（FC/NBA/MLB/NFL/CFB）、营销、活动模块、Hermes。
> 生效：2026-10-27。**禁止再使用“模拟登录 + BATOKEN + 图形码/Google 6 位码”的旧链路取数或写入。**
> 读取规范见同目录 `README.md`；本文件只管写入与权限。

## 1. 为什么必须换

- `chenchao`、`wulv` 等可模拟登录的账号已全部启用 Google 6 位动态码，且登录已被限流。
- 两个 API 账号 `wulvapi`(id 11169)、`chenchaoapi`(id 11167) 的 `google_enabled=false`，**免 6 位码**；
  但二者 `super=false`，**不是 root**，只能按角色菜单授权。
- **不需要给 root**。商品/模型已证明“逐菜单授权即可工作”，给 root 只会扩大 API 账号风险面。

## 2. 统一调用方式

```
POST http://127.0.0.1:8912/admin/<controller>.<action>     # 主线（wulvapi）
POST http://127.0.0.1:8911/admin/<controller>.<action>     # 备用（chenchaoapi）
```

- 代理自动补 `X-Dc-Key/Secret/Timestamp/Nonce/Sign`，并剔除 `cookie/batoken/authorization`。
- **不要再写登录、取 token、OCR、Google 码逻辑**；`p2pah_auth.Session` 已封装好，直接复用。
- 容器/其它 netns 访问不到 `127.0.0.1`，用 `172.20.0.1:8913`（已配置转发到 8912）。
- 签名 path：去 `/index.php`、去 `/admin`、`.`→`/`、全小写。body 必须与签名原文逐字节一致。
- 必须带浏览器 UA 与 `server: true`（代理已内置，业务侧不用管）。

## 3. 接口与权限矩阵（2026-10-27 实测，8912）

| 业务操作 | 方法 | API 路径 | 签名 path | 现状 |
|---|---|---|---|---|
| 商品列表 | GET | `/admin/goods.Goods/index` | `goods/goods/index` | ✅ `code:1` |
| 商品详情 | GET | `/admin/goods.Goods/edit?id=` | `goods/goods/edit` | ✅ |
| **商品改价/编辑（FC 球员维护、NBA 改价、FC 卡包）** | POST | `/admin/goods.Goods/edit` | `goods/goods/edit` | ✅ 空 body 到业务层 `Record not found` |
| **商品创建（上架）** | POST | `/admin/goods.Goods/add` | `goods/goods/add` | ✅ 提示“请通过产品模型来创建” |
| 模型列表 | GET | `/admin/goods.GoodsMould/index` | `goods/goodsmould/index` | ✅ |
| **模型创建（MLB 新卡）** | POST | `/admin/goods.GoodsMould/add` | `goods/goodsmould/add` | ✅ 空 body 报参数缺失 |
| **模型编辑** | POST | `/admin/goods.GoodsMould/edit` | `goods/goodsmould/edit` | ✅ |
| 订单汇总（看板六卡） | POST | `/admin/order.Order/orderStaticsDetailByEs` | `order/order/orderstaticsdetailbyes` | ✅ |
| 首页/身份 | GET | `/admin/index/index` | `index/index` | ✅ |
| **订单列表/下载** | GET | `/admin/order.Order/index` | `order/order/index` | ❌ 401 |
| **折扣码 列表/创建/编辑** | GET/POST | `/admin/market.Discount/{index,add,edit}` | `market/discount/{index,add,edit}` | ❌ 401 |
| **优惠券 列表/创建/编辑** | GET/POST | `/admin/market.Coupon/{index,add,edit}` | `market/coupon/{index,add,edit}` | ❌ 401 |
| **券使用日志** | GET | `/admin/user.MemberCouponLog/index` | `user/membercouponlog/index` | ❌ 401 |
| **会员统计** | POST | `/admin/stats.MemberStats/summary` | `stats/memberstats/summary` | ❌ 401 |

**判读规则**：`code:1` 才是成功；`code:0 + Record not found / 参数缺失` 表示**已有权限、到了业务层**；
`code:401 + You have no permission` 才是没权限；`签名无效` 是签名 path 算错；`密钥无效` 是 Key 错。
**空 body 不会创建数据**，可作为权限探针；不要为验证去真写生产数据。

## 4. 各模块落点

| 模块 | 写入接口 | 当前状态 |
|---|---|---|
| MLB 新卡上架（`mlb-admin-write`） | `goods.GoodsMould/add`、`goods.GoodsMould/edit` | 已切 8912，权限齐 |
| NBA 改价（`nba-reprice`） | `goods.Goods/edit`（先 GET 详情再 POST） | 已切 8912，权限齐 |
| FC 卡包（`fc27-pack-bundles`） | `goods.Goods/edit` | 已切 8912，权限齐 |
| FC 球员维护 / 金币全目录（`fc27-cloud-browser`） | `goods.Goods/edit` | 已切 8912，权限齐 |
| FC 自动改价 | **写 storefront（非 Admin）**，不受本迁移影响；`business_source` 读订单/券仍 401 | 读取待权限 |
| 活动页前端（公开配置、加购、`/ajax/discount`） | 主站公开接口，非 Admin | ✅ 不受影响（`campaign-preview-10` 200） |
| 活动页后台优惠配置（`campaign_backend`） | `market.Coupon/edit`、`market.Discount/*`、`order.Order/index`、`user.MemberCouponLog/index` | ❌ 等权限 |
| 折扣码/优惠券创建 | `market.Discount/add`、`market.Coupon/add` | ❌ 等权限 |
| 订单下载 | `order.Order/index` | ❌ 等权限 |
| Hermes 数据调取 | 容器封装 `business/fc-capability` 等（已 dc 化） | ✅ 恢复，无需改代码 |

## 5. 写入 SOP（每次写操作都必须照做）

1. **写前读**：先 `GET .../edit?id=` 取原始行，保存快照（用于回滚与比对）。
2. **最小字段写入**：只改需要改的字段，不整行覆盖；金额/价格用字符串与后台同精度。
3. **写后读回**：再次 `GET .../edit?id=`，逐字段比对目标值；不是 `code:1` 或读回不一致都算失败。
4. **失败回滚**：把第 1 步快照写回，并再读回确认；记录 `operation_id` 与失败原因，不盲目重试。
5. **禁止事项**：不拿生产商品做“试试看”的写入；验证写入用专用测试模型/商品，并走“创建→读回→删除”闭环。
6. **审计**：所有写入记录操作者（API 账号）、时间、接口、前后值，写进 `HANDOFF.md`。

## 6. 退役清单（旧链路，禁止再启用）

- `POST /admin/index/login` 模拟登录、BATOKEN 换票、图形码 OCR、Google 6 位码输入。
- 依赖 `P2PAH_USERNAME/P2PAH_PASSWORD` 的登录态维持逻辑（`fc27-p2pah-session` 的 login/refresh 已在 dc 模式短路）。
- 旧的“浏览器点后台”作为**主写入通道**。浏览器只保留为**API 不可用时的应急人工兜底**，且必须单独说明原因。
- 规则上：任何新任务不得再以“账号能登录”为前提设计采集或写入。

## 7. 筛选参数语法（2026-10-28 实测，含一次误判的纠正）

| 写法 | 结果 | 说明 |
|---|---|---|
| `search[i][field]=gid&search[i][operator]=%3D&search[i][val]=1327` | ✅ **有效** | 返回行 `gid` 纯净，只有 1327 |
| `search[i][field]=paytime&search[i][operator]=RANGE&search[i][val]=<start>,<end>&search[i][render]=datetime` | ✅ **有效** | 时间范围标准形式 |
| 简单参数 `site_id=266&gid=1327` | ❌ **看似有效、实际无效** | 返回的是接口**默认范围**，不是筛选结果 |
| `paytime[0]=…&paytime[1]=…` | ❌ 无效 | — |
| `start_time=…&end_time=…` | ❌ 无效 | — |
| `paytime=<start>,<end>`（整串） | ❌ 无效 | — |
| `search[i][val][0]/[val][1]`（数组） | ❌ HTTP 500 | — |

**最危险的陷阱是"简单参数"**：它不报错、`total` 量级看着也合理，但只是默认范围，会**静默漏数据**
——实测同一查询（今日 FC27）简单参数只得 **69 单**，真实为 **194 单**。

**判定筛选是否真的生效，必须检查返回行的字段值是否纯净，不能只看 total 大小。**

### 一次误判记录（供后人避坑）

2026-10-28 上午用 `site_id` 字段测等值 search，得到全站量级，据此误判"search 等值语法无效"，
把 `channel_source.search()` 改成简单参数，导致 40 分钟内查询结果残缺（今日 194 → 69 单）；
后改用 `gid` 字段并校验返回行 `gid` 纯净度，才确认等值 search 本来有效，随即回滚。
根因：**`site_id` 不是该接口的可筛字段**，不能用它的表现推断整个等值语法失效。
`channel_source.search()` 现维持**原始 search 语法**（等值 + RANGE 都走它也有效）。


## 8. 分页容错（2026-10-28）

`channel_source.pages()` 在原逻辑上补了两处，针对实时写入表：

- **总数增长**：翻页期间插入新行导致 `total` 变大 → 接受并抬高总数，不再抛 `admin_pagination_changed`；只有**减少**才报错。
- **行位移重复**：offset 分页在插入后会让同一行出现在两页 → 跳过已见 id 继续累计，不再抛 `admin_duplicate_page`。

代价是可能漏掉极少数新插入行，对统计类用途可忽略；**不允许**用于要求绝对完整的逐单核对场景。
按日期窗口查询（几十~几百单）本身稳定，全量历史翻页才会抖。

## 9. 需要技术补的菜单（只读/写入按最小集）

| 菜单 | 用途 | 影响面 |
|---|---|---|
| `order/order/index` | 订单列表/下载 | 自动改价 business_source、毛利卡、订单导出 |
| `market/discount/index` + `add` + `edit` | 折扣码管理 | 活动优惠、自动改价优惠口径 |
| `market/coupon/index` + `add` + `edit` | 优惠券管理 | 活动优惠、自动改价优惠口径 |
| `user/membercouponlog/index` | 券使用日志 | 归因、营销汇总 |
| `stats/memberstats/summary` | 会员统计 | 营销汇总 membership |

开完权限后按本文件 §3 重测，再恢复：自动改价整轮、毛利卡、营销四项、
`sales-dashboard-sync`、`fs-user-analytics`、活动后台优惠配置。
