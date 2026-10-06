# FS-Workbench 双方AI协作规则

## 当前流程 governance-20261007-v1（2026-10-07）

本段是当前流程修订候选；远端尚未更新。本仓 main 已有323文件，commit `bc3b29531cec2fab3fc090385f3d7d126eb9ada7`，tree `a4140280619771e9240e15340b0c452ab8ba9ef8`。历史“EMPTY／未入库／今晚”仅代表原任务时点，不提供未来写入授权。

1. 开始任务读取适用AGENTS、gitignore、HANDOFF、CURRENT-STATUS、OWNERS、SOURCE-MAP、未决项和模块合同；输出精确路径、owner、授权、依赖、未提交保护与基线的范围卡。
2. 代码依据、协作记录、责任映射、运行证据分别记录。模块接管标git-canonical／legacy-unreconciled／unknown；仓库路径不自动等于生产路径，PR是候选，main是集成基线。未迁移的原工程全平台HANDOFF保留，只作脱敏关联。
3. 独立分支／工作目录开发；合并前冻结commit/tree，隔离QA、契约和受影响消费者回归，必要时测候选与最新main组合树。负责人确认绑定确切head；新增提交重新评估受影响检查与确认。
4. 明确合并批准后才merge；随后读回最终merge/squash SHA、树、内容和集成产物。另获module＋source commit＋artifact SHA＋现场基线批准，才能受控单模块发布；自然周期另验。
5. 正常流向是开发→GitHub→候选/产物→QA/生产。发现漂移标drift/unknown并暂停相关写入，查部署记录与最小证据；不按mtime选源，不自动反向覆盖或销毁修复证据。
6. 共享模块列消费者、兼容方案和逐owner确认；仓库所有者权限不是全部业务批准权。D4/PoE2/Aion2归陈超，FC/NBA/MLB归吴律；其它待指派项保持待指派。共享规则由Work整合，Git写入及共享发布串行，不stash/reset/clean他人文件。
7. 代码发布与采集、价格写入、通知分别授权。不更改定价/赠送/成本/all-sites/Order主源Admin补缺/调度，不恢复退役publisher，不停正常采集。回滚保留DB、撤销状态、队列、锁、回执、策略和审计；unknown先查原ID，不换ID再写。
8. QA仅用已批准来源和生产外已获准环境；合成与真实身份分层，不复制生产凭据、用户库或上游写权限，不购资源/建长期凭据/开未知workflow。缺环境继续静态准备，必要门槛标BLOCKED。
9. 原服务器QA传输拒绝及取消继续有效；不改名、分包、编码、换工具/连接/审批机制绕过。具体动作方向以原拒绝记录为准，合法替代架构仍须独立授权。
10. 历史原字节manifest/checker仅证明原冻结对象；新候选另生成精确活动清单，两checker清单一致，不删检查或放宽秘密拒绝项。Git SHA、产物SHA256、测试输入哈希分别记录，避免文件记录自身最终commit造成自引用。
11. AI review、测试、owner业务确认、合并、上线是不同事件。规则说明与技术保护分开；空checks、200、语法或MD不能证明正式CI/真实权限通过。真实env、账号库、经营实值、订单、DB/WAL、密钥、Cookie、运行日志/锁/回执/缓存/备份不得入Git。
12. 三/四管理员为历史代码、候选政策及现场身份的待核对差异；本修订不新增、删除或降级账号，不根据旧三管理员代码覆盖已有政策，不据PR文案扩展NBA等模块写权限。最新授权及合法现场证据须分项关联。

本次GitHub治理写入尚未取得覆盖该精确载荷的授权；已准备可审阅差异。merge、保护设置、权限、生产停启、上线/回滚均另核授权。已有具体批准适用时直接推进普通步骤，不重复索取。

## 历史规则与后续更正

> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。

# 双方AI协作硬规则（首次干净私库基线）

本文件仅适用于独立FS-Workbench源码协作目录。原E工程继续本机Git、无remote、禁推原历史；不得复制其.git或整份含运行资料的HANDOFF。本首批由用户条件批准，今晚根协调可自主推进普通实现；本分工仍等待根核对最终清单和写入口，不自行push。

开始阅读README、docs/collaboration/OPERATION-GUIDE.md、CURRENT-STATUS.md、OWNERS.json、SOURCE-MAP.json、适用gitignore/合同/未决项。原工程唯一协作事实源仍是其主HANDOFF；本仓HANDOFF只记录干净协作活动，不冒充全平台事实账本。

1. 先查private远端、最新main基线SHA、任务分支、HEAD及未提交文件。使用自己的独立分支/工作目录。别人的dirty文件先记位置和哈希并保留，不stash/reset/clean、不整目录覆盖、不混入提交。原冻结C3不改。
2. 范围卡列moduleId、精确允许路径、只读依赖、禁止路径、base SHA、owner、业务不变量、测试/未验、跨模块影响及既有授权。只改规范源；baseline/before_engine、bundle、历史release和runtime不是活动真源。
3. 吴律负责FC/NBA/MLB等球类；陈超负责D4/PoE2/Aion2。共享登录首页导航吴律主导发布、陈超可参与迭代；其它owner待指派。repository write不是模块目录ACL。跨模块必要变更先列文件/理由/兼容/测试/回退及逐项owner确认，不能推导默认权限。
4. 逐路径stage，核对index/commit树、白名单和敏感内容。不git add .或-A，不Web整目录上传。禁止force push（含force-with-lease）、重写公共历史、旧ZIP/旧整包盖源码或服务器。main变化后重读差异，PR批准绑定确切head SHA，新commit使旧确认失效。
5. 用户和对应owner的业务确认、AI review、测试、合并、部署分开。已有具体授权可继续，不反复问普通步骤；尚未覆盖的重大事项/业务范围不可自行放行。未指派owner不猜归属。跨模块确认不能被一次CI绿色代替。
6. 私钥、token、密码、OAuth/会话/Cookie/Basic、真实env/config/账号库、订单/客户/经营实值、PROFIT JSON、db/WAL、receipt/locks/队列/cache/log/备份不入Git。先核对ignore与准入清单；只报告秘密类别/位置，不输出值，不测试凭据有效性。example必须是占位，不是改名真实配置。
7. 不创建新持久token/OAuth/SSHkey、不扩生产权限、不改变定价策略、不做不可恢复删除。现有global门户4管理员wulv/chenchao/DY/fstech保持；旧候选3管理员不得覆盖现场，不新增账号或伪造身份。本批NBA guard仍按原3管理员源码不扩权。缺现有只读角色就标未验，不能新账号或降级admin补测。
8. 源码入库不等releaseReady。FC使用现全局登录/角色，旧独立资格/fallback已退役；真实角色/frame/当前CAS未验，不能用旧FC-only门槛替代最新批准范围。NBA方向认可、升级后置；NBA r4稳定ID/回执与目录同步仅代码/合成层复核通过；Linux真运行与自动策略未闭合，unknown先核对旧ID，不能新ID再写。
9. 本批纳NBArev4精确7差异；新UI/auth/D4增量仍独立，不能按mtime复制。后续独立分支/PR。其它模块可独立推进，不将危险NBA候选捎带部署；共享影响仍需批准和回归。
10. 不执行未知候选代码、安装依赖或启用自动workflow来掩盖未验。仅在已核实隔离测试入口、任务授权、现有runtime下运行所需检查。静态AST/页面200/归档unit/主方摘要都不代表全运行闭包/自然周期/真实角色通过。
11. 保持Order主源/Admin补缺、all-sites、FC15档/rev25四档/赠送成本/Xbox护栏；经营120min/前端60s、Google09上海/300s、周报Mon02上海不变，旧publisher/旧采集链不恢复，Ponytail不动。
12. 上线按确切module/commit/产物及依赖/现场SHA、release锁和受控入口；受影响范围单独发布，保留DB/锁/receipt/策略/审计。经营模板不能直接发布，仍需私有PROFIT输入与网关双SHA/版本/依赖合同。代码回滚不倒退业务数据，不撤销上游写。
13. 读回实际commit/tree/blob和现场批准指标后才报成功；pending/unknown/部分成功/基线漂移停写。回滚另核具体授权与兼容，不reset/forcepush或旧包覆盖。准备/合并/上线/自然成功分别记状态。

首次empty库如需bootstrap由根核对并执行；本地Git认证失败不阻止准备和现有连接器读取。现有连接器写入口必须核实根提交/empty库能力，不能伪造parent SHA。GitHub套餐与有效branch规则/CI/CODEOWNERS仍未核实，本文件是规则而非已启用技术保护。
