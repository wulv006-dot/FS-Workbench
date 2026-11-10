# 三平台发布与bundles首次锁迁移

本说明交给本轮唯一发布者执行；代码候选、CI和部署状态见PLAN/ACCEPTANCE。本文本身不是已经操作过生产的回执。用户已授权本轮实施发布；仅在原空闲窗口串行执行，不触发额外改价轮、模型任务、timer或Players唤醒。

## 固定源与原发布器

沿`releases/fc-coins/fc-pricing-v3-20261026/deploy/`原builder/prepare/adapter及冻结`release_navigation_base.py`。默认101与旧scope保持；`--three-platform`才包含3个新增V3模块双镜像、bundles两份显式根源与既有monitor hooks源，候选总110。实际写入只使用`target_map.THREE_PLATFORM_NAMES`的新精确scope，根在最终commit前核对全部运行源差异，不拿110个候选全量覆盖。金额/部署CAS、原FC/Hermes admission、UNKNOWN、锁、备份与回退保留。

```text
python releases/fc-coins/fc-pricing-v3-20261026/deploy/build_stage.py <checkout> <archive.tar.gz> --three-platform
```

builder要求上述源已提交，外部bundles源也从同一Git commit读取。不要在尚有本轮dirty源时制作最终包，不复用旧prepare基线。

## 首次旧bundles的必要维护链

旧服务的WRITE_LOCK仅在进程内；手动请求抢锁后起daemon线程并返回202，自动路径也用同线程锁。它没有SIGTERM排空。HTTP日志用`print`且未flush，当前unit未启用无缓冲；“journal里没看到202”不能证明没有已接受请求。`wchan=poll_schedule_timeout`同时可能是网络等待或Python3.9的sleep，也不构成排空证明。

新代码所有已接受手动请求在202前持跨进程锁、自动和直接dispatch同锁，直到原终态日志完成；原publisher持同锁覆盖修改、重启和读回。新请求锁忙明确409且未起worker。没有新增持久队列或自动重放。**首次升级旧进程不认识该锁，不能因锁文件存在就声称已排空。**

首次执行顺序如下，配置及业务写入由根统一执行，子任务只完成代码和只读证据：

1. 确认原FC/Hermes执行空闲。在本stage私有目录（root:root、0600）保存bundles完整原配置、revision及当前PID/启动ticks/原scheduler身份。原设置可能含私有配置位置，不能输出到聊天、Git或公开manifest。已有adapter提供只读采集入口，输出只报摘要：

   ```sh
   /opt/python39/bin/python3 "$STAGE/deploy/fc_v3_release_adapter.py" capture-bundle-baseline --output "$STAGE/private/bundle-before.json"
   ```

2. 通过原`/api/config`使用原revision做CAS；保全原settings/bundles，仅临时将`write_enabled=false`、`write_auto=false`，其余参数不动。旧服务可能仍先返回202再在worker报`write_disabled`，不能冒称旧API已经改为409；源码可证明该错误出现在创建AdminWriter/后台调用之前。不得发送探测write请求。

3. GET原`/api/state`核新revision、完整settings与磁盘一致且两个开关确为false。等待原在途自然完成，不中断或重发。只读capture必须证明原PID/启动ticks未变、仅main和原startup scheduler两线程、scheduler实际是x86_64 `select(nfds=0,NULL,NULL,NULL)`的sleep，且`last_refresh`不在running。额外manual/HTTP worker、网络等待、配置变化、进程更换或覆盖不足均拒绝；不能拿wchan或旧日志单项替代。

   ```sh
   /opt/python39/bin/python3 "$STAGE/deploy/fc_v3_release_adapter.py" capture-bundle-bootstrap --baseline "$STAGE/private/bundle-before.json" --output "$STAGE/private/bundle-bootstrap-proof.json"
   /opt/python39/bin/python3 "$STAGE/deploy/prepare_manifest.py" --three-platform --bundle-bootstrap "$STAGE/private/bundle-bootstrap-proof.json"
   ```

   proof仅含原/新配置hash、off revision、PID及线程启动ticks、原源码SHA，不含原配置。prepare会把该metadata冻结进原manifest；后续每个原guard再现场核对，不能靠旧proof或版本标签跳过首次排空。首次锁只可在这些条件成立、且原apply已持原FC锁时建立。

4. 读取并冻结**stage根目录**的`approved-manifest.json`及其SHA。沿原adapter CLI inspect/apply，显式指定根manifest，避免把deploy内副本当成不同候选。原发布器会检查原model fence、FC队列/重试锁、完整CAS、保护文件、备份与metadata；仍需原批准SHA和唯一未使用release ID。命令如下；`MANIFEST_SHA`从本次根manifest计算，`RELEASE_ID`须为唯一新编号，不复用旧SHA/编号：

   ```sh
   /opt/python39/bin/python3 "$STAGE/deploy/fc_v3_release_adapter.py" inspect --manifest "$STAGE/approved-manifest.json"
   /opt/python39/bin/python3 "$STAGE/deploy/fc_v3_release_adapter.py" apply --manifest "$STAGE/approved-manifest.json" --approved-manifest-sha "$MANIFEST_SHA" --release-id "$RELEASE_ID"
   ```

5. 发布后检查目标SHA、原FC依赖与bundles服务；bundles `GET /api/state`同时返回`price_scope_contract=fc27_three_platform_v1`与`write_admission_contract=bundle_write_admission_v1`，证明实际加载了新进程。首次旧PID proof只用于改前准入；持同锁后的new/rollback阶段按各自完整目标SHA、已加载合同和同一off revision/hash核验，不能因正常换PID误回滚。

6. 所有读回完成后，仅在配置仍为原off revision、原off hash且无其他变动时，经原API CAS恢复完整原settings和bundles。正常revision应单调增加，恢复后的除revision外内容必须与私有原快照一致；间隔和长期策略不能改变。若CAS冲突，不覆盖别人新配置或盲重试。完成恢复后读回开关、全部设置与原周期；不人为触发新改价轮。

若apply失败，沿原journal仅回退本次代码，保留数据库、账本、队列、日志、原UNKNOWN和后续合法业务变化。保持off直到回退的旧服务与目标SHA读回确认，再按同一CAS条件恢复原配置。不能先开闸再查回退，也不能用旧全量配置/数据库盖回。

## 已有历史失败与本轮证明分开

只读原write_log的5项needs_review为历史AdminHttpError（1项524、4项502），错误记录不保留GET/POST/读回阶段，不能断言未派发或改原回执成功。4个对应商品后来有原自然auto `written`及当前Admin实际价匹配，可独立说明当前状态，但不能借此改写历史UNKNOWN。原记录完整保留，本轮无新POST探测、重发或清状态。

首次B的排空证明来自CASoff、原PID/线程实际syscall和原执行完成状态；新版本之后的发布直接使用A同锁。任一必要条件不满足，就等待原任务或报告具体阻碍，不停用P0 Coins及其依赖。

## 直接验证

`test_three_platform_release`包含新scope/101兼容、110候选、外部Git源、精确新文件身份、bootstrap配置/线程缺项、实际adapter改前→新PID读回→旧代码回退顺序与Linux真实flock合同。bundles `test_write_admission`用两个进程验证维护拒新请求、已接受请求在日志完成前保持锁、自动/直接同锁及异常不重复调用。Windows的平台限定skip由183/Linux实际执行补证；CI、发布与自然轮仍分开验收。
