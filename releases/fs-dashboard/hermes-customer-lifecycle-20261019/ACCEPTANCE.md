# 追踪池生命周期与手动全局报告 · 验收

2026-10-19 23:45–23:48 Asia/Shanghai 已部署并独立读回，真实页面验证；PR228合并状态以GitHub为准。

## 用户最新规则
以最后指示为准：不再自动生成任何单人报告。首次付款日第1天、7/14/30阶段、每日更新、手动停止保留；只在显式点击“生成追踪报告”后分析整个活跃池。
首付口径：Admin站点266、客户邮箱精确匹配、跨游戏已付款完整历史最早付款；北京时间自然日为第1天。完整覆盖或日期验证不足显示待核实，加入日期仍独立保留。

## 实际验收
- 6个生产文件独立SHA256读回全匹配；367个保护文件零漂移；fs-hermes-fc及fs-business-range均active。
- 真实页面已显示全局生成入口、5个手动停止按钮、5组首付/生命周期字段。没有点击生成按钮、没有付费分析测试。
- 停止按钮二次确认与取消验证通过，没有停止任何真实客户；详情可查看7/14/30阶段及历史原稿，点击反馈保留。
- 实际旧节点：4份完成及1份失败的初始报告保留；15个scheduled节点均已cancelled。全局报告表0条，说明发布未启动生成任务。
- 后端及路由集成12项合成测试通过：首付日/第7天/跨游戏/未知历史、停止幂等与停止后不更新、自然日刷新、旧任务退役保留历史、手动生成一次、未知不重放、权限、报告列表及停止路由。
- 页面JS语法检查通过；现有对话输入12000字符边界已与ConversationStore核对。完整池超过边界显式报错，不静默省略客户。

## 明确未验证
- 没有生成真实付费全局报告，输出质量待用户第一次主动生成后验收。
- 每日00:00–07:00更新规则已接入现有循环，首次新规则自然运行尚未到时；不能把代码检查当自然运行完成。
- 未在生产注入失败或停止真实客户。相关后端状态迁移/停止使用合成隔离库测试。

## 发布
沿用现有冻结发布器SHA256 1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de，保留锁、CAS、任务空闲、隔离组合导入、备份、回退检查。只替换本任务精确scope。
- Stage /opt/fs-release-stage/customer-pool-lifecycle-20261019
- Manifest ebcfe870d9499987b056386b3ae45108276b12668b3021f4773a942b3c93f1ec
- Backup /var/backups/fs-navigation-20261006/nav-20261019T154530Z
- 私有追踪库在服务器stage内另有0600一致性备份，未外传。
- 初始传输一片截断被校验拦截，仅重传该片后整包SHA一致。
- 初始manifest误将session镜像当Hermes镜像，被原验证拒绝；纠正为原Hermes固定镜像后通过，未放宽验证。
- 无订单、价格、凭据、权限或systemd定时器修改。内部追踪账本按授权取消未提交的单人报告；原快照与历史报告保留。

## 最终源码映射
/opt/fs-hermes-fc/customer_tracking.py = source/customer_tracking.py
fa08956d2a4cc21521a9bf98f9dcb7d1b00c7eaa0bb065bfb16102524b842852
/opt/fs-hermes-fc/tracking_controller.py = source/tracking_controller.py
0a613b8260364c02fbba59124333134cee16782ef772b71844402549e957476c
/opt/fs-hermes-fc/tracking_tool.py = source/tracking_tool.py
c030922096ba66c33cebf1638fc1dfa560ab79e3a5927155b59d919a722d4be9
/opt/fs-hermes-fc/pool_reports.py = source/pool_reports.py
51fef33b1ebe26f16a4dba59667988b3e71f979706487d0b80707a52a4d3b52a
/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/page.js = frontend/page.js
ba7cc477f63aa096685c8e85adc9f6721d9eac373e49ab96cccff2f96525a93a
同目录index.html = frontend/index.html
bcf5a1c906d1ab2075c96b5c09e158a2831858b64bf60727564637ce68cc4e8f

## 回滚
使用本次既有发布器与备份，先核任务空闲、现场哈希；不恢复整个数据库、不把已取消自动节点重新排队，不覆盖后续人工停止决定或新增报告。账本备份仅供明确故障恢复核对，正常代码回退保留新增表和历史。
