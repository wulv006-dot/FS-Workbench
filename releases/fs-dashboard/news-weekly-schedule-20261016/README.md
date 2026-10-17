# News与官方情报统一每周六凌晨

用户最新澄清：News和官方情报统一每周六凌晨一次。原game-monitor.timer由每日00:05改为Sat 00:05，服务器Asia/Shanghai不变，沿原任务统一执行官方采集/AI整理/News采集翻译，不新增timer，不主动补跑。其他经营任务不变。News保留周六保护，其余日期直接读共享快照；两个新成功快照有效至下周六07:00。既有快照、日期、费用不倒改；UI说明同步每周频率，300秒页面检查不变。

source/mmoexp_news.py、source/game_intelligence.py替换既有两个后端模块，daily.js沿139资产原publisher发布。release_backend.py复用前轮双模块publisher并固定当前基线；release_timer.py沿同一发布/当日锁备份CAS，重载systemd并只重启原timer，不启动采集service。7项调度/有效期检查、18项原翻译回归已通过，原15项发布器检查沿用当前候选复验；自然周期待观察，403风险保留。
