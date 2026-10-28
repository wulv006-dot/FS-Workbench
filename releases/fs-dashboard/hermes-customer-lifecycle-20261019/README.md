# 客户追踪池生命周期与手动全局报告

候选：2026-10-19。以用户最新要求为准，取代先前单人自动报告规划。

- Admin站点266匹配客户的全部游戏已付款订单，历史完整且付款时间有效时取最早付款。北京时间首次付款自然日为第1天；7/14/30为阶段标记。
- 历史不完整/未知付款时间不猜首付日，不用加入追踪日期替代。
- 不再加入即出报告，也不再自动生成单人7/14/30报告。未提交scheduled旧节点取消；历史完成/失败/未知结果保留。部署前须确保无活动/未知派发。
- 每日北京时间00:00–07:00更新活跃追踪客户，按自然日而非24小时轮转；失败保留旧快照和更新时间。非自动、用户主动读取可按现有规则刷新。
- 可手动停止追踪，保留历史，退出每日更新和后续全局分析池，不改变订单。
- “生成追踪报告”明确点击才调用现有Hermes持续对话服务。冻结全部活跃池的脱敏数值证据，单份HTML报告；原账号权限、模型及消费限制保留。
- 只输出匿名追踪ID，不将邮箱/UID/原订单号送给模型。首次付款范围、分段时间、未知金额、退款/问题和陈旧数据均标注。
- 同request_id幂等；已有生成任务时不再派另一份。未知派发先查原回执，不盲重跑。
- 如果完整池输入超过原对话大小边界，显式失败，不静默截掉客户。后续扩容应做分批证据工具，不假装已支持无限客户。

验证：python -m unittest discover -s tests -v；node --check frontend/page.js。
合成测试不能代替真实模型质量验收。本任务不主动点击生产生成按钮；真实生成由用户按需触发。

当前维护源在本目录source/与frontend/，不覆盖历史20261018候选包。精确活动映射、部署读回和回滚见后续验收记录。沿用既有冻结后端publisher及锁/CAS/隔离import/空闲检查/备份。

## 明确 ES 拒权后的原请求恢复

仅适用于原 `scan_jobs` 已失败且 `reason=es_export_permission_denied` 的同一天、当前配置版本。此项停止当日自动15分钟重排，旧 `retry_after=60` 也按不自动重试展示；其他失败、历史观察及以后日期保持原行为。当前外部权限仍未开通，以下是受控恢复操作合同，尚非真实补权成功验收。

1. **只读预览**：以 SQLite `mode=ro` 读取原 `scan_jobs` 全行、对应 `requests` 和当前 `config.version`，确认原 `day/config_version/request_id`，并用 `scan_job_sha256(dict(row))` 计算原任务 SHA。只保留状态、编号、版本和 SHA；不输出客户资料。原请求必须为该日的 `scan`，原任务必须明确拒权失败。当前配置已变、UNKNOWN 或仍在途均延期，不能换编号或清状态。
2. **先恢复原 ES 回执**：技术补权后，由操作者沿 ES 模块 `recheck_permission` 对同 query、同 durable root、原拒绝回执 SHA 受控验证一次；这一步可能生成导出，必须有相应授权，不用普通查询代替。成功后记录新 canonical index 的原始文件 SHA。使用 `recovered_es_receipt(day, new_es_receipt_sha, original_es_root)` 只读复核同日 ALL query、完整文件集合、原拒绝历史、无 current/legacy attempt、无 `last_attempt`。旧拒绝缺 stage 可以保留原样，不能补造历史事实；旧 good 带拒权 latch、pending/UNKNOWN 或不完整结果均不算恢复。
3. **进入原服务维护窗口**：沿既有 admission/quiescence 流程阻止新进入，确认没有活动或 UNKNOWN 的模型、报告、扫描及读取；不强停正在工作的 reader。仅停止承载 `CUSTOMER_TRACKING` 的 `fs-business-range.service` 并确认 `MainPID=0`；不停止 FC 协调器或 `fs-hermes-fc.service`。如无法证明空闲则延期，不借重启消除在途结果。保存停前服务状态及上述两份 SHA/原请求证据。
4. **Range 保持停止，沿原编号恢复**：使用现役 Range 的 Python 及相同安装模块路径，在一次性运维 Python 会话中导入 `/opt/fs-hermes-fc` 的 `tracking_controller`、`customer_tracking` 与原 `fc_daily.admin`，不导入/启动 `range_api`。创建下列无自动循环的 controller；不得以 `lambda: True` 替代原管理员校验。

   ```python
   from tracking_controller import TrackingController
   from fc_daily import admin
   controller = TrackingController('/var/lib/fs-hermes-fc/fs/customer-tracking', admin, auto_start=False)
   result = controller.resume_permission_scan(
       operator_user, original_day, original_config_version, original_request_id,
       expected_job_sha256=original_job_sha,
       es_receipt_sha256=new_successful_es_raw_sha,
       es_root=original_es_root)
   ```

   此时旧 daemon 已停止，旧 Future 不再存在；这是原持久任务的独占维护恢复，不是用新对象替换仍运行的 daemon。若调用进程本来就是持有原 controller 的进程，则该方法只移除原实例已完成、已观察、明确拒权的 Future；活动、UNKNOWN 或未观察 Future 一律拒绝。方法先校验原请求/CAS及 ES 证明，事务保留 `requests.result.permission_recovery.prior_failure` 后才接续原 `client.read → Store.finish_scan`，不新建 request ID，不运行 `_daily_loop`。
5. **有界观察和读回**：只观察上述同一任务/Future，每次 `_poll_scan(original_day)` 后读取原行；整次恢复沿原扫描850秒总预算，不加超时、不无限循环、不新建请求。到期仍 pending 时停止继续观察并报告未完成；不重放，不强杀仍在途的 reader，也不在其退出前启动 Range。待原 Future 终止并消费一次结果后，确认原编号/版本、最终状态及 `permission_recovery` 中原失败、操作者、两份 SHA 均保留。只有原完整扫描结果才可为 available；失败如实保留。关闭该临时 reader 的线程池并退出会话，确认没有遗留 reader 后，按停前状态启动原 `fs-business-range.service`，读回健康状态及同一请求。失败不清 UNKNOWN/原 ES attempt，不回滚成可重复导出状态。

该方法没有公开 HTTP 路由；重复 POST 原 `scan` 只读取幂等回执，不是恢复操作。无需新服务、定时器或队列。上线验证和真实补权恢复分别记录，不能把本地合成测试称作已恢复外部权限。
