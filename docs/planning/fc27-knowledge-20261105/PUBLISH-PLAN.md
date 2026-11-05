# FC知识只读接入交付

目标：让真实FS新turn通过现有知识工具读取五项FC知识；复用原知识scope及publisher，不改native程序、权限、服务、定价和排程。

## 已完成

- [x] PR813的knowledgeOnly分支合并且正式pr-fast通过；原锁、CAS、备份、journal和rollback保留，0代码/服务目标。
- [x] 原25条已发布知识逐项克隆并核SHA，增加`fc.reporting.methods/data/report/business/maintenance`五项；原FS路由13ID保留，现18ID；其它用户路由及baseline保持。
- [x] 原合成CSV样本已归档；用户后续明确要求单对象彻底清理，主控完成5行、5文件和4专属空目录删除，原始备份/审计保留，outcome/cost unknown不改写。不提交此前拟议的archive-aware修复。
- [x] 原21目标/52保护清单重检，仅首页保护SHA来自合法独立发布而变化。保留原88a清单，核准仅此保护前值更新为230ec6a3…52672，首页不是本次目标。
- [x] 单次发布`nav-20261105T002653Z`；本次manifest SHA256 `fb979b890afefcc1a90c691bcbedacef415d4fc8b9ee578263d2bd834e4bcb0a`。
- [x] 21目标与52保护SHA、owner/mode、原知识/其它路由/PID读回通过；真实已发布policy task_selection与五主题正文loader均available。0服务动作。

## 正式入口与后验

- [x] Chrome FS持续对话UI新建正式会话并只发一次虚构短题，原turn completed；真实`fs_get_knowledge_index`及单份`fs_read_knowledge`的pin/receipt/正文SHA通过，广告CAC $40与知识revision 20261105-1回答正确。使用既有模型，保留正式验收会话，不造binding、不手写冻结文件、不改API设置。
- [x] 正式FS通过KB使用本次知识，不要求另装native技能；native正式技能安装未做，新增会话实际美元费用unknown。
- [ ] 自然报告与长期经营效果另验；不以loader或共享独立题通过替代。

本次原publisher备份为`/var/backups/fs-navigation-20261006/nav-20261105T002653Z`。回退沿同publisher及该原backup/批准SHA；未知结果先核原ID/journal，不换ID重放，不恢复旧整包。详细版本、实际回执及证据见[知识库交付记录](../../../knowledge/reporting/fc27-monthly/DELIVERY.md)。
