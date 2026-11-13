# D5 知识定义候选检查点

基于 `416167951cfe261d55f2aba299e2cd020a082cf0` 连续施工。本次补统一业务基准、月报 DATA 与唯一 knowledge/index；不建立第二目录，不发布服务器或 Notion，不恢复暂停报告。

定义统一订单渠道、历史首购渠道和价格窗口；国家／分钟筛选范围、原生及本地区间复购、SEO已记录付款收入、未知成本与来源修订分别标明。V6.1仍为分阶段候选，旧生产定价未被文档自动激活。

索引6条语义revision升级，4条仅更新共同源哈希；原effective_at保留，新增knowledge_updated_at。其余20条逐对象未变，包含原邮件及非FC条目。定向断言保留既有能力与来源选择规则，未放宽容量或生产加载限制。

验证：候选20条可读，生产选择仍为not_published；统一closeout真实检查106项，99通过、7项Linux kernel lease专属跳过，0失败/错误。不是106项全通过，也不是模型实际消费。首轮知识包269475字节超过262144，压缩新增重复正文后261731字节，余413字节；没有删除原内容或增大限额。后续补正文须继续保留必要定义并消除重复。

对应准备清单 `KL-fabb2537048b4d6c1f6305d8`，plan SHA `a4a3d73c3b110b8ae21f7b0242fea0e8abe7e66550a020dbf906342d75503452`。清单列出将来发布／加载／Notion步骤，但本轮只有plan，没有approve或执行。该清单绑定当时并行工作树，最终整合变更后重新识别，不把旧hash当未来发布授权。摘要见 `evidence/d5-knowledge-candidate-validation.json`，本机日志 `.agent_runtime/d5-closeout*.log`。

旧 V3 知识发布器仍校验原三平台候选身份、条目版本及运行基准来源证明。真实 D5 候选经该入口在身份检查被拒，未生成归档；独立回归也验证原 V3 候选在运行基准来源证明不匹配时仍被拒。D5 沿统一 closeout 准备。后续发布须完成本次发布身份、运行基准来源证明和现场原目录及路由读回，使用对应发布合同。

## 数据与报告知识交付候选

复用邮箱知识的逐目录覆盖流程和原 `knowledgeOnly` 发布器。独立发布身份为 `fs-fc-admin-es-shared-20261113-r1-<完整Git提交>`。在每个已包含对应 current 条目的目录内，按候选前后差异定点更新 `fs.data.sources`、`fs.customer.identity`、`fs.finance.procurement`、`fc.marketing.attribution`、`fc.reporting.data`，版本统一为 `fs-fc-admin-es-shared-20261113-r1`。财务、归因保留现场各目录的独有文字。原8条路由的权限、模块、entry_ids、历史选择、已审技能绑定及基准兼容字段不变。报告数据条目只更新原来选它的目录，邮件知识及已有历史保留。Hermes的 `fs.learning.methods` 和全部定价执行条目沿现行版本，FC新规则由激活批次同步。

187只读快照为13:05:52新加坡时间，13:13:26补核原发布器保护文件并确认原policy、基准哈希相同。原policy SHA256 `78fb43b2fd39396369a33e86f0468412fa9194cc5cd6be17e31cae9677c93bda`。原运行基准字节匹配既有Git运行载荷及其来源证明，SHA256 `0389965b78bc509243fa2e794dc5ce15e2ab304ff8ec5295446d6cf00296e372`；本批列为CAS保护对象，路由仍绑定原值。F6运行基准迁移的候选provenance及真实路由变化随FC激活另验。

3个现场目录共13处条目更新。原冻结发布器离线validate通过62个候选目标和95个保护对象。唯一现役写入目标是 `knowledge-load-policy.json`，其余是新不可变目录。187活动装配的最终上下文上限为327680字节，7条既有报告／任务路由当前装配均可读；最大候选从301433增至305486字节。第8条原生路由的目录选择上下文从32073增至35000字节。容量核证仅返回字节与判断，未复制个人记忆或技能全文。

本地现场证明位于 `.agent_runtime/d5-proof-cas`，使用Git数据提交 `ca770903912651f430eeb2345dc82d7c9191fa10` 和本地适配补丁，manifest SHA256 `2f20a54a7daa12a6da68ede65fc16dcb14435512b2ff88ce1e295b48aabd1bda`，`releaseReady=false`。待最终提交后，用实际固定提交重建正式候选并复核现场快照，再沿原发布器inspect及统一变更清单执行。可用命令为 `python -B tools/prepare_order_email_knowledge.py --shared-admin-es --snapshot <新鲜只读快照> --output <未存在的本地目录> --commit <最终完整提交>`。本次未apply、未创建测试会话、未调用模型、未恢复报告计划。

下一步继续F1原生适配修正、F2离线证明和F5整合；完成本检查点不停止总方案施工。
