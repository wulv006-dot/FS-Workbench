# 部署与恢复记录

## 当前状态

Order 全局服务已上线、现有登录态有效；活动调用方已迁移。FC 原部分完成操作已按原 ID 人工核对并补完，后续原定时器自然安全重试已完成真实改价、ALL 回读、清缓存、公开售价验证及球员类目请求确认。PR/正式 CI/合并单独读回，结果见本机 GIT-RESULT.json 及对应 PR，不能从业务通过推定。

## 发布方式和回退

服务源码 `/opt/fs-order-session/`，systemd `fs-order-session.service`。健康 `http://127.0.0.1:8768/health`，无凭据 HTTP 端点。代码来源为本项目独立任务目录，上传隔离 staging 后编译检查，逐文件私有备份、替换前核对、原子替换及哈希读回。备份 `/var/backups/order-global-*-20261021-v*`；每批 `receipt.json` 记录前后哈希。

回退只针对各批源码和服务接线。不能覆盖运行 DB、工单、队列、锁、策略、账本或回执；不能恢复消费者的独立密码登录。若需回退共享会话代码，应先停止受影响消费者，修复共享入口后恢复。原 Admin 服务不在此次回退包内。

新增服务以 enabled/active 验收；FC worker 已恢复。NBA 服务重启加载新实现；RPG 发现既有 dispatched 工单，未重启其执行器，后续新工单按绑定源码加载新认证。sales、旧 dashboard 的退役/冷却调度未擅自开启。

## FC 原操作与失败保全

1. 原故障自动操作 `9090ef56-7249-480e-b20a-91e34405323e`：`hook_scope_paused`，保留。
2. 恢复后的手动完整采集 `5cd374f5-dc03-40c5-88bb-9903c2cccd4c`：ready，三平台有效成本及当轮报价。
3. 自然操作 `f1815592-9d7d-45ba-82c8-9c8da6ff42f4`：Order 的 PS/Xbox 写入和同步已确认，随后 ALL 同步在原固定 `chenchao` 身份检查前失败。原 job 保持 failed；原 ALL 账本 `needs_reconcile` 且 steps=[]，证明未发生 ALL 价格下发。
4. 用户新增两账号白名单后，FC 容器改为只消费 8767。对同一原操作先锁内核对 Order 实际值、空账本、原文件哈希、当前策略、全局身份及两轮稳定来源，再补完此前未执行的两项 ALL 同步；没有重放 Order 价格或同步请求。六产品回读一致，原执行审计恢复 CONFIRMED，保留 original_failure/recovery；原自动 job 不改写为自然成功。
5. 2026-10-21 15:24:02 +08:00 原清缓存一次成功；15:24:40 +08:00 三平台公开 100K 售价按原判据 verified。恢复证据在服务器 `recovery-receipts/f1815592-9d7d-45ba-82c8-9c8da6ff42f4.json`。
6. 参数恢复为 revision 39，原 120 分钟、10% 最低毛利、三平台和分档完全保留。自然操作 `0ca88db2-4c21-4d85-94e2-c4289457706d` 在新增适配器的导入前失败 `process_output_invalid`。已在真实镜像中复现导入路径缺口并修复；该 ID 无 execution/ALL 账本，原失败保留。增加回归测试覆盖入口加载与两账号。
7. 参数原值再次保存为 revision 40。发现 Order 健康验证实测 2.41 秒，FC 的新接线原 2 秒超时会误告警，已改为 8 秒；仍失败即阻断，没有删除监控/锁或放宽价格判据。

## 检查结果

- 本地 16 项测试通过：会话合并与失效清空、全局不可用阻断、cookie jar 替换、8767 仅取 token、两账号白名单/第三账号拒绝、外部请求路径拒绝、真实容器导入回归、future import 和源码漂移拒绝。
- 服务器最终 16 项通过；本机按 pr-fast 隔离、禁止外网及外部进程的执行方式同样 16 项通过，0 skip。
- root 可取 Order 会话，nobody 被拒绝；健康接口不含 cookie、token 或密码。
- 受保护的 Order 价格管理、统计、发货记录三个真实页面 HTTP200 且认证有效。
- FC 实际成本采集 PS/XBOX/PC valid；NBA `/api/read` 实际 ok；RPG 全局身份 ready。
- FC 实际镜像带本次挂载：writer 可导入、两账号名单可读取；Admin 身份 GET code=1、白名单通过，没有独立登录。
- Madden 实际浏览器容器与 RPG 实际工单镜像均成功读取8768会话，未触发业务写入。
- 未为其他游戏发起业务写入；未复验球员 wiki 价格。

## 已完成自然周期验收

2026-10-21 15:40:42 至15:43:07（Asia/Shanghai），原定时器的 revision 40 自动安全重试 `f8189270-230b-4d65-9abc-dc05087c5011` 为 ready/confirmed：PS、Xbox 真实改价，PC unchanged，blocked_platforms={}。执行账本 CONFIRMED/readback_confirmed，ALL 三步骤及六产品回读确认；清缓存一次成功，实际变价的 PS/Xbox 公开 100K 售价 verified，三平台公开数据均当轮刷新。

后续球员任务 `f976f32c-c142-55fc-80e6-cf1916e507ac` 为 ready/confirmed，category_all 请求 accepted，price_verification=disabled、sample_count=0。不据此声称球员 wiki 价格复验通过。

原失败操作、人工恢复和本次新自然成功分开保留。当前120分钟、10%最低毛利、三平台及分档保持原值；只重新保存恢复了配置版本。最终脱敏证据见 `verification.json`，源码/现场哈希见 `source-map.json`。

正式 CI、PR 和合并 SHA 单独记录于本机 GIT-RESULT.json。登录态未来失效时，消费者统一阻断，由唯一会话入口完成认证，不得恢复独立登录洪水。


## 长读取稳定性后续

8768轻探针v3已上线，完整限制说明见LIMITS.md；60秒13次健康均ready，0.8—3.2ms。8767锁分离/90秒读取候选已完成并在真实源内存编译，16项测试通过；当前进程和镜像未切换，避免丢失有效登录和打断Sales全量。候选不作为上线证明。Sales同页重试由另一会话PR270负责，当前源码后续清理哈希已在source-map单独标记，不回写旧补丁。
