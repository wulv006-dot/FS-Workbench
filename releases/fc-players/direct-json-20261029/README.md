# FC Players 逐人 JSON 新增候选

原新卡入口、人工确认、source policy 与 manual narrow 权限继续使用。新计划冻结原 selected XLSX、候选、API 21属性表单和逐人 payload SHA；系数、折扣、PlayersType、展示 Price 遵守下述用户确认的规则，不套测试值。图片允许明确无图，保留原手工图片维护流程。

用户已确认系数1.1、折扣90、模型展示Price9999。PlayersType从同次完整转换文件按同name+Version分组：2026-11-07用户补充，只有一张卡时默认normal，因为Signature是基础卡之后额外推出的升级款；有两张卡时仍按IS低normal、高Signature。分类依据完整context，不仅看勾选人数，也不跨name或Version比较。完整context路径/SHA随plan和每人item冻结，运行前重新核验；双卡缺IS、同IS及多于两张的歧义组只阻断该人，其他必填属性校验保持。缺行情采用用户确认的fallback_9999：模型PS/PC市场币输入仍为None/blank，原同步后只对对应缺价平台的商品unit_price兜底9999，有价平台不覆盖，六商品均可启用。后台后续正常自动更新保留。

本次只更新分类代码、对应测试与本规则，不自动改变旧计划冻结的payload/digest，不解除旧scope或补跑24076/24078，也不重做已成功的60名。发布及真实新建另按实际授权和回执记录，规则入Git不代表生产已生效。

2026-11-07后续复核：分类上下文按所选姓名补查无days_new限制的完整分页和导出，再精确核对姓名+版本组ID；不得把“时间窗口内只有一张”当全源单例。完整组与证据随计划冻结，上传集合不扩大。补查失败只标记对应姓名/版本的失败项，后续正常项继续，错误码和FUTBIN ID保留供人工处理；未派发过add的失败项在事务核验后释放自身范围，任何已派发或UNKNOWN历史保留原保护。继续原任务优先使用有完整证明及SHA的最新派生计划，不改原冻结计划/原ID。

用户最终确认逐项启售和保留正确成功项，无整批同时启售要求。图片缺失/上传失败独立记录，不影响售卖。失败逐项报告，不扩大到整批或其它正常功能。原62人已在后续明确授权下补齐，实际回执见single-card-normal-20261107/README.md；本段后续分类来源与续跑修复仍区分候选、合并和上线。

执行使用原 SQLite/events，按原 execution/FUTBIN/phase/payload SHA 事务认领，再发一次 JSON。add、shelves、tags、sync、逐商品状态均留 intent/accepted/readback。intent/unknown 重入只核 GET，不自动重 POST；已落 accepted 但回读失败保留原接受证据，后续只读补验。sync 无接受回执时，不能只凭产品现价宣称同步成功。

同步接受也不代表算价已完成：有真实行情的平台若unit_price仍为本轮9999占位，保留原accepted并停止该人的启售及后续兜底阶段；后端完成原同步后，同execution仅GET补验，不重发sync。缺行情平台的9999才可按用户授权作为最终兜底。此项只验证占位已收敛，不声称已独立核算后端定价公式。

shelves 明确 site_ids=[266]、三个 FC aid、status=0，严格验全球基准0 / MMOEXP主站266 × 三平台共6个唯一组合，不能以非空或条数代替。原 price-writer.lock 覆盖同步和必要的fallback_price写价，busy 留同 ID 待续。含缺价者精确调用原同步一次并保存accepted回执，再验有价平台有效unit_price；缺价平台独立逐商品fallback_price phase只写unit_price9999并精确读回，之后逐商品启售。未知市场币不补0/9999、不跨平台；已完成且释放scope的人由原verified记录跳过，避免后来自动更新又被旧兜底覆盖。每人失败或UNKNOWN不阻塞其他可执行人。

**混合计划兼容保留**：新卡与既有卡一起操作时，先核全部既有 mid/FUTBIN/gid/cid；错映射在新 add 前阻断。既有卡仍用原 adapter.add_tags/set_recommendation，分别留 extra_tags/extra_recommend receipts、读取核验及逐范围收尾，不对既有卡新增 shelves/sync。existing-only 原分支保持，manual narrow 未扩大权限。

旧 multipart plan 不自动重执行。root 受控迁移需保原 plan digest，并追加 direct_plan_migration event：root_controlled=true、原请求 no_enqueue 证据、完整派生 direct_plan 与其 SHA。首验用同原 execution 的 only_futbin_ids 子集，其余保 pending；后续全批跳过已核动作，禁止另起重传。

维护文件位于 source/，部署应逐目标映射，不能整包覆盖图片/UI或其他模块。原 new_card_service.py 精确基线 SHA 为 ee523ab232e8007169e17e1fcd38c6582d58a22af9be489cc23c9a3e2d0c25ae。候选本地离线测试不代表正式 CI、发布或真实业务验收；现场原20请求与 no_enqueue 证明由 root 独立核实。

本次用户已明确确认原请求“没入队”；这是用户提供的核实结论，不冒称本机已独立读取上游队列。实际恢复前仍完整查重原20个FUTBIN ID，保存核对与本次双标签授权后，在原execution执行首验23700，验收后继续其余19人。原plan/digest和原失败事件不覆盖。

原任务详情增加“继续原任务”。服务端保原管理员/owner/会话/CSRF和显式确认，只允许原冻结JSON计划或有受控证据的迁移计划；不接受浏览器传入另一份plan。按钮按任务编号保存提交中状态，重新查看结果也不产生重复POST，失败提示保留在当前页面。

从仓库根运行本目录现有离线测试：

```powershell
D:\codex\FC27\.buildenv\Scripts\python.exe -B -m unittest discover -s releases/fc-players/direct-json-20261029/tests -v
```
