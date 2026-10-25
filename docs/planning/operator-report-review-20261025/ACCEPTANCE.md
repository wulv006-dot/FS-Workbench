# 落实与真实验收

用户2026-10-25明确要求纠正Hermes所有报告的生成核心，以及Codex/ChatGPT自身指导和审核；图表/HTML按需。用户又明确批准首轮自然日报/周报/月报自动抽查，完成覆盖结束、最多两周。

## 已落实

- 项目AGENTS入口及旧字段教材已引用统一REVIEW-STANDARD；Git PR472正式CI40180263962通过，head`f988e24936172b3b86d03dad58ef813e60d09188`，merge`8220cf7b1ca5a55c453e94edd7ae1286e3b3385d`。只同步规则、计划和方法快照，不上传业务HTML或私人证据。
- 持久记忆新增便笺`20261025T170609-business-report-review-priority.md`及用户最终澄清便笺`20261025T172158-all-reports-human-decision-core.md`，第二份明确所有报告/问题分析和按需可视化；原记忆文件未改。
- Notion现有业务基准页`3ff9a8a7-9c4e-81bc-8a4f-eb15aab87a5a`已单次置顶“所有报告生成与审核的核心逻辑｜2026-10-25用户纠正”，读回确认仅一个标识，覆盖主判断/主次/取舍、重要性校核、语言、按需可视化与审核顺序，固定Git正文/计划链接可见，原内容保留。
- 原生skill_manage、锁/CAS/备份及原pending`18598b7b`应用完成：data-storytelling1.0.17、report-html-authoring1.5.11及各自新参考共4文件SHA读回一致，15个其他Markdown保护未变。未删原案例/字段能力，未改业务配置、定价/预算/权限/排程或未知写入保护。
- 原生理解会话stored`20261025_091843_4c1f59`，实际skill_view读取4文件并核版本/SHA；能解释先核心问题、给主次和取舍、无图短答同核心、只有会改方向才深查。历史练习的跨场景事实混淆已在原会话一次短反馈中纠正，原ACK字节保留；理解练习不当长期掌握。
- 实际新日报FS记录`f9e6ecd5572d1cabb975308bbf867e56`、task`590d6d490cfa689619b9c2fd7242d529`、run`run_84db13a0195849f19efa446eef7073b1`已在17:29成稿，64207B/SHA`1e3718dcbfd07626e98dabb93de72923bde9d3f801e6203462bc51a154176faf`。冻结`learning-c3ac9e0b…`实际输入knowledge_present=true，使用新版入口；原数据和各旧稿保留。
- 按新审核口径，只对新稿影响经营主次的表述做一轮编辑收口：不把单均成本与每K售价混比，获客不能被一张Coins页持平排除，避免强造新老客精确贡献，保留投放/新客入口与Items的优先方向和普遍降价暂不优先。经营定稿FS记录`eca94779aad934b26535b0b457a11eed`、task`56220489e94e526778e0c5e01ed134b6`、run`run_f217bed1f0df49499c1d3203d891e43f`，17:39成稿，67549B/SHA`6282afbcd26fab72dcc7b7c047bb4448defcb4db94c50c6198e0c574265d528b`。FS真实首屏、目录、趋势指标/对照/投放指标/主题切换及390px窄屏已看。发现新客标题与图表同id导致标题被图替换，沿原后续入口仅修这一处显示，FS记录`bf134376fd948a172fdc3a9c9409ab9a`；经营正文不再重写。
- 自动抽查已创建并从实际TOML读回：ID`automation`、kind heartbeat、ACTIVE、当前thread`01a16d84-0860-7cb1-8628-5403bf7da1d0`、每天08:10、UNTIL2026-11-08，三类首份覆盖后关闭。当前自然样本0/3，不能称已验。

## 保留的异常与边界

原学习反馈直接用旧runtime ID的RPC4001明确未接单；按原stored ID恢复会话，首次resume返回字段差异在提交提示前KeyError，原回执保留；修正兼容读取后在同一原会话提交一次并完成。没有换持久ID重发已完成学习。自动化首次缺destination返回参数拒绝、未创建；补上当前thread目的地后只创建一份并读回。

本轮没有修改FS共享UI、采价或交易程序；网页指南只用于报告阅读/交互检查。规则持久化、原生理解、本次应用、浏览器阅读与未来自然表现分别记状态，不能以CI、文件存在或一句已记住代替全部完成。

## 24号成品与真实阅读验收

最终FS记录`bf134376fd948a172fdc3a9c9409ab9a`、task`56c7fe4307d59c31438dd046f55e6132`、run`run_74712985afea4582ad13288975828e1d`，17:46原生成完成、17:49真实页面已核。67567B/SHA`090cd3a6c83b8594b11aa309b3f9c67a9daf21d5c59cf6af2de3d609c253ad2a`。请求COMPLETED、native_completed=true；业务task因既有来源缺口仍PARTIAL，未伪改complete。

- 主线已给判断和取舍：单量相对稳，优先处理新客价值/高客单结构、投放扩量回报与Items供给承接，普遍降价暂不优先；PC跟进不挤占主线。属于本次受指导应用，通过不等于用户已认可或长期每次稳定。
- 显示修复与经营定稿逐字节比较，只有两个预期id替换：新客标题锚点保留、图表宿主改customerChart，所有id唯一，正文/数据/CSS及其他脚本原字节一致；没有覆盖旧稿、模型原文或ready哈希。
- FS真实入口已打开，标题和图表各自可见；目录和折叠可用。由于其他字节完全一致，复用经营定稿已通过的趋势指标、对照、投放指标、主题和390px窄屏检查。最终桌面截图只保留私有证据目录，不同步Git/Notion。
- 冻结知识learning-065f079181156835cd7144300409bf699d5c8f66f5eb1974a1f5bfb3f733f3b9实际knowledge_present=true；两次provider成功响应、invalid/unknown均0，未计算未知费用。FS包装器report-html-1.5.1与Desktop正式方法版本分开。原night_daily_20261025失败记录仍保留，不用人工重做冒充自然成功。

[FS实际成品](https://47.85.224.112/dashboard/fs-home/brain/index.html?report=bf134376fd948a172fdc3a9c9409ab9a&view=html)。未来首份自然日报/周报/月报目前0/3，按已建有界自动抽查接续，不为验证额外出报。
