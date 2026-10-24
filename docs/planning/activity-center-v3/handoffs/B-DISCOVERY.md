# B 后台只读发现

工作要求：FS-V3-G1-START-01。项目：fs-campaign-center-v3。角色：B，只读发现；唯一工程主控为 /root。

## 范围与证据

- 2026-10-24 在 PC-20260909OJLI 文件系统检查；未 SSH、未请求 Admin/Order、未新增登录、未修改业务代码或共享配置。
- 新检出：`D:\codex\2026-10-24\task\fs-campaign-center-v3`；主控提供的 main 基线 `2c976e7f849b3b7916e006dd6907e633051cb3fb`，独立分支 `codex/fs-campaign-center-v3-20261024`。以下相对路径均对应该检出。
- 已读适用 AGENTS/HOTFIX；已读 V3 本机 ZIP 的两份业务参考中与 B 相关的商品、券管理、归因、数据版本与 W0-W3 内容。V3 排除 Matchday/竞猜/竞猜奖励，普通活动券管理保留。
- 原 E 盘工程及旧私库检出仅用于初始定位，未修改；最终事实以新检出源码为准。未把 release 源码当成生产现场版本。

## 既有 FS 模块

根：`releases/fs-dashboard/campaign-analytics-20261023/`。

| 源码 | 已证行为 | 限制/复用建议 |
|---|---|---|
| `app/analytics/production-server.mjs:18` authorize | 每次向现有 8895 auth verifier 传原请求方法/URI与Cookie，基于返回 user/role 判断；只接受 loopback 反代入口 | 保留原鉴权，不新建后台登录/角色 |
| 同文件 POST 分支 :28-38 | 仅管理员 POST；固定 Origin、JSON content-type、CSRF；限制请求体 300000 bytes | 新管理动作接同一入口边界 |
| 同文件 config/catalog/export :41-47 | 已有配置、商品目录、导出；catalog.js 使用服务端保存的编排 | 当前输出强制 preview；不能靠改字符串宣布生产交易接通 |
| `app/analytics/store.mjs:23-35` makeStore | state.json、revision CAS、operationId同内容重试、历史活动不可删除、history/<rev>.json、atomic写入 | 操作日志仅保留100项，不足以承担长期券/交接去重账本 |
| store validateLayout :13-21 | 从已存在catalog.products中选ID，核商品类型、三人组卡版本、SBC核心与搭档 | 目前不是动态Admin目录；新商品仍需真实目录投影扩展 |
| `app/analytics/products.js` | 现有商品编排消费者 | 应延展现有UI，区分页面展示字段与主站商品字段 |

已有入口：`/dashboard/analytics/campaigns/analytics/`、products.html、connect.html；服务文档记录仅监听 `127.0.0.1:8948`。这些是代码/文档证据，本角色未现场读回。

## Admin / Order 已有消费者

### 会话边界

- `shared_backend_session/shared_admin.py:admin_token_from_service` 只读取 `http://127.0.0.1:8767/session/admin-token`，拒绝重定向、限响应长度、核token形式；错误仅返回 shared_admin_unavailable。不得把token放公开配置/日志。
- `shared_backend_session/sales_auth.py` Session：绑定 Admin owner token，不独立登录；Order 从服务器现有 `fs_order_client` 填受限共享cookie jar。Order客户端导入搜索现有 `/opt/fs-order-session` 等活动路径。
- `shared_backend_session/README.md` 指定活动映射：shared_admin.py 至 `/opt/fs-shared-session/shared_admin.py`；Sales auth 至 `/opt/sales-dashboard/collector/p2pah_auth.py`；SBC客户端至 `/opt/fc27-sbc-tool/admin_client.py`。需主控现场核SHA与调用者后采用，不能整包覆盖。

### 商品

`shared_backend_session/sbc_admin.py` 已有明确allowlist及结构检查的 AdminClient：

- `list_models:322` → GET `/admin/goods.GoodsMould/index`，gid/cid/title LIKE/extra_search、page/limit、total、siteConfig/gameAreaConfig。
- `get_model:631` → GET `/admin/goods.GoodsMould/edit?id=...`，核 `data.row`。文件中有两个同名 get_model 定义，实际采用后定义，不应误读前一个作为最终行为。
- `list_goods:733` → GET `/admin/goods.Goods/index`，gid/mid/cid/site_id/page/limit，保留模型、站点与平台维度。
- `get_goods:800` → GET `/admin/goods.Goods/edit?id=...`，核 `data.row`。
- 已有 edit_model、edit_model_status、edit_model_more、add_model、shelves、edit_goods_price；本项目仅按所需精确字段复用，不顺带触碰基价/自动定价。
- `AdminClient._bytes:951` 仅 GET 可重试，POST 单次；拒绝登录/刷新路由。其现有allowlist不含券写动作，不能为了接入猜测扩为任意路径。
- `releases/fs-dashboard/admin-data-tools-20261018/candidate/hermes/admin_product_orders.py:collect` 已有 site266+FC27 gid1327+mid 映射核验与平台验证；该封闭工具的 profile/model限制不能直接伪装成多游戏目录。
- 站点266与ALL模板0不同；实际购买引用必须用对应站点商品行，不能因在售表有多站同名行直接取第一项。商品 model_id、goods_id、sku_id保持不同命名空间。

### 券码 / 使用 / 订单

`releases/fs-dashboard/channel-effects-20261021/source/channel_source.py`：

- `pages:139` 已有完整分页：total稳定、ID去重、空页/超总数/分页上限拒绝，不把不完整结果当完整。
- `collect:256` 复用 `/opt/sales-dashboard/collector/p2pah_auth.py` 与8767 token。
- GET `/admin/order.Order/index`：site_id=266、paytime RANGE，按最多28天窗口读取，并在返回后再校验站点与时间。
- GET `/admin/market.Discount/index`：折扣码列表。
- GET `/admin/market.Coupon/index`：券模板列表。
- GET `/admin/user.MemberCouponLog/index`：每批100个order_no、site_id=266；返回再核站点和订单号。
- `enrich:191` 及 load_costs 复用现有Order共享服务/销售交付缓存；不要把Order全库分销订单当本项目订单。

`releases/fs-dashboard/traffic-member-20261009/admin_links.py:inventory` 有上述三券读取端点的脱敏投影，但只取一页并标 partial，不能直接用作完整券目录。

`channel_effects.py:normalize` 保存：order_no、site_id、discount_code、paytime、pay_status、amount_usd_format；券日志id、coupon_id、memberCoupon.grant_batch_no、use_time、status。已有normalize按站点和订单号去重，并把pay_status=2或已退款状态标成refunded。

**不可直接照搬的业务判据**：旧渠道 completed() 要求 status='已完成'且非退款，服务于旧渠道完成口径。V3活动已付口径是“实际应用活动绑定优惠 + 主站有效付款”，不能把未履约但已付订单漏掉；付款枚举及当前实付字段含义须现场核验。

## 券写动作的准确状态

- `docs/planning/hermes-fs-service-account-20261021/PERMISSIONS.md` D15 明确业务目标为创建/编辑、定向发放、批次及结果、停用/撤回/作废等现有动作；该文档也明确精确动作需技术映射，不凭菜单推定按钮已开放。
- 新main受控源码/文档搜索未发现可直接复用的具体券创建/编辑/发放/停用Python客户端。
- 历史Admin frontend capture `mlb_admin_import_20261012/evidence/capture_20261012/entry.js` 只证 `/admin/market.Coupon/` 控制器前缀，不证明某个具体写方法、请求体、权限或读回合同。没有把 `/index` 推断成 `/add` 或 `/edit`。
- 因本角色未请求后台，所有券动作仍是“源码读取已定位/精确写合同待核”，不是能力不存在。下一步应由主控在原187通道读取现有后台动作/前端请求记录，只读确认路径与字段；测试/禁用草稿验证按主控唯一派发。

## 写入安全风险（已立即报告主控）

1. **不能直接用 Sales Session.post_admin 发送非幂等券写入。** `shared_backend_session/sales_auth.py:_post_admin_once` 对网络异常可重发3次，post_admin还可因token判据再发POST。新券/发放超时可能已执行，自动重发会重复业务效果。只复用会话读取，使用一次派发、持久operation日志、原引用查询和 unknown 阻断；或选择已有 POST 单次的受控客户端，但必须先有已核路径。
2. 旧 state.operations 最近100项只适合草稿编辑，不适合券/交易的长期去重与unknown对账。另用模块独立持久事务记录，保留原数据，不做全站迁移。
3. channel_source 返回原后台信息量大，公开端只能接白名单商品/规则投影，不能暴露后台原响应、成本、会员或共享凭据。
4. 活动引用必须精确ID/批次+版本+生效区间；共享 fc27-season2 只可归到活动组，缺页面区分不能按最后打开页面硬分配。
5. 混合订单整单实收与活动商品行实收分开；没有行分摊应为待分摊，金额/成本跨币种不混算，退款稳定引用去重。

## 最小 B 改造建议（未实现）

1. 在现有 app/analytics 管理服务下接入活动配置扩展，保留原registry/layout/history与鉴权；建立版本化商品投影、优惠绑定、能力状态及发布状态。
2. B新增薄的受控后台适配层，复用8767/8768；商品读用上述现有消费者语义，券目录用完整分页；只允许实际核定的路径/方法/字段。
3. 把需要真实读回的后台动作记录为明确能力矩阵；缺精确请求合同的写动作返回具体未接入结果，不能静默失败/假成功，也不降低已经存在的业务能力。
4. 实现活动绑定与已付订单事实纯逻辑（适用site+精确benefit+版本时间+付款），加无浏览记录、通用券误匹配、共享引用、混合订单、多活动去重、退款测试。行为漏斗与业务订单账分开。
5. 主控统一完成实际后台核验、真实最小写回、publisher与生产读回；本角色本轮没有执行这些动作。

## 模型 / effort 核实

本次spawn未指定覆盖，继承父设置。正式 collaboration.list_agents 只返回agent_name与agent_status，没有model/effort字段；本角色现有可用只读接口未取得实际model/effort证明。不能以自述猜测。本轮按主控要求停在只读P0检查点，等待后续按已核Sol High重新明确分派。
