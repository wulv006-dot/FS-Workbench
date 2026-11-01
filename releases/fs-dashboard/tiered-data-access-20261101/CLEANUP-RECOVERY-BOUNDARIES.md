# 可再生证明、纯dry-run与恢复取舍

## 当前实现和证据

新增eviction_policy.py、recovery_contract.py、test_eviction_policy.py及synthetic-only CLI。没有apply/delete/rename回调，没有daemon/timer。只接受显式管理manifest、固定root/数据集白名单及64hex.data.json对象，不凭目录或“cache”名字认定可丢。live proof示例verified=false，当前没有任何已完成真实Admin/Order回源证明，不能借fixture冒充。

Proof合同区分current_state与historical_as_of，并要求源合同、scope、明确日期窗、字段、稳定键、分页/边界/退款/失败非空等检查及证据hash。schema验证只证明证明材料的格式/自洽；真实证据和批准状态必须来自原宿主可信registry，本候选不签发真实proof。

dry-run只列候选或hold及bytes/stat/ref-epoch/proof/policy。L0/L3、frozen、活跃/未知job、主库/key/journal/原Excel、两个旧backup所属用户分析root始终排除。未知文件、symlink/祖先symlink、hardlink、非普通文件、hash不符、root越界、时间窗不被proof覆盖、未知pin/引用扫描不完整、超对象/批预算均hold。哈希流式有界，打开后核inode/普通文件，文件变化失败；不输出正文。

recheck在注入的原maintenance_lock内重读引用及文件stat/hash；新增pin、ref epoch漂移、锁失败、扫描异常都拒绝。它仍只回dry-run判定，不接受删除函数。后续若拟启用，必须沿原cache_retention.cache_lock/admission及原7日可逆压缩回收合同，不直接永久删除；Excel原冷归档恢复合同不变。候选清单不是删除授权，操作时需再核引用/pin/负载。

本轮相关10项：Windows9通过、真实symlink1项因权限跳过，最终Linux必须执行。源与fixture均不触网；CLI只构造一个18字节临时合成对象并在dry-run前后确认原字节/mtime保持，fixture准备/清理不算生产清理收益。所有生产对象mutations=0，旧backup释放0。

## 恢复/必须保留边界

| 场景/类别 | 允许的恢复方向 | 不能承诺/不能做 |
|---|---|---|
| 已有真实proof的L1当前副本，单个MISS | 同scope/policy/range复用日事实，缺片再有界取；预算不足转job/partial | 不整库导入或复制全库备份；当前任务尚无live proof |
| 新轻量读模型为空 | 只schema与必要元数据，按第一个具体问题懒加载 | 不能空模型=零业务或自动全客户历史采集 |
| 权威主库丢失 | 明确unavailable/recovery_required；指定一致性恢复链，或用户接受损失后显式有界新基线 | 不用新空库冒充完整，不自动重建UNKNOWN/执行回执/策略/身份 |
| identity key存在但旧mapping丢失 | key并不等于完整客户CID映射；只能复用已验证mapping，或明确新的分析身份namespace及相应批准 | 不声称旧随机CID可由key自动重造，不擅改登录身份/凭据或新建key |
| frozen recipe/旧as-of必要输入缺失 | 恢复指定pin输入，缺失则missing_history；可按接受取舍声明旧能力不可用 | 今日上游不能替代旧时点名单/金额或原recipe版本 |
| 必要日facts/锚点/已承诺历史 | 作为L2/L3保留原口径、revision、身份指纹和引用 | 不随热窗到期当缓存淘汰 |
| L0、UNKNOWN、journal、receipt、权限策略、key、唯一Excel | 原权威域的一致性/恢复链；持续保留新写 | 不混入本轮清理，不用旧整包覆盖新写 |

recovery_contract只生成决定，不执行恢复/采集/初始化；rollback_read_configuration只提出读路由回退，并有保留新orders revision/UNKNOWN/receipt/key/journal的fixture。没有新增“全部历史零损”门槛。用户已接受故障后重采和部分历史原样恢复损失，这一取舍继续有效。

两旧backup已核精确8文件/分配24262172672字节；3207可读fd无引用、2不可读，已知源码未引用两绝对目录，仅是有范围的现场证据。30日回执本轮未验签/复演。现代码尚未生产启用，因此不能称数据问题已在真实入口修复。

## 不把全部04功能变成24GB清理门槛

旧backup的处置只需其适用的必要条件，不要求先完成所有UI/rangejob/全年回放：确认自动全备仍停用；把必要缺库失败保护按活动源小补丁部署并从真实入口确认；明确本次保留/放弃能力与事故后有界新基线流程；复核指定恢复依赖/当前目录状态；父任务取得删除当时的精确范围确认。当前尚未发布必要修复/验证替代恢复，故不申请立即删除。独立缓存policy与旧历史恢复点删除始终分开。

真正拟发布时先核活动源与原publisher TARGETS，再给最终逐文件before/after hash、影响、开关、旧SQLite行为与回滚；本轮不生成可执行生产载荷、不推送/合并/部署。
