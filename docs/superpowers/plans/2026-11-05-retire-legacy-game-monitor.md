# 退役旧游戏监控台实施计划

> **For agentic workers:** 使用 superpowers:executing-plans 在本会话连续执行，末尾一次独立审阅。

**Goal:** 删除新版的资料工具入口及现役旧页面，退役旧周六采集、Hermes 十栏目维护和桥接调用，由周二/周五新任务统一提供情报与本站资讯。

**Architecture:** 新 UI 只读 intelligence 与 SEO 数据；旧 index 地址直接提供新版，不保留旧应用。新版采集复用现有解析和翻译库，并输出现有日报所需的数据合同；删除旧活动任务，不删除不可变发布历史及备份。所有 UI 载荷继续沿原 publisher/锁/CAS 发布。

**Tech Stack:** 原生 JS/Python，现有 systemd 219 与 Hermes cron 原生管理 API。

**Spec:** 本聊天用户明确要求旧工作区、旧采集计划退役删除；原周二/周五北京时间10:10安排继续。

## Global Constraints

- 本轮已授权实现、删除专属旧计划与运行文件、合并及发布，不重复确认。
- 不停共享 Hermes bridge、日报、FC/P0、定价或RPG任务；只移除旧监控台专属调用。
- 旧内容不继续提供；日报原路径改为新版内容，原回执/备份及只读解析发布库保留。
- 缺失/失败不当零，不伪造成功；模型和Search/Fetch沿现有已获授权账户。

## Review Focus

- 新任务的资讯采集不能受旧周六 guard 跳过，失败不能覆盖上次好资讯。
- 原日报需要 game-monitor.json 和带 public_sha256 的完成状态；必须与新快照字节一致。
- 去除旧 tab/按钮/iframe 与接口读取，旧 hash 回到行动页。
- 旧 active 静态资源从新载荷剔除，历史不可变版本仍受原发布器保护。
- 删除 cron 使用其原运行身份和原生 remove_job；共享 host 只删确切旧 hook，锁/CAS/备份不省略。

## Task 1：UI 与发布载荷

Files: web/app.js、index.html、styles.css、source-model.js、prepare_ui.py；tests/test_build.py、test_prepare_ui.py、source-model.cjs、browser.cjs。

- [ ] 先建立去除旧tab/iframe/daily读取、新旧index同新版载荷、剔除旧资产的失败检查。
- [ ] 移除旧入口和数据读取；以新HTML替换index；只从本次新版本剔除旧资产和逻辑路由。
- [ ] Python/Node及浏览器相关检查通过，固定UI SHA并提交。

## Task 2：采集与日报数据合同迁移

Files: backend/discovery.py、tests/test_discovery.py、README.md、deploy/fs-game-intelligence.service。

- [ ] 先测试周二/周五资讯路径、失败保留、日报快照和SHA状态同新内容。
- [ ] 复用 mmoexp_news.collect/enrich_zh，按新周期发布；旧路径仅作为日报现有合同，内容由新任务独占提供。
- [ ] 相关Python回归与183隔离验证通过后提交。

## Task 3：退役与发布

Files: 新增必要退役函数和测试；现役 nightly-pipeline host 只移除旧controller hook；README记录退役状态。

- [ ] 核当前源摘要和任务状态，测试专属路径、精确hook移除及不触及共享任务。
- [ ] 整体独立审阅；正式CI通过并合并。
- [ ] 沿原身份/锁/备份/CAS安装新任务，首次实际运行读回；退役周六unit、Hermes任务6534331b5100、旧controller及专属profile/drop-in。
- [ ] 沿原publisher准备、inspect、apply并读回；真实入口只剩新版、只有周二周五新计划；记录覆盖缺项和未到期的自然周期。

## Ledger

- 已核现场：旧unit为fs-boss-game-monitor.{service,timer}；Hermes原生任务6534331b5100已启用；共享host Git blob 90defd9659e31abe5a1ed8b7f779d82ba345d64e 对应 nightly-pipeline-20261023/source/host.py。
- 日报读取器仍依赖旧public/game-monitor.json及.status.json；改由新任务提供同合同，避免修改/重启共享Hermes。
- 原生Hermes计划运行身份为uid9876；root容器身份读取profile会被拒绝，使用原运行身份已验证可读，不改变ACL。
- 新版继续复用原解析/翻译与发布库；这是新版依赖，旧计划与controller才是本次删除的活动对象。

- 独立审阅完成：日报合同、新路由鉴权与资产删除范围通过；现场发现原publisher保护旧unit两文件，已用精确两路径退役合同修复并观察回归先失败后通过，其他保护对象保留。
- 现场旧controller latest=rolled_back_verified，旧Hermes任务state=scheduled、fire_claim=null、latest_execution=completed、handoff_pending=0；默认uid9876确认。执行仍在原锁下复核这些条件。
- 旧profile4MB、旧state125MB、磁盘余116GB；采用低压缩级别和流式归档SHA，不一次加载整个备份。
