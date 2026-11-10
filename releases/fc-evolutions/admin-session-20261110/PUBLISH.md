# Evolutions 正式 Admin Session 适配

## 来源与目标

2026-11-10，现役 `/opt/fc27-evolutions/source/evolutions.py` SHA-256 为
`02931d6dbd00a7ce7c6dcf349f77999d6257111f444a8075a8433ae6ee0d14cd`。
本轮从主 PC 既有 `fc27_evolutions_20261021/source/evolutions.py` 核得完全相同字节后归入本目录；没有从服务器再次导出此前被拒绝的源码。原测试使用合成商品，不包含生产配置、凭据或订单资料。

沿既有 `deploy_fc.publish` 和 `release_navigation.locks` 发布，只替换两个目标：

| 本目录维护源 | 现役目标 |
| --- | --- |
| `source/evolutions.py` | `/opt/fc27-evolutions/source/evolutions.py` |
| `tests/test_evolutions.py` | `/opt/fc27-evolutions/tests/test_evolutions.py` |

原 `fc27_evolutions_20261021/publish_fix.py` 证明既有发布入口；其旧 SHA、任务 ID、automatic=false 前提属于旧版本，不能原样重放。负责人为本次确切候选生成原 publisher 目标、CAS 和回滚记录，发布后只重启原 `fc27-evolutions.service` 使其加载新源码。不变更 unit、端口、Nginx、UI、数据库或配置 revision。

## 调用合同

Backend 使用现役 `/opt/fc27-cloud-browser/fc_shared_admin.py` 的 `SessionManager(read_private_config())`、`ensure()`、`request(path, data=...)`。该现役共享模块 SHA-256 为 `cad58a1a711a7f3a430d471cd256481bb4c6efb18a68f1a9df6610e2f0281af7`；本次不修改共享模块、身份、配置或主备路由。请求沿正式 8912/已有配置允许的备用通道，不使用旧 token broker 客户端。

继续使用原 vendor 的纯 `build_query` 编码嵌套过滤条件，以及原 `p2pah_price.fetch_rows` 读取 Order 各平台单位价。商品目录、平台身份、数量、折扣、完整编辑字段、计价和独立平台覆盖规则不变。

HTTP 非 200、无效 JSON、未明确业务成功均不认成功；不把上游响应正文写入错误。商品 POST 只派发一次，超时沿原 operation UNKNOWN，不切换旧客户端、不自动重发。清缓存仅原有明确限流允许延迟后重试，网络超时仍不重试。

## 验证与真实入口

Linux 原生测试（含 fcntl、持久化、唯一 writer）：

```sh
python -m unittest discover -s releases/fc-evolutions/admin-session-20261110/tests -p test_evolutions.py
```

本轮新增正式 Session/编码/HTTP 与业务失败/超时单次派发/错误脱敏回归，以及真实 Admin 当前状态覆盖历史阻断、原 UNKNOWN 结果保留、缺商品/平台不符/金额缺失/在途/读取过期仍阻断、重启与时间推进不复活旧阻断、新 UNKNOWN 继续阻断的回归。automatic、revision 和原调度时间不变。Windows 的 Backend 隔离测试仅验证六项会话合同，不替代 Linux 文件锁测试。正式 CI 映射由负责人加入原 `tools/pr_fast.py`。

新增历史覆盖后的 183 Python 3.9 隔离完整测试 40/40 通过、0 skip，真实 fcntl 和文件持久化验证通过。外部接口使用 mock，不调用业务接口。最终证据为 `.agent_runtime/fc-platform-discount-20261110/linux-evo-admin/unknown40-run183.log`，替代初版 33 项测试证据。这不代替正式 CI、发布或真实预览验收。

原失败 refresh `58408694-8be9-4f3f-901b-beb815b2ad63` 保持 failed / AdminAuthRequired，不重放。发布后由原登录入口发起一次新的 refresh，只允许目录、Order 单价读取和预览缓存，不 apply 商品。

正式页面为 `https://47.85.224.112/dashboard/fc27-evolutions/`，按钮“拉取模型与单价”对应 `POST /dashboard/fc27-evolutions/api/refresh`。原 UI 使用 same-origin 登录会话、`X-Evo-Request: 1` 和 JSON `{request_id: crypto.randomUUID(), expected_revision: state.config.revision}`；调用人和角色由门户传递，不能手工固定或冒用 `X-Evo-User`。随后原 `GET /dashboard/fc27-evolutions/api/state` 读取 job、snapshot、rows 和 config。验收逐平台重新计算 `coins / 1000 * Order 平台单位价 * premium`，有明确单平台固定价则依原配置；比较原独立平台 target、错误覆盖和快照时点；历史阻断是否退出以实际 `current_state_coverage` 证据和 blocked 读回为准，不能仅凭理论报价推断。

## 历史 UNKNOWN 与当前状态覆盖

用户本轮明确要求：已经成为历史、且后续有效当前状态覆盖的记录不得一直卡当前自动化。原 operation `36e7fdf4-5479-4273-91d7-44480263cd55-186204551` 仍保存 unknown；没有原 POST 成功回执不能改成 confirmed，也不重发其旧目标。

成功 refresh 读取完整 Admin 目录和 Order 单价后，对历史记录分别核对：原 job 已终态且完成时间不晚于本次 Admin 读取开始；原商品 id/gid/cid/mid/aid/site/sid 与现态一致；当前单位价、折扣及价格一致且可用；本轮读取在 5 分钟内。符合时只在原 operation 追加 `current_state_coverage`，含原 operation、新 refresh ID、读取起止时间、Admin 来源和该商品当前价格/身份。旧 status、target、before、原 job 回执保持。

已覆盖记录退出当前 blocked；缺失商品、在途、缺原结束时间、身份不符、金额缺失、失败或过期读取均不解除对应阻断。覆盖是一条已经成立的历史事实，不在一小时后失效；重启恢复同样识别它。新操作产生的新 UNKNOWN 独立阻断，未来写入仍执行原 fresh-read、CAS、锁及单次 POST。

本次不调用旧 reconcile，不清缓存、不写商品、不改变 automatic=true / revision=4 / next_auto_at。有效 refresh 解除最后一项 blocked 后，已到期的原自动调度将自然恢复执行；这不是重发旧目标或另建周期。真实验收须同时读回覆盖证据、原未知回执、当前 blocked 和原自动任务结果，不能只以页面或报价成功宣称全部写入完成。

原 reconcile 的待核对筛选同步跳过已覆盖历史记录，避免以后把这些旧结果伪写成 confirmed_after_unknown；未覆盖记录仍沿其原能力处理，本次没有调用该入口。

脱敏诊断和本地红绿记录位于 `.agent_runtime/fc-platform-discount-20261110/evolution-*` 与 `evo-auth-*.log`，不将生产 state/jobs/operations 或私有配置纳入发布包。
