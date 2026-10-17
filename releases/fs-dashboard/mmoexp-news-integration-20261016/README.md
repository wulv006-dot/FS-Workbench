# MMOEXP News 共用采集接入

将主站 SEO 资讯加入现有游戏情报夜间任务。游戏监控台与 Hermes 共读一份有版本的 seo-news.json；不新增 timer，不调用额外模型，不改价格/订单/权限。

- 固定来源：站点 robots.txt 公布的 https://www.mmoexp.com/new_sitemap.xml 与其中 /News/*.html 正文。页面导航不作为游戏归属证据。
- 有界选取近期文章，优先兼顾不同游戏；12篇/160KB上限，缺篇标 partial，不代表完整资讯覆盖。
- 明确标“MMOEXP News／主站SEO资讯”，与官方公告分开；发布日期不推成事件日期或倒计时。
- 原00:05 game_intelligence.collect 完成官方读取后采集SEO；失败保留旧快照，不中断官方批次。
- Hermes 新增只读 fc.query_game_news：复用公共快照、SourcePins及原用户OFF门禁；不临时抓取、不重跑采集。
- 监控台沿原5分钟刷新读取受登录保护的快照及状态，原官方卡片/倒计时、底部历史备用入口保留。
- 后端仅4文件CAS、原锁/备份/回滚/在途任务门禁；前端复用原139资产不可变发布器，服务器内生成路由，仅切daily.js并增加两条相同登录保护的JSON路由。

验证：42项Python测试、8项Node UI行为测试；生产采集及真实页面结果以本任务交付记录为准，合成测试不冒认自然夜间成功。

重跑：tests目录运行unittest；node tests/test_news_ui.cjs。read_live.ps1为只读元数据读取。生产apply成功不得盲重放，按原release ID查journal；手动refresh会刷新采集快照，并非纯只读检查。
