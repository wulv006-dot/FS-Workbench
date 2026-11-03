# FC27 活动日历与原发布通道恢复

用户2026-11-03提供活动表，并明确要求“恢复并发布”。本包仅更新现有游戏监控台的FC项目；包含18条表列活动，保留5条“官方确认”和13条“社区追踪”的原表来源、起止日期、简介和市场等级。没有声称独立官网核验或市场评级实测。

`index.html`基于`before.html`，只增加FC活动数据、更新FC阶段摘要与活动历史，并在现有情报栏目用现有卡片样式渲染日期日历。每日情报刷新保留日历，不创建没有准确时刻依据的小时倒计时；其他游戏与原事件保留。

检查：`python build.py --check`重建并比对完整页面、SOP及非目标数据；`node check.cjs`检查脚本编译、当前/历史显示、18条活动在每日刷新后可见和原10栏目。没有新增依赖、定时任务、价格或订单写入。

同一PR修复原自动发布模块：保留ProtectSystem=full，仅ReadWriteDirectories=/etc/nginx以支持原发布器原子替换路由；原publishing_unknown只有在原备份清单、已回滚且未尝试激活的journal和原活动页面SHA一致时，才转rolled_back_verified。失败不改为成功、不重放旧任务、不放宽模型修改events/phaseboard的合同。

发布沿原publication.prepare、固定publisher、原锁/CAS/备份/路由读回。先将原失败任务对账为回滚终态，再用此独立授权包发布，不重放旧MapleStory候选。ReadWriteDirectories drop-in安装到原fs-hermes-ops-bridge.service.d，保留其他drop-in及既有任务。实际合并/上线/浏览器结果另存交付回执。
