# Notion 同步稿：Admin 取数通道迁移（2026-10-27）

> 状态：**待同步**。`tools/knowledge_closeout.py plan` 在本机与私库检出均失败：
> `Ran 87 tests ... FAILED (errors=30)`，关键错误 `native_plugin_exact_registration_delta_required`。
> 该失败在旧基线 `campaign-fix66` 上同样复现，属既有夹具/环境缺口，与本次迁移无关。
> 通道修复后，按本稿执行一次 `plan → approve → begin → record`，change_id 用 `admin-dc-proxy-20261027`。

## 应写入的结论

Admin 后台启用 6 位 Google 码后，共享会话（BATOKEN）无法续期并被限流 6 小时。
自 2026-10-27 起，FS 与球类的 Admin 取数统一改走数据中台 HMAC 代理，**登录态机制退役**。

- 主线：`http://127.0.0.1:8912`（`dc-proxy-fs.service`，账号 `wulvapi`）。
- 备用：`http://127.0.0.1:8911`（`dc-proxy.service`，账号 `chenchaoapi`，原样未动）。
- 容器封装层（fc27-p2pah-session，8767）经 `172.20.0.1:8913` 转发同样走 HMAC，
  通过挂载文件放开上游白名单并对非默认上游跳过 login/refresh；
  `session/admin-token` 现返回 `dc-hmac-proxy`，Hermes 封装接口零改动恢复。
- 看板六卡、竞品与成本采集、商品/首页读取、营销汇总框架均已恢复并实测。
- 当前阻塞只剩**菜单权限**：`order/order/index`、`market/discount/index`、`market/coupon/index`、
  `user/membercouponlog/index`、`stats/memberstats/summary`。两套 Key 权限等价。
- 待权限开启：自动改价 business_source、看板毛利卡、营销四项、
  `sales-dashboard-sync`、`fs-user-analytics`。
- 文档：私库 `docs/planning/admin-dc-proxy-20261027/README.md`（PR #565 已合并，main `e26fccc9`）。
