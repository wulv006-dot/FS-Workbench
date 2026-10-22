# 发布与回滚（每批须绑定具体批准清单）

## 载荷与现有发布器

`python tools/prepare_knowledge_release.py --output <独立未存在的staging目录>`只离线生成载荷。它将明确索引的Git原文复制成不可变发布物，记录原路径/提交/哈希；不产生第二份可写业务源。派生索引的published表示供发布的固定产物类型，**文件仍只在离线staging，不能因此称已部署**。源仓库索引仍为candidate。

确切作用域：

- 活动文件只含`/opt/fs-hermes-fc/business_context.py`、`controller.py`、新增`knowledge_catalog.py`。
- 知识发布目录只含`/var/lib/fs-hermes-fc/fs/knowledge-releases/knowledge-layering-20261023-1/`内的索引及其引用原文。保留原目录、旧快照、经验DB、请求映射和账本。
- 不写`business-baseline.md`、FC策略目录、learning-loop、技能原文、nightly-schedule、knowledge-load-policy、定时单位、认证或权限配置。

`deploy/release.py`只是确切作用域adapter：加载既有`fs-business-baseline-20261021/deploy/release.py`，再用其冻结navigation发布器。两个依赖保留原字节哈希，不按文本LF内容哈希校验发布器。CAS、锁、空闲检查、准入fence、备份、逐文件意图账本、原ID回滚全沿旧实现。本次没有另建文件替换/回滚器，也不用会调整定时器的daily-archive adapter。

## 批准后连续执行

1. 在同一change_id下核最终Git/CI、载荷SHA与本清单；只读重新核活动源及保护对象。controller、business_context须仍与W0基线一致，否则先保留并行修改、重做最小补丁和受影响测试；不覆盖原FC任务。
2. 由Codex补齐现有publisher所需的`beforeSha256`、`unchangedRequired`、服务状态和镜像ID，并保存具体最终manifest。旧基准/保护对象变化先核其含义，不能删保护对象或放宽断言。离线生成的manifest默认`releaseReady=false`，缺失基线不能apply。
3. 批准覆盖本载荷且现有publisher inspect通过后，使用原安全SSH入口上传到独立合法staging，调用原adapter的inspect→apply；固定approved-manifest-sha、release-id。活跃任务期间等空闲，不取消/抢占。若现场不支持现有publisher，停在候选并报告缺口，不绕过CAS。
4. 仅Python消费代码更新需要原服务顺序`fs-hermes-fc.service`、`fs-business-range.service`的准入fence和健康读回；只更新知识正文/索引时不重启业务服务，不触及nginx或定时器。服务操作仍须清单批准。
5. 读回三个文件、知识目录/索引/原文哈希、原受保护文件和原任务状态。在隔离临时根内用新loader选指定模块和条目→原freeze→loaded_learning→effective_learning，确认内容/ID/版本可还原；这是实际代码只读装配验证，不是模型运用验证。
6. 真正模型验证或普通报告入口切换需在批准范围明确列请求ID、只读工具与适用模块；本载荷不写生产路由策略、不切FC改价/教学、不触发改价或重教学。原始FS/飞书会话没有因共享profile而自动接线。
7. Notion按迁移映射写摘要与固定版本链接并fetch读回；再完成统一收尾账本。

## 失败、重试与回滚

发布前缺基线/哈希/正文/权限就保持上一有效版本。发布中断/结果未知先查原release-id、backup/journal、实际文件哈希和任务绑定，不换ID重跑。不明确是否已发布时不改索引路由、不把候选塞进生产。

按旧发布器`rollback --backup <本次原backup路径> --approved-manifest-sha <原值>`恢复确切前值；保留DB、队列、旧任务知识快照、回执及全部原失败证据。只回滚本次文件，不能用旧整包覆盖。恢复必要服务和实际哈希后才记回滚成功。Notion只修订本change_id管理摘要，不删除人工内容与历史。

本批已按用户确认完成发布：原ID`nav-20261022T174000Z`、manifest SHA256 `9a10341094914ccf4b1c18e552bfe0a9e7456a678eb1da196c279c50f70fef95`、原备份`/var/backups/fs-navigation-20261006/nav-20261022T174000Z`。10目标/50保护、两项原服务健康及隔离装配已读回；Notion三页已写后核验。真实模型调用与回滚演练未执行。已发布对象不得再次apply；回滚前先核后续并行发布和活动哈希，不能拿本批旧before值覆盖其他任务。详[交付回执](DELIVERY.md)。
