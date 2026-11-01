# 04逐任务完成/待验/未做矩阵

这是当前本地候选状态；“代码/fixture实现”不等于生产恢复。历史固定包说明保留各自时点，不覆盖本矩阵。

| 04任务 | 本地已实现/证据 | 待验 | 尚未做/接线 |
|---|---|---|---|
| 1只读盘点 | 正确隔离worktree/remote、187身份/已知source hash、Python3.9.18 SQLite3.7.17、两backup逐文件/占用/fd范围 | 全数据集活动映射、容量增长/负荷实际基线 | FC/NBA/MLB/RPG逐dataset目录未全覆盖，不称全站完成 |
| 2日期/capability | 独立half-open/calendar/五边界/授权先于cap合同，query结构schema | 真实source最早/最新边界及完整capability/result schema | 实际endpoint、picker/dayMin、旧URL、导出/Hermes同policy未接 |
| 3范围下推/proof | 固定scope/date/fields planner、summary整窗/详情按profile分片、proof格式与错误类fixture | 真实Admin/Order字段/分页/空/退款/水位再生证明 | 真实source adapter尚未实现/接入；无live proof登记，不扩采 |
| 4轻量日档 | 原Archive/catalog轻事实、幂等修订/dirty/币种、同SQLite读事务，审查P1已修 | 目标旧SQLite运行、真实口径/延迟/WAL/锁与维护引用 | 未配置真实dataset、原timer/锁接线，未生产DDL |
| 5受限job/cache | 订阅取消/晚结果、grant/epoch复验、HMAC/cursor、预算、同源水位、持久页与generation+revision CAS、artifact/pin候选 | 真实IAM、source稳定水位、原host/admission锁、故障续读/私有下载 | 未注册API/Hermes；Retry-After退避/正式报告pin/原宿主集成未完成 |
| 6用户历史 | read_at/orders_at版本索引默认关；缺库正常加载禁止创建；c079/f630 Linux已验适用路径 | 活动源diff、真实一致性副本recipe shadow、索引/WAL空间及迁移 | 生命周期current/period_end小锚点未实现，仍有全历史分析路径 |
| 7成员分页/导出 | 原Service默认关的真DB keyset/stream、原recipe/hash绑定、精确筛选、签名cursor、两阶段发布合同；v2共享投影集/总预算 | 当前新sink/v2预算与实际私有sink/manifest读回、旧snapshot影子迁移 | 默认未启用，真实epoch/sink/verifier/publisher和UI下载未接；不是已上线 |
| 8前端/Hermes | 具体A协调接口方案/可复用合同 | owner窗口内同policy及授权错误/大结果验收 | 尚未实际修改共享A/B入口或前端日期适配器 |
| 9缓存治理 | 纯dry-run/protected-root/proof/pin-epoch竞态/预算/文件完整性fixture、例policy disabled | symlink Linux反例、可信引用/正式pin/实际再生proof | 无apply，无生产清理策略、daemon、额外timer或删除 |
| 10恢复/回滚 | 三类缺失决策、frozen不回源、接受新基线损失、只回读路由保新写fixture | 指定保留能力一致性恢复/影子验证，身份mapping与recipe真实依赖 | 本轮未重做旧backup恢复/验签；未执行生产恢复/新采集 |
| 11影子/发布 | 本地固定提交/直接测试/两次固定Linux包、独立窄审P1修复；当前最终包待验证 | 当前完整固定包Linux/独审/CI、逐source灰度与真实入口 | 未推送、PR、合并、部署、切换；无生产批准清单 |

## 验证版本必须分清

- c079b3b：父独立Linux users265/tiered14通过，0skip；不是当前全包。
- f630a6e：父独立Linux users276/tiered41通过，0fail/error/skip，源码只读断网；包含真正POSIX缺库竞态、原writer/recipe及generation交错。1次SQLite ResourceWarning保留；不称零警告。
- 本轮当前改动：成员测试17项（Windows16通过、1POSIX待云）；proof/清理/恢复10项（Windows9通过、1真实symlink待云）。当前sink/v2/总预算尚未Linux验收；不重跑已知Windows fcntl失败整套或无关91工具测试。
- 187只做:memory: DDL/CAS探针，22组DDL在当时源码通过；后续v2新表及新逻辑仅静态基本SQL兼容核查，不把探针绿当完整旧SQLite验收。Python3.9 AST当前15份source通过。

## 索引成本与硬边界

旧候选1万同数据第二快照仍增约4808704字节refs。v2对相同query_hash/private_hash复用签名分类集，1万成员body/ref各10000而非20000；第二相同输入快照只增小manifest，本fixture未增加allocated DB数据页。不是所有不同问题/日期都可共享。
新首次1万索引增9125888字节，约1.095秒、Python heap峰值2331244字节；首次比旧候选更大，不能据此声称总存储一定下降。真实WAL/RSS/多group/长期增长未知，必须校准。
build默认总refs/records<=100000、估算新增<=64MiB、实际SQLite净page增长<=64MiB、协作式总耗时<=30秒；可信配置受限上调。超行/估算bytes/实际page/中途时间反例验证同事务回滚，原20body/20ref/1set/1manifest不变，未发布新ready。时间在每行及commit前检查，单次序列化/SQL无法被此Python检查硬抢占；page净增长不等于OS/WAL/journal峰值，失败也不原地VACUUM或强制截WAL。

## 下一最小动作

1. 父任务一次验证当前固定Linux包+独审，特别确认sink成功不等同迭代耗尽、publisher在原锁内复验、v2旧recipe等价、总预算回滚和真实symlink。
2. 用A-INTEGRATION-PROPOSAL统一协调真实epoch/私有artifact宿主、capability/range adapter与UI窗口；没有真实scope的模块保持关闭。
3. 先核必要缺库保护的活动源最小发布载荷和恢复取舍；申请准确生产前置/回滚清单。全04 UI/job未齐不作为旧backup清理的额外全历史门槛，但必要修复/真实验收和删除当时确认不能省略。
4. 之后按dataset完成真实proof、影子/空间/锁验收，再考虑获批policy的原锁可逆回收。两旧backup永久删除始终单列；本轮释放0。
