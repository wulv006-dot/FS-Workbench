# RPG / Order P0 恢复记录（2026-10-23）

本记录为本次子 Agent 的模块交付，不替代父任务统一验收。时间均为北京时间。

## 已确认原因与影响

- 10:54、11:24 两批 AION2 / ARC Raiders / 暗黑破坏神4共6张工单，均在 `SrvSession.__init__ → fs_order_client.apply → cookies` 阶段失败，错误为 `global_order_unavailable:order_probe_unavailable`。它们没有产生写价结果文件；保留原失败ID，不重放。
- 全局 Order 8768 的身份探针原先在 `fc27-cloud-browser` 内运行，共用 FC 竞品 Chrome。该 Chrome 达3GiB触发OOM后，Order会话获取也失败。8768本身检查真实身份页，问题并非仅看HTTP 200；浏览器容器成为跨业务单一故障域。
- 全局 Admin 8767是独立容器。本轮还发现 RPG 清缓存工具继续读取旧本地token并独立OCR登录；09:25 / 10:23 AION2分别写48 / 42行成功，但主后台清缓存失败。这是另一项认证接入遗漏，不能统称由SSH或同一个Chrome导致。

## 已执行恢复

1. **11:52:55 Order隔离**：复用原Chrome镜像，新增无公网端口的 `fs-order-browser`，独立持久profile。只在内存中迁移3条Order cookie，原共享HTTP / socket合同、身份校验及所有消费者路径不变；原Chrome不重启。
2. **11:54:52 首次真实重启验收失败**：普通持久profile不能保留原session cookie，已用内存保全的原cookie恢复，未重登或延长有效期。失败回执原件保留。
3. **11:57:25 修复会话恢复参数并通过真实重启**：新容器加入 `--restore-last-session`，原profile、原cookie保留；旧容器作为stopped备份。单次真实restart后，身份和cookie指纹一致。主隔离回执为 `verified` / `durability_verified=true`。
4. **12:05:30 RPG五文件受控发布**：原FC队列锁及全部读写锁、RPG空闲与执行器锁内，复用原 `publish()` 备份 / CAS / 原子替换 / SHA读回，仅重启RPG执行器，原业务配置、计划和数据库历史保持。
5. **12:06:30 仅补缓存**：原工单 `J20261023102347-1` 的42行成功与旧 `clearcache_ok=false` 保留；单独调用全局Admin清缓存一次，真实HTTP200 / code1。没有重写这42行价格。
6. **真实UI入口已读回**：原发布器保留旧mtime导致Jinja一度显示缓存模板；在SHA不变的前提下更新时间戳，HTTP入口已加载未知、部分写入、缓存未刷新标签，未重启主RPG服务。

## 安全恢复边界

- Admin只读全局8767，删除此模块独立登录、账号读取与token落盘路径。仅已确认的30秒频控可以等待31秒重试同一清缓存请求；超时或未知POST不重放。
- RPG在原工单ID下落盘执行阶段，每次真实价格写入前先fsync记录尝试数。完整结果必须匹配原ID。
- 仅持久化证明“进程已结束、零次写入”的预写故障，保留原自动failover能力；超时、结果不全、已写入或复核不一致，禁止克隆新ID重放，保留原单 `unknown` / `partial` 待核。
- 后台已成功而缓存未确认，不触发重新写价。数据库仍用原status，细分状态进入 `result_json`、执行器状态与页面/CSV，不改历史失败结果。
- 当前Hermes `monitor.rpg` 仅检查内存采集tasks和服务状态，尚不消费逐工单的 `write_state`。本次不能声称Hermes群告警链已接通；执行器既有告警另保留。

## 验证与限制

- 本地14项相关回归、服务器Linux10项相关回归、JS语法及4个状态断言通过。
- 新候选在原镜像/临时profile真实运行Order只读ping与Admin status，均rc0，阶段记录零写入；8767登录次数2→2，Order登录次数0。
- 独立的可公开CI检查为RPG8项与Order10项；不依赖私有基线，不包含业务原始载荷。追加兼容检查证明既有只读及单独缓存命令不要求价格操作阶段；价格写入仍要求原ID证明。该单文件兼容补丁已CAS发布，未重启服务。
- 补丁生成器已在服务器Python3.9.18完整运行：原备份仅在服务器临时目录提供，五个生成物SHA均精确匹配当前活动文件；未修改生产。生成器实际运行需要显式提供符合SHA的受控基线，CI不携带或依赖这些原业务文件。
- 截至12:08，恢复后的RPG未产生新的自然写价工单，不能宣称新的自然写价周期验收完成。旧6单失败及原ID保留。采集tasks当前均done、全局8767/8768 ready；这些证据不等于新变价验收。
- 内存源头的竞品文档短驻留候选由独立子Agent准备，具体归父任务的FC内存交付，不能把此次隔离或reload兜底称作第三方泄漏函数已定位。

## 12:48 新自然周期验收通过

原采集任务 `3b3f3b338ab5` 于12:15:57开始，原自动流程于12:32:49生成以下四张工单；观察过程中没有创建、重放或手动触发价格写入。原失败工单、发布时点的待验状态和首次耐久失败回执均保持原件。

| 原工单ID | 结果 | 实际写入 | 缓存与完成时间 |
| --- | --- | ---: | --- |
| `J20261023123249` | 物品改价完成，失败0、复核不一致0 | 11 | 清缓存成功，12:42:03完成 |
| `J20261023123249-1` | AION2改价完成，失败0、复核不一致0 | 56 | 同步/记录价格及清缓存成功，12:46:19完成 |
| `J20261023123249-2` | ARC Raiders三个服务区同价，无需改价 | 0 | 不要求清缓存，12:46:30完成 |
| `J20261023123249-3` | 暗黑破坏神4四个服务区中三个同价、一个改价，失败0、复核不一致0 | 1 | 同步/记录价格及清缓存成功，12:47:17完成 |

四单均为原ID、单次尝试、`done` / `write_state=confirmed`，执行阶段已完成，结果文件的 `operation_id` 与原工单一致。本批没有新增unknown或partial。12:48:22全局8767/8768均ready，登录次数分别为2和0；验收观察没有产生新的独立登录。新自然结果证明本次共享会话和RPG执行/缓存链路恢复，不能据此宣称长期稳定。

物品单执行期间仍观察到Order上游查询页耗时和超时；同一全局会话的身份页能够响应，部分物品查询页出现8秒以上只读请求超时，执行日志亦出现60秒页面导航超时，最终原工单完成。此慢查询仍需独立追查，现有证据不足以归因到具体SQL、网络环节或认证失效，不能靠反复重启浏览器处理。

未知写入保护已通过相关代码/合同回归，本次没有对生产写入注入超时或中断，因此不能称已通过真实故障注入验收。Hermes逐工单告警尚为规划，见 `RPG-MONITOR-WIRING-PLAN.md`；没有新增群通知或调度。

脱敏证据为同目录 `RPG-NATURAL-ACCEPTANCE.json`：仅保留工单运行ID、数量、布尔结果、时间、状态及结果SHA，不含客户标识、订单载荷、具体价格、请求正文、完整日志URL或会话。ARC Raiders的0行表示同价确认，不计作真实写入，也不计作清缓存成功。

## 精确入口与证据

- 维护候选：`rpg_global_admin_recovery_20261023/`。双SHA映射：同目录 `SOURCE-MAP.json`。
- Order隔离回执：`/var/lib/fs-order-session/browser-isolation-20261023.json`；服务目标SHA `e94f54cebe50cbede113ce4205ad2fe337b176438e0e864c1caa73ae90d3c88a`。
- 首次耐久失败：`/var/lib/fs-order-session/browser-restart-20261023.json`；最终成功：`/var/lib/fs-order-session/browser-session-restore-20261023.json`。
- RPG发布回执：`/var/lib/fs-order-session/rpg-recovery-20261023.json`；补缓存回执：`/var/lib/fs-order-session/rpg-cache-recovery-20261023.json`。
- 备份：`/var/backups/order-browser-isolation-20261023-v1`、`/var/backups/rpg-global-admin-phase-20261023-v1`。回退须原SHA/CAS及原空闲锁检查，先核未知操作，不重复执行发布脚本。

公开同步仅允许无秘密helper、精确补丁生成器、自包含测试和SHA映射；完整原业务代码、原始回执、cookie/profile及私有基线不随此文同步。
