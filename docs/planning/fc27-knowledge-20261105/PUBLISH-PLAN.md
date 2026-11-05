# FC知识只读接入交付

本轮新版已由原publisher发布，真实FS在明确正确工具协议提示后读取应用通过；首轮无提示工具使用失败保留，不称全自主通过。来源为[PR836](https://github.com/wulv006-dot/FS-Workbench/pull/836)合并`b55864d9ed9d69b4dbf118befd49cb92e9f8ae43`，methods revision `20261105-2`、data revision `20261105-3`。

## 新版同步实际结果

- [x] 原ID `nav-20261105T114622Z`完成，manifest SHA256 `b38db8bd994aa19aed249ff74e8813dd3b26cd9b9603daccdedeeb4d12db111e`；20个全新不可变文件先写，原policy最后原子CAS，21目标/72保护及其它路由读回通过。
- [x] catalog SHA256 `d1b767485b1c2cdaa75d272759184ae872d31c8c96050ea01629ee90a6e8d9b3`，发布后policy SHA256 `13cbc03d490ba752f0e3af14d7d914407ada2d844b90b3ad4cb413da40db13fe`；其余28条知识、旧目录和旧pin保持可读。
- [x] [PR850](https://github.com/wulv006-dot/FS-Workbench/pull/850)合并`e587dc123c7de65f2c4e0131177714cbeb4ea826`，仅knowledgeOnly复用reader-entry，保留事务/完整quiescent及原发布器，运行时分支不变；183真实回归7/7，正式CI42027112705的knowledge组104/104、0 skip。
- [x] 原成本PID14757继续持admission READ，发布0服务动作；不终止业务、不改模型默认/权限。
- [x] 共享candidate `skill:c2a74616`沿原review_queue完成3更新/12保护；新会话实际skill_view读取及独立迁移题通过。
- [x] 正式Chrome同CID第二个新turn `d3191adb0218489cac9eb9abbf97fe86` completed；在只给正确工具协议、不含经营答案的提示后，原host与SDK读取methods2/data3正文SHA一致，三题回答正确。首轮failed及错误保留，无重放或guard放宽。
- [ ] native正式技能安装未做；日更/周复核自然窗口、自然报告及长期效果另验。

本版stage为`/opt/fs-release-stage/fc-reporting-knowledge-20261105-b55864d9`，原备份/journal为`/var/backups/fs-navigation-20261006/nav-20261105T114622Z`；回退沿原publisher及原ID合同，不用旧整包覆盖。详细分层证据与首次失败边界见[交付记录](../../../knowledge/reporting/fc27-monthly/DELIVERY.md)。

## 首版46034b08历史记录

以下原勾选项及首版发布ID仅证明当时版本，不代替本版。

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
