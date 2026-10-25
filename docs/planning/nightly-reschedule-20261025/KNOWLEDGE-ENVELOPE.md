# 日报实际补跑发现的知识封装容量阻塞

2026-10-25用户已批准时间表合并上线、补出10/24日报及FS真实查看。PR460已合并并发布六文件；随后正式补报POST明确返回422，原request_id无requests记录、无模型派发。保留该回执，同ID待修复后接续，不创建重复任务。

当前真实独立取证：补报及普通daily均在`business_context.learning_bundle`末尾拒绝`desktop_learning_bundle_too_large`；完整文本263020字节，超过262144上限876字节。该证据确认本次准入原因，不反推旧凌晨ValueError必定相同。

最小修复：原文累计MAX_TOTAL仍262144、单文件131072、reviewed技能总量262144、完整冻结快照1048576及哈希/身份/路由保护保持。仅为原文加目录、标签、元数据后的文本设独立MAX_CONTEXT327680字节，超限仍拒绝；不删除或截断教材，不改模型/权限/业务规则。当前活动源按只读线上完整文件建立，唯一行为差异为该封装上限，旧文件归档保留。

维护源`releases/fs-dashboard/nightly-reschedule-20261025/source/business_context.py`→`/opt/fs-hermes-fc/business_context.py`。单文件增量沿同目录`deploy/knowledge_envelope_release.py`调用原nightly publisher；原CAS、备份、双锁、准入、空闲及回退保留。六文件发布不重放，其他生产源受保护。

检查：新增4项覆盖完整正文/目录保留、原文超限、封装超限、1MiB快照写前拒绝，原17项保持。完整21项在私库正确目录本地通过；E根候选因原publisher兄弟目录缺失的2项路径失败保留，不冒充通过。正式PR CI及实际发布、冻结加载和真实报告另验。
