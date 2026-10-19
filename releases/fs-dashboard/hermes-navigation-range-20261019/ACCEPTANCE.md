# Hermes 导航与客单区间 · 验收记录

2026-10-19 22:22 北京时间，dot 云端浏览器与既有 Workbench 会话独立验收。

## 已发布并读回
- Hermes 父入口 `/dashboard/modules/hermes/` 显示3个卡片；侧栏对应智体决策报告、持续对话、智体客单追踪。已从数据分析页实际点击父入口确认。
- 对话、客单、报告页面均只有一个侧栏。云端1165px视口实测侧栏 x=0、width=236px，正文 x=236px；原左上角堆叠已消失。
- 新卡片页移除装饰溢出，最终 scrollWidth=clientWidth=1180。浅/暗主题状态均核验；客单深色截图检查通过。
- 客单日期输入包含起止日。真实单日2026-10-18读取完成；真实2026-10-17～18明确显示已取得1/2天及缺失17日，不把缺失填零。此处仅为功能验收，不构成业务销量结论。
- 倒置日期显示“结束日期不能早于开始日期”。区间读取中切走，再通过浏览器返回，17～18筛选仍保留并恢复读取；不再停留在失效读取状态。
- 相关单元检查：有效/无效日期、跨月含首尾、93天上限、未来日期、去重、缺失与零区分、配置版本变化、最后请求生效、静态导航/卡片/CSP/原publisher合同。
- 两次发布仅静态文件及原脚本版本查询串；没有后端、模型、定时器或业务数据库变更。

## 精确发布证据
第一次备份 `/var/backups/fs-navigation-20261006/nav-20261019T141540Z`，18文件；manifest SHA256 `f4c904cdc12a9e36837a7c9bbb8c8c26434b0516843acf52b1e8b030aab55d91`。
验收小修备份 `/var/backups/fs-navigation-20261006/nav-20261019T142020Z`，6文件；manifest SHA256 `ca38f56e9ba3bd5f9072fc4275078b1612a634b6f968a1a99522aed44e1593d2`。

独立最终哈希读回：18个最终目标零漂移；首次另核6个保护目标零漂移，nginx与marketing-range服务active。后续小修复用同一保护表并通过CAS。实际加载新CSS使用v2查询串，避免30天缓存继续使用v1。

最终关键SHA256：
- `/var/www/hub/hubnav.js`: `fe6df485dceb303eb5828e54a1d949e2791b9f5bb0aedf564cc5ebd6d3ceab08`
- `/var/www/hub/nav.js`: `43a9fa3b646601833e682fee25f904a52e2d53dfdf8af8c866723e6c7cc9a96c`
- `/var/www/hub/hermes-nav.css`: `a8b5444ed1b927368a8fa00c70c37dd633a4ed03b1f0cde11355dbaf5bbb9376`
- `/var/www/dashboard/modules/hermes/index.html`: `6b34dd9749cae617918687bbfa345a2b87f22a173660cfadfbf6f2931ab76eff`
- `/var/www/dashboard/fs-home/hermes/conversation/index.html`: `c078d31b986d71c37c5fa88ca7aac9bd7ecb1172c5d652b08e702b70f8fb9514`
- `/var/lib/fs-navigation-formal-static/workspace-native-20261006-346f59eea565/index.html`: `ec7814903309a5babc7d27d2bf745d07ad13c5230b079bb2a3ff079b75d89f61`
- 同目录 `page.js`: `7584b337ac09f1c4d3c86114af0355731be3f4a472db82eac481becdf1059701`
- `/var/www/dashboard/fs-home/brain/index.html`: `1fd85ce89146ec0304f74637917bc67df9fc4a08ef75f8cf2bd6482ad5fd3dd3`

## 范围与未验证
- 真实浏览器验收使用既有wulv会话；未冒充完成所有角色测试。服务器门禁和严格CSP保留。
- 区间“查看”实际验证；“扫描所选区间”的串行补扫复用原scan动作，未为UI验收主动运行生产批量扫描、修改筛选配置、加入观察或发起模型分析。其生产长区间性能未测。
- 浏览器跨文档过渡是渐进增强，仍是独立页面；未完成常驻SPA外壳，未量化所有浏览器/网络下的切换时延。
- 对话历史中的既有失败任务未重跑；本次导航修复不代表模型任务恢复。
- 不上传客户明细、对话原文、原始经营数据或截图中的客户信息。

## Git 与回滚
PR https://github.com/wulv006-dot/FS-Workbench/pull/226 。CI首次因新目录未登记失败，已增加最小实际检查映射，未关校验；后续run39267220773、39267928534成功。最终提交与合并状态以PR读回为准。
当前源码在本目录candidate及polish补丁，`prepare_release.py`是冻结现场输入，不能直接重放成新的发布；需重新核对当前基线。回退按小修→首次发布的倒序使用既有publisher，若存在后续他人变更先核CAS，保留账本、数据库、锁、任务与权限。
