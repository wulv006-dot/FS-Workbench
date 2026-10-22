# 用户分析最小发布

`prepare_stage.py` 从当前FS源码checkout、原SSH生成的23目标/74保护文件SHA回执及三份当前导航原字节生成独立stage。若目标、原字节或新增/已有边界不同则拒绝；不能据旧交付整包回盖。导航只增加用户分析入口和精确路由，现有内容按字节保留。

`release.py` 是现有渠道publisher的本任务适配，冻结底座仍为 `fs_channel_dashboard_20261021/deploy/release_navigation_base.py`，SHA256 `1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de`。沿用原发布锁、活动源CAS、74文件保护、Hermes admission fence、持久备份及回退。既有profile的9876:9876/0700与父目录0:9876/0750必须精确相符，不改目录权限。

目标仅10份用户模块、5份宿主/工具/IAM薄接线、3份导航、3份新静态文件及2份新用户作业单位。原渠道/FC writer/worker/利润红线/角色成员/来源范围及既有调度不在写入清单。

新作业在03/18/33/48分触发，每日状态先于源采集独立推进；每片非阻塞复用原渠道采集锁，忙时保留结果并退让。今日重叠、昨日、最久未复核历史片和前一历史日各一片，不逐客户请求。缺少可靠退款变更游标的限制继续公开。新日切只把真实运行写入私有daily-transitions.jsonl，构造触发不算自然验收。

生成stage默认releaseReady=false。正式受影响CI、候选核验及当次授权范围满足后，冻结releaseReady=true的确切manifest及SHA，再由原SSH运行publisher inspect/apply。active/unknown研究任务、聊天或锁占用均延后发布，不清状态、不停止在途任务。

应用只重载必需range、Hermes研究/普通聊天、原认证及Nginx，并启用本次新用户timer。认证重载不新增账号或重建登录。普通聊天在写入及重启前使用原认证的idle证明；不把该瞬时检查称为绝对无竞态保证。

回退使用本批 `/var/backups/fs-navigation-20261006/nav-...` 原manifest SHA调用同一publisher rollback；新timer撤下，旧目标按本批CAS恢复。私有客户账本/密钥/冻结快照/备份保留，不回放任务或回退同期FC变更。私有账本备份当前是同机恢复副本；隔离恢复已验，不代表异机灾备。
