# 双方AI协作硬规则（首次干净私库基线）

本文件仅适用于独立FS-Workbench源码协作目录。原E工程继续本机Git、无remote、禁推原历史；不得复制其.git或整份含运行资料的HANDOFF。本首批由用户条件批准，今晚根协调可自主推进普通实现；本分工仍等待根核对最终清单和写入口，不自行push。

开始阅读README、docs/collaboration/OPERATION-GUIDE.md、CURRENT-STATUS.md、OWNERS.json、SOURCE-MAP.json、适用gitignore/合同/未决项。原工程唯一协作事实源仍是其主HANDOFF；本仓HANDOFF只记录干净协作活动，不冒充全平台事实账本。

1. 先查private远端、最新main基线SHA、任务分支、HEAD及未提交文件。使用自己的独立分支/工作目录。别人的dirty文件先记位置和哈希并保留，不stash/reset/clean、不整目录覆盖、不混入提交。原冻结C3不改。
2. 范围卡列moduleId、精确允许路径、只读依赖、禁止路径、base SHA、owner、业务不变量、测试/未验、跨模块影响及既有授权。只改规范源；baseline/before_engine、bundle、历史release和runtime不是活动真源。
3. 吴律负责FC/NBA/MLB等球类；陈超负责D4/PoE2/Aion2。共享登录首页导航吴律主导发布、陈超可参与迭代；其它owner待指派。repository write不是模块目录ACL。跨模块必要变更先列文件/理由/兼容/测试/回退及逐项owner确认，不能推导默认权限。
4. 逐路径stage，核对index/commit树、白名单和敏感内容。不git add .或-A，不Web整目录上传。禁止force push（含force-with-lease）、重写公共历史、旧ZIP/旧整包盖源码或服务器。main变化后重读差异，PR批准绑定确切head SHA，新commit使旧确认失效。
5. 用户和对应owner的业务确认、AI review、测试、合并、部署分开。已有具体授权可继续，不反复问普通步骤；尚未覆盖的重大事项/业务范围不可自行放行。未指派owner不猜归属。跨模块确认不能被一次CI绿色代替。
6. 私钥、token、密码、OAuth/会话/Cookie/Basic、真实env/config/账号库、订单/客户/经营实值、PROFIT JSON、db/WAL、receipt/locks/队列/cache/log/备份不入Git。先核对ignore与准入清单；只报告秘密类别/位置，不输出值，不测试凭据有效性。example必须是占位，不是改名真实配置。
7. 不创建新持久token/OAuth/SSHkey、不扩生产权限、不改变定价策略、不做不可恢复删除。保持三admin wulv/chenchao/DY，不新增fstech或伪造身份。缺现有只读角色就标未验，不能新账号或降级admin补测。
8. 源码入库不等releaseReady。FC普通同事FC经营字段已业务批准，限定投影/四静态/真实身份负向未验未部署；不得开放内部全站range。NBA方向认可、升级后置；C3 UI稳定ID/结果核对与目录持久性/Linux及自动策略未闭合，unknown先核对旧ID，不能新ID再写。
9. 新UI/NBArev4及其它进行中任务不属首批，不按最新mtime复制。后续独立分支/PR。其它模块可独立推进，不将危险NBA候选捎带部署；共享影响仍需批准和回归。
10. 不执行未知候选代码、安装依赖或启用自动workflow来掩盖未验。仅在已核实隔离测试入口、任务授权、现有runtime下运行所需检查。静态AST/页面200/归档unit/主方摘要都不代表全运行闭包/自然周期/真实角色通过。
11. 保持Order主源/Admin补缺、all-sites、FC15档/rev25四档/赠送成本/Xbox护栏；经营120min/前端60s、Google09上海/300s、周报Mon02上海不变，旧publisher/旧采集链不恢复，Ponytail不动。
12. 上线按确切module/commit/产物及依赖/现场SHA、release锁和受控入口；受影响范围单独发布，保留DB/锁/receipt/策略/审计。经营模板不能直接发布，仍需私有PROFIT输入与网关双SHA/版本/依赖合同。代码回滚不倒退业务数据，不撤销上游写。
13. 读回实际commit/tree/blob和现场批准指标后才报成功；pending/unknown/部分成功/基线漂移停写。回滚另核具体授权与兼容，不reset/forcepush或旧包覆盖。准备/合并/上线/自然成功分别记状态。

首次empty库如需bootstrap由根核对并执行；本地Git认证失败不阻止准备和现有连接器读取。现有连接器写入口必须核实根提交/empty库能力，不能伪造parent SHA。GitHub套餐与有效branch规则/CI/CODEOWNERS仍未核实，本文件是规则而非已启用技术保护。
