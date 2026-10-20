# FS 智体中心管理员判定故障修复

状态：13项定向测试通过，GitHub隔离分支已创建；PR/部署/生产验收推进中。此前权限拒绝在用户追加授权及会话审批配置更新后解除。

用户报告2026-10-20 12:46北京 /advisor?mode=hermes 返回503、详情200，夜间状态每5秒写入nightly_PermissionError。该现场结果为用户实测，本轮没有宿主独立复测。

范围：仅controller.py报告列表与fc_daily.py策略加载及直接回归。负责人：当前Codex；业务归属吴律。来源固定于私库main e72ecf3f7b6ab85d21d4720c5284bbacd8d87f60，候选路径fs_hermes_admin_recovery_20261020/。controller源为releases/fs-dashboard/hermes-report-repair-20261019/source/controller.py；fc_daily源为releases/fs-dashboard/fs-revision-20261015/ai/candidate/fc_daily.py。后者及宿主活动字节尚待现场核对，禁止按本候选整包覆盖。

实现：管理员模块按mtime_ns/大小/设备/inode缓存；变化时编译新字节以避免同秒pycache复用。每次仍调用活动策略is_admin/status，让RBAC策略热更新与撤权生效。加载/引擎降级返回admin_unverified及脱敏错误类型，真正不在策略名单返回not_admin。失效后不沿用缓存管理员身份，不改策略和账号。

列表一次读取授权结果；验证失败只读本人报告、导入池保持同一身份过滤，禁生成/删除/续行并显式返回authorization与admission.reason。nightly.status的PermissionError仅令夜间状态blocked，列表仍200。详情、证据和原产物代码路径保留；夜间实际执行仍需合法管理员，未放宽nightly.config或开启任务。

验证：13项Python本机测试，无skip。覆盖并发只加载一次、mtime/原子替换失效、缓存模块仍热更新策略、撤权、缺文件/ImportError/语法错误/策略degraded、本人池过滤、正常共享池、异常authorizer、详情产物，以及提取既有Handler与真实SQLite的本机HTTP请求200。此为合成数据本机集成，不是生产/真实账号/UI/自然夜间验收。测试第一次HTTP用例因合成SQLite连接线程限制失败，修正夹具后13项全部通过。没有调用模型或重跑报告。

重跑：在工程根执行 python fs_hermes_admin_recovery_20261020/test_admin_recovery.py 。本测试仅临时目录与loopback，无生产写入，可安全重跑。candidate/tools/pr_fast.py接入现有pr-fast，未新增workflow；正式GitHub CI未执行。

阻塞：统一SSH入口在读取C:\\Users\\Administrator\\.ssh\\fs_admin时被沙箱拒绝，故用户要求的ls、admin_cli status和bind mount核验均未执行。GitHub创建隔离分支被工具拒绝：MCP tool call requires approval, but approval policy is never；没有换凭据、API或其它通道重试写入。30分钟PR预计因该拒绝不可兑现。

后续：恢复允许的Git写入与宿主访问后，先核实时下main/PR和两活动源码SHA；提交本目录PR.patch对应最小载荷并执行pr-fast。宿主确认策略文件可读、admin_cli status的degraded/admins与8931挂载；若确证陈旧挂载，按本次授权仅重启fs-business-range，保留Hermes服务。使用现有发布锁/CAS/备份与精确新载荷；不可用旧manifest/候选整包盖回。随后真实8931 GET带X-Auth-User:wulv应200、页面连接待恢复消失，并核合法管理员接口与原nightly错误不再新增；下一自然夜间周期独立观察，不补跑或伪造成功。



## 追加授权后宿主复核

宿主策略代码root:root 0644，进程内外inode2235172相同，没有陈旧bind mount证据。admin_cli真实策略generation10/revision b2063367864717d5，超级管理员为DY、chenchao、fstech、wulv；mmoexp本次不是管理员，不据历史猜测扩权。新Python进程中四人admin=true且policy.status.degraded为空，但长期运行8931仍列表503/会话403，故障与长期进程状态有关，具体被吞内部异常尚未取得，不能宣称已证实挂载陈旧。

本次重新下载两个活动源：fc_daily.py SHA256 5b4a00a3da8e6cfed5e85aa1c3c5de998c8e49b87c3ca3fae7bad3c299fa0b80；controller.py SHA256 01e2687ea0a6a2786808bdac158340de6f51cc00e7cbf77cdef753bd4da7e774。fc_daily旧候选仅末尾空行有差异，已按活动字节重建最小补丁。策略、账号、Hermes网关及原失败证据保持。


## 发布范围

PR #245：77e1ab8f1fc5eae599de3242c98d233c89e8dd83 首版CI run39373502427/pr-fast成功；新增精确两目标发布适配器后按新head复验。复用SHA1d070ee8…f2de的既有release_navigation_base.py，保留发布双锁、来源/消费者CAS、admission与provider锁、真实在途队列检查、intent日志、备份及按原ID回滚。fc_daily从不变保护池转入本次目标CAS，未减少实际文件保护。新增适配器仅停启fs-business-range，不重启Hermes服务；会话/客单任务与来源读取仍须空闲。15项本地测试（含两项发布范围、源哈希、冻结发布器和仅8931重载断言）全部通过。


## 云端续接：2026-10-20 13:25 北京时间

原任务因用量限制中断，沿用 PR245 及候选，不重建任务载荷。独立复现 CI 的两项 frozen_publisher_drift：仓库 LF 字节 SHA256 为 57f4baf8db15fc791375b641fb618ef87a867901643bc0aa33f10804b8fcb840；仅转换为 CRLF 后恰好得到原固定值 1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de。改为固定仓库 LF 字节，仍拒绝任何字节漂移，不取消哈希检查。15 项定向测试在 dot 云端重新通过。后续部署必须携带仓库 LF 版本的基础发布器。此处仅记录测试修复，未部署。
