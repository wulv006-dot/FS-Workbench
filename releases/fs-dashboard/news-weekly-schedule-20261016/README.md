# News每周六凌晨一次

用户2026-10-16明确要求News改为每周六凌晨一次。沿原每日00:05 Asia/Shanghai游戏情报任务，仅News的refresh在周六采集/翻译，其余6天只读共用快照、不联网、不调用模型、不改状态文件。官方游戏情报频率保持。新成功快照有效至下一周六07:00，保留真实采集日期和失败状态；既有快照不倒改。

维护源source/mmoexp_news.py，固定替换/opt/fs-boss-workspaces/backend/mmoexp_news.py；基线331eb022…。release_backend.py复用前轮publisher，仅收窄到1个已存在模块；无重启/新增timer/自动补跑。5项调度测试、18项沿原翻译回归通过，周六真实自然周期待观察；现有403风险仍保留。
