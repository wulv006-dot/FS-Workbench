# Admin 取数通道切换与自动改价停摆诊断（2026-10-27）

> **2026-10-28 本轮用户确认覆盖：**Admin默认全部直接API；仅有证据证明直接API不能实现、且8767绑定DC能实现的极特殊项才可例外，否则最终退役8767。本页下方“保留纯封装”“会话回退”和回滚到session的内容只保留为历史，不再作为默认执行方案。FC保留原Order writer，Admin部分走API。`price`原价展示保持，不强制归零；实际单位价核`unit_price`。完整现行范围见[本轮合同](../admin-recovery-review-20261028/CONTRACT.md)。旧401表只表示当时权限，当前须真实复测。

> 状态：**通道已双轨就绪（8911 备用 / 8912 主线），自动改价与毛利卡被菜单权限阻塞，等后台授权。**
> 本文件记事实与取证，不改业务口径；写价、改价、发布仍按原合同与原 publisher。

## 1. 起因

Admin 后台启用 6 位 Google 码后，`fc27-p2pah-session` 的共享会话自 2026-10-27 17:00 起
`identity_unverified → google_code_required` 连续失败，BATOKEN 无法续期。
所有依赖登录态的链路成片失败，**不是采集器或看板代码坏了**。

## 2. 自动改价停摆取证（老大问的「竞品价格停在 15:22」）

| 项 | 事实 |
|---|---|
| 最后成功轮次 | 15:22（`/var/lib/fc27-cloud/quotes/fe0f495c-….json`，297KB） |
| 之后轮次 | 16:24 / 16:31 / 16:48 → `admin_page_failed`；17:21 → `pricing_admin_shared_source_unavailable` |
| 17:21 轮快照 | `valid_competitors=3`、`valid_costs=3`、`fx=valid`、`source_coverage.ready=true` ⇒ **竞品与成本采集其实成功** |
| 停摆点 | Admin 侧（我方商品/优惠/订单）取不到 ⇒ 整轮 failed、不产出 quotes ⇒ 页面看到的竞品价停在 15:22 |
| 协调器状态 | `fc-pricing-v3.service` active，`v3/heartbeat.json` 每轮更新，队列正常 |

**结论：竞品采集没坏，是整轮被 Admin 环节掐断。**

## 3. 通道现状

| 端口 | 服务 | 凭据 | 定位 |
|---|---|---|---|
| 8911 | `dc-proxy.service`（`/opt/p2pah-dc`） | `chenchaoapi`（`/etc/p2pah-dc`） | 备用线路，RPG 侧原样未动 |
| 8912 | `dc-proxy-fs.service`（`/opt/p2pah-dc-fs`） | 老大 Key `dc7921d1…`（`/etc/p2pah-dc-fs`） | **主线**，本次新建 |

两套都用 `ser_cred` 加密保险箱（`.seed + /etc/machine-id` 派生口令，0400 root），明文只在内存。
`__health` 均 200。

## 4. 已接入

| 模块 | 方式 | 状态 |
|---|---|---|
| 看板六卡（`fs-business-range` → `summary_bridge.py`） | `dc_request` 直调 `order.Order/orderStaticsDetailByEs` | ✅ 实测 FC27 今日 252 单 / $17536.67 / 98 新客；`FS_SUMMARY_ADMIN_CHANNEL=session` 可回退 |
| `p2pah_auth.ADMIN_API` | 早已是 `http://127.0.0.1:8911`（RPG 侧切的） | ✅ |
| `shared_admin.admin_token_from_service()` | 新增兜底：会话取不到 token 且 8911 健康时返回占位 `dc-hmac-proxy` | ✅ 实测返回 `('dc-hmac-proxy', None)` |
| 球类/其他工具（9 处引用 8911） | `nba-reprice`、`mlb-admin-write`、`fc27-pack-bundles`、`dashboard-collect`、`fs-campaign-dashboard`（benefits/adapters）、`fc27-cloud-browser`（session service）、`sales-dashboard/collector` | 均已在 8911 上，未改 |

## 5. ⛔ 阻塞：菜单权限（两套 Key 完全等价，都缺）

| 接口 | 8911 chenchaoapi | 8912 老大 Key | 用途 |
|---|---|---|---|
| `goods/goods/index` | ✅ | ✅ | 商品列表 |
| `goods/goods/edit` | ✅ | ✅ | 商品详情/改价 |
| `order/order/orderstaticsdetailbyes` | ✅ | ✅ | 订单汇总（看板六卡） |
| `order/order/index` | ❌ 401 | ❌ 401 | 订单列表 → **毛利卡 + 自动改价 `business_source`** |
| `market/discount/index` | ❌ 401 | ❌ 401 | 折扣码 → 自动改价优惠口径 |
| `market/coupon/index` | ❌ 401 | ❌ 401 | 优惠券 → 自动改价优惠口径 |
| `user/membercouponlog/index` | 未测（同族） | 未测 | 券使用归因 |

`fc_pricing_v3/business_source.py` 至少 8 处调用 `order/order/index`，另需 `market.Coupon`、
`market.Discount`、`user.MemberCouponLog`。⇒ **只修 token 不足以恢复改价**，必须补菜单。

## 6. 待办顺序（按老大要求：先能跑，再切主线）

1. 技术为 Agent 角色勾上 `order/order/index`、`market/discount/index`、`market/coupon/index`、
   `user/membercouponlog/index`（只读列表即可）。
2. 复测 8912 上述接口全部 `code:1`。
3. 把消费者默认指向 8912（`p2pah_auth.ADMIN_API`、`shared_admin` 健康探测、`summary_bridge`），
   8911 保留为故障回退（改回一行即可）。
4. 跑一轮真实改价，核对：竞品价时效 → quotes 更新 → 决策与写价回执 → 公开价读回。
5. 再同步 Notion 与仓库文档（避免把半截状态写成结论）。

## 8. 迁移完成（2026-10-27 21:40 最终状态）

- **主线 8912 / 备用 8911** 均已上线。9 处消费者（`p2pah_auth`、`shared_admin`、`summary_bridge`、
  `nba-reprice`、`mlb-admin-write`、`fc27-pack-bundles`、`dashboard-collect`、`campaign_backend/benefits`、
  `adapters`）已切 8912，备份 `.bak-20261027T2000`。
- `shared_admin` 改为 **dc 优先**，旧 8767 会话仅作 dc 不可用时的回退。
- 营销汇总 `custom_range.py`/`range_api.py` 改本地 `admin_links.collect(dc_request)`。
- **容器封装层 dc 化**：`dc-proxy-docker.socket`（`172.20.0.1:8913` → `127.0.0.1:8912`）+
  `fc27.env` 的 `P2PAH_API_BASE` + unit bind mount `/opt/fc27-cloud-browser/dc-session/p2pah_session_service.py`
  （放开 base 白名单 + 非默认上游 login/refresh 短路）。`session/admin-token` 现返回 `dc-hmac-proxy`，
  `business/summary` 200，**Hermes 封装接口零改动恢复**。
- 系统检查：11 个相关服务 active；看板 FC27 今日 Admin available、orders 308 / revenue 21045.87；
  竞品/成本采集持续推进（20:26/20:27 新证据）。
- **退役范围 = “BATOKEN 共享会话 + Google 码”机制**；容器保留为纯封装层，不再承担登录。
- **仍失败、等权限**：自动改价 `business_source`、毛利卡、营销四项、`sales-dashboard-sync`、
  `fs-user-analytics`。权限缺口扩为 `order/order/index`、`market/discount/index`、`market/coupon/index`、
  `user/membercouponlog/index`、`stats/memberstats/summary`。
- 关键坑：`P2PAH_API_BASE` 有硬校验 `unexpected_api_base`（须挂载放行）；容器 `--rm` 禁止
  `docker restart`；login 短路后 `refresh()` 必须在 token 为空时回退 `login()`，否则 `status` 停在 starting。

## 7. 回滚

| 改动 | 回滚 |
|---|---|
| `summary_bridge.py` | `cp summary_bridge.py.bak-20261027T1745 summary_bridge.py` + 重启，或设 `FS_SUMMARY_ADMIN_CHANNEL=session` |
| `shared_admin.py` | `cp shared_admin.py.bak-20261027T1800 shared_admin.py` |
| `live_summary.py` | `cp live_summary.py.bak-20261027T1735 live_summary.py` |
| `range_api.py` | `cp range_api.py.bak-20261027T1735 range_api.py` |
| 8912 服务 | `systemctl disable --now dc-proxy-fs` |
