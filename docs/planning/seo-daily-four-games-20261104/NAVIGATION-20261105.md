# SEO导航注册修复 · 2026-11-05

## 原因与范围

导航JSON已正确注册SEO，但navigation-experience增强把历史内嵌清单重新渲染到侧栏，覆盖了新增项。#820使build.cjs支持显式输入现役清单；本批prepare-current.cjs复用该入口并核对现役文件，仅更新两份导航的registry常量及14个消费者的导航资源版本引用。

用户明确允许本批16文件复制核对、测试后原发布器安装与读回。导出严格只有16个JS/HTML和两份非秘密Nginx配置目标，不附带凭据、数据库或原发布器代码。原发布器在服务器原处复用、执行前核SHA；未在本机复制或重写。

16目标沿用现役repair-v3清单：hubnav.js、nav.js、主Nginx配置、formal路由，以及首页、数据分析、Hermes、球类、RPG、机器人、协作、关于、报告、持续对话、任务台、FC金币页。入口正文、主题、权限、数据服务、FC/RPG writer和timer不变；共享页面仅替换原导航URL中的版本参数。

## 候选与验证

- 版本：navigation-seo-20261105-c5278648b6dd。
- manifest SHA256：ce98fea29539d31c723fcfafadb786fa7513c9d12c03aaab85420bae4fd954c3。
- stage：/opt/fs-release-stage/seo-navigation-20261105-c5278648b6dd。
- 原publisher：/opt/fs-release-stage/navigation-experience-20261103-repair-v3/release_ui.py；SHA256：39b6e5b55c0723fafb11743996a51154c1a01828e9370d06dedaddab7264a957。
- 原publisher inspect通过：16目标、sourceCAS、protectedCAS，mutations=false。候选不包含任何SEO事实、快照或AI控制写入。

Node合同覆盖两renderer读取同一现役清单、固定16文件目标、清单外字节保留、缓存引用更新、源漂移拒绝。CI初次发现测试样本重复转换已有CRLF；已隔离复现并只修正样本构造，保留一致性断言，候选载荷未变。

08:06:58真实白天预检：snapshot seo-2026-11-05，facts_hash仍为32236b7d7339329fd25f2ce12f2376785cb7a7df6c9f2181b36f4b01d012f788，文件SHA仍为2d2058479e031e9b9cffde513785eb36799b0d0f6d6a52ca9325d48e7e4a2772，core.db修改时间仍为1793820135655190458ns。未手动重跑或补采。

## 发布与恢复方式

原CLI按自身目录找manifest，运行原字节时以本批stage作为__file__，保留原共享锁、目标CAS、原子备份、Nginx检查/reload和rollback。执行前同时核原publisher与本批manifest的上述SHA；sys.argv使用该stage内的逻辑入口及原inspect/apply/rollback参数，原代码不改动。不要直接执行旧stage的apply，也不要把旧manifest或整目录恢复到当前线上。

构建命令：`node ui-system/modules/navigation-experience/prepare-current.cjs <捕获目录> <捕获manifest> <现役navigation.json> <新候选目录>`。输出manifest和targets仍交给同一个原publisher。回滚使用本批实际apply产生的备份目录与本批manifest SHA，保留后续修改的CAS保护。

## 实际安装与入口验收

2026-11-05 08:13:10 CST按用户授权执行原publisher：16文件CAS/备份和Nginx语法通过，仅reload，businessWorkerTimerActions=0。备份：/var/backups/fs-navigation-20261006/nav-20261105T001310Z。回滚沿上述原publisher，rollback参数为该备份绝对路径与本批manifest SHA；先核后续文件未变化，不重放旧apply。

真实已登录Chrome先打开数据分析工作区，侧栏显示SEO监控台，实际点击进入SEO页面，读取seo-2026-11-05及30行。保持1份导航、8个分组、唯一SEO菜单项；活动脚本引用navigation-seo-20261105-c5278648b6dd。截图seo-navigation-live-20261105.jpg保存在本机任务凭证目录。工作区正文原7张卡片未改，本批只修复左侧菜单。

08:15:20逐文件核对16个目标SHA全部匹配；snapshot_id、facts_hash、文件SHA和core.db修改时间均与08:06安装前及04:01夜间相同。daily实际最后启动仍是03:20:00，退出码0，状态inactive；下一timer仍为11/06 03:20。FC调度、FC worker、RPG链路、Nginx、统一登录均active。白天固定读取抽验通过，完整白天及下一自然周期仍待观察。

本批原publisher备份保留；SEO代码、数据、暂存与发布回滚副本合计19,210,425字节，实际分配块19,906,560字节。两个/tmp捕获/上传归档逐一核绝对路径与SHA后回收，213,925→0字节；正式stage、回滚副本和数据备份保留。无新增模型或供应商消费。

代码CI：#821 run41939502305成功，71项Python及导航/固定快照Node合同；此前换行样本失败已复现后修复，未跳过断言。生产手机、共享服务停机/断Key注入未执行。本修复不把可选AI标为启用，也不完成尚未接线的人工行动台或可选排名/页面来源。
