# FS四游戏SEO日更基础

维护源：本目录及 `ui-system/modules/seo/`。唯一技术方案：`docs/planning/seo-daily-four-games-20261104/SPEC.md`。当前现场、用户成交预估口径与真实验收状态见同目录BASELINE/PROGRESS。

基础不导入AI桥接、模型SDK，不等待Hermes。GSC/GA4直接复用原受控身份，Admin直接调用现有 `site_summary.collect` 的MMOEXP原生汇总。使用GA4 `ecommercePurchases` × 同日/游戏/主站Admin `customer_price`，标记预估；不是逐单核验金额，不重新计算客单价。缺来源留空，源日/时区不改名。

`runtime.py` 是唯一批次入口；四游戏按最新日期轮转，历史窗口30日、近期14日小汇总修订，失败/游标保留。白天调用在初始化凭据与工作库前返回，不回源。`snapshot.py` 在发布前生成指标和规则，只输出截止昨日合格日期的新SQLite包，之后只读。HTTP宿主在原FS数据分析前缀下复核FS Cookie，不采信身份头；开关独立控制库，校验原edit权限、同站Origin和revision。

## 相关检查

    python -X utf8 -m unittest discover -s mmoexp_google_data/seo/tests -v
    node ui-system/modules/seo/test_model.cjs
    node ui-system/modules/seo/test_ui.cjs

正式CI使用现有pr-fast的seo-daily组。隔离Linux验证优先183；不停止共享Hermes或RPG，不拿183现代SQLite通过冒充187旧SQLite已验。浏览器测试需要现有Playwright环境，数字是独立测试夹具。

## 配置和候选

config.example.json故意没有资源基线；不凭默认数值启动生产采集。config.187-calibrated.json采用本轮现场样本及余量，包含正常预警/运行/应急与宿主保留，已用于187基础安装；首夜实际峰值及后续观察边界见ACCEPTANCE-20261105.md。HTTP响应和临时制作空间有充分有限余量；没有200请求、5天/10分钟或240秒业务硬限。

候选构建输入为本次只读获取的baseline哈希、现役formal路由、navigation.json及校准配置。输出目录须不存在：

    python -m mmoexp_google_data.seo.prepare --baseline BASELINE.json --formal FORMAL.conf --navigation NAVIGATION.json --config mmoexp_google_data/seo/config.187-calibrated.json --output NEW_STAGE

构建只追加SEO路由与导航项，不替换旧壳或整个导航；沿用仓库原FS发布器SHA256 5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357 的锁、CAS、私有备份、原ID对账和回滚。新资产/代码独立不可变目录；仅SEO web/daily/timer三个unit。03:20为单个timer，Persistent=false，不在白天补跑。新安装AI默认全关，已保存选择留在独立控制库，不随发布覆盖。

前端按参考demo分为经营全景、游戏日程、数据来源；概览呈现需求/搜索/成交预估、国家矩阵和行动中心。原明细与AI设置保留下钻和旧tab地址，无快照时也可独立打开AI设置。展示只读已发布事实，不回源、补采、模拟排名或更改日期；未配置的国家/日程/AI显示实际边界。说明见`docs/planning/seo-daily-four-games-20261104/UI-DEMO-ALIGNMENT-20261105.md`。

只读授权不自动包含生产安装；已获本轮安装范围授权后，从本机既有入口暂存，核本批manifest和实际CAS，并顺序执行 `python release.py inspect`、`python release.py apply MANIFEST_SHA nav-YYYYMMDDTHHMMSSZ`。apply会启动SEO web及未来自然timer，不手动触发日报；执行前重新确认CAS、端口、资源、主业务服务和时区。部署异常沿原批journal/manifest核对后回滚，禁止换ID盲重放。回滚格式 `python release.py rollback BACKUP_DIR MANIFEST_SHA`，只还原本批代码/路由/SEO单元，不还原业务数据库或用户开关。

## 维护和恢复

基础事实默认35天；当前和上一快照，两份验证备份。备份包括一致工作库和快照，复制到隔离目录重新打开并核hash，成功后才轮换。制作/恢复临时空间和过期候选计入占用。清理只作用SEO登记目录；AI关闭仍本地清理。记录逻辑删除及物理字节，不强删WAL，不重建主库，不全FS VACUUM或drop_caches。

`retention.restore_backup(backup, new_directory)`只允许不存在的目标目录，验证后返回可读工作库。正式恢复须沿本批维护授权先停SEO自身入口并保存现场，恢复到独立候选后读回，不能覆盖共享主库或凭据。

## 当前边界

四游戏Admin/GA4各30日、GSC各28日已真实发布；187旧SQLite、FS入口、部署、首夜自然批次、白天固定读取抽验和基础备份实际恢复有证据，完整白天持续/下一自然周期仍待观察。可选SERP/页面URL清单未配置，显示真实缺口。AI仅适配/隔离测试通过，未接现役Provider/费用账本/研究/主动问答，不会真实调用；不能据此宣布AI上线。人工行动状态尚未接入现有任务台。最新回执以同目录规划文档的ACCEPTANCE、NAVIGATION和UI-DEMO-ALIGNMENT记录为准。
