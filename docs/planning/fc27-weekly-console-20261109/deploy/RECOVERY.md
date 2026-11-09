# 原任务恢复与 curl 热修复 — 2026-11-09

本记录归档总控执行的恢复、发布及独立读回，不含生产数据库行、凭据或模型原文。原41目标发布另见 [README](README.md)。

## 原操作：已确认未派发

- operationId：`8dd85cc4-32c3-4cb7-9af1-ae46dea6aa7a`。
- task：`bfb3d4bc39111250646ade712860e3ae`；run：`campaign_b731b300aa3dfb1c9aa0c88f29add897`。
- 原因：现役 range 进程使用 `/usr/bin/curl` 7.29.0；旧 provider 将浮点 deadline 传入 `--max-time`。使用同一 binary 的 `--max-time 1799.999 --version` 和 `1799.0` 均在参数解析时 exit 2，整数 `1800` exit 0。这是零网络复现；提前写入的派发标记不能证明已向模型发送请求。
- binary SHA：`8f406d8115fa235eb3d3e979e5f4d22a2319c8dac4ec1899f82b29f7abf4ca2d`；旧 provider SHA：`681afc43b0a7ce6f3664b92b31cba2092ad029ec3cdbb14ea112557f757fe19a`。
- 原身份的模型元数据 GET 返回 200；它只证明该次读取可用，不作为模型 POST 或计费用量证据。

首次调用使用了错误的脚本路径，脚本未执行。随后总控上传实际恢复脚本，默认 inspect 核对原行哈希及零网络证据后，显式执行 `--apply`，结果为 `reconciled_not_dispatched`。任务变为 `FAILED`、version 3，模型账本为 `not_dispatched`，原推荐及周更操作为 `unavailable`；真实 UI 已读回。后续 inspect 返回 `already_reconciled`。

恢复持有原 admission 锁；先保存私有审计，再提交预算库原 fingerprint，最后在任务库同一事务中更新原任务、推荐和周更状态。所有行按原 ID、owner、版本及完整行哈希核对。reservation、原 tokens/金额估算、runId、原 `network_started=1` 标记保留；不删除记录、不重派模型、不把估算改写成实际费用。

私有审计位于服务器 `/var/backups/fs-campaign-weekly-reconcile-20261109/8dd85cc4-32c3-4cb7-9af1-ae46dea6aa7a/recovery.json`，不入库。单份脚本及5项 fixture 测试归档于 [curl-recovery](curl-recovery/)。脚本固定上述原操作，默认只读；不能用于批量清理其他 unknown。

## 热修复：已部署并读回

- PR934 已合并，提交 `c9edd8bda`；正式 CI 1801 通过。
- 发布 ID：`nav-20261109T063600Z`；实际执行时间为 **2026-11-09 06:32 UTC**，不将 releaseId 字符串当作实际时间。
- 候选源：`56cdb54d5c21f88d5a686e667b0a1770fbf71182`。
- 原 stage：`/opt/fs-release-stage/fc27-weekly-20261109/curl-fix-stage`。
- 原备份及 journal：`/var/backups/fs-navigation-20261006/nav-20261109T063600Z`。
- manifest SHA：`de6043faae526ae9172fd39e5b472dd41c727f605899a30aceb4d644921dbca8`。
- launcher SHA：`b9c8395d0669932f12c4cc772f7e990793ad4102444d018201a7cf01a37bf40d`。

4个目标为 `fs_inprocess.py`、`proxy_gateway.py`、`campaign_recommendations.py`、`openai_provider.py`，均位于 `/opt/fs-hermes-fc/`。沿原发布器、锁、CAS、备份和原 ID 恢复；保留38个 unchanged guards，激活范围仅 `fs-business-range.service`。总控读回4个源码 SHA 全部匹配，活动管理、公开运行和业务 range 三服务 active。

归档 [manifest](curl-fix/manifest.json)、[targets](curl-fix/targets.json) 和 [原激活 adapter](curl-fix/release.py)；不重复复制候选源码。部署或回退不能直接重放已使用的 releaseId；先核原 journal。`not_dispatched` 账本仍须由兼容读者解释，不能整包回旧代码或清理审计。

## 新真实模型验收：调用成功，草稿校验失败

- 新 operationId：`45f35de9-b9d7-4294-9f51-6f814a1c51d8`。
- task：`d0e4f06a9352ac0939706e08d90ac635`；run：`campaign_9669bb071fda9346b46422c1b47c9f39`。
- 真实 `gpt-6.1-sol`、high 推理调用成功：input 4,257 tokens，output 2,039 tokens，total 6,296 tokens，来源为原调用回执。
- 返回内容每个 SBC core 只有1位搭档，未满足原核心加2位搭档的校验，因此推荐状态为 `failed`。保留失败及已发生用量；后续修复由原任务继续核查，不能把它写成草稿保存成功。

截至本记录，**尚未保存本次三页草稿、未启用周日自动计划、未发布活动、未修改优惠券、未发送社区消息**。后续验收结果由总控另行更新，模型调用成功不等同于业务验收完成。

## 后续单目标修复：已部署，真实验收待返回

- PR936 已合并，提交 `c0eb262b5382763e28a561b0b304cb9fa59277e4`；正式 CI 1805 通过，run `42574492697`。
- 候选源：`4db18035a4ceea7aca7dfd96275c9611d07c16ad`。
- 发布 ID：`nav-20261109T064500Z`；沿原 publisher 发布1个目标，保留41个 unchanged guards，仅激活 `fs-business-range.service`。
- 目标：`/opt/fs-hermes-fc/campaign_recommendations.py`，SHA `9a70af59a9459956f6e4db363cc7966d7313cf0583e8cd3460d73a261be5073a`；总控独立读回一致，相关服务 active。
- manifest SHA：`604ba7b550f9a24fd27b7ecbecd8b5de360234a49d1030bde65549f072e64f9e`。
- launcher SHA：`30e4f3ca326be5716982a817c5ed389c20422d105ef033efc9f11f84b15fca66`。

归档 [manifest](cardinality-fix/manifest.json)、[targets](cardinality-fix/targets.json) 和 [原激活 adapter](cardinality-fix/release.py)，与本次 stage 字节一致，不重复复制 payload 源码。此前操作的失败及已发生用量保留。

总控已从真实管理台点击新一次手动运行，尚在等待结果；本条只证明修复部署及源码读回，**不证明三页草稿保存、计划启用或自然周更成功**。
