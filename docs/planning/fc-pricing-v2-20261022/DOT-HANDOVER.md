# 老D／ChatGPT云端Dot观察交接包

最新r4（13:16）：改密页面静态修复已上线并读回；角色变更待用户核定，新身份使用/接管暂停。页面真实私密改密尚未验，原Work观察及服务器周期保持。详见[当前交付](DOT-ACCESS.md)。

整理于北京时间2026-10-22 11:15，版本 `dot-observation-handover-20261022-r1`。本次仅根据已有回执整理，生产状态证据截止11:06:25；没有为交接刷新生产、采集行情、重跑模型或切换调度。本文不是实时状态接口，也不代表责任已移交。

最新增量为`dot-observation-handover-20261022-r3`：专用身份已上线并通过服务器只读/拒绝/同会话权限撤销验收，凭据交付与Dot新身份登录因云端浏览器保护受阻，尚未接管。末尾r3及DOT-ACCESS.md覆盖r2未授权/未创建的旧提案状态。11:19–11:20旧云端wulv实读仍为当时事实，不能当新专用身份验收；r1/r2历史表和原失败保留。

## 1. 身份、负责人和责任

| 对象 | 已核身份／范围 |
|---|---|
| 当前Work | 《Hermes自动改价策略》，`01a159da-838f-7aa1-88ff-829cb53e167a`；任务身份已由本机线程ID及read_thread核对 |
| 当前执行负责人 | 本Work的Codex；FC业务负责人／原数据owner为吴律（wulv） |
| 老D交接任务 | 来信自报`01a16195-4e3d-704c-99c9-a051acf1900b`，主对话`01a157da-9d64-7793-b14b-eb28f7df10c0`；已收到来信，尚无其云端FS实读及调度证据 |
| 已授权本期交接 | 用户明确要求Dot联系本Work，由本Work教学。先交规则、数据口径、观察与提醒方法，完成云端实做后再移交观察责任 |
| 当前保持 | 原Work监控、原服务器自动采价／改价、原发布与回退链。没有给Dot新增生产写价／部署／凭据权限，也不重启用户已取消的旧Dot FC巡检 |

本次按来信要求在本任务及持久材料答复，不向老D主对话主动通知，不跨线程回信，不委派实现。

## 2. 实际生产版本与业务边界

- 维护源`fc_pricing_v2_20261022/`；FS Coins读取源`fs_coins_evidence_20261021/source/coins_evidence.py`。
- 实际代码PR333，head `8065dcfb8a95efa3b685113d55fc46d09bc40504`，merge `9a3f0aeb0c7e29ac2799249e7e91ffe68e0b589d`。正式CI、双Linux Coins25／V261和Node通过，10:26:51沿原publisher发布`nav-20261022T022651Z`。
- 发布manifest SHA256 `40a1dcca92705ae587eac30a71239d3dee5d98ae0e6c8d526dd3923646ed1a7b`；11:06原监控136活动／保护文件无漂移，保留PR331财务／Nginx和PR327执行历史链修复。
- 当前核心`business-baseline-20261021-v13`，SHA256 `6c77e58095fbc4b572bad9e9b1311aec71dab85a06acc1f50ad21438dddcd58b`。当前Coins reader SHA256 `b56df46bafc74042f2347edd25561bd0606f347e91163b2b59f084720820b2fb`。
- 纯文档PR334已合并`e5f387674a8382125fc8d9b71c5c887e302cdf94`，九项文档／JSON／截图从最终merge逐SHA一致，生产动作0；不能拿这个merge冒充生产发布。

硬规则：

1. 优惠后实收减完整采购成本，再除以优惠后实收，采购毛利率至少10%。含全部交付／赠送、所有套餐、整数K自定义及舍入，策略、模型、人工或恢复不可豁免。采购10%不等于扣广告等全部费用后的净利10%。
2. PS/Xbox共同成本／共同基础价，PC独立；同池取最新已核有效交易，不同时刻记录不同不叫同时点冲突。最新同时点真冲突不能退旧成本兜底新价。
3. VIP／积分／折扣码／优惠券互斥，当前普通最低留存70%；七折券1289门槛0、最多减50美元。真实优惠结构用于经营回顾与明示假设情景，不能用平均结构绕过个别合法成交的红线。
4. 售后补偿1259独立核实际扣减和核销，不用面值乘次数、不重复从净收入扣一次，不豁免其他未知固定券。
5. 原设置revision40、ON、auto、120分钟、三平台、最低10%、来源server/revision3保持；其他商品固定金币公式不改，球员wiki复验不恢复。
6. .99只在主候选后独立核预算：净让利1%、采购毛利消耗5%、毛利率下降1个百分点及全目录红线同时满足；不是固定10.09边界。
7. 用户最新收敛：游戏活动／热度／需求只做观察测试，先记活动前后策略优缺点，再凭持续数据考虑下一期迭代。本期不加热度涨跌系数，不更改既有报价或执行权限。

## 3. 原请求、账本和不能重放的动作

下列为11:06前已核回执，接手前只读检查最新状态；不能把旧快照当当前报价。

| 原对象 | 原ID | 截止状态 |
|---|---|---|
| 本轮行情／报价run | `f10e868b-ae49-47ce-bc66-e97f9d4eb505` | collect ready；11:06来源已到期，quote_usable=false，不重新使用或重放 |
| Hermes操作审核 | `fc0a7982-2dc2-498a-8fb3-b91ebc4f22a0` | ready，真实原会话已完成 |
| 后台预览 | `c016e399-a003-468b-b07c-398b3b23eee3` | 对应原执行，不能改run／SHA后沿旧预览写入 |
| 最新执行 | `521c3d63-e99e-508f-908b-da97e8dd1a70` | CONFIRMED、sync_confirmed；10:39:58后台确认，10:41:00–01独立公开三平台matched |
| 早前失败保留 | `d91adb32-a3ac-5d1e-9d1c-0d23e1a0173a` | 原job仍failed，但audit CONFIRMED、独立reconciliation confirmed/verified；Order没有重放 |
| 最近自然周期 | `07db8dd9-45d9-4f00-90b4-6ae0dc473ac0` | 10:04–10:09完成no_price_change，不能叫新自然变价 |

11:06队列0、未确认执行0、原timer active；当时下一自然周期为北京时间12:09:24。只证明该次读取，没有证明以后一直为空。10:41公开100K标价为主机11.20、PC10.45美元，是带时点历史事实，不是本报告推荐的新价。

原执行账本在服务器`/var/lib/fc27-cloud/`，监控证据`/tmp/fc-pricing-v2-20261022/monitor/2026-10-22/030625Z-private.json`。出现UNKNOWN／超时／失败先核原ID、audit.changed／after／sync和reconciliation，不能换request_key、清状态、重跑execute／restore或重放原模型提交。旧发布／Git／教学intent同样不能当可重复脚本执行。不要因研究源缺失停原正常自动化。

## 4. 已完成、待验与教学方法

已完成：真实生产切换、后台写入／清缓存／独立公开读回；08:00及10:04自然no_price_change；FS原执行→预览→报价链读取、当天准确区间缓存与优惠结构读取；核心v13真实装入任务；一条方法经验经原CAS发布→撤销→恢复并进入新任务，auto_publish=false。

真实模型：操作conversation `f7d373beb8e5448ba54d7d9e3d2215ff`，turn `56c93fa3cee749398b9a9603ea42a8d0`，task `06416402b22cb28b12d08937d3739b2b`，run `run_3a2a95c1185d4892abf4bb8b19d4da8f`；31次high实际转发并用多轮工具完成本轮执行。提供方内部effort未回显，不能称已验证内部档位。

原只读教学conversation `9a1db9aee2414258af42a5b2e632fa90`：需求题turn `29e01921cec846a8bc77c764f1f0f6b5`有3次high及真实工具；后继turn `9f034454370d495d975d194394111c00`／task `5e5c2157a65ab501edbcf4657f0fdaa4`有1次high纠正新题。时区、反证及全七折比较分母的旧错误均保留，不称稳定掌握。最新两次教学未自动发布为新经验。

给老D的教学重点：先让Hermes声明来源、范围、单位和假设，再自行调用工具、列式、提出可推翻自己的事实；用新场景验，不让它照抄答案。基本式为“完整交付成本＝交付K×人民币/K成本÷本轮人民币/美元汇率；采购毛利＝实际净收−成本”。未来概率未校准就只算条件情景。

以下金额全部虚构，只是已有教学算例，不能当当前售价或执行许可：同一完整交付每单成本7美元，旧标价12、新11.50，旧100单。

| 对照假设 | 持平旧目标所需整新单 |
|---|---:|
| 双方均80%全价／20%七折；采购毛利 | 113 |
| 双方全七折；采购毛利 | 134 |
| 旧80/20、候选50/50；采购毛利 | 155 |
| 双方80/20、期间广告总额相同；广告后贡献 | 113 |
| 双方80/20、每单广告均2美元；广告后贡献 | 126 |

113／134／155不能混用旧分母，保本条件不是需求预测，也不是自动恢复旧价的充分条件。没有同范围Ads时广告后贡献未知；缺Ads不创造24–48小时强制等待或永久否决所有合法基准。

尚未完成：10:41新价格后的成熟效果、后续自然变价、长期采购毛利额改善／价格因果、稳定泛化、首次10月26日10:00 Astra周复核、活动正式上线后对照、云端独立观察移交。11:06 Coins收入快照仍10:08、成本10:43、ES00:57Z，营销原准确区间pending；平台／售K／同范围广告／退款实结仍有缺口，不能算降价后的完整收益。

## 5. 云端现有入口、工具与访问缺口

| 路径／能力 | 本Work已有证据 | 老D云端状态 |
|---|---|---|
| [FS工作台](https://47.85.224.112/dashboard/fc27-coins.html) | 本机已登录wulv及真实业务验收 | 未实读，云端独立会话／网络／证书／角色未验；不继承本机登录 |
| 既有同源只读HTTP | 页面使用`GET /api/fc27/cloud/automation`、`/pricing/state`、`/monitor`、`/jobs/<原ID>` | 路径已由维护源核实，不代表云端已获认证；不得伪造受信身份头或开放内部端口 |
| Hermes注册工具 | `fc.get_data_catalog`、`fc.query_pricing_evidence`、`fc.query_market_snapshot`、`fc.query_marketing_snapshot`、`fc.query_official_intelligence`；`fs.pricing.control`只读capabilities/state/read_quote/read_job | 在原FS任务与租约内可用，不是Dot天然拥有的独立公开API；以Dot实际工具清单和身份验收为准 |
| [Notion现行规则](https://app.notion.com/p/3ff9a8a79c4e81bc8a4feb15aab87a5a) | 25／26节及原21–24已读回；本次补27节交接包 | 本Work连接可读写，Dot自己的连接与读取回执待验 |
| 私库固定文档 | [PR334冻结观察标准](https://github.com/wulv006-dot/FS-Workbench/blob/e5f387674a8382125fc8d9b71c5c887e302cdf94/docs/planning/fc-pricing-v2-20261022/DEMAND-OBSERVATION.md) | 老D补充来信自报已核main观察标准；本Work未另验其云端认证或是否仅浏览文档，不能外推FS访问 |
| 运维SSH | 本Work既有本机受控连接可用 | 不是脱离本机的现成云端路径；不复制私钥或借本次交接扩权 |

对已注册工具，现有只读取数示例为`fc.query_pricing_evidence({profile:"FC27",kind:"price_history",start:"2026-10-22",end:"2026-10-22",page:1})`，kind另有order_costs/readiness；日期要按实际观察日，历史须分页。先核capabilities/catalog及覆盖，缺工具就报告缺项，不模拟调用成功。

来源分工：Admin实收一次为主，Order实际历史交货成本；后台“采购成本／利润率／6.65”是调价参数，不是经营真实成本／毛利／本轮FX。优惠推广分类不等于站点分销。不能把内部127.0.0.1服务当云端公共入口，不能把旧副本当实时源。

公开情报：EA官方工具只按需读索引及最多6正文，不穷尽；四竞品观察不是全市场消费意愿。当前没有注册Futbin/FutGG/Reddit/YouTube/X全套社媒量化工具。只记可合法读取的来源、原帖、时点和覆盖；未取到不等于无事件，负面播放量不等于购买意图。10月23日活动／C罗名单仍按官宣或实际上线核定，原时区与北京时间分开。

实际缺口：Dot云端对FS的合法独立登录／角色和只读回执；Notion自身连接及私库云端认证范围；云端独立调度与不依赖本机的实跑证据。用户已授权教学，不需再次批准整理资料；本轮不申请创建凭据、持久权限或网络变更。若后续实际访问需用户登录／确认具体连接，先列目标、用途和最小缺项，由原产品私密流程处理，不在聊天输出秘密，不绕过警告。

## 6. 唯一执行方与交接验收清单

服务器原FC队列／worker是唯一业务执行链。老D本期只观察／提醒，既有Hermes操作授权也不转给新云端任务。原本机`fc-coins-v2`07:30–20:30每小时观察与`astra-fc-hermes`周一10:00复核继续；只有实质变化、失败或需处理时通知。没有恢复旧Dot FC巡检。

- [x] 老D交接来信已收到，报告整理完成。
- [ ] 老D读回本报告版本及核心v13，复述10%全组合、共同成本、UNKNOWN和热度只观察边界。
- [ ] 老D从云端合法FS入口读取同一状态，回报原ID、源时点、SHA／版本、coverage和真实工具回执；不能只复述本文。
- [ ] 使用同一快照做一轮只读影子核对，区分后台写入、独立公开暴露、自然周期与成熟经营窗；现有数据缺项不补零。
- [ ] 后续获准演练中，老D证明云端调度保存和不依赖本机的实际运行，源失败会报告缺口。本轮不要求用户关机，不启动断机测试。
- [ ] 同一观察账本登记唯一责任owner、切换时点、回退责任，再处理被取代的本机观察任务；本轮不切换，服务器自动周期不受影响。

通过前三项只证明理解与同窗读取，不等于24小时覆盖；收到资料不等于接管。未验收前本Work保持观察责任。

### r2：云端独立只读访问阶段已通过

证据来自老D任务`01a16195-4e3d-704c-99c9-a051acf1900b`转交的云端实做回执；本Work未二次控制其云端浏览器。本次可记为“对端实做回执已核一致”，不是本Work重新实测，也不保证会话以后持续有效。

老D报告于北京时间10月22日11:19–11:20，通过产品安全登录框在自己的云端浏览器登录FS，页面身份wulv；独立读到Notion第27节r1及既有GET automation／monitor／pricing/state。没有复制本机登录、重新采价或重放旧请求。已有证据按此更新：

- [x] 云端独立登录及这三项只读访问，本次通过。
- [x] Notion第27节r1实际读取，按老D回执通过。
- [x] 与原账本的ID／设置／状态／时点一致性，本次通过。
- [ ] 全部教学边界与活动运行源码SHA／知识工具的云端独立复核尚未完成；不影响本次连通阶段结论。
- [ ] 下一自然周期的只读影子观察与经营覆盖核对未完成。
- [ ] 24小时调度、独立持续会话及观察责任正式移交未完成。

具体API回执：monitor generated_at=`2026-10-22T03:20:02.973536Z`，即北京时间11:20:02；pricing observed_at=`2026-10-22T03:20:09.656721Z`，即11:20:09。revision40、ON／auto、120分钟、最低采购毛利10%；queue_depth=0、incomplete_executions=0。最近自然仍`07db8dd9-45d9-4f00-90b4-6ae0dc473ac0`、no_price_change，next_at=`2026-10-22T04:09:24.595974Z`，即北京时间12:09:24。

publication仍关联原执行`521c3d63-e99e-508f-908b-da97e8dd1a70`、matched，public_checked_at仍为02:41Z（北京时间10:41）历史读回，主机11.20／PC10.45。monitor／pricing在11:20重新生成，不表示公开价也在11:20重新采集。原报价`f10e868b-ae49-47ce-bc66-e97f9d4eb505`已过期、execution_ready=false，这是原时效保护生效，不是自动化停机或需重放的故障。老D正确按原ISO统一时区，且没有把不同时刻两条共同成本误判同时点冲突。

下一步只读影子观察建议：

1. 沿既有观察时点，在12:09原自然周期实际发生后读取原state／monitor；有新job只读GET jobs/该原ID。没有实际新job就记“尚未观察到”，不能仅凭next_at已到宣布运行成功。
2. 区分原新job排队／运行／终态；保留其run、review turn／task／模型run、原执行及报价指纹。若no_price_change，明确这是自然评估后无变化；若真的变价，分别核后台确认、清缓存及新公开读回。matched若仍指521c3d63和10:41旧观察，不能叫新周期公开验收。
3. 若原job failed／UNKNOWN／PARTIAL，只记录原audit、changed／after／sync及reconciliation，提交具体缺口供当前负责人判断；不要点采集、执行或恢复，不换ID，不取消原任务，也不因观察源失败停止服务器周期。
4. 先对同一已有快照核对范围、源时间、覆盖与已完成群体，再谈经营效果。10:41前后价格窗分开；缺售K、晚到成本、同范围广告或退款实结时保持未知。不为此影子验收调用会触发刷新／采集的入口。
5. 教学衔接先只审已有Hermes答卷和回执，不新开付费模型：分别说明原任务取了什么证据、推导、反例、实际操作、公开读回及遗留错误；区分113／134／155的对照分母，重复旧答不算新场景掌握。

老D可回交一份最小只读观察记录：观察时间UTC及北京时间、原job/run、来源／覆盖、模型与工具回执、执行／公开身份和各自时间、支持／不利证据、未知、下一次要核的事实。只带非秘密聚合与操作ID，不带凭据或客户／订单明细。

本轮不新增观察任务或调度，不要求用户关机，不启停原本机观察，不恢复已取消的旧Dot FC巡检，不创建凭据或改变权限／网络。当前独立FS只读连通缺口已解决到本次时点；仍缺云端持续调度／会话与正式移交回执，服务器唯一writer保持。

#### r2附加：专用只读身份与受控凭据的只读核查

用户经老D新增授权对接／核查，明确尚未批准新账号、长期凭据、持续访问配置或权限／网络变更。本Work只读检查现有服务代码、白名单配置元数据、身份与角色统计；没有输出密码／哈希／token／session，没有复制本机凭据到云端。

已核事实：

- 外部入口继续复用现有HTTPS FS域名／IP与三项GET，不开新端口。门户服务仍绑定loopback，原Nginx鉴权链在前。
- 现场已有FS IAM/RBAC，不再是2026-09-30本地三管理员硬编码。现存策略generation10、updated_at为2026-10-20T11:58:33+0800，九角色／九绑定；本次读取policy SHA256为`82b14330b3f231a1cb43d4e8003a545d5bc9f7f324b359ecec7361287e2c0654`。未来变更不能因旧SHA不同就自动回退。
- 认证源统计：门户dashboard有5个身份、deploy有4个；独立FC Gate有6个账号，其中3个活动非admin。按用户名／用途中的Dot、readonly、observer、monitor等明确标识，本次未找到专用观察身份候选；一般非admin账号数量不等于可以借用他人账号或已证明纯只读。
- 现有Viewer规则是全资源view，Auditor同样宽泛；策略还保留特定绿茵任务PATCH兼容例外，显式deny在例外之前生效。不能仅套Viewer名称就声称“只能看FC、完全无写能力”。
- 实际权限解析中，`GET /api/fc27/cloud/automation`、`/monitor`、`/pricing/state`及`/jobs/原ID`当前均为`unmapped:view`。只在内存给虚构主体coins:view时四GET均403，写动作被显式deny403；没有创建主体、调用业务写接口或保存候选策略。不能为求读通授予全部unmapped:view。
- 门户当前有效配置：普通会话12小时，remember分支30天；cookie配置Secure，源码有HttpOnly／SameSite=Lax。这个配置不证明老D当前会话的确切到期时间或会自动续期；本轮没有读取云端cookie秘密。门户还兼容独立Gate会话，Gate会话／自动续期与撤销范围本次未做实际账户演练。
- 门户token校验签名及到期，verify另核当前认证组与IAM。删除IAM绑定会回落到默认Viewer，不能当作撤销；单纯改密码或清一个浏览器cookie也不能冒称所有旧会话已失效。撤销应对专用主体显式拒绝业务读取，并按实际认证来源禁用身份，最后以旧会话对目标GET真实返回401／403验收，不做全局签名密钥轮换影响他人。

现有受控存储能确认的方式：Dot已有产品私密登录表单和自己的云端会话。OpenAI说明在提供“Save to Passwords”时可选择保存登录，但用保存密码进行新登录仍要用户确认；有效会话可继续用，不能据此承诺长期无人工续期。[官方说明](https://learn.chatgpt.com/docs/dots/computers-and-apps)。本Work没有可用的FS专用凭据库交付工具，未取得老D云端企业vault连接清单，不能声称全局没有vault，也不能把聊天、Notion、GitHub、交接文件或本机DPAPI文件当云端凭据存储。

待用户逐项确认的具体方案（仅提案，尚未实施）：

1. **主体**：如没有另一个可证明适用的现成身份，建议新建独立`dot_fc_observer`；不借用wulv管理员或他人账号。由现有FS身份管理员创建，归用户所有，登记用途与责任人。
2. **最小范围**：首期只许上述三GET及必要登录／静态页面；jobs/原ID须先检查返回字段、只纳入获准原任务的非秘密状态。Coins同窗经营聚合如需额外现有接口，先列字段／期间／覆盖后另纳入，不开放订单／客户明细、其他游戏、Hermes发起、原始配置或部署入口。
3. **权限实现**：复用IAM，但先明确FC观察API资源／精确路径的授权映射，赋予专用观察角色；对edit／execute／deploy／manage显式deny，覆盖兼容例外。不授予全站Viewer或全部unmapped；若需映射代码／Nginx规则调整，须作为明确权限变更列出并经确认后走既有PR／CI／发布，不在本次只读核查里偷偷实施。
4. **期限和撤销**：先沿普通12小时会话，不改全局TTL，不默认启用30天remember。主体建议按7天试用复核，但当前未核到逐主体自动到期能力，7天复核日期不能写成服务器已强制到期；硬性自动到期或续期机制如需要，须另明确并批准。随时可由管理员对该主体显式拒绝读取并禁用认证来源，以旧会话拒绝读回验收。
5. **谁存到哪里**：由用户／FS身份管理员通过产品私密登录流程把专用凭据直接用于Dot；若界面提供Passwords并且用户明确确认保存，则存入该用户账号的产品受控密码库。本Work只记录主体、用途、权限、期限与凭据库记录标识，不接收或转发明文。当前缺一个已验证的管理员→Dot受控入库通道，不能承诺无需任何一次私密输入即可自动交付。
6. **仍需确认**：是否批准新专用主体及上述路径／字段范围；是否批准所需IAM映射与显式deny变更；普通12小时还是另定经验证的主体期限；由谁完成私密登录／可选保存、谁负责撤销。若必须无人值守自动续期，还缺受控机器认证／凭据代理的现成能力证据，不用长期管理员session或复制cookie替代。

核查中遇到旧systemd不支持`--value`及本地旧角色AST结构假设错误，均改为当前现场方法后继续；未重复任何登录或业务写入。rbac加载器在策略缺失且路径位于/opt时会初始化文件，因此本次只读现存JSON并做内存求值，没有调用加载器初始化或写回策略。原生产和观察职责保持，本提案交由用户确认后才可实施持久访问变更。

## 7. 持久位置与后续读取

- 本地当前包：`E:/WorkBuddy/大超服务器/docs/planning/fc-pricing-v2-20261022/DOT-HANDOVER.md`；协作增量事实入口：根`HANDOFF.md`。
- 云端可尝试读取：上述Notion页第27节；本Work将读回验证保存成功，但Dot能否读取须它自己验证。
- 已归档事实：[观察标准](https://github.com/wulv006-dot/FS-Workbench/blob/e5f387674a8382125fc8d9b71c5c887e302cdf94/docs/planning/fc-pricing-v2-20261022/DEMAND-OBSERVATION.md)、[本批实际验收](https://github.com/wulv006-dot/FS-Workbench/blob/e5f387674a8382125fc8d9b71c5c887e302cdf94/docs/planning/fc-pricing-v2-20261022/FEEDBACK-ACCEPTANCE-20261022.json)、[使用与干预](https://github.com/wulv006-dot/FS-Workbench/blob/e5f387674a8382125fc8d9b71c5c887e302cdf94/docs/planning/fc-pricing-v2-20261022/USAGE.md)、[两套策略](https://github.com/wulv006-dot/FS-Workbench/blob/e5f387674a8382125fc8d9b71c5c887e302cdf94/docs/planning/fc-pricing-v2-20261022/STRATEGIES.md)。
- FEEDBACK-ACCEPTANCE-20261022.json SHA256 `231c84d5cc8177d1c63dea7ed638d597a688f37e5a0b58d48a0cea9fc8b625db`；DEMAND-OBSERVATION.md SHA256 `32c94622e66a873a33bee53f3d763ab0f21f7fec2c77379f43b38a2274e8764c`。它们冻结的是原时点，未来以最新合法回执核定，不能固定旧SHA否决已批准的新版本。
- 私有原模型与运行证据仍在服务器`/tmp/fc-pricing-v2-20261022/`和项目`.agent_runtime/fc-pricing-v2-20261022/`；只提供路径与核验状态，不向云端输出客户／订单明细或凭据。

本报告仅是教学／交接准备，不是另一次上线、云端接管、权限授予或新监控。旧原始记录、失败和unknown全部保留。


## r3：专用身份已上线，云端私密交付仍受阻

本段覆盖r2“尚未批准/未创建”的旧提案状态；具体授权、四目标发布、原意图、真实允许/拒绝及未完成项见[DOT-ACCESS.md](DOT-ACCESS.md)。PR335/336均已合并，原publisher nav-20261022T041407Z已部署，4目标/134保护共138SHA匹配。dot_fc_observer已创建，FCObserver仅精确GET状态/监控/报价与审查后Coins任务状态，服务器HTTPS四GET200、八项越权403、同一会话显式权限撤销403及恢复200均实际通过。其他角色/绑定比较无变化，10%/rev40/auto/120分钟保持。

验收密码只在服务器进程内生成使用，已丢弃；没有可发送的TXT、密码或cookie。密码版本重置后旧会话网关302返回登录、sessions0；原脚本误期望公共401而停下，保留原失败，没有单独捕获verify401，不改写为通过。原准入及状态验证仍成立，原意图和审计保留。

老D转交12:10云端protected_command_failed，随后人工接管也失败并要求停止；不再重试或绕过。因此服务器身份已就绪不等于Dot新身份登录，私密凭据交付、持续调度、续期及正式接管均未完成。没有现成FS vault交付工具；由用户/身份管理员在现有账号权限页私密设置该主体密码，再在Dot产品安全登录框恢复后直接输入，不能转到聊天/Notion/Git/文件。原Work观察与服务器唯一writer继续。

原自然job a5914831-e264-4b34-b755-fa5bdba27c36于12:10:11创建、12:12:49 ready/no_price_change；原Hermes turn be064bbb755b460c8c4c743546fa9314、task f5b04372ee5064c056e8be30cf8e61ae已完成。下一计划14:12:49。这是服务器原周期，Dot本轮云端尚未独立读回。12:27原监控138SHA无漂移/队列0/未确认0，matched仍是521c/10:41旧公开观察，不能算新自然变价。


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
