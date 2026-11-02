# Admin 实时单页：候选与接线边界

目标是业务需要时查当前源，不重建派生库。`AdminLivePage` 固定单个 site/game、上海业务日半开范围、最多 28 日且最早不早于服务当日减 365 日、不晚于明日，最多 5 条、一个请求、262144 字节和 10 秒；只投影订单 ID、付款时间、状态。无跨页游标，不接快照引擎和完整缓存。即使源报 total=0 或实际条数不满页，均返回 `status=partial, complete=false, semantics=live_non_snapshot`、观察时间和实际范围，total 仅为源当时声称值，不证明历史/跨页完整。上游 401/403/429、timeout、字段/站点/游戏/时间不匹配均明确失败。

2026-11-02 09:00 UTC，既有管理员服务身份 `wulv` 的用户分析资源权限和 admin 身份通过，真实服务配置仅 site 266 且含 game 1327；经现役 `/opt/fs-order-session/fc_shared_admin.py` 固定 HMAC 8912 代理做一次 `2026-10-29`、page=1、limit=1 的只读请求返回 200，且 `id/site_id/gid/paytime/status` 均存在并匹配范围。仅输出结构和布尔值，无客户明细、采集落库或新凭据。这证明该时点的一个单页，不证明任意用户站点 grant、所有游戏或历史、跨页水位或长期可用。

`ConfiguredAdminAuthorizer` 仅允许可信 host 注入的 subject 具备现役 IAM 用户分析资源权限且 `is_admin`，并要求当前 `W0_verified` 配置站点集合恰为 `{266}`、所选 game 在配置 projects 内；不把资源访问自动等同任意站点权。每次读、读后重新计算完整 IAM policy 和 config 的摘要，任何更改/撤权拒绝结果；缺失或不明确即拒绝。它不支持普通成员、多站或不存在的细粒度授权，后续要由原 IAM 提供明确 grant，而不是默认放大。

`SupervisedAdminTransport` 按现有 range 宿主 `subprocess.run(timeout=...)` 方式调用固定受保护 worker，强制整个子进程墙钟超时；`admin_live_worker.py` 仅访问固定 `/admin/order.Order/index`，只允许现役固定 HMAC proxy `127.0.0.1:8912`、page 1、站点 266、已验证格式的 game 和日期，使用既有 shared `SessionManager`/headers，不登录、换凭据或调用 sync；源响应读入前限制 262144 字节。worker 的本地预期 SHA 和已核 shared 文件 SHA 均校验；版本漂移失败关闭。超时后子进程被结束，上游代理可能已收到一次只读请求，不能自动重试或声称请求从未发生。真实机器 Python/代理部署后的组合与进程权限还未验。

`admin_live_host.get` 仅在现役用户配置 `live_admin_single_page` 严格为 true 时启用；缺失、假值、IAM/配置缺失均不可用或拒绝。当前未改变配置，功能未上线。部署候选仅六个新模块 `admin_live_page.py`、`admin_site_authorizer.py`、`admin_supervised_transport.py`、`admin_live_worker.py`、`admin_live_dispatch.py`、`admin_live_host.py`，另需已有 route/tool 的最小补丁和用户配置的可控开关，不包括完整 PR737 其他治理功能。实际发布前必须固定源、worker 和宿主合并后的 hash，核部署路径、uid/权限/进程终止、回退以及独立审查，按已授权窗口进行；不能把代码提交或单页探针当部署验收。

## A-owned 宿主的建议差异（未应用）

当前 GitHub main 中 `dashboard-refresh-20261025/source/range_api.py` blob `82a2ad8fd6254e1231d97f33364e7ac42051f0c4`，在既有 `X-Auth-User` 非空校验之后、`/users` 分发之前增加仅 GET 的独立分支，使用原 `self.reply`（已有 no-store）：

```python
  if uri.path=='/users/live-orders':
   try:
    from admin_live_host import get as get_live_orders
    status,data=get_live_orders(parse_qs(uri.query,keep_blank_values=True,max_num_fields=4),self.headers.get('X-Auth-User'))
    self.reply(status,data)
   except Exception:self.reply(503,{'error':'live_source_unavailable'})
   return
```

该分支必须位于 `USERS is None` 检查之前，避免派生库缺失时误阻塞源查询；默认开关关闭、可信身份由现有 nginx auth_request 注入。当前运行中 host 在 08:58 的 SHA 为 `6ad36b9be9790c0392874ee748c8f2e9bade24cb1b23ef1585fed59464ff9d32`，与当前 GitHub main 文件不是同一版本；应针对获协调窗口内的现役版本重做最小 diff，不从仓库全量覆盖正在施工文件。

## Hermes 工具建议差异（未应用）

`hermes-server-unify-20261022/fs_readonly/__init__.py` 当前 main blob `97a045fdd5ca8bc824b244c1197195846e88d76c`：增加固定工具 `fs_query_admin_live_page`，仅接收 `site_id/game_id/start/end_exclusive` 四字符串；只调用固定 `/users/live-orders`，将该路径加入原 loopback allowlist，直接返回 partial、实际时间与缺口。沿用原 30 秒/10 MB 外层，不能接受任意 URL、SQL、headers 或自选身份；当前工具沿用现有受信 server profile `wulv`，如未来支持多用户，必须从宿主取得真实 caller 而非沿用固定 owner。

此文为 owner 可审合同，不证明 route、工具、config 已接入或上线；不得打断 T3。备份退役不以此功能部署为门槛。
