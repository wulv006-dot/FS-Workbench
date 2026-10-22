# FC Coins V2实际交付与验收

2026-10-22 08:27 Asia/Shanghai。本Work实施，范围内PR/合并/部署已获用户授权；Astra仅分析复核，无外派实现。机器可读细节见[ACCEPTANCE.json](ACCEPTANCE.json)，23维护源与现场SHA见[SOURCE-MAP.json](SOURCE-MAP.json)。

## 代码、正式检查与实际部署

PR318–325均按原正式CI通过并合并，最终相关Python检查60项，在本地和两套Linux运行；Node金额、原未知请求恢复、显示与控件合同通过。末次源42c9717c91aaffc0e4f69420186afb3d2869d406，merge3e6928d8426e86940f4442a49ddb12f7793a15f5。

| 生产代码切换 | 范围 | 源提交前缀 | manifest SHA前缀 |
| --- | --- | --- | --- |
| nav-20261021T223347Z | 初始23目标/107保护 | 552e3d7396e6 | 1a5e382495dd |
| nav-20261021T225156Z | 原生Python调用共享Admin运行环境 | dfc01130f7c5 | c9001049a6ae |
| nav-20261021T231127Z | 工具合同/旧报价/入口授权字样 | 960eb30b4036 | ed3052f88064 |
| nav-20261021T234700Z | 完整分段报价与原执行审计回执 | 68d898c35826 | ffd88ea09e32 |
| nav-20261021T235522Z | 用户确认70%优惠、补偿分离、v12 | 3a0403956fcb | 9f5cf7fa5257 |
| nav-20261022T001622Z | 原失败与对账并列、公开时点、意图/任务分开 | 5676eab1a7e3 | 12b80b6da6db |
| nav-20261022T002421Z | 同owner任务账本读取真实模型回执 | 42c9717c91aa | 9b5c3867d824 |

最后单目标加129保护，总130活动/保护文件逐SHA匹配；23本地维护源亦与现场一致。原publisher、身份、锁/CAS、备份及回退保持，备份在原/var/backups/fs-navigation-20261006/对应releaseId。没有更改价格policy文件，仍revision40/on/auto/120min/all3/min10，原采集位置server/revision3。

保留PR313/315的channel、cost、workflow及归档修复；没有覆盖dirty、改流量页、改其他商品公式或重启退役球员wiki复验。E原仓未stage/commit/push，无新remote；新维护目录不在server_187/manifest白名单，不重建无关副本。

## 实际写价及原ID对账

07:24新采集e0427e4f-4289-48b1-a80d-349a7a7aa92c，按当时v11/65%及全目录安全价形成候选。真实Hermes操作会话e027a2b3d3584bd6af69110a8c1ecc13，task451eba76d3beef83751cfeffbb1d8813、run_88227980858f4af7934963a364d5a4ed，39次提供方响应均high出站转发。

原执行d91adb32-a3ac-5d1e-9d1c-0d23e1a0173a于07:28已修改Order三平台。ALL第一步GET返回200/code302，三个POST均未派发；audit最初PARTIAL，原job失败。Hermes曾错误重复尝试两次，均被当前公开/后台不一致保护拒绝，未生成新写审计，原错误保留。

通过原锁、身份、policy/source/job/audit/ledger CAS及备份，只续原ID三个确定未派发ALL POST，Order没有重放。07:46六产品读回通过，清缓存一次，07:46:35–36公开读回100K主机$12.05、PC$11.25。audit已CONFIRMED/readback_confirmed、job仍保留failed并有confirmed/verified对账。

08:02独立公开观察仍为12.05/12.05/11.25，与08:04后台预览匹配；monitor仍关联原确认写入ID，最近观察时间与原写入时间分列。不能据“failed”说没写，也不能抹去失败改成一开始全成功。

## 第一V2自然周期

原timer自然创建317c75b7-7213-4701-a25f-dbdb3c345025，08:00:19运行、08:04:42结束，ready/no_price_change。完整核心采集完成，IGGM http_blocked沿原非核心降级。共同池最新成本为Xbox08:00:33记录4563088/¥0.401562每K，PC独立¥0.40/K；当前普通留存70%。

程序当时基准100K主机$10.58、PC$10.46。Hermes automatic_review真实task632eb7e221061bc43941d84dfd385dc6、run_425153e06c7b4e67b7f8ec364598835e，共11次high提供方响应，选择保持12.05/11.25，程序验证并采用；本轮没有新价格写入。下次原周期当时为10:04:42。

08:04冻结报价在保持价下报告采购毛利25.38%/20.37%，仅是该轮成本和优惠合同下的核算；08:20读旧回执不等于又验过安全，过期后不能执行。首个no_price_change自然成功不等于下一次真实变价自然验收或长期增利。

## 真实入口与模型学习

浏览器真实wulv入口读回新页面，保留统一导航与布局；公开价显示时点，历史候选明确过期，预览/执行被禁，最低输入10。原失败与对账同时显示，原自然模型会话、任务与run现已显示。服务四项active、队列0、未确认写入0，原timer active。未为验收保存开关或人为触发额外写价。

Hermes工具实际读取核心business-baseline-20261021-v12/SHA ff1d09b3a93ddf5c33b8377f3e5125fae88629fefef2b3b970d449155699ff5e；独立新会话9a1db9aee2414258af42a5b2e632fa90有6+2次high回执，多个真实工具与未见算术通过。high实际转发已核，提供方内部effort/后端版本未回显。详细分级和原错误见[学习验收](LEARNING-ACCEPTANCE.md)。

方法经验042e4e…通过原审核/CAS发布→撤销恢复原四条→重新发布，并进入新独立任务；auto_publish=false，未把当前售价、客户或成本写成方法记忆。此次证明受控闭环和本批迁移，不称稳定经营能力。

## 10:47反馈修正与实际变价

PR333、核心v13及当天Coins准确区间读取已实际发布，原136活动/保护SHA吻合；真实Hermes31次high多工具后沿原执行521c3d63完成变价，10:41公开主机$11.20、PC$10.45/100K标价。细节见[反馈验收](FEEDBACK-20261022.md)，截图[evidence-live/feedback-20261022-1045.jpg](evidence-live/feedback-20261022-1045.jpg)。原08:27验收保留，不改写为本次结果。

用户最新只要求活动前后观察测试：热度不进入改价，优缺点及反证同记，后续数据支持再迭代；[标准](DEMAND-OBSERVATION.md)已加入原每日监控。Dot云端尚未接管，缺Dot可调用入口、其FS登录与实际独立运行回执；当前FS发布权限无缺口。当前模型操作证明本批纠正可执行，仍有时区/反证等错误，继续教学，不称稳定掌握。

## 未完成与持续跟进

- 未证明长期增利、价格因果、最佳降幅或稳定泛化。后续自然变价、晚到成本、退款、成熟销量及可比投放仍需观察。
- Coins逐套餐/平台同范围Ads、完整补发/退款费用不足时，广告后贡献或净利保持未知；不能把采购10%称净利保证，不能外推完成覆盖单到全站。
- 补偿模板当前领取/使用0，无实际核销可做真实损失对账；以后按订单实际优惠USD/核销记录核验，面值与次数分列。
- 首次每周Astra自然复核计划10月26日10:00，尚未发生。每日本机跟进继续；一次06:30切换跟进处理完已暂停。服务器原价格周期独立运行。
- 当前FS维护没有新增访问/发布权限缺口；Dot云端观察移交缺项见上文。现存收入商品分摊、Order参考率分母另由财务任务核验，不据此更改定价参数或猜支付费。

截图：[工作台](evidence-live/workbench.jpg)、[人工干预](evidence-live/hermes-controls.jpg)。预切换的旧准备资料保留归档，不再作为当前指针。


## r4：13:08改密页面修复已上线；新身份使用及接管暂停（2026-10-22）

本节覆盖12:46“页面尚未修复”，保留原两次400及接口验收未覆盖页面的事实。PR339最终head `4dd30bbb4e34bf03ed228a583d1605166ca31263`、merge `f5f5355151aa1530dbc11b6cd44545683b5378c2`；保留PR337并行更新后，正式pr-fast `39725708600/job119648987201`成功。Node12场景及双Linux各控制台30/权限22通过。完整分发器自检在Ubuntu正式CI执行：服务器缺Git、Windows不能创建Linux换行文件名夹具，这些环境失败保留，未删除或放宽CI断言。

页面setPassword仅按服务端kind=native构造native:+m.name，注册账号保持m.subject；角色绑定仍用裸用户名，后端正则/管理员/CSRF/密码长度/PBKDF2/会话撤销不改。保留活动共享导航，代码差异只有该行及末尾补换行。

原publisher于13:08:13发布 `nav-20261022T050813Z`，manifest `8f56fa92b5002d5535a990bf122d69b41de2266a82983cd1ea93518d1c91688f`，stage `/opt/fs-release-stage/iam-password-contract-4dd30bbb4e34`；1目标/139保护共140SHA吻合，备份 `/var/backups/fs-navigation-20261006/nav-20261022T050813Z`，无服务重启、密码/权限/价格或周期写入。保留MapleStory原journal `workspace-native-20261006-e17a041d4294`及Nginx SHA `df08e52cde5ce98723ec0819285a27028b6d67516bb17ad877e7d1cafa8efb45`，未用旧保护清单回退他人上线。

13:08:57真实页面与app.js均200，JS SHA `da2d93c8b7ebed63526b80ade74246d0cf267383e5854115297b5cb8f7b9a75d`，no-store。全新匿名浏览器对实际脚本做仅测试用内存插桩，原生请求为native:dot_fc_observer，注册仍reg:UUID；全部POST在浏览器内截断，服务器收到0个测试POST。没有读取用户输入、代设密码或重用会话。账号仍enabled/version3；用户真实私密改密/新身份登录尚未验收，不把浏览器模拟成功称真实改密成功。

### 角色变更只读审计与当前暂停

12:38:36原 `POST /__auth/access/api/member/roles` 返回200，IAM generation13→14，revision `84e54e25015f20b9`；审计actor为已认证主体wulv，不能据此认定实际真人。角色由FCObserver变为Analyst、ArpgOps、Auditor、CollabEditor、Deployer、FCObserver、PricingOps、SportsOps。generation13原policy.json.bak与当前四项edit/execute/deploy/manage显式deny完全一致。本Work未改变或回退这些角色；老D已向用户核定，未答前新身份使用/接管暂停。

现行实际策略离线求值480组合，额外允许读取0、写入/部署允许0；专用主体硬白名单仍限定精确GET automation、monitor、pricing/state和审查后Coins jobs。此为现行策略离线求值，不是新身份真实HTTP登录验收。额外角色不能据此视作已获授权或永久保留。

13:16使用原生单FCObserver非秘密夹具，在匿名隔离浏览器执行现行openMember/saveMember：10个角色框只默认勾选FCObserver，请求只含FCObserver；所有POST截断、真实角色写入0，未复现默认全选。当前源码无成员全选动作，按m.roles逐项勾选、只提交checked；缺当时DOM及请求体，既不认定人为主动全选，也不宣称排除历史异常。

私有证据 `/tmp/iam-password-contract-20261022/{release-result.json,browser-readback.json,final-readback.json,role-audit.json}`；本机同名私有目录还有role-ui-readback.json。原400、来源前缀根因、旧接口验证及失败均保留。云端protected_command_failed及私密交付/续期/调度/唯一责任仍未完成，不重试保护操作。

13:12原监控140SHA无漂移、v13/rev40/on/auto/120/min10、queue0/incomplete0，公开仍521c/10:41旧观察，下一原周期14:12:49。Coins10:08收入/10:43成本/00:57Z ES仍partial，营销准确区间pending，不补零、不据此判断新价效果。原监控已原子更新合法stage引用并留旧引用；原Work观察继续、FS唯一writer，不新增采价/模型/监控任务。

## 14:57 自然变价与教学增量

原自动周期75bcdde5-1fa8-4851-965d-eeebe874660f已CONFIRMED并清缓存、独立公开matched：14:16:52–53 PS/Xbox $10.95、PC $10.45/100K，另送5K。完整目录10%硬线通过，原120分钟及v13/140SHA保持，下一16:16:53；本轮没有代码部署。

原自然模型8次high、两轮只读教学2+1次high；首答错误保留，纠正后新题通过。纯方法经验沿原事件审核/CAS发布，5→6条、auto_publish=false，下一自然独立迁移待验。带时点回执见[NATURAL-1416-ACCEPTANCE.json](NATURAL-1416-ACCEPTANCE.json)，优缺点及经营覆盖见[原监控](MONITOR-20261022.md)。ES仍复用08:57文件，收入/成本刷新不等于Coins身份同步；经营增利、广告后贡献、活动高峰和价格因果未验，Dot接管仍暂停。


### 2026-10-22 16:12 v14实际代码发布

PR346最新head1b3e7f06c434de08b0547ed1d968afd6798c13e6/merge921e08cc7f4c091b567dc5ca62312217158a8169，正式pr-fast39745692097/job119713450335成功；本地FC71/Coins26/工作流22及Node、双Linux同组通过。原publisher nav-20261022T081134Z，manifest20589dc3dc66839e87ce7fe1fc865184ea82d5452faba73c165045e8f446dad3，stage/opt/fs-release-stage/fc-margin-v14-0f15fdc16e7c，12目标/128保护共140SHA通过。新知识business-baseline-20261021-v14 SHA2b7fe12ecccf3144f71f7b48b5275ec4500dc6d9b5ece556fc3641240df70bd8。用户未优惠红线及全部合法优惠豁免已进入活动源码，尚待新鲜报价/原自然16:16/真实模型与公开读回，不把代码上线等同新报价执行。

保留PR345原game-monitor发布workspace-native-20261006-21e164f34066，原manifest2b6d7852fda07fd4f728050f679db7519866c3db73eb38c14a80d911e43acf03，Nginx新SHAefcb720854f7f952d80b590741bc0c6a481610e65264c486478d7b95ad95c415。早前旧140清单对此出现一次active_drift；核清原成功发布回执后仅在新候选保护清单保留该合法变更，旧清单/失败不改。PR347并行controller修复已纳入main；首次合并405已核behind/未合并，更新原分支后新CI、19文件同字节验证及合并完成，原失败意图保留。

隔离stage首次workflow ImportError源于未复制其原仓库测试依赖，补齐原Git依赖后双Linux119全通过，无改断言求通过。历史真实只读10/15–21已识别有效已付2522单，订单USD164244.24/实际优惠15000.00/未折扣179244.24，留存91.63153025%；一条FC商品身份缺失/平台及数量未保留，状态partial。该比例不是资格核销率或未来概率。沿原档案读取，collection_triggered=false/business_writes=false。

16:12原监控081241Z-private：140无漂移、v14/rev40/on/auto/120/min10、queue0/incomplete0/timer active；原publication仍75b/14:16旧价格，quote_usable=false，不重放旧报价。原fc-coins-v2已更新本次用户覆盖口径但调度不改；Notion第30节async task_5aca4cbbcedf4dacbbeff4a6e4123b24 succeeded，真实最终fetch另验。UI真实刷新发现步骤仍残留“优惠后成本红线”文案，正在小范围修订，程序新口径已上线，不假称所有文案已完成。
