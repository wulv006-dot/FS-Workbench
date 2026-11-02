# Hermes每日技能审核候选

状态：2026-10-23本地候选。无Git提交、正式CI、生产发布、配置切换、模型请求或群消息。原记忆审批流程保持。

私库此前无此模块，基础`review_queue.py`、`test_review_queue.py`及`apply_review_batch.py`来自E工程`hermes_memory_approval_20261022/`的已验维护源；日报三文件来自`hermes_memory_review_20261022/`。现场版本与本次来源校验由主审补入总SOURCE-MAP；安装版本以本轮只读合同为准，不采用网上新版API。

## 改动与实际边界

- 原容器外`review_queue.py list`同时列MEMORY、FS经验和原生SKILLS候选。候选SHA针对完整原记录，目标SHA覆盖所有受影响技能包，不只SKILL.md。
- `decide`在原容器外ROOT保存完整候选、决定、原request ID与完整包前值。包含所有文件、二进制、目录、mode/uid/gid；根目录及包内符号链接、非常规文件、逃逸路径、未批准profile均拒绝应用。不能安全读取的候选仍可保留原文并拒绝。
- 审核通过复用安装版`_skill_mutation_locks`，锁内再核候选和完整目标SHA，调用原`apply_skill_pending(payload)`，保留原生参数、扫描、内容/路径、批处理、删除与恢复等保护，不另写应用器。安装版源码SHA改变须重新核合同。
- 拒绝只移出原pending；原候选、理由、备份仍在容器外审计。应用返回失败且前后包一致才记录`blocked_not_applied`；发生目标变化、传输未知、应用后pending清理失败均保留UNKNOWN。
- 相同决定重跑只读原回执；同候选存在applying/UNKNOWN时，换理由生成新request也不重放。`inspect --request-id <原64位ID>`只观察原pending、当前完整包及原回执，不应用或改写成功状态。
- 审核前用`inspect --decision-file <审阅草稿>`只读取得与原候选/目标SHA匹配的完整包前值，包含全部支持文件；再审定理由/证据和逐包模块，最后才`decide`。该读取不会生成应用回执，不把备份时点偷当已审。
- 原06:00日报增加pending/skills的完整operations及已审发布索引的观察值，仍只读、原窗口/消息归属、原模型/费用/引文校验不变。磁盘技能、可写索引和模型建议均不能自称已审、已加载或已应用。

`reviewed_skills.py`只提供完整包核对和索引消费，不改变原技能工具或删除现有技能。新索引初始为空：现有78份技能没有自动获得“全部已审”身份，原有使用能力保持。

## 索引与普通FS/飞书消费

根审计权威：`/var/lib/fs-hermes-memory-approval/approved-skills.json`。由completed、approve、applied且成功的原回执生成，拒绝、未知、失败均不进入。专用发布目录为`/var/lib/fs-hermes-memory-approval/published-skills/`，原子更新同字节`index.json`，保留`versions/<索引SHA>.json`。容器仅将此专用目录只读挂载至`/approved-skills`，不暴露原候选/备份；必须挂目录，单文件挂载会在原子替换后留旧inode。宿主FS直接读专用发布目录。

合同`fs-hermes-reviewed-skills-v1`，items包含id/relative_path、package_sha256、全部files manifest、modules、description、review_request_id及candidate_id。已审meta必须由审核决定逐包提供，不能由候选内容自行授权。

统一调用：

```python
list_reviewed(skills_root, index_path, modules, *, expected_index_sha)
current_catalog(skills_root, published_root, modules)
read_reviewed_skill(skills_root, index_path, modules, skill_id,
                    expected_sha, file_path='SKILL.md', *, expected_index_sha)
```

显式旧版本读取的`expected_index_sha`须由外部已审核publisher/冻结policy绑定。普通新任务调用`current_catalog`：只接受上述宿主专用目录或容器`/approved-skills`，逐层核目录root-owned、不可被group/other写、非符号链接，index同样regular/root-owned/不可groupother写；单次O_NOFOLLOW读取并核inode/哈希/完整包，把返回的全文及索引SHA冻结到本任务。信任来自经审批的专用只读投影，索引内部自哈希本身不构成审批权威。索引不存在返回missing，普通FS/native仍保持原技能工具及既有精选方法。modules匹配在helper内casefold，保留原FS/FC27等名称。

每次审批完成由原review_queue的同一export更新专用current索引；新任务读取current，在途保持旧pin，无须每日改scope routes。`publish-index`只从已完成原回执重建索引及可读投影，用于初次空索引准备或已知应用成功后的投影失败修复，不调用原生应用器。投影失败不会将已持久化completed的真实应用改成UNKNOWN而误重放；应用阶段未知仍按原ID检查。本候选没有新建守护或定时，也不把仅改profile文件当作多入口已同步。原skill_view实际读到的内容仍须独立调用回执验收，目录pin不冒称工具全文已受同样哈希拦截。

## 检查与待验

本地以已有bundled Python执行`python -m unittest -v test_review_queue.py test_reviewed_skills.py test_daily_review.py`。系统Python3.14缺tzdata，已换现有bundled运行时，没有改生产时区逻辑或增加依赖。

目前32项：31通过，1项真实符号链接创建因Windows权限不足未执行；相同拒绝分支另有mock边界通过。覆盖创建、修改、删除、支持文件、多文件包、候选/完整包CAS、审核前完整包只读inspect、等待原锁期间候选变化、拒绝、应用失败、部分写入UNKNOWN、cleanup UNKNOWN、持久备份先于应用、原request幂等、换理由阻重放、索引外部hash及模块、专用current信任检查/两版本保留/下一任务自动可见及旧任务不变、已知应用成功后的投影失败不变UNKNOWN、原memory决定兼容、日报完整候选输入与原连续引文校验。离线native application使用fixture，current的Linux uid/mode使用明确fixture来验证分支，不能冒称真实Linux原生函数、跨进程锁或多入口已应用验收。

生产审批前后的精确清单须包括：原生依赖合同、只读投影/mount及外部expected hash、原06:00任务/06:10 heartbeat原ID更新、`skills.write_approval false→true`、真实受控候选先入队且文件不变、审批应用、拒绝不生效、删除包可恢复、UNKNOWN对原ID、下一FS/飞书任务实际加载及自然日审核。不得为验收改现有业务规则、费用、消息来源或定时。

## 审批/回退

本地候选完成不授权生产切换。上线范围为审批入口/helper、日报候选，并在原heartbeat提示后追加已批准的技能审核增量；保留原审核账本、pending、技能包、索引历史与在途任务。回退代码不回卷记忆/技能/审计、不清UNKNOWN，也不自动关闭原本已生效的记忆审批或停掉学习。新gate发生真实问题须按具体证据处置，不以简化为由擅自降回无审核写入。

06:10 heartbeat提示按增量追加：原ID`hermes`、ACTIVE、每日06:10、目标线程`01a163bd-b059-7e00-b261-145baf9eaae5`保持；原2340字提示字节及SHA256 `54681cfabec5c122fb8a6d0a56a98a94b4f550f229ce90cfef185aad67ff9edc`保留，按用户现行授权执行。`AUTOMATION-PROMPT.txt`只提供技能审核/索引闭环补充，不能整段替换原提示或缩减原记忆审批，也不授予新业务权限。组合稿由主审保存在忽略的review-packet；本轮实际automation_update次数为0。

## 独立消费者审阅

现有pr-fast已登记本模块三组测试；共享`reviewed_skills.py`改变会同时选择知识层和native消费者。实际FC V2维护源的conversation_service改变会带上原conversation完整消费者组。知识层新增任务选择与真实目录/输入预算测试，native新增任务pin测试，新FS/native候选producer均进入原dispatcher。原失败/skip/空测试门禁不变。

已修本轮发现的native技能module大小写错拒，使用同一casefold合同并补大写fixture；只读专用测试仍限定原两个知识工具，不能借`skill_id`读技能。飞书允许注册工具schema不等于准入，须以可信owner/profile/chat/thread task route精确pin；未准入不可读取。生产身份映射不明的路由保持disabled候选，不冒充wulv授权。

源挂载新鲜核对证明宿主`/var/lib/fs-hermes-fc/profile`与native`/profile`同源，完整包mode/uid/gid检查保留。启用skills gate会将原skill_manage的单操作、批处理及背景写入送原pending队列，原生apply仍只由外部审核入口调用；本轮未切gate。原06:00候选代码实际读`/profile/pending/skills`的完整operations，不是只改提示；仍不批准或应用技能。

本地环境为Windows 64位、bundled Python3.12.14。完整相关单元测试有333项有效结果：332通过、1项真实符号链接因权限未执行；另有Node UI检查、dispatcher自检和语法检查通过。这些结果复用同代码的先前通过，最后差异只定向复验。conversation发布测试初次3项失败源于未改旧conf的CRLF工作区转换；确认仅换行、恢复HEAD原字节后，原3项全过，Git逻辑差异为0，旧SHA与validator均未改。正式CI、真实native脚本、真实gate/技能应用、多入口加载与自然日周期仍未执行。

## 2026-11-02 原生聊天owner审核接口（候选）

普通聊天不再靠固定教材注入获得长期知识。A按owner创建`/var/lib/fs-hermes-fc/native/profiles/<sha256(owner UTF8)>`，启用原生memory/skills工具及原write approval；会话workspace与profile分离。原pending记录不含owner/session，A可信工具回调必须先用同home的`wa.get_pending`回读真实record，再把完整摘要与真实run binding登记到原ConversationStore。

`native_review.py`以mode=ro/query_only读取已存在的`/var/lib/fs-hermes-fc/fs/conversations/conversations.db`，从`native_pending_sources`左连接`native_conversation_runs`，用Python解码binding，兼容旧SQLite、不依赖JSON1。严格核对owner/cid/turn/session/run/lease/profile_key与subsystem/8hex pending ID/64hex record SHA，不创建缺库或表。后台review子进程从`hermes_constants`设置owner home ContextVar后才导入官方memory/skill工具，finally复位，不改process env。只使用fs-hermes-fc受信控制面，不在模型执行容器内审批。

沿用原CLI：`review_queue.py list --native-owner wulv`；inspect、decide、publish-index均传同owner，可选`--native-session`只缩小来源。决定必须携带list给出的完整`native_source`，原候选正文和SHA、目标SHA、完整备份、原request幂等与UNKNOWN保护继续有效。每owner回执和发布索引位于原ROOT下`native/<profile_key>`，审批投影写该owner的memory-review，旧desktop默认路径和体验不变；原生memory不能借此修改共享business_context。

未映射或原pending内容与登记SHA不同的项不作为可批准候选；未映射项只列ID和待核状态，不伪造来源。新候选进入pending不等于已生效。原daily_review可读取root选定的`--native-pending-file`观察快照，仍不应用或批准。原heartbeat仅追加同一队列的owner消费，不新增调度；当前新增源未发布、原heartbeat实际追加未验，不能称日审已自动接通。
