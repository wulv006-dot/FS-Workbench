# FC 每日复盘修复（2026-11-09）

恢复每日只读复盘的摘要提交、原请求状态识别及效果取数等待。负责人吴律 / Codex；不修改定价、writer、原操作、共享 Sol 配置或暂停的报告日程。

## 原因与修复

- `daily:2026-11-08` 冻结数据已到位，旧桥的 12,000 字符上限拒绝摘要。超长时把需求模型、影子预测的重复字段转为表头和数据行，保留全部数值及覆盖、财务边界，不截断正文或提高上限。真实原摘要候选渲染 11,273 字符，源数据未改变。
- `daily:2026-11-07` 的原 turn 为 `dispatch_unknown`，按原 run 查询返回 HTTP 404；首次修复先明确记录 UNKNOWN / do_not_replay。进一步核对原事件账本发现同 run 的 `run.completed` 及 3,309 字符原输出，事件 SHA256 为 `080d6f2e4348057c408c063cf750a7cd3d4e0a674687ab41e135da9aad9f3935`，因此问题是完成状态未同步，并非当日数据未到位。追加修复只认原 turn 最新终态事件，核事件类型、同 run 和非空输出，记录来源哈希；只有特定原 dispatch_unknown 回执允许再核，绝不重发模型。无证据、错 run 或较新失败事件不能推定成功。
- 已提交请求查询原回执时不再重新构造提示词；继续校验原 owner、run、mode 和绑定快照。
- 两处 `fc_pricing_v3.daily` 只读取数子进程超时从 240 秒改为 600 秒。效果更新仍在原独立 lane；每小时算价、写价与保护不变。
- 沿原 `fc_v3_release_adapter` 增加精确三目标 scope：`hermes_pricing_bridge.py`、两个原消费者的 `fc_pricing_v3/daily.py`；其余目标受原哈希保护，保留原锁、CAS、备份与服务检查。

## 验证

- 新回归先复现摘要超长、原请求被提示词阻断、dispatch_unknown 误作 pending、300 秒取数被提前中止，再修复通过。
- Windows 每日复盘追加原事件对账后 38 项、发布范围 13 项通过。扩大 FC 806 项有 5 failure / 1 error / 11 平台 skip，均属固定源码哈希/历史回放受 CRLF 影响；对应 21 项在 183 的 LF 源码环境全部通过，未修改固定校验。
- Windows 具体未通过项：`test_runtime_contracts.RuntimeContracts.test_simulation_bridge_pins_local_and_runtime_pure_versions`、`test_legacy_api_replays_saved_snapshot_without_quote_or_writes`；`test_shadow_simulation.ShadowBehavior.test_frozen_legacy_replay_uses_real_asof_evidence_and_distinct_sources`、`test_historical_results_keep_real_fixed_and_causal_meanings_separate`、`test_legacy_replay_cannot_move_asof_forward_to_include_future_sources`、`test_legacy_replay_uses_saved_decision_time_after_sources_finish`。上述 Linux 验证覆盖这六项。
- 183 已有 Python 3.9.18 镜像，断网、只读挂载、0.25 核 / 256 MiB、64 PID，无业务挂载；直接相关复盘/效果/发布保护 77 项全部通过、无 skip。初次容器缺 Node，且发布锁测试要求容器内 UID0，环境修正后通过；JS 检查已在 Windows 完成。
- 独立审查发现新增 scope 未接入 `load_base.active_targets`，已补齐并增加实际选择路径检查；复审无遗留阻断项。
- 原终态事件追加修复后，183 同环境直接回归 78 项全部通过、无 skip，独立复审通过；较新失败/取消终态不回退到较旧完成事件，错 run 和无完整输出继续未知。
- 知识收尾识别无正式条目影响；Windows 缺时区数据后使用公共系统时区文件完成检查，不新增生产依赖或知识发布。

## 发布与实际结果

首修 PR922 合并 `cc00a195fd0d6196d07df8677f0862bbd4866cf9`，源码 `a3968ceab4460e0db1ef2112df627482023359be`，正式 CI42540900418 成功。沿原发布器发布 `nav-20261109T003800Z`，manifest SHA256 `9b04e8809239d32d1fa30683f1271b502d6eb9322ba1a8f4f64c2dac595073a7`，三目标及163保护项一致，五个原服务 active；备份 `/var/backups/fs-navigation-20261006/nav-20261109T003800Z`。

追加修复 PR923 合并 `7607511d1e8bc69b2a3df6197977bc16fbba3991`，源码 `58ef05f34d8e978142f9fd791f8c2d3302843673`，正式 CI42541744348 成功。沿原发布器发布 `nav-20261109T004600Z`，manifest SHA256 `856a806d1a77d967a7edf5ddf93920905facead14fbb5646d9be498ae8aa7309`，三目标/163保护项及五服务读回通过，备份位于同名原 publisher 备份目录。

11/7 沿同一原请求及同 run 完成事件恢复原 3,309 字符复盘，原输入 SHA 一致，原每日作业 done / completed；首修阶段的 UNKNOWN 告警补入原事件哈希解决凭证，历史保留，没有模型重发。11/8 原先未提交的同一请求恢复正常提交，生成 3,819 字符复盘并完成，原输入 SHA 一致，原每日作业 done / completed。两日复盘均 `price_write_performed=false`，重试次数33/10保留；回补旧日后最新复盘指针仍指向已完成的11/8。

最终通过原 HTTP `/pricing/v3/daily-review`、`/pricing/v3/review-state` 读回11/8 completed；两日原 turn/run、结果和输入哈希核验通过。原11/7底层会话的过期运行查询仍404、stored_state仍dispatch_unknown，完成认定依据是其最新且身份匹配的原终态事件，未伪造或覆盖原事件/运行。修后08:37自然小时轮08:39:57完成，done / confirmed；小时效果更新最近done / updated。600秒等待已上线，未来自然取数耗时和跨日稳定性仍需自然运行积累，不把延长等待等同于接口加速或长期稳定证明。
