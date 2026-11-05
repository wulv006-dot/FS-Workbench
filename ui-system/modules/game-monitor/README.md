# FS 游戏情报台

首页回答“今天哪些游戏值得行动，以及为什么”。正文顶部下拉框筛选29款游戏，左侧沿用固定工作台导航。保留新版日程和18条FC原表日历，事实、判断及执行分开。

## 现役入口与数据

- web/、build.py：单HTML，复用FS主题和鉴权，不新增生产前端依赖。
- source-model.js：仅读取 intelligence.json、intelligence.status.json、seo-news.json、seo-news.status.json；失败保留旧值，并展示最新失败及部分覆盖。
- backend/discovery.py：周二、周五北京时间10:10，统一执行DeepSeek Search/Fetch、官方原文校验、MMOEXP资讯采集及中文整理。页面每分钟重读；有效期衔接下一计划轮，保留事件不续期。
- 官方域内玩家帖不冒充公告，Steam须匹配登记应用。Search/Fetch使用现有获批账户，不另加内部试点额度。官方收费见 https://api-docs.deepseek.com/guides/search/ 。
- 日报仍消费 game-monitor.json 及带SHA的 .status.json；这两个既有数据合同由新任务提供，内容与新情报快照一致，没有旧采集器继续写入。
- 新任务复用 game_intelligence 原文校验、mmoexp_news 采集/翻译与原子发布库；这些是新版依赖，不是旧活动计划。

## 旧系统退役

用户2026-11-05明确要求删除旧工作区及其计划，取代此前的保留决定：

1. 移除“资料与工具”、iframe、旧链接与daily读取。index.html旧地址直接提供新版，旧应用HTML不进入新载荷。
2. 新载荷剔除旧daily.js、集成脚本及工具/封面资产，移除其当前逻辑路由。历史不可变版本和备份保留，不作为现役工作区。
3. retire_legacy.py沿原bridge锁核SHA、备份及验证后，删除旧周六fs-boss-game-monitor unit、Hermes任务6534331b5100、旧controller、专属profile/state和发布drop-in。共享host只移除该controller hook，不停共享bridge和其他任务。
4. 新任务接管资讯，复用collect/enrich以避开旧refresh()的周六限制；失败不覆盖成功快照。原日报、FC/P0、RPG、Order和权限保持其职责。

## 构建和验证

在仓库根目录运行：

    python ui-system/modules/game-monitor/build.py --output <候选目录>/operations.html
    python -m unittest discover -s ui-system/modules/game-monitor/tests -p "test_*.py" -q
    node ui-system/modules/game-monitor/tests/source-model.cjs

浏览器使用宿主已有Playwright，运行 node ui-system/modules/game-monitor/tests/browser.cjs <候选目录>。检查不请求退役接口、无旧tab/iframe、筛选、失败状态、提醒预览及响应布局。pr_fast.py沿用现有workflow。

## 发布和恢复

prepare_ui.py --asset ... --stage ... --adapter .../publication.py 只准备并inspect；正式写入沿原冻结publisher、原锁、CAS、备份与读回。适配器固定canonical Git blob；精简后的库存允许小载荷，不改变最终publisher实现。

退役脚本只清理旧运行链路，不发布UI。备份目录存在时核原回执，不盲重放。恢复沿本批原publisher备份和退役回执，保留数据、状态和请求，不整包覆盖、不自动复活已退役计划。

代码、CI、合并、上线、首次实际采集与自然轮分别记录。报价和需求专用接口尚未内嵌，使用原控制台；钉钉仅预览。
