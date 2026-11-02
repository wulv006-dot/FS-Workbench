# 发布准备与 CI 覆盖核对（候选，未推送）

业务代码固定在 e31e131e19c66e9e6f0e8e957969c2069d41fbe4。本次追加仅 pr_fast 映射和此收尾记录，不修改已送独审的 proof/users 业务源码。没有生产、合并、删除授权的扩展。

## 当前 main 与归属

只读 fetch 核得 origin/main=587e96a4058347b9ad361fa91dd63a33e1de662e；共同基线为4e31c61ff39064377ce277e3c2dc55c5b7ee5b58。main新增PR734的AGENTS及FC CURRENT-BASELINE文档，与候选路径无交集，git merge-tree --write-tree检查无冲突。此为本地试合并对象检查，分支未合入main、未推送；发布时仍须核最新base和实际GitHub CI。

OWNERS.json无本候选路径的精确candidatePaths登记；表明allocation不完整，不能声称已有逐文件owner记录。遵循父任务和T3 B已确认分工：数据owner拥有本候选内部policy/planner/checkpoint/user_runtime/members/export及故障测试，真实身份/grant/epoch、私有artifact和认证下载、range_api路由/身份传递仍属原A；Hermes/UI/维护锁由原owner+A协调。本轮不改OWNERS业务分配、不改T3源。

## 实际缺口与最小修复

旧映射对新tiered包20个Python路径报UNMAPPED；user-analytics组遗漏test_missing_store/test_revision_range/test_member_keyset。现登记tiered-data-access组执行该包全部7个现有test模块，users追加上述3个，保留原10个模块和weekly日期Node检查，保留所有无关路径映射及严格失败/空测试/skip拒绝门槛。selfcheck追加6条新包路径分类反例。

完整候选选出self、tiered-data-access、user-analytics。捕获实际main分发调用并与目录模块核对：users13/13、tiered7/7，无UNMAPPED；捕获只是分发/语法检查，**不属于套件执行通过**。

## 本机实际执行与未执行

- pr_fast.py --selfcheck：通过；首次因稀疏checkout缺两个原有HTML/CSS fixture失败，按HEAD原字节补齐后通过；没有删除或跳过自检。
- 全部候选Python3.9 AST/JSON及git diff --check：通过。
- test_weekly_dates.cjs：原4项语义检查通过。
- e31e131的proof受影响测试16项：Windows15通过、真实symlink权限不足1skip；已交父任务Linux验证，不把skip写成通过。
- 原0c29890父任务Linux users282/tiered51结果仅按未改源码哈希复用；本次proof新增6项及实际CI组合不能套用旧333结论。
- 本机未运行完整pr_fast的POSIX users/tiered套件；Windows已知fcntl/权限语义不满足。需父任务受支持Linux/最终GitHub实际CI验证，不能将上述捕获结果写成完整pr_fast PASS。没有重复无关91工具测试。

## 知识收尾

调用既有knowledge_closeout.plan做只读影响识别，affected_ids=[]、steps=[]、blocking_conflicts=[]，本候选未修改正式知识条目/读取入口/规则来源，无需Notion或知识生产发布。未调用会无条件重跑无关knowledge全套的CLI，未登记虚构外部完成回执。项目摘要在CURRENT-ACCEPTANCE-MATRIX、A-INTEGRATION-PROPOSAL及本记录中保留候选/待接线边界。

父任务拿到最终proof Linux和独审回执、核CI后通知推送，再执行独立分支+draft PR。无merge/mark-ready/deploy/delete；两backup未动，释放0。真实registry/source adapter/grant/epoch/sink/维护锁接线仍关闭。
