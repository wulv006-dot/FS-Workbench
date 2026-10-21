# Hermes 服务器入口统一（运行入口已验收）

2026-10-22 北京时间。用户授权：飞书群使用服务器Hermes、巡检归服务器、客户端只连接服务器。

- 原因已核实：同一飞书应用曾由独立profile和FS主profile两个服务器进程接收；不是简单的Windows/服务器之分。独立容器无/fs及/fs-source。
- 已将唯一网关交给原hermes-dingtalk systemd服务，在fs-hermes-desktop服务器容器中运行，共用主profile及进程命名空间；不使用--force绕过单实例锁。Windows客户端通过原专用SSH连接该服务器后台。默认桌面Hermes快捷方式已改为服务器入口，旧链接在项目.agent_runtime中备份。
- 原巡检0018aa8c8439迁至主profile，北京23/02/05/08、12条执行记录（10完成、2历史失败）和原告警去重状态保留；旧profile同ID已暂停。桥每五分钟、正常静默、自修白名单保持。
- MEMORY与三个已审business-context文件原已一致。保留主profile更新技能；旧USER差异仅在服务器存档，不覆盖当前USER。旧聊天库不覆盖主库。
- 用户实发接入验收消息已在主profile收到，Hermes实际读取/fs/tasks.sqlite3并确认下次02:00。第二条群消息实际调用fs_get_data_catalog和fs_query_native_statistics，状态available；主库有完整回复，网关记录发送。未把原生回复生成或发送日志称为飞书消息API逐条读回。
- 原生群/客户端已安装并启用FS只读插件，注册5工具，复用FS现有loopback查询合同。客户端真实模型也已完成工具调用，不用文件/终端代替。未新增MCP依赖、账号/登录或数据规则；mcp__fcro旧前缀原本来自研究任务工具注册，并不代表已有MCP server。
- 本机通过巡检34、迁移6、取数插件6项测试，共46项。最后只读collect（2026-10-22 00:46北京）返回connected、全部监测服务active、issues=[]。原任务下一次2026-10-22 02:00北京；下一自然周期和整机重启未验。
- 普通聊天曾误把Admin原生统计称为ES，并沿用旧的Order优先解释。已备份后追加现行口径，指向服务器活动business-baseline-20261021-v7，强调Admin原生总盘优先、Order补缺/参考率、经营估算和ES独立范围。追加说明不冒充模型已掌握全部业务规则。
- 自动审批拒绝GitHub创建分支，理由为当前授权未明确涵盖远端写入。未换工具绕过。用户随后明确授权白名单同步、PR、正式CI及通过后合并，现按该新授权推进；E原库不添加remote或推送。新增最小pr-fast映射覆盖本模块12项检查，保留私库全部既有巡检测试，再追加2项连接检查，巡检共34项。

维护源：hermes_server_unify_20261022/、fs_hermes_ops_20261020/；服务器备份与原回执：/var/backups/hermes-server-unify-20261022/。迁移脚本属于一次性操作，不直接重跑--apply；先核receipt及当前实际状态。最终验收另存acceptance.json，不改写原迁移过程回执。详README.md、SOURCE-MAP.json及SYNC-WHITELIST.json。
