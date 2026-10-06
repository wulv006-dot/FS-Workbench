> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。

# Admin与Order后台接口及机器访问需求

版本：v1.1（全业务增补；v1.0历史保留）　｜　日期：2026-10-06　｜　用途：请后台开发确认接口、口径和访问方案

## 一、先请开发确认这几件事

我们准备把FS全业务经营看板与运营工具接成稳定的云端链路，覆盖D4、PoE2、Aion2、FC、NBA、MLB及已有其它业务，需要Admin、Order提供正式接口和机器访问。优先经营准确读取、FC读写及ARPG现有核心合同，采用通用接口加项目差异附表；NBA高级自动写后续规划。

**数据规则必须统一：订单数量、订单金额、单均价、利润率用Order后台；Order没有的字段再用Admin补充。** 两边都有的字段优先Order，两边总数不同可以分别展示并保留来源，不人为调平。实际订单采购成本若从Order取得，仅取`genre=1`订单发货记录并按项目原生单位解释。D4定价成本字段、千岛DWC、Aion2 DD373参考成本另列来源，不能混成实际订单成本或套FC的CNY/K、赠送公式。

| 优先级 | 必需能力 | 请开发交付 |
| --- | --- | --- |
| P0：经营采集 | Order准确区间汇总、Admin补源、游戏/品类/平台/网站字典 | 正式只读JSON接口；全站及筛选口径；历史覆盖、数据时间与错误说明 |
| P0：FC经营读取 | 销售、采购成本、原生利润率、分类及商品排行 | FC范围字段、原生排行单位/分页、成本类型与单位；日期筛选准确聚合 |
| P0：长期运行 | 云服务器可持续访问，采集与控写权限分开 | 官方机器身份、短期access token、安全可撤销续期、配额及网络要求 |
| P0：FC受控操作 | 明确商品/模型的改价、手动上新、上下架、标签/图片及价格同步 | 最小写字段、预览、版本校验、幂等回执、独立读回与公开价生效合同 |
| P0：ARPG现有核心合同 | D4物品/Gold、PoE2套餐/league、Aion2 Kinah服务区读取与有界写 | 通用目录/价行/成本能力加项目ID/单位/precision/scope差异；不改现定价策略 |
| 后续升级 | NBA有限策略自动运行、MLB/Aion专属上新、更多细分维度 | 先给支持情况与依赖；NBA高级自动写不是本次P0 |

我们需要后台先回复：哪些已有接口可正式使用、哪些要新增或调整、每项负责人和交付顺序。附录记录的是源码中已发现的调用，不代表开发已承诺支持，也不代表本轮核验了生产可用性。新接口的URL、方法、字段和scope名称请由后台确定，我们不会自行猜测。

本文件只提出需求，不创建账号、发放权限或启用生产写操作。**不要求永久Cookie、不共用root/admin账号、不在聊天交付密码或token。** Google的GA4/GSC/Ads是独立外部来源，不要求Admin或Order开发提供Google凭据。

## 二、经营数据口径

### 2.1 来源与业务范围

主源页面：Order后台「统计管理 → 订单统计」，`https://order.p2pah.cn/#/stats/admin_order/index.html`。

补源页面：Admin后台「统计管理 → 订单统计」，`https://admin.p2pah.cn/#/admin/statics/orderEs`。

运营总览统计**所有网站合计**。ARPG、球类、FC和各游戏保留自己的明确筛选；全站不能默认缩成MMOEXP单站。当前代码有一个历史key叫`MMOEXP`，其业务范围实际是所有网站合计，请以范围定义为准。主源失败时不得静默用Admin订单/金额顶替；保留上次成功数据并标过期或显示不可用。

| 经营指标 | 来源及原字段 | 要求 |
| --- | --- | --- |
| 订单数量 | Order「订单数量」 | 原生准确区间订单数，不当商品件数 |
| 订单金额 | Order「订单金额」 | 原值及币种、精度、退款/支付状态说明 |
| 单均价 | Order「单均价」 | 使用后台原值，说明分母，不以Admin客单价替代 |
| 利润率 | Order「利润率」 | 使用后台原值，支持负值；明确毛/净、收入、成本、手续费、退款与汇率公式 |
| 付款人数 | Admin `paid_payments` | 准确区间去重人数；明确去重依据 |
| 新客人数 | Admin `new_people` | 明确首次付款/注册等判定、跨站去重与历史窗口 |
| 新客付款金额 | Admin `new_amount` | 明确新客已付金额、退款处理和币种；不是总金额`amount` |
| 复购率 | Admin `repeat_rete` | 保留原字段拼写；说明分子分母及人数/订单口径 |
| 新客占比 | Admin `new_people / total × 100` | 同Admin范围与日期；分母0不可计算；不得除以Order订单数 |
| 收款总额、货款总额 | Order对应原字段，当前展示CNY | 明确结算范围；不能直接差值标为USD利润 |
| 其它重叠指标 | 两源共有则优先Order | 逐字段保留来源，不按整份响应随意切源 |

请开发同时给出利润金额、成本总额的可用性与定义。当前源码能取Order利润率，尚不足以证明利润金额或毛/净公式。没有正式金额依据时，我们不会反算利润、平均项目利润率或把`pure_amount`当利润。

### 2.2 准确日期与一致性

日期选择要驱动所有对应范围的顶部数字和明细，不保留固定今日值。请接口提供准确整区间聚合，人数、复购率、利润率不能把每日值相加。日、小时、周、月图表保留实际颗粒与桶边界，不把周/月桶冒充每日数据。

请确认时区、时间字段和边界。我们的统一时区为`Asia/Shanghai`；客户端选中最后一个自然日时，内部使用该日次日00:00作为排他结束时间。上游若采用不同边界，需要明确转换。原生商品排行的`paytime RANGE`当前适配为开始至排他结束前1秒，也需要后台正式确认。

每份响应希望包含：查询起止、时区、网站/游戏/类型/平台/订单/支付状态、币种及单位、字段定义版本、数据生成时间、业务数据截至时间或水位。Order/Admin分别保留来源和读取时间；同一个日期区间不等于两个后台在同一事务时点读到数据。若可以固定`asOf`或一致性水位，请明确支持方式；不能支持时如实返回各自时间。

经营链路维持服务器每120分钟生成一份统一版本快照，各业务页面每60秒检查新版本。准确区间结果绑定快照版本及截止时间，采集失败保留上次好数据并标过期；快照整体原子切换，避免页面混用不同版本。我们自己的快照服务承担发布，不要求上游开发复制页面逻辑；上游需提供可固定批次/范围的事实输入。不得由此改变任何价格自动执行频率。

### 2.3 维度与映射

希望尽量提供已有且有价值的维度：网站来源、游戏、产品类型、平台、国家地区、设备、付款方式、优惠码、订单/支付状态。已有字段直接使用，缺字段明确未提供，不能当0。

| 当前已定位维度 | 边界与待确认 |
| --- | --- |
| Order「来源」图表、订单状态、产品类型 | 来源图表当前可读金额；需正式维度ID/名称/度量和过滤合同 |
| Admin `site_rank` | 网站来源，不能直接称UTM、广告或获客渠道；如有真正channel字段请另列 |
| Admin `country_rank`、`game_rank` | 有数量/金额和名称；需字典、未知值与跨页完整性 |
| Admin `chart_pay_device` | 当前只有设备名称与订单数，没有已证实设备营收 |
| Admin `chart_pay_style` | 付款方式、订单数、金额；需单位与状态定义 |
| 优惠码 | 请求有`discount_code`，当前维度输出未提供；请说明是否支持聚合 |

Google营销数据仍由我们独立读取。需要关联时，请后台提供稳定的网站ID、游戏/商品ID、渠道/优惠码字典，以及各字段时间和币种合同；不把所有网站交易额直接除MMOEXP单站GA4人数当转化率，不申请Google授权或投放写权限。

## 三、FC与商品操作

### 3.1 FC经营与原生排行

FC经营四核心仍来自Order，客户字段仍由Admin补缺。FC商品排行使用Admin原生`productSalesByEs`，不得拿订单趋势或代表商品名称推算排行。需要确认`pid`与`goods.id`关系、`sale_total`单位、`order_count`定义、分类树版本及站点/平台/支付状态过滤。

当前`order_count`是商品分组内次数，不可直接求和当全站去重订单；`sale_total`单位没有官方确认，不直接标USD、标准件数或到账金币。代表行的标题/时间不代表全部订单的平台。分类按原生祖先树：Players 9627、Packs 9629、SBC 9625；未知/冲突分类保留未知，不靠名称猜。

Order与Admin ID命名空间必须分开：FC Order游戏1322、Admin游戏1327；Order类型1/2/4与Admin目录类型不同。后台请提供稳定的对应关系及新增/删除/变更规则，不能让客户端把同名字段当同一个ID。

### 3.2 订单发货采购成本与汇率

Order实际订单成本接口只返回`genre=1`的订单发货记录；外部报价/定价参数的项目差异见第八节。至少包含稳定记录ID、游戏/平台/产品类型、发货类型、交易时间及时区、数量/赠送、采购单价与币种/单位、更新时间。排除采购打款、销售补发、销售赠送；缺记录或过期要能明确判断。

FC现校验三平台最新有效成本，单位CNY/K，限定最近有效记录。NBA历史源码仍用`genre=0`和宿主本地时间，**这不是本需求认可的成本口径**；请开发说明旧枚举，给genre1或等价明确订单发货合同，后续单独适配，不在本文件中改现运行。

汇率请明确来源、币对方向、有效时间、到期时间、精度、手续费及舍入。区分定价汇率与历史订单结算汇率。当前Order定价表守卫与NBA默认值6.65只证明已有定价参数，不能当实时外汇接口或历史结算依据。若无独立FX接口，可提供后台采用汇率的正式字段与版本，不编造新URL。

### 3.3 FC控写最低合同

改价、手动上新、上下架、标签/库存/图片、价格重算和缓存更新均属于受控写。请按商品/模型ID、游戏、网站、平台和可写字段授权，保留非目标字段及现有数量/折扣/赠送向量。普通读取身份不得获得“整个后台edit”权限。

需要有无副作用的预览：目标对象、当前值、拟改值、范围、版本、影响商品、单位及到期时间。正式写携带批准计划、稳定`requestId`和规范化`payloadHash`，并以旧版本/旧值做CAS校验；对象已变化则拒绝，不能覆盖最新值。请求ID相同但内容不同必须拒绝。

后台需要持久回执或作业状态：pending、confirmed、partial、failed、unknown，逐项说明成功/失败对象和生效版本。客户端收到超时、断线或未知结果后只读查状态与独立读回，不换新ID、不盲重传。认证刷新也不能重放未知写。

写后用独立GET核对实际商品/模型值，不能把POST回显当生效。价格链还要区分后台价、同步、缓存、公开销售价各阶段，给出对应版本/时间及延迟上限。缓存操作希望缩到指定网站/商品；当前全局清缓存有副作用和限流，不授予采集主体。历史FC同步表单是GET但会写价格，请后台提供明确受控写协议，不能因GET而授只读权限。

新卡Excel请提供列schema、大小/数量限制、FUTBIN ID等唯一键、去重/部分成功清单、job_id与进度合同；图片需限定PNG/大小/哈希/附件归属和返回attachment_id，模型icon写附件ID，不写本地路径。当前公共上传签名依赖不作为安全长期机器身份方案，请提供官方有限上传授权。指定模型重算必须列明IDs，未批准时拒绝空ID全类目重算。

## 四、人员权限与机器scope分开

| 主体 | 读取 | 写入 |
| --- | --- | --- |
| 匿名 | 不读经营数据和私有JSON | 拒绝 |
| 现有合法FC普通登录 | 全部FC销售、成本、利润、排行及准确范围 | 不可改价、上架、改配置或管理权限 |
| 现有合法管理员 | 在既有合法业务范围读取 | 仍需具体操作范围与批准计划，不自动授所有业务写 |
| 官方采集机器主体 | 经核准的经营聚合、字典、成本和商品只读scope | 无价格、库存、上下架、缓存或账户写scope |
| 官方受控写机器主体 | 最小写前读/写后核验 | 仅批准的游戏/网站/对象/字段；与人类批准者分开审计 |

FC-only身份不能扩到其它游戏、内部全站数据、营销或管理入口，也不撤销原有其它业务合法权限。服务器必须真实校验scope，不能只隐藏按钮。本站人员管理员身份与上游机器API scope是两层授权，本文件不修改现有账号或指定新的管理员。

请求返回可验证的机器subject、scopes、有效期及禁用状态。上游授权名称由开发给定，表中的scope是能力描述，不是已存在的正式scope字符串。人员批准者、实际机器执行者、操作范围及结果分别记录，不能凭同名username冒充管理员签名或会话。

## 五、长期机器访问和凭证安全交付

需要服务器可以持续运行，尽量去掉人类图形验证码与浏览器Cookie作为持续在线依赖。请开发采用官方服务身份、短期access token与安全续期：可以选受支持OAuth client_credentials、受控轮换refresh或等价短时服务签名，具体协议、端点与TTL由开发确定。**不是要求永不过期token或永久Cookie。**

现有Order是验证码绑定会话；Admin客户端使用batoken，存在`/admin/login`与`/admin/index/login`两个调用变体。Players源码有`/api/common/refreshToken`原语，但尚未确认适配长期机器运行。请说明权威登录/续期合同、返回结构、token/refresh TTL、轮换与撤销、并发续期、禁用后失效时间、过期错误码。已有刷新函数不等于机器方案已经支持。

凭证交付责任请这样分工：后台开发提供正式文档、sandbox访问方案和最小权限清单；授权负责人审批具体主体/范围；后台或安全负责人通过公司批准的秘密管理渠道交付或配置生产认证；集成负责人只在服务器受控秘密存储中接入。生产凭证不在本需求文档、聊天、Git、前端、URL、截图或普通日志流转。

密钥/续期凭证应可单独撤销、轮换、有审计和过期提醒；只读与写主体分别管理。凭证丢失或过期采集标不可用并告警，写默认拒绝，不降级到共享管理员Cookie。请求中不收集真实凭据，也不因本文件自动创建账号、token或扩大网络白名单。

## 六、错误、配额、分页与网络

请给版本化API文档或等价完整schema、稳定错误码及兼容/废弃规则。HTTP状态与业务code都要明确，401认证失败、403权限不足、409版本/状态冲突、422输入不合法、429配额、5xx服务故障应可区分。历史Admin JSON code302/409与HTTP语义不同，请列转换关系和处理方式。

只读瞬时网络/5xx可有限退避重试，遵守`Retry-After`、jitter与最大次数；认证或字段合同失败不得无限重试。写操作只按服务端幂等与状态查询合同处理，不因“失败”自动重发。请给单主体配额、并发、batch上限、最长区间/历史范围、响应/作业超时及维护窗口。

分页至少需要稳定排序、唯一ID、total、游标/页大小上限和完整性标识；最好支持固定查询批次/水位，跨页数据变化应能检测。FC native排行当前同值offset排序不稳定，客户端不得无限扩大limit或重复分页猜完整结果。需要后台明确稳定cursor或完整有界导出合同。

网络请确认云端出口/IP要求、正式域名、TLS证书链和主机名校验、超时与重定向规则。不沿用历史代码关闭TLS验证的方式，也不开放任意网络目的地。可选callback应签名、有事件ID和重放保护；无callback支持时给可只读查询的作业状态即可。

审计至少记录subject、approvedBy、requestId、接口/对象/字段范围、前后版本、时间和结果；不得记录凭据及未经授权的原始客户信息。认证失效、数据过期、分页不完整、未知写结果和公开价不一致都要有可定位告警。

## 七、请按这些场景验收

先在sandbox用合成数据验接口，再由双方确认有限生产读取和受控写验收计划。不要为了测试真实改价、重跑采集或改账户。

| 场景 | 通过标准 |
| --- | --- |
| 全站及游戏/品类/平台筛选 | 返回范围与字典一致，Order/Admin ID不混用，all-sites不是单站 |
| 今日、跨日、周/月、自选区间、空区间 | 边界准确，所有汇总随日期变；空/缺失不残留旧值 |
| 付款/新客/复购 | 原生整区间去重；new_amount不混总额；新客占比用Admin自己的total；零分母不可计算 |
| 利润/成本/汇率 | 原生定义可解释，负利润保留；只genre1订单发货；无依据不估算 |
| 原生商品排行/分页 | 单位和分组明确，唯一ID/total完整；分页变化可拒绝或重查，不重复计数 |
| 同批次版本与失败 | 时间/水位可追踪；主源失败不换补源；快照原子发布、保留好数据并标过期 |
| 登录与scope | 匿名拒绝；普通FC读全FC且不能写/越范围；机器采集scope不能写 |
| token到期/撤销/限流 | 安全续期与禁用生效可证，失败有明确码，限量退避，不泄露认证信息 |
| 受控写并发/冲突 | 预览无副作用；旧版本CAS拒绝；同requestId同内容不重复写，不同内容拒绝 |
| 超时/断线/部分成功 | 可只读查回执及独立读回；unknown不盲重传，结果逐项可审计 |
| 价格公开生效 | 后台/同步/缓存/公开价分阶段核对，版本和可见时间明确 |
| 导入/上下架/图片 | 有界ID/字段，保护非目标内容；去重、附件归属及未知结果处理通过 |

请开发回复支持/不支持项、真实接口版本、scope/配额、需要新增的字段、sandbox准备时间和验收负责人。生产开通及操作由双方另行确认，本需求不授权部署或修改价格策略。NBA高阶自动策略留到后续规划，不让其整模块拖住其它已验证模块；现有安全门槛仍需满足。

## 八、FS各业务项目差异与后台回复项（v1.1补充）

本需求覆盖FS全部现有业务，包括大超维护的D4、PoE2、Aion2和球类FC、NBA、MLB。通用接口只申请一次，参数、ID、单位和写scope按项目区分；不能把FC的1K、赠送到账、PS/XBOX/PC或利润规则套到所有游戏。未找到完整实现的能力列待确认，不编接口。

### 8.1 商品、区域、数量与价格

| 项目 | 已发现结构及ID | 单位、精度和版本差异 | 当前缺口/正式要求 |
| --- | --- | --- | --- |
| D4物品 | Order gid456；商品SKU/包装规格，通过index_item读取、goodsEdit有界写。公开ajax/goods物品筛选用category_id，不能与cid同时传 | USD标价→实际折扣后客户价，必须区分每件/整包与计数；写器5位，engine又有tick/dec约束。折扣以实测优先，历史90不是永久常数 | 官方SKU/模型、aid/cid/region/server/platform映射、允许写字段和precision/tick；跨区商品不合并 |
| D4 Gold | 每服务区一价行，与物品机制分开。源码历史默认S15普通/专家、Eternal普通/专家，需确认现在赛季和真实映射 | costprice是CNY/M定价参数；b2c/前端USD/M；展示可按100000M。成本小数位配置默认6，不是所有商品统一6位 | 后台price-row ID与公开aid/竞品serverId分别映射；itemEdit costprice写、getweb1同步、禁止allserver；实际容器executor/读回闭包待核实 |
| PoE2 | Order/Admin统计gid552；存在poe2_align、通用engine/frontend/backend调用。区服标签样例Standard/Hardcore/Forbidden Rites SC/Runes of Aldur SC | 同游戏+区服/league+商品族比价。Divine Orb(1000+50 Free)源码按付费1000计数、赠送50不计价，这是该套餐映射，不是FC成本公式。标价5位另需tick/最小正价 | 前台aid与后台aid不是同一号码；公开cid1338/4459为源码回退值。真实league/season/version、模型/SKU/全部映射与当前成本/部署闭包需大超和开发确认；不能称完全没有实现，也不称完整已验 |
| Aion2 Kinah | Order826、Admin与公开Game_id891；公开cid6527/site266。按region+server+race区分，非球类平台分组 | 统一比价USD/M百万Kinah；DD373原CNY/万×100/USDCNY；ELD USD/K×1000；G2G Mil Kinah直接USD/M；显示每M；成本scale配置默认6 | NA West/NA East/EU/South America/Asia、天族/魔族及小服ID；Nezekan/Nezakan别名需明确。实际backend row/aid/model/赛季如有待字典；不得拿大区均价伪装真实小服成交 |
| FC | Order1322/Admin1327，Coins/Players/Packs/SBC原合同；Coins与模型商品关联分开 | K、现有数量/折扣/赠送向量按FC合同，价表/模型/商品精度分别确认 | 现正式FC只读与admin控写仍优先；FC-only不扩其它业务 |
| NBA | Order1306/Admin1329；VC mid42278471、Admin平台aid21595/21591/21597，与Order成本aid21764/21766/21768分开 | VC unit_price的实际单位、档位/赠送及精度未获正式字典；不能套FC K。真实Order成本genre0历史差异需改进合同 | 已有有限Admin Goods写/读回和公开价格只读；高阶自动策略后续非P0，基本稳定与写安全门槛保留 |
| MLB | Order922/Admin927经营统计；所读工作台托管任务/Excel，ShowDD是外部卡片来源 | 卡片/年版本、数量、平台、后台模型/SKU、价格单位/精度未核实 | 全量agent与正式商品创建/上架/写价闭包未定位；先确认后台可用通用商品能力，不编MLB专属API |
| NFL27/CFB27/FC26等 | 当前统计映射已在附录B | 保留各项目版本/类别/币种，不套FC27规则 | 本轮最小经营聚合可读；专属商品写/成本需要明确合同再授权 |

D4 Gold源码默认价行/公开aid/竞品ID仅作映射线索，不作为当前写白名单：S15普通row15711/public aid15943/IGGM27589；S15专家15712/15945/27591；Eternal普通11914/11916/11507；Eternal专家11916/15403/11509。真实赛季切换、停用区服和后台商品ID请开发与大超核准，不能从老默认自动授写。Aion2的Order826和公开891也不能互换。

### 8.2 成本类型和定价合同不能混写

**经营看板的实际订单成本**若由Order发货记录取得，仅接受genre1订单发货，并按游戏原生数量、赠送、币种、单位和记录类型解释。CNY/K只在已核实FC Coins成本成立，不能向D4/PoE2/Kinah推广。

**定价参数与外部报价成本**单独保存来源、时间和单位：D4物品有千岛订单簿深度加权进价(DWC)，先按库存深度取价，再乘商品刻度/数量除汇率；对标区服失败、降级区服会使成本不可信，现源码冻结相应跟价。PoE2所读代码有通用成本函数，但未确认专属成本全链，不能因此声称它已接千岛。Aion2有DD373综合排序推荐第1条报价，原单位元/万Kinah，**不是已发生Order订单结算成本**。

经营利润率继续用Order原生值；Aion外部参考毛利(公开售价−DD373参考成本)/公开售价、D4/PoE2引擎估算毛利与Gold定价marginRate必须分别命名。Gold marginRate如0.20是定价输入，不能当经营净利润率；没有官方成本/结算定义不将参考毛利标为实际利润。

现源码已有项目定价分支，需要保留而不是统一重写：D4/PoE2物品目标标价按竞品真价×SKU计数×让价系数/实测折扣；D4 Gold采购成本反推包含汇率、定价marginRate和前端系数，源码D4默认前端系数1.052631579，Aion默认1.0，不能照抄旧5.32除数。tick舍入不能把极低价抬高越过策略上限或变成0后强行写。

Aion源码同时含dd373_markup与旧multisrc策略。实际执行分支可按DD推荐价加价、G2G次源、配置默认售价顺延；旧多源min及同大区均价分支也存在，部分头部注释仍说成本仅监控/无报价不兜底，与后续执行分支不同。**当前生效模式、适用游戏、加价/兜底与参数必须由大超确认，文档不选择策略、不启用旧策略或默认售价，不用模拟目标价冒充真实成交。**

### 8.3 通用读写能力按项目分scope

后台需支持同一通用能力携带明确game/region/server/platform/category/model/SKU/site/currency/version：批量目录及价行读取、准确成本读取、最小有界批量写、逐项状态、独立读取实际值。范围中的league/season/race字段只在实际支持的项目使用，返回“未提供”而不是捏造统一字段。D4/PoE2物品goodsEdit与D4/Aion金币itemEdit是两种能力，允许字段不能混用；金币工单一游戏一单，不能将826写到456。

Order /game/admin_game_price/itemEdit?ids=<价行ID>的POST costprice写已在工单说明定位，实际srv_run/p2pah_local实现不在冻结候选，完整form数值字段/响应/旧值校验仍待正式合同。后续getweb1更新b2c与FC现getweb0同步不同，不可互换；5–15分钟是历史说明，不作为开发承诺的当前SLA。请提供正式同步状态与公开价格一致性时间，写后独立读回是要求，不能以已有工单文字称已验。

所读D4 apply_price代码的成功路径主要记录code/台账，不能代替每SKU的独立后台GET和公开售价格验收。PoE2既有专用对齐工具生成计划，由其它执行器真写；是否完整部署、SKU白名单、正价/tick、成本源和生产读回须大超确认。机器scope限批准项目/价行/字段/范围，不能为ARPG申请FC专用GoodsMould全类目重算或任意标签/图片写。

### 8.4 调度与第三方边界

交易经营快照120分钟/前端60秒与竞品采集、查价、算价、执行写价是不同链路。本轮不调整任何调度：D4/PoE2源码due默认1小时；配置可选0.25/0.5/1/3/6/12/24小时；Aion有0.5小时注释及独立watch15分钟。归档d4follow-collect.timer与aion2-watch.timer均为15分钟声明，但不是本轮实机systemd核查，不能报成现生产频率；需要大超确认当前有效配置/units/drop-ins。空转executor poll10秒也不是写价频率。

千岛、IGGM、DD373、G2G、ELD、ShowDD和Google属于独立外部来源，其网络/授权/限流/报价真实性由各链路维护。Admin/Order开发只提供自身聚合、目录、价格、实际订单成本和受控操作合同，以及必要关联ID；不要求其代开第三方账号或给外部密钥。MMOEXP自有公开ajax/goods是独立销售价核验入口，D4物品category_id、PoE2 cid、D4 Gold与Aion Gold的Game_id/cid/site_id参数不同。

### 8.5 请开发与大超逐项目回复

1. 正式Order/Admin/public game IDs、模型/SKU/价行/站点、region/server/platform、race及实际league/season/version字典；旧区/赛季停用与映射更新规则。
2. 每类商品/货币的数量、计价数量、赠送、pack/min_qty、币种、价/成本单位、scale/tick/舍入、最低正价和批量上限；字段缺失用明确状态。
3. 各项目实际Order genre1采购成本可用性，与外部参考成本/定价costprice分开；利润原生定义、汇率来源/生效时间和定价系数。
4. 每项目可用读、preview、写字段/ID范围、机器scope、幂等/CAS/逐项回执、独立后台读回、同步缓存与公开价生效合同。
5. 现支持与需新增、完整实现/只工单/未定位的区别；大超核对D4/PoE2/Aion2实际配置与当前定价策略/调度，后续形成有限sandbox和生产验收计划。文档不承担配置开通或部署。

## 附录A：源码已发现的完整调用表

以下共36项调用记录、32个host/path组合。状态只表示静态源码证据，不是正式API承诺或当前生产可用性。所有条目都请开发确认正式版本、方法、编码和scope。

主机简称：Order=`https://order.p2pah.cn`；Admin=`https://admin-api.p2pah.cn`；Media=`https://b2c-api.p2pah.cn`；PublicMMOEXP=`https://www.mmoexp.com`；Internal是本站消费接口，不要求Admin/Order开发提供。

“方法推断”表示源码通过受控SessionManager的data参数调用，代理实现不在本次冻结源码；POST及body编码需后台确认。“默认路径”可能被配置覆盖；“历史尝试未验证”不能据此授权执行。

| 记录 | 系统 / 方法 / 路径 | 用途与读写 | 源码证据状态 | 需后台确认 |
| --- | --- | --- | --- | --- |
| ORDER-STATS | Order GET `/stats/admin_order/index.html` | 经营统一主源：全站/ARPG/球类/FC准确区间统计；当前读取HTML DOM和图表，不是已公开JSON API（只读） | 源码已发现；正式版本待确认；S001,S002,S005,S032 | 请提供与原页面完全同口径的稳定JSON读取合同，具体新URL由后台指定；利润率毛/净、收入/成本/汇率/手续费/退款定义；status/gid=0和站点全集定义、缺省aid语义；原生各区间边界/数据一致性时间/币种/精度/历史覆盖 |
| ADMIN-ORDER-SUPPLEMENT | Admin POST `/admin/order.Order/orderStaticsDetailByEs` | Order未提供字段的补源；不替换Order四核心、不在Order失败时静默切源（只读） | 源码路径已发现，方法推断；编码待确认；S003,S004,S005 | SessionManager受控实现不在冻结包；data调用推断POST，正式HTTP method/JSON或form编码待后台确认；支付人数去重ID/新客首付判定/复购率明确分子分母；site_rank是网站来源，不等于UTM/广告归因；country/device字典；pay_status=1与Order订单状态/支付时间共同语义；new_amount币种/是否仅新客已付金额/退款扣除规则 |
| ADMIN-PRODUCT-RANK | Admin GET `/admin/stats.productSalesByEs/index` | FC原生商品销售分组排行，不能用Order曲线代替（只读） | 源码已发现；正式版本待确认；S006,S007 | sale_total是原生销售量，单位未核实，不当作USD或到账金币；order_count是商品分组内次数，不等于全站distinct订单；代表行paytime/标题不能代表所有订单平台/SKU；平台/站点/支付状态精确筛选官方支持情况 |
| ADMIN-CATEGORY | Admin GET `/admin/goods.GoodsCategory/categorySelect` | FC商品分类树及跨源类型映射（只读） | 源码已发现；正式版本待确认；S006,S007 | 树版本、撤销/变更通知；Players9627/Packs9629/SBC9625不是Order tid，不合并命名空间 |
| ORDER-COST-FC | Order GET `/order/admin_delivery/index.html` | FC三平台最近有效订单发货采购成本；需要后台JSON替代DOM（只读） | 源码已发现；正式版本待确认；S013,S014 | genre=1确切枚举与订单发货字段；排除采购打款/销售补发/销售赠送；成本金额含税/手续费/赠送单位、结算时间/平台历史覆盖；是否可原生按最新记录+稳定排序+total查询 |
| ORDER-PRICE-FC | Order GET `/game/admin_game_price/index.html` | FC成本价/售价/折扣/汇率/赠送档位的只读预览和独立写后回读（只读） | 源码已发现；正式版本待确认；S015,S016 | 稳定JSON明细及版本/etag；页面内成本保存的实际XHR接口未由本轮源码定位，不能编造URL；6.65是现后台定价汇率守卫，不是已证明实时外汇 |
| ORDER-PRICE-SYNC-FC | Order GET `/game/admin_game_price/saveprice.html` | 历史表单同步价格有业务副作用；HTTP GET不得按只读授权（敏感写） | 源码已发现；正式版本待确认；S015 | 历史GET副作用应由后台给正式受控POST替代及鉴权；原子/部分成功范围、requestId/CAS/状态查询、public价格可见时间；不在本轮调用 |
| ORDER-D4-LIST | Order GET `/game/admin_game_price/index_item.html` | D4/POE2商品价与成本列表、预览和独立回读（只读） | 源码默认路径；有效配置与正式合同待确认；S022,S023 | 此为源代码默认路径，可由配置覆盖；现场有效路径未核实；稳定JSON及游戏/区域/数量/售价vs标价单位字典 |
| ORDER-D4-EDIT | Order POST `/game/admin_game_price/goodsEdit` | D4/POE2明确商品ID列表价格受控写；不扩大其它游戏（敏感写） | 源码默认路径；有效配置与正式合同待确认；S021,S023 | 默认路径可被配置覆盖，需官方确认；项目和字段级scope/CAS/idempotency/readback/public缓存传播；cprice:null是否保持原值必须明确 |
| ORDER-LOGIN | Order POST `/admin/public/dologin.html` | 现有人类登录协议证据，作为机器认证升级背景，不请求共享管理员凭据（认证原语） | 源码已发现；正式版本待确认；S021 | 官方机器身份及安全可撤销续期替代方案；现会话TTL/失效原因/并发限制 |
| ORDER-CAPTCHA | Order GET `/new_captcha.html` | 现Order人类登录图形验证码（认证原语） | 源码已发现；正式版本待确认；S021 | 与session绑定；不是长期机器认证方案 |
| ADMIN-LOGIN-CONFIG | Admin GET `/admin/index/login` | Players官方客户端登录配置（认证原语） | 源码已发现；正式版本待确认；S008 | 配置/验证码启用语义 |
| ADMIN-LOGIN-PLAYERS | Admin POST `/admin/index/login` | Players人类登录响应合同（认证原语） | 源码已发现；正式版本待确认；S008,S011 | 与NBA /admin/login 别名和不同响应结构的正式版本关系；短token TTL/refresh TTL及rotation/revoke规则；不把当前refresh默认认成机器服务支持 |
| ADMIN-LOGIN-NBA | Admin POST `/admin/login` | NBA客户端采用的另一登录路径（认证原语） | 源码已发现；正式版本待确认；S025,S026 | 与/admin/index/login的权威统一登录合同及版本兼容 |
| ADMIN-CAPTCHA | Admin GET `/api/common/captcha` | Admin现有图形验证码（认证原语） | 源码已发现；正式版本待确认；S008,S025 | 一次性绑定与失效规则 |
| ADMIN-REFRESH | Admin POST `/api/common/refreshToken` | Players源码已有刷新原语；本轮未请求/未验证当前有效性（认证原语） | 源码已发现；正式版本待确认；S008,S011 | 可否官方用于受限服务主体而非管理员浏览器会话；TTL/rotation/revoke/reuse detection/异常和并发续期；候选 OAuth client_credentials/受控refresh或等价方案由后台选择，无已知OAuth URL |
| ADMIN-IDENTITY | Admin GET `/admin/index/index` | 验证真实服务身份与有效scope；现读返回不同user结构（只读） | 源码已发现；正式版本待确认；S018,S017,S008 | 官方可稳定读取subject/scopes/roles/expiry；机器身份与人类批准者分开记审计 |
| ADMIN-MODELS | Admin GET `/admin/goods.GoodsMould/index` | FC Players模型列表/筛选/标签与现有价格同步前置读取（只读） | 源码已发现；正式版本待确认；S009,S019 | 变更版本/稳定游标、更新时间、删除增量、分页一致性 |
| ADMIN-MODEL-DETAIL | Admin GET `/admin/goods.GoodsMould/edit` | 模型明细与写后独立回读；不是用模型默认price替代真实商品价（只读） | 源码已发现；正式版本待确认；S009,S010,S012 | 模型/产品/附件关联、版本、字段字典 |
| ADMIN-TAGS | Admin GET `/admin/goods.GoodsTag/tagSelect` | FC Players标签字典（只读） | 源码已发现；正式版本待确认；S009 | 标签生命周期/用途/排序；跨业务scope |
| ADMIN-GOODS | Admin GET `/admin/goods.Goods/index` | FC Coins/Players/NBA真实商品列表；按各自id/gid/cid/mid/site_id/aid范围读取（只读） | 源码已发现；正式版本待确认；S009,S019,S026,S017 | 价格单位/折扣/赠送/库存/状态字段明确关系；模型price不是SKU实际售价 |
| ADMIN-GOODS-DETAIL | Admin GET `/admin/goods.Goods/edit` | 商品身份校验与独立写后回读（只读） | 源码已发现；正式版本待确认；S017,S026 | 响应版本/CAS及规范化副作用；零库存与下架区别 |
| ADMIN-GOODS-EDIT | Admin POST `/admin/goods.Goods/edit` | 有界商品价格/库存写：Coins保护档位向量；Players仅total；NBA有限unit_price（敏感写） | 源码已发现；正式版本待确认；S017,S010,S026 | 字段CAS/idempotent requestId/batch partial/status查；写前保护非目标字段；NBA高级策略后续，但当前写安全门槛不能省 |
| ADMIN-MODEL-EDIT | Admin POST `/admin/goods.GoodsMould/edit` | FC模型上架/下架/标签/图片最小字段写，管理员批准计划（敏感写） | 源码已发现；正式版本待确认；S010,S012 | 上下架状态具体枚举、more完整保护、tid清空语义、附件scope/CAS；不能顺带编辑价格 |
| ADMIN-IMPORT | Admin POST `/admin/goods.GoodsMould/importPlayers` | FC手动批准新卡Excel导入（敏感写） | 源码已发现；正式版本待确认；S010 | Excel列schema/大小/数量限制、部分成功清单、去重FUTBIN ID、异常未知禁止重传 |
| ADMIN-IMPORT-PROGRESS | Admin GET `/admin/goods.GoodsMould/importPlayersProgress` | 已批准导入作业只读进度和最终结果（只读） | 源码已发现；正式版本待确认；S009 | 明确状态枚举/百分比/成功失败模型ID/错误码/最终回执保存期 |
| ADMIN-SINGLE-EDIT | Admin POST `/admin/goods.GoodsMould/singleEdit` | 现有FC模型单字段/批量编辑原语；最小正式字段清单需要后台核准（敏感写） | 源码已发现；正式版本待确认；S010 | 不得因源码有原语授予任意模型编辑；字段/ID/scope正式契约 |
| ADMIN-RECALC | Admin POST `/admin/goods.GoodsMould/recalcFc27Price` | FC指定模型重算商品价格；区分类目级历史函数与当前明确ID逐模型工作流（敏感写） | 源码已发现；正式版本待确认；S010,S019,S020 | 现源码同时有id=[]类目级函数，不默认授予或执行；正式scope应拒空ID；cost/discount/give与Coins已确认价格版本绑定；不可仅HTTP成功认改价生效 |
| MEDIA-UPLOAD | Media POST `/upload/file` | FC已批准PNG上传并取得附件ID；要官方有限上传权限/安全签名替代客户端公共签名依赖（敏感写） | 源码已发现；正式版本待确认；S012 | 官方上传授权scope/有效期/撤销/文件哈希幂等/附件读写归属；现公开signer JS固定SHA，不作为机器长期认证方案；不输出签名素材 |
| ADMIN-CACHE-CLEAR | Admin POST `/admin/tools.Caches/clear` | 现FC已确认改价后清缓存，影响公共价格一致性；需要缩小范围（敏感写） | 源码路径已发现，方法推断；编码待确认；S018 | SessionManager body推断POST；HTTP编码待官方确认；限流/幂等与前台读回，禁止普通采集角色清缓存 |
| ORDER-CACHE-LEGACY | Order GET / POST `/admin/setting/clearcache.html` | 历史D4源码仅尝试的清缓存路径；不能当已验证API（副作用未知，不能当只读） | 历史尝试；方法/副作用未验证；S024 | 源码明确触发method/登录机制未验证；禁止将GET视只读；另一源码注释clearcachepost.html不是本轮完整验证endpoint，待后台指定 |
| ORDER-COST-NBA | Order GET `/order/admin_delivery/index.html` | NBA现读取采购单价；记录现实现与genre1目标合同差异（只读） | 源码已发现；正式版本待确认；S027 | genre0未明确保证只订单发货；需后台以genre1/明确deliveryType返回有效成本；时区/单位/去重/排序/total；不能以过滤qty1price>=10替代业务字典 |
| PUBLIC-NBA-PRICE | PublicMMOEXP POST `/ajax/goods` | 公开商品实际售价只读核对；POST不等于敏感写（只读） | 源码已发现；正式版本待确认；S028 | 公开价缓存更新时间/站点货币/折扣赠送换算/实际下单价一致性；其它游戏官方公共价格路径未独立核实 |
| LOCAL-VERSIONED-SNAPSHOT | Internal GET `/dashboard/fs-home/transactions/current.json` | 本站消费接口，非申请Admin/Order新授权；同一不可变快照+SHA版本（只读） | 本站消费合同；非上游申请接口；S031 | FC-only需精确FC投影新接口（URL未定），不能放整个transactions目录；现场auth仍需验 |
| LOCAL-EXACT-RANGE | Internal GET `/range (loopback:8931; existing public adapter /dashboard/fs-home/range.json)` | 本站按快照cutoff钉住原生准确区间，Order+Admin各自capturedAt；不是跨系统事务同一时点保证（只读） | 本站消费合同；非上游申请接口；S032,S033,S034 | 普通FC登录需要仅FC范围投影与缓存隔离，不允许直接开放内部allsite range；同date区间不意味着读自同一上游业务水位；需官方asOf/watermark |
| ORDER-GOLD-EDIT | Order POST `/game/admin_game_price/itemEdit` | D4/Aion2金币价行costprice受控写，按单游戏拆单 | 工单说明已发现；实际executor/完整form/响应待确认；S035,S048 | 官方schema、scope、精度、CAS/幂等回执、独立回读及getweb1传播 |

### 每项已知参数、响应与分页

以下保留实际字段拼写与当前调用限制；“当前客户端上限”不是后台承诺的配额。正式编码、默认值、字段单位及范围需要开发回复。

- **ORDER-STATS**：参数/筛选 `{"status":"all:空；ARPG现用3，枚举含义待确认","gid":"0=当前代码全站；各游戏见gameMappings","tid":"空或Order产品类型；FC coins1/items2/boosting4","start_paytime":"Asia/Shanghai 本地分钟字符串","end_paytime":"分钟字符串；边界含义需官方确认","aid":"FC分类reader显式0；通用reader未显式传aid","site":"当前reader无独立站点参数；all-sites语义需正式字典"}`；响应：订单数量→orders；订单金额→revenueUsd；单均价→averageOrderUsd；利润率→profitMarginPct；发货完成率；最小/最大订单金额；收款总额(CNY)；货款总额(CNY)；图表订单数/订单金额、来源、订单状态、产品类型。分页/批量：整页原生区间汇总；曲线可能小时/日/周/月，保留原生桶，不伪造日颗粒。

- **ADMIN-ORDER-SUPPLEMENT**：参数/筛选 `{"order_status":"空或ARPG101；与Order3对应需字典","pay_status":1,"game":"空=当前全站，或Admin游戏ID","site":"空","country_code":"空","client":"空","date":"[start,end] Shanghai本地时间","pay_type":"空","time_unit":1,"cid":"空","discount_code":"空","product_type":"空/明确类型"}`；响应：total；amount；paid_payments；new_people；new_amount；repeat_rete；pure_amount；refund_order_num；refund_amount；deducted_amount；shipped_rate；payment_rate；customer_price；min_order_amount；max_order_amount；site_rank；country_rank；game_rank；chart_pay_device；chart_pay_style。分页/批量：原生准确区间聚合，不把日去重人数/比例相加；维度未证实分页。

- **ADMIN-PRODUCT-RANK**：参数/筛选 `{"page":1,"limit":"1000起，total不足重取；最大10000","order":"order_count,descending","search":"gid=1327；paytime RANGE [start,end-1秒]，render=datetime","site/platform/status":"接口当前源默认，独立含义未核实"}`；响应：data.total；data.list.pid/gid/cid/title/sale_total/order_count/paytime；goods.id/cid。分页/批量：当前一次完整批量+total一致/去重验证；旧offset排序同值不稳定且pid排序未生效，需稳定cursor/snapshot及total。

- **ADMIN-CATEGORY**：参数/筛选 `{"gid":1327}`；响应：data.list.id/children；分类祖先路径。分页/批量：树返回；无分页证据。

- **ORDER-COST-FC**：参数/筛选 `{"gid":1322,"aid":0,"cid":1,"genre":1,"status":-1,"op_id":0,"show_ccy":-1,"is_stock":"","keyword":"","sn":"","start":"今天前7天00:00","end":"明天00:00","page":"1..15当前上限"}`；响应：record_id；delivery_type；trade_at；platform；cny_per_1k。分页/批量：逐页直到空；无官方total证据；取平台最新有效行并校验类型/时间。

- **ORDER-PRICE-FC**：参数/筛选 `{"gid":1322,"rows":"PS21942/XBOX21944/PC21946","allserver":"必须false","websites":"预览默认无特定网站选中","B2C":"必须选择"}`；响应：row id/gid/platform；costprice；b2c；lirunlv；exchange_rate[rmb]；网站/B2C筛选。分页/批量：三已核对行，不猜其它游戏写范围。

- **ORDER-PRICE-SYNC-FC**：参数/筛选 `{"server_id":"1322","selected_web":"b2c","getweb":"0","site":"只允许已确认mmoexp.com/既有明确范围"}`；响应：页面新同步反馈；之后Order/Admin/public多层独立回读。分页/批量：表单操作，不是正式JSON批量合同。

- **ORDER-D4-LIST**：参数/筛选 `{"gid":"D4默认456/POE2默认552；官方字典待定","aid":"受控配置","cid":"受控配置","keyword":"受控配置","page":"显式页面"}`；响应：id/gid/name/pack/min_qty/unit_price/sale_price/cprice/discount。分页/批量：当前HTML行解析，total/稳定排序待正式API。

- **ORDER-D4-EDIT**：参数/筛选 `{"body":"rows[{id,gid,min_qty,unit_price,cprice}]","unit_price":"已有写器五位小数标价，不二次除折扣"}`；响应：code/msg/wait。分页/批量：显式有限rows；服务端上限/原子性未公开。

- **ORDER-LOGIN**：参数/筛选 `{"username":"人自行输入","password":"绝不在文档或聊天提供","captcha":"图形码、同会话"}`；响应：code=1；三会话Cookie名称；不含任何值。分页/批量：无。

- **ORDER-CAPTCHA**：参数/筛选 `{"height":32,"width":150,"font_size":18}`；响应：image PNG。分页/批量：无。

- **ADMIN-LOGIN-CONFIG**：参数/筛选 `{}`；响应：data.captcha。分页/批量：无。

- **ADMIN-LOGIN-PLAYERS**：参数/筛选 `{"json":"username/password/captcha/captcha_id/keep"}`；响应：data.userInfo.token；data.userInfo.refreshToken或data.refreshToken。分页/批量：无。

- **ADMIN-LOGIN-NBA**：参数/筛选 `{"body":"username/password/captcha/captcha_id/keep"}`；响应：data.token。分页/批量：无。

- **ADMIN-CAPTCHA**：参数/筛选 `{"server":1,"id":"captcha_id"}`；响应：PNG/JPEG/GIF/WEBP实际签名检查。分页/批量：无。

- **ADMIN-REFRESH**：参数/筛选 `{"json":"refresh_token"}`；响应：data.token；data.refreshToken。分页/批量：无。

- **ADMIN-IDENTITY**：参数/筛选 `{}`；响应：adminInfo.username或客户端权威身份结构。分页/批量：无。

- **ADMIN-MODELS**：参数/筛选 `{"page":">=1","limit":"1..200","order":"sort,desc当前批量同步","search":"gid1327/cid9627；额外合法筛选；禁扩大scope"}`；响应：data.list；data.total；模型id/gid/cid/status/定价输入。分页/批量：完整页total一致，唯一ID，当前同步最多100页/10000模型。

- **ADMIN-MODEL-DETAIL**：参数/筛选 `{"id":"明确正整数"}`；响应：data.row；id/gid/cid/status/more/auto_off/tid/icon及原生定价输入。分页/批量：无。

- **ADMIN-TAGS**：参数/筛选 `{"gid":1327,"cid":9627}`；响应：data.list.id及标签明细。分页/批量：list；无分页证据。

- **ADMIN-GOODS**：参数/筛选 `{"page":">=1","limit":"Players<=200；NBA当前50","search":"field/operator/val；具体scope见gameMappings/coinProducts"}`；响应：data.list/data.total；商品id/gid/cid/mid/site_id/aid/unit/unit_price/more/status/total。分页/批量：total跨页一致，唯一ID；服务端应提供稳定游标/批次版本。

- **ADMIN-GOODS-DETAIL**：参数/筛选 `{"id":"有限白名单商品ID"}`；响应：data.row及完整允许/保护字段。分页/批量：无。

- **ADMIN-GOODS-EDIT**：参数/筛选 `{"id":"已读身份一致","allowed":"按模块/操作字段scope分离，禁整行任意写"}`；响应：code及写回结果，必须再GET验证。分页/批量：当前部分客户端全row提交，建议官方最小PATCH式合同，方法URL由后台定。

- **ADMIN-MODEL-EDIT**：参数/筛选 `{"body":"id + more/status/auto_off/tid；图片专用id+icon=attachment_id"}`；响应：code；GET详情回读。分页/批量：有限模型列表，现客户端不同操作白名单。

- **ADMIN-IMPORT**：参数/筛选 `{"multipart":"gid1327/cid9627/xlsFile"}`；响应：导入作业job_id及结果需后台正式字典。分页/批量：批量文件/限制/幂等性待正式合同。

- **ADMIN-IMPORT-PROGRESS**：参数/筛选 `{"job_id":"已提交作业ID"}`；响应：data进度结构，未在此客户端固定字段。分页/批量：无。

- **ADMIN-SINGLE-EDIT**：参数/筛选 `{"params/json":"非空payload；实际业务允许字段由上层适配器与后台共同定义"}`；响应：code；明细独立GET回读。分页/批量：未确定批量范围。

- **ADMIN-RECALC**：参数/筛选 `{"json":"gid1327/cid9627/id:[明确model IDs]；禁止未批准id=[]全类目"}`；响应：code及真实商品列表独立回读。分页/批量：后台批量上限/原子性未明确；客户端每模型回读。

- **MEDIA-UPLOAD**：参数/筛选 `{"multipart":"file + token/timestamp/id/view/type/watermark，签名值不写文档"}`；响应：upload.picture.code=200；file.id/full_url。分页/批量：单图；PNG文件名FUTBIN ID映射；attachment_id用于icon。

- **ADMIN-CACHE-CLEAR**：参数/筛选 `{"server":1,"body":"type=all,file=空"}`；响应：code=1；code0操作过于频繁；401/403拒绝。分页/批量：全局副作用；官方请求定商品/网站scope及传播状态。

- **ORDER-CACHE-LEGACY**：参数/筛选 `{}`；响应：页面文本，无可靠结果合同。分页/批量：无。

- **ORDER-COST-NBA**：参数/筛选 `{"gid":1306,"cid":1,"genre":0,"aid":"0/21764/21766/21768","status":-1,"op_id":0,"is_stock":"","show_ccy":-1,"start/end":"48h或7d，当前JS宿主本地时区格式"}`；响应：id/aid/area/time/price/qty。分页/批量：当前一页，未核total/分页；缺平台后历史补取。

- **PUBLIC-NBA-PRICE**：参数/筛选 `{"form":"Game_id1329/top_cid1/aid21595或21591或21597/cid9633/site_id266"}`；响应：goods.index.list[0].unit_price/game_area_format/goods_list。分页/批量：当前只读第一个商品对象；全部档位数量与正确选择待合同。

- **LOCAL-VERSIONED-SNAPSHOT**：参数/筛选 `{}`；响应：snapshotId/path/sha256/generatedAt/timezone/serverIntervalSeconds/clientCheckSeconds/staleAfterSeconds。分页/批量：path固定snapshots/{id}/snapshot.json。

- **LOCAL-EXACT-RANGE**：参数/筛选 `{"profile":"当前白名单","start/end":"day含所选最后日，内部转[start,end+1day)；hour转最后小时+1","snapshotId":"必须当前版本","grain":"day/hour","analysis":"仅FC27 fc27-categories/fc27-products"}`；响应：status/query/baseSnapshotId/rangeId/generatedAt/profile/consistentPeriod/resultSha256。分页/批量：202 pending/429 busy；单worker最多4 pending，每60s最多6启动；cache按query/baseSnapshotId确定hash。

- **ORDER-GOLD-EDIT**：query `ids=<价行ID>`，工单指明`data_type=costprice`；实际form数值字段未知，由后台确认。D4 gid456/Aion2 gid826每单一游戏；同步getweb1/selected_web=b2c/server_id该游戏，禁止allserver。响应、批量上限、回读及SLA正式待确认。

## 附录B：当前游戏映射与字段补充

这是当前代码映射，状态枚举与全站空值请后台正式确认，不直接当两个系统的同一ID。

| 看板key | 范围/名称 | Order gid | Admin game | 当前Order/Admin订单状态 |
| --- | --- | --- | --- | --- |
| MMOEXP | 所有网站合计 | 0 | 空：所有网站 | 空 / 空 |
| POE2 | Path Of Exile 2 | 552 | 552 | 3 / 101 |
| D4 | Diablo 4 | 456 | 456 | 3 / 101 |
| AION2 | Aion 2 | 826 | 891 | 3 / 101 |
| FC27 | FC27 | 1322 | 1327 | 空 / 空 |
| NBA2K27 | NBA2K27 | 1306 | 1329 | 空 / 空 |
| NFL27 | Madden NFL27 | 1258 | 1309 | 空 / 空 |
| MLB26 | MLB26 | 922 | 927 | 空 / 空 |
| CFB27 | CFB27 | 1256 | 1307 | 空 / 空 |
| FC26 | FC26 | 824 | 833 | 空 / 空 |

Aion2是Order826/Admin891，不替代Aion167或Classic512。FC商品身份还包含mid/cid/aid/site_id，平台与目录不应共用数字空间：Order价表PS21942/XBOX21944/PC21946；Admin Coins mid41217957/cid9623，PS aid21587、XBOX21585、PC21589，site0或266。正式映射及写白名单请单独核准。

其它已定位指标字段如下。Order重叠字段优先，Admin订单/金额仅作为对照或Admin自身比例分母；缺失保持null/未提供。percent要明确是百分数还是比例，不能猜单位。

| 标准字段 | 来源 | 原字段/标签 | 单位与说明 |
| --- | --- | --- | --- |
| orders | Order | 订单数量 | orders；primary |
| revenueUsd | Order | 订单金额 | USD；primary |
| averageOrderUsd | Order | 单均价 | USD；primary-if-present |
| profitMarginPct | Order | 利润率 | percent；原生准确区间值；利润率不日求和、不平均，不推算利润金额 |
| fulfillmentRatePct | Order | 发货完成率 | percent；primary-if-present |
| minOrderAmountUsd | Order | 最小订单金额 | USD；primary-if-present |
| maxOrderAmountUsd | Order | 最大订单金额 | USD；primary-if-present |
| receiptsCny | Order | 收款总额 | CNY；primary-if-present |
| goodsPaymentCny | Order | 货款总额 | CNY；primary-if-present |
| orders | Admin | total | orders；补源订单统计原值 |
| revenueUsd | Admin | amount | USD；补源订单金额 |
| payingCustomers | Admin | paid_payments | people；付款总人数，按补源原字段 |
| newCustomers | Admin | new_people | people；补源新客户人数 |
| newCustomerRevenueUsd | Admin | new_amount | USD；补源新客户总额 |
| repeatRatePct | Admin | repeat_rete | percent；后台复购率原值；上游未公开分子分母，不在本系统推算 |
| pureSalesUsd | Admin | pure_amount | USD；纯销售额；不是利润 |
| refundOrders | Admin | refund_order_num | orders；补源退款订单数 |
| refundAmountUsd | Admin | refund_amount | USD；补源退款金额 |
| deductedAmountUsd | Admin | deducted_amount | USD；补源扣除金额 |
| fulfillmentRatePct | Admin | shipped_rate | percent；补源发货完成率原值 |
| paymentSuccessRatePct | Admin | payment_rate | percent；补源支付成功率原值 |
| averageCustomerUsd | Admin | customer_price | USD；补源客单价原值 |
| minOrderAmountUsd | Admin | min_order_amount | USD；补源最小订单金额 |
| maxOrderAmountUsd | Admin | max_order_amount | USD；补源最大订单金额 |
| newCustomerSharePct | Admin | new_people / total * 100 | percent；同Admin日期/网站/游戏/状态；total=0不可计算；不除Order订单数 |
| profitUsd/costUsd | unknown | 尚无已核实字段 | USD；Admin补源未提供；Order收款CNY/货款CNY不直接当USD净/毛利润；须官方利润金额和成本/汇率定义 |

## 附录C：证据与交付边界

本文依据`interface-matrix.json`、`author-summary.md`、`source-evidence-index.json`整理。36项调用与项目差异对应37个文件的66段SHA/行号证据；本次是静态只读检查，不读取生产凭据、原始订单或客户数据，也没有向上游发起实际接口请求。源码中的历史实测说明与候选运行合同均保留时间边界。证据编号对应下表，完整SHA见同目录JSON，不把内部Windows绝对路径放进转发正文。

| 证据编号 | 源文件相对路径 | 行号 |
| --- | --- | --- |
| S001 | `fs_transaction_snapshot_20260930/primary_reader.py` | 20–56 |
| S002 | `fs_transaction_snapshot_20260930/primary_fields.py` | 1–38 |
| S003 | `fs_transaction_snapshot_20260930/supplement_reader.py` | 6–30 |
| S004 | `fs_transaction_snapshot_20260930/supplement_fields.py` | 1–73 |
| S005 | `fs_transaction_snapshot_20260930/collector.py` | 10–47 |
| S006 | `fs_transaction_snapshot_20260930/fc_product_contract.py` | 1–106 |
| S007 | `fs_transaction_snapshot_20260930/fc_product_reader.py` | 10–46 |
| S008 | `fc27_players_cloud/球员维护工具/admin_client.py` | 325–421 |
| S009 | `fc27_players_cloud/球员维护工具/admin_client.py` | 424–549 |
| S010 | `fc27_players_cloud/球员维护工具/admin_client.py` | 553–641 |
| S011 | `fc27_players_cloud/球员维护工具/admin_client.py` | 643–740 |
| S012 | `fc27_players_cloud/player_web/media_client.py` | 15–70 |
| S013 | `fc27_cloud_browser/collect_p2pah_cost.py` | 18–88 |
| S014 | `fc27_cloud_browser/collect_p2pah_cost.py` | 112–179 |
| S015 | `fc27_cloud_browser/repricing_dom.js` | 115–216 |
| S016 | `fc27_cloud_browser/preview_backend.py` | 15–84 |
| S017 | `fc27_cloud_browser/coin_all_sync_job.py` | 17–98 |
| S018 | `fc27_cloud_browser/clear_cache_after_write.py` | 20–65 |
| S019 | `fc27_cloud_browser/player_sync_job.py` | 99–169 |
| S020 | `fc27_cloud_browser/player_sync_job.py` | 522–573 |
| S021 | `opt/d4follow/core_p2pah.py` | 17–32 |
| S022 | `opt/d4follow/core_p2pah.py` | 329–389 |
| S023 | `opt/d4follow/core_p2pah.py` | 474–529 |
| S024 | `opt/d4follow/core_p2pah.py` | 535–590 |
| S025 | `opt/nba-reprice/backend/p2pah_api.py` | 10–33 |
| S026 | `opt/nba-reprice/backend/p2pah_api.py` | 132–214 |
| S027 | `opt/nba-reprice/backend/server.js` | 226–335 |
| S028 | `opt/nba-reprice/backend/server.js` | 338–398 |
| S029 | `opt/nba-reprice/backend/server.js` | 52–57 |
| S030 | `opt/mlb-online/mlb_server.py` | 3–28 |
| S031 | `fs_transaction_snapshot_20260930/atomic_snapshot.py` | 85–132 |
| S032 | `mmoexp_google_data/weekly_report/range_parser_release_20261005/source/range_api.py` | 30–57 |
| S033 | `mmoexp_google_data/weekly_report/range_parser_release_20261005/source/range_api.py` | 110–180 |
| S034 | `docs/integration/RUNTIME-CONTRACTS.md` | 3–23 |
| S035 | `opt/d4follow/core_gold.py` | 54–151 |
| S036 | `opt/d4follow/core_gold.py` | 317–369 |
| S037 | `opt/d4follow/core_gold.py` | 580–586 |
| S038 | `opt/d4follow/core_gold.py` | 695–770 |
| S039 | `opt/d4follow/core_gold.py` | 466–507 |
| S040 | `opt/d4follow/poe2_align.py` | 76–116 |
| S041 | `opt/d4follow/engine.py` | 168–194 |
| S042 | `opt/d4follow/engine.py` | 257–270 |
| S043 | `opt/d4follow/engine.py` | 48–96 |
| S044 | `opt/d4follow/engine.py` | 484–510 |
| S045 | `opt/d4follow/engine.py` | 895–918 |
| S046 | `opt/d4follow/core_front.py` | 348–397 |
| S047 | `opt/d4follow/core_p2pah.py` | 30–43 |
| S048 | `opt/d4follow/app.py` | 2399–2493 |
| S049 | `opt/d4follow/app.py` | 535–617 |
| S050 | `opt/d4follow/aion2_watch.py` | 1–22 |
| S051 | `opt/d4follow/core_dd373_cost.py` | 64–78 |
| S052 | `opt/d4follow/core_dd373_cost.py` | 270–280 |
| S053 | `opt/d4follow/core_dd373_cost.py` | 391–409 |
| S054 | `opt/d4follow/core_qd.py` | 153–192 |
| S055 | `opt/d4follow/tracker.py` | 169–194 |
| S056 | `opt/d4follow/core_g2g.py` | 17–48 |
| S057 | `opt/d4follow/core_eld.py` | 16–66 |
| S058 | `opt/d4follow/core_multi.py` | 18–42 |
| S059 | `opt/d4follow/srv_exec.py` | 20–60 |
| S060 | `opt/nba-reprice/backend/p2pah_api.py` | 57–61 |
| S061 | `opt/nba-reprice/backend/p2pah_api.py` | 181–214 |
| S062 | `opt/mlb-online/mlb_server.py` | 3–28 |
| S063 | `etc/systemd/system/d4follow-collect.timer` | 1–15 |
| S064 | `etc/systemd/system/aion2-watch.timer` | 1–14 |
| S065 | `opt/d4follow/engine.py` | 971–977 |
| S066 | `opt/d4follow/engine.py` | 1208–1216 |

目前未定位正式Aion/MLB专属商品创建接口、Order FC成本单元格保存XHR、实时FX接口；不编造端点。历史清缓存尝试只列证据，不作新授权。Google外部接口与Ponytail不在本后台需求实施范围；其它未知运行闭包不以本文件宣称通过。

生产认证只能按第五节受控交付。文档可用于开发确认和排期，不等于已创建身份、扩大权限、开通访问、提交源码或部署服务器。

修订记录：v1.1补FS全业务项目差异、ARPG Gold工单接口证据、外部成本/定价/利润区别及源码调度边界。v1.0同文件历史与原JSON已本地归档；Library使用同一文件身份保留版本历史。
