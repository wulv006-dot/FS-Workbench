# 游戏卡片News中文补缺与CFB26退役

当前游戏监控卡仅消费官方事件，News虽已采集却未进入卡片。本次增加中文News补缺，保留官方优先、独立SEO标签和无明确事件时间不生成倒计时；CFB26从现行列表和后续情报采集移除，历史资料不删除。

- source/index.html：现行DATA排除CFB26，无官方事件时按game_key选择中文News，主卡/详情展示来源和原文链接。
- source/daily.js：下方News标题摘要中文，原文折叠；SEO独立更新也重绘主卡；历史模式保持隔离。
- source/mmoexp_news.py：原夜间任务中沿官方DeepSeek与既有调用账本翻译，保留原文/采集时刻，重复内容复用；翻译失败不掩盖已采原文。
- source/game_intelligence.py：删除CFB26现行映射，其他官方来源及验证不变。
- release_backend.py：仅2既有后端文件，固定旧SHA、共享发布锁与原当日采集锁、备份/CAS/回退，不重启服务或触碰Hermes任务。
- prepare_frontend.py：原139资产发布合同，服务器内生成配置，只切两游戏前端路由，其他路由原字节保留。

33项Python与9项Node测试通过。正式翻译使用一次真实官方模型响应；初次数值校验将月份数字化/省略目录序号误判，修正后重验原响应，无模型重发。原费用行不倒改。

当前主站索引真实403，使用本日已采9篇；不绕WAF、不假装完成新的新闻采集。正式上线及页面验收见docs/planning/game-monitor-news-cards-20261016/DELIVERY.md。
