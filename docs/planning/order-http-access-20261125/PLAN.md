# Order 后台访问去浏览器化：总方案与施工规划

- 任务：`order-http-access-20261125`
- 负责人：Claude（总方案、协调、统一交付）；各阶段施工由 Codex gpt-6.2-sol 子任务执行；方案评审由 Codex gpt-6.2-astra 完成（2026-11-25，结论"需修改后施工"，必须修改项已并入本版）
- 基线：`origin/main` `1b724d1bc3edaa3de8ad39c47699124f6551cca4`
- 授权：用户 2026-11-25 确认五个方向均可开工，最后统一交付。**本授权不含 187 部署、P0 传输切换、真实 Order 登录和任何写操作**；这些在交付时逐项请用户确认。187 上只允许只读盘点（不改文件、不重启、不读凭据、不导出会话）。
- 来源：本会话架构审查（Claude + Codex 6.2-sol 并行只读盘点）

## 1. 已核事实

| 事实 | 证据 |
|---|---|
| 仓库现有 Order 读法（发货统计、发货记录、订单列表、价格管理页）均为 HTML，未发现原生 JSON 读取实现 | 全仓检索 |
| 返回 JSON 的位置：登录 `POST /admin/public/dologin.html` 返回 `{code}`；`itemEdit`/`goodsEdit`/`saveprice.html` 返回 `{code,msg}`；订单详情页内嵌 `var orderDeliveryData = {...}` | `releases/fc-coins/fc-pricing-v3-20261026/source/collect_p2pah_cost.py:79`（FC 已核）；RPG 注释 `opt/d4follow/core_p2pah.py:15-40`、`opt/d4follow/_p2pah_srv/p2pah_local.py:420-560`（RPG 实测，行号待施工方逐项复核） |
| **FC 现行自动改价不写 Order 售价**，Order 只读成本、订单与利润 | V6.1 合同 `docs/planning/fs-fc-admin-es-20261112/HERMES-V61-CONTRACT.md:35,96`；两段价 `projection_status='not_required'`（`coin_all_sync_job.py:363-371`） |
| Order 会话寄存在 187 `fc27-cloud-browser` 容器的常驻 Chromium；`fs-order-session` 结果缓存 20 秒，到期后在下一次检查时经 `docker exec` + CDP 刷新，经 Unix socket 发 cookie | `order_global_session_20261021/service.py:32-92`，`client.py:13-63` |
| P0 成本采集在 `fc27-cloud-cost:1` 容器内经 CDP 打开发货记录页读 DOM，并在页内 `fetch` 订单详情；外层 180 秒硬超时；有页数上限、PC 独立页限、按剩余样本数最多两单的详情批次 | 活动源 `releases/fc-coins/fc-pricing-v3-20261026/source/collect_p2pah_cost.py:343,455,506` → `/opt/fc27-cloud-browser/collect_p2pah_cost.py`（`deploy/target_map.py:297,360`）；包装 `releases/fc-coins/cost-timeout-20261025/source/collect_p2pah_cost.sh:11` |
| 同一发货记录页已有 HTTP 读法（lxml） | `shared_backend_session/sales_auth.py:139`，`sales_collection.py:34,375,397`，`releases/fs-dashboard/dashboard-refresh-20261025/source/channel_cost_source.py:20,59` |
| 发货统计 `/stats/admin_index/delivery.html` 已是 HTTP，但全局、RS、管理台各有一份解析；看板/管理台导入路径是 `/opt/sales-dashboard/collector`，与成本容器不同 | `releases/fs-dashboard/shipping-profit-20261024/source/{business_shipping,rs_shipping}.py`，`releases/fs-dashboard/management-november-20261103/source/business_shipping.py:58-63`；维护源映射 `docs/planning/business-shipping-profit-20261024/ACTIVE-SOURCE-MAP.json:13,126` |
| 旧标量 writer 以 DOM 操作写 Order（双击单元格、点同步、监听 Noty） | `releases/fc-coins/fc-pricing-v3-20261026/source/price_writer.py:151-220,471`，`fc27_cloud_browser/repricing_dom.js`（行号待施工方复核） |
| 187（47.85.224.112）据 RPG 注释自 2026-09-27 起在 Order IP 白名单；V6 Order 适配器以 `ProxyHandler({})` 直连。**当前线上连通性待只读核验** | `opt/d4follow/srv_exec.py:12-16` |

## 2. 目标与非目标

**目标**：Order 的所有 FS 读取经一个 HTTP 深 module 完成；P0 链路不再依赖 Chromium 访问 Order；Order 会话不再寄存在浏览器里；Order 协议知识集中在一处。

**非目标**：
- 不新建任何 Order 真实写价链路。FC 现行协议不写 Order 售价。
- 不改 RPG（`opt/d4follow/`）代码。RPG writer 独立，FC 不借用其写权限；协议知识只单向抄录。
- 不改定价算法、成本口径（`latest_3h_valid_order_delivery_median_v1`）、毛利合同、原 ID/CAS/UNKNOWN 保护。
- 竞品采集仍用浏览器，不在本任务范围。

## 3. 目标结构

```
/opt/fs-order-session/（成本容器已只读挂载，PYTHONPATH 已含）
  fs_order_client.py   ← 现有 interface：cookies() / fill_jar(jar)，不改
  order_http.py        ← 新增：Order 读取深 module
  service.py           ← 会话负责人；阶段 4 增加内部 adapter
```

看板、管理台等其他消费者的导入路径不同（`/opt/sales-dashboard/collector` 等），由阶段 3A 的消费者映射决定各自如何获得 `order_http`，不预设。

### `order_http` interface（草案，施工可调整，但须保持以下语义）

```python
iter_delivery_pages(query, *, max_pages, deadline) -> Iterator[DeliveryPage]
    # 逐页产出；调用方可随时停止。query 含 gid/aid/cid/genre/start/end/page 等原参数
    # DeliveryPage: page_no, rows（按表头文本定位列）, has_next, raw_sha256
    # 结束原因显式区分：caller_stopped | source_exhausted | page_limit | deadline | failed(reason)
order_detail(order_id, *, timeout) -> DetailResult
    # 状态必选其一：found(goods, deliveries, complete) | not_found | parse_failed | login_lost | timeout
    # 不用 None 混合多种含义
shipping_stats(filters) -> ShippingStats
    # /stats/admin_index/delivery.html：表单实际选值回读 + 统计表
```

实现约束：
- 业务停止条件（够样本即停、PC 页限、详情两单批次）留在调用方；module 只提供逐页读取、预算与结束原因。
- 优先只用标准库（`urllib` + `http.cookiejar` + `html.parser`）。在阶段 1 用同一批脱敏 HTML 对比标准库解析与现有 lxml/DOM 解析的输出；一致则不新增依赖，不一致或成本过高再按消费者环境决定。
- cookie 只来自 `fs_order_client.fill_jar`，不落盘、不登录。
- 登录失效（跳 `login`、出现 `password` 输入框、`dologin`）显式报 `login_lost`，不当空结果。
- 超时、重试、并发不高于现有调用方；不新增总兜底。

## 4. 阶段

每阶段一个 PR，按 `docs/ops/HOTFIX.md`：最新基线、PR、`pr-fast`，处理已出现的有效审查意见后合并。依赖：0+1 → 2；0+1 与 3A → 3B；4 独立；5A 可并行，5B 依赖 2、3B 的部署验收。

### 阶段 0｜Order 协议文档（与阶段 1 同 PR）

`docs/planning/order-http-access-20261125/ORDER-PROTOCOL.md`：登录（先取验证码拿 `PHPSESSID`；`PHPSESSID`+`user`+`admin_username` 三个 cookie；`dologin` 返回 `{code}`，非验证码错误立即停止）、读取路由与参数、HTML 结构锚点、`orderDeliveryData`、写接口（`goodsEdit` 哨兵语义、`itemEdit`、`saveprice.html` 的 `getweb=0/1` 与 `allserver` 禁勾、`clearcachepost.html` 返回 HTML）、分页教训、IP 白名单。每条标明来源文件、实测日期，区分"RPG 实测""FC 已核""待核"。

### 阶段 1｜`order_http` module

- 新增 `order_global_session_20261021/order_http.py` 及测试；加入 `/opt/fs-order-session/` 发布清单与 SOURCE-MAP。不改任何调用方。
- 测试只经 interface，使用脱敏 HTML 夹具（优先复用仓库已有夹具；不足时由负责人在 187 只读抓取并替换订单号、邮箱等个人信息）。覆盖：多页、空页、登录失效、表头变动、缺列、嵌套标签、截断、详情缺 `orderDeliveryData`、详情 404、超时，以及各结束原因。
- 含标准库 vs 现有解析的夹具对比测试。

### 阶段 2｜P0 成本采集直接切换到 `order_http`

用户 2026-11-25 明确：直接切换，不做影子比对，不保留双路径开关。

- `collect_p2pah_cost.py` 的 Order 读取改由 `order_http` 提供，删除 Playwright/CDP 读取代码；`valid_record`、同单核验、V6 样本窗口、异常值、页限、详情两单批次与输出 JSON 契约原样保留。
- 包装脚本去掉 `FC27_CDP_ENDPOINT`，保留 fs-order-session 挂载与 180 秒外层超时；`target_map.py` 哈希钉与测试同步更新。
- 验收：离线回归；部署后核对一次三平台真实自然轮成本 `valid` 及下游定价决策正常。回退方式为重新发布上一版文件，不加运行时兜底。

### 阶段 3｜看板与成本消费者收敛

**3A 消费者映射（只读，可与阶段 1 并行）**：逐个列出全局发货统计、RS 发货统计、管理台、渠道成本、销售采集、实际利润的维护源、187 运行入口、解释器与依赖（含 lxml）、模块可见路径、socket 权限；核清 `business_shipping_profit_20261024/source/` 与 `releases/fs-dashboard/shipping-profit-20261024/source/` 的发布关系。产出 `CONSUMERS.md`。

**3B 收敛**：依 3A 结论，把上述消费者的 Order 读取改用 `order_http`；以同一夹具比较改前改后输出逐字段一致；毛利口径与 API 返回结构不变；只改活动维护源，历史副本不动。

### 阶段 4｜会话 module 直接改为 HTTP

用户 2026-11-25 明确：直接切换，不保留浏览器 adapter 与配置开关。

- `service.py` 删除 `docker exec` + CDP 浏览器探测，改为自持 cookie jar；用 `/admin/index/index.html` 现有身份判据探活；失效时按协议 OCR 登录（复用 `shared_backend_session/manual_captcha.py` 的 ddddocr 接口），限次沿用 `FC27_OCR_ATTEMPTS`，非验证码错误立即停止。
- 消费者 interface、socket 路径、`ready/cookies/error` 结构不变。
- 必须定义并测试：并发失效时只有单一续期者登录，其余等待结果；服务重启后首次请求的行为；探活**传输失败**（超时、5xx、429）只报不可用，**不触发登录**，只有明确的身份失效才登录。
- 离线测试覆盖：有效、失效重登、验证码错重试、密码错停止、限次耗尽、并发失效、探活超时。
- **上线前置（需用户授权部署）**：确认共享账号的实际使用方（FC、看板、RPG 等）和恢复窗口；确认 OCR 依赖与运行身份在服务环境可用。若同账号新会话会使浏览器里的旧会话失效，不影响消费者（均经 socket 取 cookie），但回退到旧版需要浏览器重新登录，需事先准备该步骤。

### 阶段 5｜退役浏览器路径

**5A 盘点（只读，可并行）**：对每个拟移除组件——`price_writer` 旧标量 DOM 路径与 `repricing_dom.js`、`range_primary_reader`、`fc_order_reader`、成本容器的 CDP 依赖——逐项确认：活跃调度、在途旧标量操作、尚须原 ID 对账的 UNKNOWN、按需调用（Hermes/MCP、路由）、回退依赖。已有后续真实现态覆盖的历史 UNKNOWN 按[现态覆盖规则](../../agents/agent-workflow.md#execution)退出阻断。产出 `RETIREMENT.md`。

**5B 退役（依赖 2、3B 验收）**：5A 确认无用途的组件，从活动发布清单与 SOURCE-MAP 移除；历史目录保留。仍有用途的停在报告，不删除，不新建 HTTP 写价。旧标量若仍在用，其 `getweb=0` 是否推送 mmoexp 与 RPG 实测结论可能冲突，只记录待核，不改行为。

## 5. 验收

| 层级 | 内容 |
|---|---|
| 代码 | 各阶段相关回归、`pr-fast` 通过 |
| 部署 | 187 文件哈希与发布清单一致（需授权） |
| 真实入口 | 切换后三平台自然轮成本 `valid`、下游定价决策正常；看板发货毛利与切换前同日同范围一致（需授权） |

未做的层级在交付报告如实标 unknown。

## 6. 风险

- Order 改版 HTML：表头定位 + 显式失效，集中在一处修。
- 时间预算：P0 外层 180 秒硬超时；HTTP 路径须保留现有页限与批次。
- 会话互顶：阶段 4 上线时由负责人在授权窗口内完成首次登录并核对各消费者。
- P0：切换后保留上一版文件可直接回发。
