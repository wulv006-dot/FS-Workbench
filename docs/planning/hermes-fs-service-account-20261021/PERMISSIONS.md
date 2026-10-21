# Hermes / FS 全新专用账号权限开通单

日期：2026-10-21。对象：技术负责人。**从一个全新、零权限账号起步**；账号名/UID由技术创建后回填，本文不默认继承wulv、吴律浏览器、服务器旧会话或任何旧角色权限。用户要求以覆盖完整功能为先，不能沿用早期“最小只读/暂不申请”清单缩减本次申请。

建议提供一个统一业务身份，在 **Admin、Order、FS分别建号/绑定角色**。这三个系统、媒体上传、文件下载、Google和模型代理通常不是同一权限库；同名或一个系统的“管理员”不能证明其它系统已授权。Admin与Order申请覆盖现有工具所需的完整业务管理权限，包含读、导出、商品/模型/库存/价格写入及相关任务和回读；FS授现有业务管理员角色并补齐各模块允许名单。后台具体权限节点、ID、角色ID与数据范围由技术按当前ACL逐行回填。

**本次交付是权限需求与开通验收单，尚未创建账号或授予权限。** 账号具备写权限后，实际业务仍走现有执行器、锁/CAS、利润底线、UNKNOWN对账和原批准范围；不因本清单打开自动策略、生产写价、上品或调度开关。先补现有名单即可，不另建权限框架，不移除旧合法账号，也不改写旧任务归属。

## 给技术负责人的执行要点

1. 创建专用账号，记录各系统不可变UID、角色ID和全部游戏/站点/平台范围；不要复制人的token/cookie。账号应能读全所需历史、跨操作员数据及全状态，不仅是“本人创建”。
2. 每个功能同时开通**页面菜单、后端接口/动作、数据行范围、字段、导出/上传、辅助字典及异步任务/文件/写后回读**。有菜单、HTTP 200或空list不是权限通过。
3. 按接口真实语义开权限：POST也可能只读统计，GET也可能saveprice写入或生成导出。读写不能只按HTTP方法判断。
4. 在原FS管理员/项目grant及模块允许名单内加入新账号，特别是策略/学习的wulv限定、报告/任务owner、查询profile和各执行器身份绑定。后台权限和应用名单均须通过。禁止用前端伪造X-Auth-User解决。
5. 用新账号建立新的合法共享会话，沿当前唯一Admin/Order会话入口分发；旧Sales/SBC/Players等独立登录退役状态保持。接口调用与执行器审计能识别新业务身份；若后端保留另一受控writer身份，须记录委派关系，不假称使用新账号写入。
6. 逐条回填下面矩阵的ACL节点/ID、角色、账号UID、数据范围、接口样例、原请求ID和结果。缺路径的业务需求仍须开通并回填，不因本单无法从客户端获知ACL ID而省略。

## 一、覆盖范围与必须同时申请的层

| 层 | 开通内容 | 验收关键点 |
|---|---|---|
| 网络与会话 | 正式服务出口IP、Admin/Order/API/媒体/下载域、验证码/登录/刷新/身份、共享会话消费者 | 新身份真实登录、过期可控恢复、无独立登录死循环 |
| 业务后台 | 全部现有经营/订单/履约/会员/营销/商品业务能力；读写和导出/上传都列明 | 页面及真实后端动作、字段和分页均通过 |
| 数据范围 | 全部现有游戏、主站+卫星站、区服/平台、历史/全状态、跨操作员/供应商/推广人 | 能用条件查询；MMOEXP分析仍显式限MMOEXP，不能用推广“分销”标签排站点 |
| FS应用 | 全看板/工具入口、原API、管理员与项目grant、owner/允许名单 | 新用户直接调用不能因旧wulv名单或profile授权缺失被拒 |
| Hermes | 任务/连续会话、模型代理、工具目录/schema/代理允许名单、研究/模拟、学习及报告管理 | 新任务实际工具调用和模型回执；后台有权限不等于注册了新工具 |
| 执行与结果 | 原writer/导入器、任务/进度/失败、缓存、前台回读、审计、回退机制 | 有真实成功结果才验收；不能以队列accepted或合并当完成 |
| 外部资源 | Google、行情/资讯/汇率、球员库、通知、文件和知识归档等实际依赖 | 另列资源ID/角色；P2PAH账号不会自动取得这些权限 |

## 二、逐项功能开通矩阵

下表每项均为本次申请覆盖，**新账号全部未验**。读写能力不足仍会拒绝。详细机器回填字段在[PERMISSION-MATRIX.json](PERMISSION-MATRIX.json)，可导入技术内部权限表；backend_acl_name / backend_acl_id / role_id / new_account_id / grant_status / acceptance_status / receipt / owner均待回填。

| ID | 系统 | 功能 | 必须开通的动作 | 数据/操作范围 | 权限性质 |
|---|---|---|---|---|---|
| A01 | 身份 | Admin专用账号 | 登录配置、验证码、登录、刷新、身份、退出、会话恢复 | Admin菜单/API/媒体域实际使用身份 | 认证 |
| A02 | 身份 | Order专用账号 | 登录、验证码、会话、身份、过期判定与恢复 | Order管理及统计模块 | 认证 |
| A03 | 身份 | FS专用账号 | 统一登录、页面和API身份、角色及项目授权 | 全部现有FS模块；新账号加入管理员/允许名单 | 认证/读/写 |
| A04 | 身份 | 服务端访问条件 | IP白名单、WAF/API网关、域名、HTTPS、跨域及机器会话策略 | 实际服务器出口、获准浏览器和各API/媒体/下载域 | 网络准入 |
| A05 | 身份 | 共享会话接入 | 将新账号绑定现有Admin/Order会话代理及合法消费者 | 沿当前统一会话入口；不恢复旧独立登录器 | 认证配置 |
| A06 | 身份 | 范围字典 | 游戏、站点、卫星站、区服、平台、品类、商品及状态字典 | 所有现有业务游戏/站点/平台；不能只开FC或只开自己创建的数据 | 读 |
| A07 | 身份 | 完整数据权限 | 跨操作员/推广人/供应商、全状态、历史及分页、字段、导出权限 | 不使用“仅本人/本组/新建后数据”默认范围；按任务筛选MMOEXP | 读/导出 |
| A08 | 身份 | 新身份审计 | 记录账号ID、实际操作者、任务、原请求、变更前后和结果 | Admin/Order/FS/执行器审计可关联；保留旧任务原归属 | 读/审计 |
| D01 | Admin | 经营原生统计 | 初始化字典、ES聚合、时间曲线、游戏/站点/品类/国家/支付/来源、新老客、退款/CB/追回 | 全部现有经营范围，含准确区间与历史 | 读 |
| D02 | Admin | 旧统计兼容 | 普通订单统计初始化及聚合操作节点 | 仍被工具依赖或有独有数据的旧接口；退役须给替代映射 | 读 |
| D03 | Admin | 订单列表及详情 | 单号、客户邮箱、原状态、付款/订单时间、商品、数量、币种、实际优惠、来源、推广人、支付状态 | 全状态及分页；客户邮箱与支付邮箱分别授权 | 读 |
| D04 | Admin | ES订单下载全链 | 创建导出、取原任务、查询状态、列文件、下载全部分片、失败信息、重用归档 | ES销售订单下载及ES下载订单数据；历史日期、全原状态 | 导出生成/读/下载 |
| D05 | Admin | 指定订单日志 | 精确单号、操作人、时间/状态筛选、全分页、完整备注及字典 | ES订单日志与仍有独有内容的旧日志；按需脱敏 | 读 |
| D06 | Admin | 商品销售分析 | 销量排行榜、产品订单、国家/游戏详情抽屉、全部页与总数 | 每个游戏/模型/产品/平台/主站卫星站 | 读 |
| D07 | Admin | 产品身份与选择器 | 游戏→类目→模型→产品、平台/区服/站点、标签、附件、分页及详情 | 全现有业务；允许查询所有相关产品而非只读本人产品 | 读 |
| D08 | Admin | 会员及游客追踪 | 会员列表/详情/状态、首购/历史订单关联、新老客原标记、冻结/可用状态只读字段 | UID与客户邮箱；UID=0游客仍可按订单邮箱追踪 | 读 |
| D09 | Admin | 会员统计及复购 | 会员统计初始化、summary、按站点/游戏/日期统计、复购关联明细 | 历史及全部分页；明确首购与成熟观察窗 | 读 |
| D10 | Admin | 会员/订单身份导出 | 追踪所需邮箱等指定字段导出、文件生成与下载 | 限受控内部取数进程；不能把密码/密码哈希等混入模型 | 导出 |
| D11 | Admin | 折扣码汇总与筛选 | 码、推广人UID、MMOEXP站点、应用游戏、有效起止、统计窗口、状态、Total Used/Sales/Sum | 完整搜索、分页及统计辅助操作节点一并授权 | 读 |
| D12 | Admin | 折扣码配置 | 新增、编辑、有效期、游戏/站点限制、状态开关及详情回读 | 现有发码/改码功能的全部动作；使用仍经原批准链 | 写/回读 |
| D13 | Admin | 优惠券模板/会员券 | 模板、发放批次、会员券对象、有效期/状态及适用范围 | 列表、详情、字典及关联订单 | 读 |
| D14 | Admin | 核销与复购追踪 | 核销列表、90天复购订单、原订单金额/优惠、状态、导出及分页 | 核销ID/模板ID/会员券ID/批次号分别保留 | 读/导出 |
| D15 | Admin | 优惠券发放与管理 | 创建/编辑券、定向发放、批次及发放结果、停用/撤回/作废等现有动作 | 精确动作及可撤销能力由技术映射；不得凭“券菜单”推定已开全部按钮 | 写/任务查询/回读 |
| D16 | Admin | 推广归因及佣金 | 推广人列表/详情、月份统计、游戏费率、关联订单、推广链接/渠道与统计导出 | 推广人/站点/游戏全范围；推广分类不代替站点 | 读/导出 |
| D17 | Admin | 效率/履约/异常 | 订单处理效率、客服、发货/问题/退款/CB/消损/追回状态与明细 | 当前使用及历史曾被拒的统计节点均纳申请 | 读 |
| D18 | Admin | 商品/模型创建与导入 | 模型/产品新增、批量表导入、服务器接收文件、导入任务ID与进度 | FC Players、MLB及全部现有自动上品消费者；不能只开上传而缺导入执行 | 写/上传/异步查询 |
| D19 | Admin | 模型维护 | 模型详情、标题/规格/描述、状态/上下架、标签/推荐、平台/区服/站点关系、图片绑定 | 现有edit/singleEdit等实际字段级限制也需开通 | 写/回读 |
| D20 | Admin | 产品维护及库存 | 产品详情、创建/编辑、实际库存/售卖状态、平台和站点产品映射 | 模型和产品是不同ACL；单条与批量操作分别授权 | 写/回读 |
| D21 | Admin | 商品改价及重算 | 单品售价/原价/折扣价编辑、批量编辑、FC类别/模型重算、结果查询 | FC Players/Packs/SBC/Bundles/Gallery等实际调用链；保留原身份/配置护栏 | 写/回读 |
| D22 | Admin/媒体 | 图片及附件 | 上传签名/初始化、文件上传、附件ID/详情、模型/产品绑定及最终图片读取 | Admin API与实际媒体上传域可能分开认证/IP许可 | 上传/写/读 |
| D23 | Admin | 缓存及前台生效 | 原缓存清理操作、站点/产品范围、任务状态、实际商品/金币公开入口回读 | 没有清缓存/公开回读，写入成功也不能验收最终售价 | 写/读 |
| D24 | Admin | 内容/活动现有能力 | 新闻创建/编辑、促销产品、秒杀/活动配置、优惠创建、发布状态与回读 | 当前FS实际连接的内容/活动模块；未知写动作由技术逐项映射 | 读/写/回读 |
| O01 | Order | 经营全盘与分类 | 订单统计、游戏发货、供应商发货、状态及品类统计 | 全游戏/站点含G2G/ELD原全局范围；按任务选范围 | 读 |
| O02 | Order | 发货统计/参考利润 | 销售总额、采购总额、利润率及历史准确区间 | Admin缺项补源；不把参考率叫财务净利 | 读 |
| O03 | Order | 订单列表/详情/日志 | 游戏/区服/类型/标题/单号/客户邮箱/原状态与日期筛选、完整日志 | 关键字=客户邮箱/角色名；问题/取消/退款/CB均可查 | 读 |
| O04 | Order | 单笔交货成本 | 交货记录列表/详情、订单号、供应商、数量K、成本CNY、类型、时间、利润率及分页 | 最新有效订单发货成交成本与历史成本分别读取 | 读 |
| O05 | Order | 采购汇总/供应商 | 交货记录统计、供应商分平台数量/总价/最新单价、库存记录读取 | 关键字=供应商；供应商主数据和成本/库存读权限 | 读 |
| O06 | Order | 损失与客服统计 | CB/退款/问题、成本损失统计、客服处理统计、原生日志与字典 | 含历史被拒cb_order/customer_order_count两个节点 | 读 |
| O07 | Order | 金币价及参数读取 | 游戏/平台价格列表与详情、最新采购价、调价参数、利润/汇率参数、B2C价、赠送 | FC/NBA/MLB/Madden及现有支持游戏；每K/套餐明确 | 读 |
| O08 | Order | 金币写价 | 参数/单价编辑、批量或平台联动保存、必要同步、原写入状态、回读 | itemEdit/saveprice等GET也可能写入，按动作申请而非只按HTTP动词 | 写/回读 |
| O09 | Order | 道具/ARPG写价 | 物品/金币价格列表、goodsEdit等现有编辑、区服/规格/供应商成本参数 | D4/PoE2/Aion2及FS当前RPG支持范围 | 读/写/回读 |
| O10 | Order | 价格联动/缓存 | 金币到球员/类别的现有同步、缓存刷新及任务回执 | 保留球员wiki价格日常复验退役范围，不据开权限重开复验 | 写/任务查询 |
| O11 | Order | 订单/履约操作储备 | 若“全业务账号”包含后续人工处置：备注、改状态、派单、交货/补发/取消、退款、CB处理等实际动作 | 逐动作登记；目前研究工具没有这些写工具，现存写链以外仍待实现/批准 | 能力储备/写 |
| F01 | FS | 全工作台与查询 | 首页、全局经营、准确区间、结构、销售/利润、流量Google、周报、游戏监控与经营页 | 全部已登记游戏/看板/工具，含独立入口与API | 读 |
| F02 | FS | 数据查询工具 | profile/统计、产品订单、ES结构、优惠、渠道、新老客、队列、成本和能力补证 | 全profile grant及字段/日期/平台/站点范围；非默认仅FC27 | 读/按需取数 |
| F03 | FS | 订单及客户追踪 | 候选筛选、已核客户关联、添加/更新/停止、日更、历史与手动活跃池报告 | 新账号自身池及明确共享池；允许名单/管理员门按现规则补齐 | 读/应用写 |
| F04 | FS/Hermes | 研究与连续会话 | 创建/读取会话、提交/续轮、事件/进度、停止/引导、恢复及本人历史 | 真实新owner映射、任务账本及模型费用预留/归属 | 应用写/读 |
| F05 | FS/Hermes | 报告管理 | 生成日/周/月/区间/专题报告、读取HTML/附件/历史、导入/修订/反馈/共享 | 生成、归档、读取与管理操作分开；不自动继承旧账号私有报告 | 应用写/读 |
| F06 | FS/Hermes | 学习闭环 | 候选/复盘、模型复盘、人工review/publish/revoke、暂停/恢复、版本与使用记录 | 新账号加入原名单并授FS项目/scope；CAS/本人来源检查保持 | 应用写/审核/读 |
| F07 | FS/Hermes | 策略研究与模拟 | capabilities/propose/simulate/read_review/learning.propose、草案与模拟历史 | 当前wulv限定处增加新账号；策略开关/底线/生产写价保持原规则 | 应用写/只读模拟 |
| F08 | FS/Hermes | 所有现有研究工具 | 附录C逐个工具及兼容名的schema、代理允许名单、任务scope、数据源授权 | 新账号端到端调用；有底层接口权限仍要有工具权限 | 读/计算 |
| F09 | FS | FC金币改价台 | 原采集/手动刷新、报价/预览、批准后执行、策略配置与启停、任务/回执/前台回读 | 原锁/CAS/UNKNOWN/人工OFF/利润底线不变；账号有权不代表现在切开关 | 读/执行/配置 |
| F10 | FS | FC Players/Gallery | 搜索/采集、计划预览、手动上新、图片绑定、模型维护、批准写价、执行进度与读回 | 沿现有模块scope与名单；不恢复wiki例行复验 | 读/写/上传 |
| F11 | FS | FC Packs/SBC/Bundles | 产品映射、方案/定价、维护配置、现有写价动作、任务进度与回读 | Bundles一期/二期按当前实际部署区分；不能因历史文档只读漏申请现有写通道 | 读/写/配置 |
| F12 | FS | NBA/MLB/Madden | 价格/采集/配置、MLB表生成下载与后台导入、上新及各现有执行器 | 各模块单独API门、后台身份、进度/回执与结果回读 | 读/写/上传/下载 |
| F13 | FS | ARPG及其他现有工具 | D4/PoE2/Aion2、G2G等现有工作台的数据、报价、配置、写入与回读 | 申请业务能力覆盖；保持各模块owner和原执行范围，不实施新供应商系统 | 读/写/配置 |
| F14 | FS | 经营采集/刷新服务 | 业务准确区间、营销、销售、订单成本等刷新及原任务状态 | 既有服务消费者支持新账号；不因权限盘点启停timer或补跑 | 按需取数/读 |
| F15 | FS | 任务台/活动/运维视图 | 任务读写/自检、活动账本/操作史、健康/日志/审计/失败和UNKNOWN对账 | 现有管理员写动作与各模块scope；不能只开前端菜单 | 读/应用写 |
| F16 | FS | 发布回退能力 | 若该账号承担既有发布角色：受控发布入口、状态/备份/回退与审计读取 | 独立于业务后台ACL；沿原发布器/锁/CAS，不能借业务账号默认获得SSH root | 受控运维 |
| X01 | 外部 | Google数据 | GA4属性、GSC站点、Ads全部当前白名单账号及所需报告维度 | 另有OAuth/服务账号绑定；Admin/Order权限不能替代 | 读/现有导出 |
| X02 | 外部 | 模型代理与Hermes服务 | 现有模型别名/推理配置、工具调用、多轮、费用归属、用量与请求回执 | 沿现有额度/到额停止；新FS owner映射到既有代理授权 | 调用/读 |
| X03 | 外部 | 公开行情/资讯/汇率 | Lootbar/U4GM/IGGM/U7Buy、FUTBIN/现有球员库、ShowDD、官方新闻、公开售价、汇率 | 现有网络/浏览器/合法登录态及各实际来源；不是Admin角色可解决 | 读 |
| X04 | 外部 | 文件和媒体交付 | ES/商品表/图片/报告产物的上传下载、分片、保留/清理与读取 | 受控路径访问/文件ACL，不以“下载按钮可见”替代实际文件读取 | 读/上传/下载 |
| X05 | 外部 | 通知与知识归档 | 现有飞书/钉钉/邮件/Notion等已接入目标的实际应用权限 | 按现有报告投递/告警/归档功能列绑定；不自动赋全部通讯录/任意发送权限 | 现有投递/归档 |
| X06 | 外部 | 其他平台接入凭据 | G2G/ELD等当前实际接入源/写入通道的账户与API角色 | 后台“分销”推广标签不代替第三方平台登录授权；新迁移/供应商系统不在实施范围 | 按现有功能 |

## 三、已知后端接口逐动作清单

Admin JSON基址为 `https://admin-api.p2pah.cn`；页面为 `https://admin.p2pah.cn`。Order为 `https://order.p2pah.cn`。Media/Open接口的实际域/认证必须按当前客户端回填，不能把相同路径机械拼到Admin域。路径大小写、点号、尾缀保持原记录。**下表来自现有源码/合同，包含历史入口；本轮未逐项重新请求，更没有用新账号验收。** 技术先映射正式ACL；若已退役，填替代接口并覆盖同功能，不盲调旧登录或未知写入。

| ID | 系统 | 方法 | 精确已记录路径 | 权限语义 | 依据 |
|---|---|---|---|---|---|
| ORDER-STATS | Order | GET | `/stats/admin_order/index.html` | read | S1 |
| ADMIN-ORDER-SUPPLEMENT | Admin | POST | `/admin/order.Order/orderStaticsDetailByEs` | read | S1 |
| ADMIN-PRODUCT-RANK | Admin | GET | `/admin/stats.productSalesByEs/index` | read | S1 |
| ADMIN-CATEGORY | Admin | GET | `/admin/goods.GoodsCategory/categorySelect` | read | S1 |
| ORDER-COST-FC | Order | GET | `/order/admin_delivery/index.html` | read | S1 |
| ORDER-PRICE-FC | Order | GET | `/game/admin_game_price/index.html` | read | S1 |
| ORDER-PRICE-SYNC-FC | Order | GET | `/game/admin_game_price/saveprice.html` | write | S1 |
| ORDER-D4-LIST | Order | GET | `/game/admin_game_price/index_item.html` | read | S1 |
| ORDER-D4-EDIT | Order | POST | `/game/admin_game_price/goodsEdit` | write | S1 |
| ORDER-LOGIN | Order | POST | `/admin/public/dologin.html` | authentication | S1 |
| ORDER-CAPTCHA | Order | GET | `/new_captcha.html` | authentication | S1 |
| ADMIN-LOGIN-CONFIG | Admin | GET | `/admin/index/login` | authentication | S1 |
| ADMIN-LOGIN-PLAYERS | Admin | POST | `/admin/index/login` | authentication | S1 |
| ADMIN-LOGIN-NBA | Admin | POST | `/admin/login` | authentication | S1 |
| ADMIN-CAPTCHA | Admin | GET | `/api/common/captcha` | authentication | S1 |
| ADMIN-REFRESH | Admin | POST | `/api/common/refreshToken` | authentication | S1 |
| ADMIN-IDENTITY | Admin | GET | `/admin/index/index` | read | S1 |
| ADMIN-MODELS | Admin | GET | `/admin/goods.GoodsMould/index` | read | S1 |
| ADMIN-MODEL-DETAIL | Admin | GET | `/admin/goods.GoodsMould/edit` | read | S1 |
| ADMIN-TAGS | Admin | GET | `/admin/goods.GoodsTag/tagSelect` | read | S1 |
| ADMIN-GOODS | Admin | GET | `/admin/goods.Goods/index` | read | S1 |
| ADMIN-GOODS-DETAIL | Admin | GET | `/admin/goods.Goods/edit` | read | S1 |
| ADMIN-GOODS-EDIT | Admin | POST | `/admin/goods.Goods/edit` | write | S1 |
| ADMIN-MODEL-EDIT | Admin | POST | `/admin/goods.GoodsMould/edit` | write | S1 |
| ADMIN-IMPORT | Admin | POST | `/admin/goods.GoodsMould/importPlayers` | write | S1 |
| ADMIN-IMPORT-PROGRESS | Admin | GET | `/admin/goods.GoodsMould/importPlayersProgress` | read | S1 |
| ADMIN-SINGLE-EDIT | Admin | POST | `/admin/goods.GoodsMould/singleEdit` | write | S1 |
| ADMIN-RECALC | Admin | POST | `/admin/goods.GoodsMould/recalcFc27Price` | write | S1 |
| MEDIA-UPLOAD | Media | POST | `/upload/file` | write | S1 |
| ADMIN-CACHE-CLEAR | Admin | POST | `/admin/tools.Caches/clear` | write | S1 |
| ORDER-CACHE-LEGACY | Order | GET | `/admin/setting/clearcache.html` | write-or-side-effect-unknown | S1 |
| ORDER-CACHE-LEGACY | Order | POST | `/admin/setting/clearcache.html` | write-or-side-effect-unknown | S1 |
| ORDER-COST-NBA | Order | GET | `/order/admin_delivery/index.html` | read | S1 |
| ORDER-GOLD-EDIT | Order | POST | `/game/admin_game_price/itemEdit` | write | S1 |
| ADMIN-MEMBER-SUMMARY | Admin | POST | `/admin/stats.MemberStats/summary` | read | S1 |
| ADMIN-DISCOUNT-LIST | Admin | GET | `/admin/market.Discount/index` | read | S1 |
| ADMIN-COUPON-LIST | Admin | GET | `/admin/market.Coupon/index` | read | S1 |
| ADMIN-COUPON-LOG | Admin | GET | `/admin/user.MemberCouponLog/index` | read | S1 |
| ADMIN-SITE-LIST | Admin | GET | `/admin/site.Site/siteList` | read | S1 |
| ADMIN-ORDER-LIST | Admin | GET | `/admin/order.Order/index` | read | S1 |
| OPEN-createNews | Admin | POST | `/api/open.platform/createNews` | write | S1 |
| OPEN-createDiscount | Admin | POST | `/api/open.platform/createDiscount` | write | S1 |
| OPEN-createCoupon | Admin | POST | `/api/open.platform/createCoupon` | write | S1 |
| ADMIN-STATS-INIT | Admin | GET | `/admin/order.Order/getOrderStatics` | read | S2 |
| ADMIN-STATS-TIME | Admin | GET | `/admin/order.Order/getOrderTimeDuan` | read | S2 |
| ADMIN-OLD-STATS | Admin | POST | `/admin/order.Order/orderStaticsDetail` | read | S2 |
| ADMIN-EXPEND-DETAIL | Admin | GET | `/admin/order.Order/orderExpendDetail` | read | S2 |
| ADMIN-STATS-EXPORT | Admin | POST | `/admin/order.OrderExcel/xsDownload` | export-generation | S2 |
| ADMIN-STATS-LOG-EXPORT | Admin | POST | `/admin/order.OrderExcel/xsLogsDownload` | export-generation | S2 |
| ADMIN-EXPORT-CLEANUP | Admin | POST | `/admin/order.OrderExcel/delOrderEXport` | write-export-cleanup | S2 |
| ADMIN-MEMBER-LIST | Admin | GET | `/admin/user.Member/index` | read | S2 |
| ADMIN-MEMBER-EXPORT | Admin | GET | `/admin/user.Member/export` | export | S2 |
| ADMIN-MEMBER-INDEX | Admin | GET | `/admin/stats.MemberStats/index` | read | S2 |
| ADMIN-ES-LOG | Admin | GET | `/admin/order.OrderEs/getOrderLogsindex` | read | S2 |
| ADMIN-ES-REFUND-NUM | Admin | GET | `/admin/order.OrderEs/getRefundNum` | read | S2 |
| ADMIN-LEGACY-LOG | Admin | GET | `/admin/stats.OrderLog/index` | read | S2 |
| ADMIN-ES-EXPORT | Admin | 待技术确认原合同 | `/admin/order.OrderExcelByEs/downloadsMake` | export-generation | S5 |
| ADMIN-GAMES | Admin | GET | `/admin/site.Game/gameList` | read | S2 |
| ADMIN-COUPON-REPURCHASE | Admin | GET | `/admin/user.MemberCouponLog/repurchaseOrders` | read | S2 |
| ADMIN-COUPON-EXPORT | Admin | GET | `/admin/user.MemberCouponLog/export` | export | S2 |
| ADMIN-COUPON-EMAILS | Admin | GET | `/admin/user.MemberCouponLog/exportEmails` | export | S2 |
| ADMIN-AFFILIATES | Admin | GET | `/admin/market.Affiliate/index` | read | S2 |
| ADMIN-AFFILIATE-STATS | Admin | GET | `/admin/market.Affiliate/statindex` | read | S2 |
| ADMIN-AFFILIATE-RATES | Admin | GET | `/admin/market.Affiliate/gameRates` | read | S2 |
| ORDER-CB-STATS | Order | GET | `/stats/admin_order/cb_order.html` | read | S2 |
| ORDER-CUSTOMER-STATS | Order | GET | `/stats/admin_order/customer_order_count.html` | read | S2 |

`getOrderLogsindex`及`statindex`是既有公共脚本记录的直接拼接结果，不能擅自“修正”为带斜杠路径。当前浏览器核到ES日志UI `/admin/orderes/orderlog`、折扣码UI `/admin/market/discount`、ES下载UI `/admin/order/makeExcelByEs`；**UI路由不是JSON API路径**。技术须核当前部署是否仍使用表中同一接口，再开ACL。订单日志辅助计数与状态字典也要开。

### 必须补齐映射，不能漏开的依赖

| 系统 | 仍需技术填写的当前接口/ACL | 对应功能 |
|---|---|---|
| Admin | ES导出状态/任务列表/分片文件/签名下载域 | D04 |
| Admin | 折扣码Total Used/Sales/Sum相关辅助统计动作及完整搜索字段 | D11 |
| Admin | 会员详情/可用与冻结状态/首购历史 | D08 |
| Admin | 优惠券定向发放/批次/停用或撤回 | D15 |
| Admin | 商品/模型add、批量上下架/标签/库存/价格字段的正式ACL | D18-D21 |
| Admin/媒体 | 当前上传签名/凭证初始化/附件查询的实际域和动作 | D22 |
| Order | 订单列表/详情/完整日志及交货记录统计的当前实际URL | O03-O05 |
| Order | 发货统计/供应商统计及各只读详情的当前URL | O01-O02/O05 |
| FS | 各动态kind/新账号名单/项目grant/资源owner范围 | F01-F16 |
| 外部 | Google及其他平台的实际资源ID/角色与账号绑定 | X01-X06 |

会员列表可能附带密码/密码哈希等多余字段：后台可见不等于应传给Hermes。取数适配器只保留本功能需要的字段；模型使用脱敏订单/客户标识与必要原因，原始日志、邮箱和财务明细留受控服务。此字段处理不减少账号申请的业务权限。

## 四、Hermes工具与应用允许名单

以下名称由本轮 `/opt/fs-hermes-fc` 活动源码提取，包含现有工具和兼容别名；**不以源码出现就宣称每个别名已注册可调**。开通后，以新任务实际工具目录/schema、代理允许名单和来源权限联合验收。`fc.query_customer_tracking`等敏感查询还受现有管理员/任务owner门约束。下表是新账号的开通目标，不表示现在有新账号成功回执。

| 工具名 | 能力 | 新账号需核对 |
|---|---|---|
| `fc.calculate` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.check_report_html` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.compare_periods` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.get_breakdown` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.get_business_snapshot` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.get_data_catalog` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.get_metric_definitions` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.get_order_reference` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.get_problem_clues` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_action_history` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_business` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_capability` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_cohort_observation` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_customer_tracking` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_discount_analysis` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_es_order_structure` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_game_news` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_market_snapshot` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_marketing_snapshot` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_native_statistics` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_official_intelligence` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_product_orders` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_queue` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.query_reference` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.read_evidence` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.read_history` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fc.read_skill` | 读取/计算/验证 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fs.learning.propose` | 策略草案/模拟/学习候选 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fs.pricing.simulate_candidate` | 策略草案/模拟/学习候选 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fs.strategy.capabilities` | 策略草案/模拟/学习候选 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fs.strategy.propose` | 策略草案/模拟/学习候选 | schema/代理/任务owner与scope/底层来源，均未验 |
| `fs.strategy.read_review` | 策略草案/模拟/学习候选 | schema/代理/任务owner与scope/底层来源，均未验 |

策略/模拟/学习现有`wulv`限定处，应按用户本次说明**把新账号加入原允许名单**，并保持旧账号和其它规则。普通L1发布/撤销、L2方法候选、显式模型复盘、学习暂停/恢复分别开通原管理员动作。旧报告/经验仍按原owner保留；共享或迁移访问另作明确资源授权，不改写历史账本。

本轮新补的折扣码筛选和ES日志入口是有效业务查证方法，**尚不是新注册的Hermes直连工具**。账号权限齐备后，如需Hermes直接调用，应在现有工具注册/schema/代理与取数适配中接线并测试；不能只授后台权限就宣称Hermes已可直接调用。

## 五、FS真实入口与执行器覆盖

本轮以`nginx -T`实际加载配置确认入口族，包括 `/dashboard/analytics/`、`/dashboard/marketing/`及周报、`/dashboard/data-tools/`、`/dashboard/fs-home/`、`/api/hermes/conversations`、`/api/fs/v1/profiles`与`/api/fs/v1/statistics`、`/sales/`、`/api/fc27/cloud/`、`/dashboard/fc27-quote-api/`、`/dashboard/fc27-activity-api/`、`/tools/fc27-players/`、`/tools/fc27-gallery/`、`/dashboard/fc27-bundles-api/`、`/dashboard/fc27-sbc/`、`/nba2k27/`、`/mlb/`、`/api/madden/cloud/`、`/d4/`、`/g2g/`、`/dashboard/tasks/`和受控`/deploy/`。具体路径清单存JSON；路径存在不代表相应上游健康或新账号可访问。

FS同源数据/管理复用原advisor入口与既有kind，包含ES/产品/优惠查询、cohort/客户追踪、报告、学习、策略等。这里不能仅给静态页面读权，必须覆盖其同源API、子路径、POST管理动作和后台任务资源。任务ID/owner授权由服务端确定，不让客户端任意填写身份。

功能级检查：Coins金币写价；Players新卡导入与模型图片；Gallery写价；Packs/SBC/捆绑包产品与价格；NBA金币/类别改价；MLB导入表生成、文件上传、后台模型/产品生成；Madden及RPG现有采集/写入。这些共享后台接口，但有各自scope、身份校验和应用名单，须逐模块跑通，不能只验FC27一个入口就盖全部。

## 六、新账号端到端验收流程

1. **身份与范围**：技术回填账号名、各系统UID/角色/ACL版本，使用新会话验证真实身份；全部profile/游戏/站点选择器可读。比对一个已知有数据的授权历史窗口，排除仅本人数据、字段裁剪或错误的空列表。HTTP200但业务code401/403/302仍失败。
2. **经营看板**：新账号读Admin原生聚合、Order参考统计、FS准确区间及流量数据；来源、时间、币种和范围正确。新权限不改变Admin优先/Order补缺，不用不同范围强行核平。
3. **折扣码链**：新账号在Admin限定MMOEXP、选码/推广人/游戏、分别设置有效期和统计窗，读Used/Sales/Sum；复用或显式生成同窗ES原任务，读取状态、全部文件并对单号/原状态；精确单号查询ES日志和Order详情。只开ES创建却不能查任务/下载文件，不通过。
4. **会员/追踪链**：按已核客户邮箱查原订单、会员/游客状态、首付款和完整历史；建立/停止一个明确的追踪对象、手动活跃池报告，并在新Hermes任务核实际工具证据。不能因UID=0或新账号看不到历史而判断无客户。
5. **改价链**：先只读成本、参数、当前前台与可比行情，生成原预览、确认新身份的writer授权与锁/CAS。实际写权限测试在技术批准的测试商品/隔离环境进行；若只能生产验证，先给确切目标与批准范围，再单次写、查原回执、缓存及前台读回。生产测试未做时填“写权限未实测”，不能冒称可用。未知结果只查原ID。
6. **上品/图片链**：测试模型/产品与图片→预览→实际上传→导入执行→原job进度→模型/站点产品列表/详情→图片及售卖状态回读。只成功写了Excel、上传文件或拿到job，不算商品已创建。测试对象清理由正常可恢复流程处理，不能删生产历史。
7. **Hermes链**：以新owner开真实任务，获取目录并实际调已授权工具、多轮模型、报告归档；实际知识版本正确。用一条测试经验完成原人工审核/发布/新任务使用/撤销，查版本和旧任务不变。学习/策略名单、项目grant、工具scope缺任一项均不通过。
8. **其它模块和外部源**：每个现有工作台至少一条真实读链；需要写的逐模块验原执行器。Google资源/模型代理/文件媒体/合法行情与通知归档按单独身份绑定核。保留失败和未测，不凭一个管理员角色名宣布全部通过。

**逐项回执格式**：清单ID｜新账号及UID｜系统/游戏/站点/资源｜角色/ACL节点及ID｜方法+路由/动作｜原请求/任务ID｜业务code与结果｜读取/执行时刻｜覆盖/分页/字段｜脱敏证据｜通过/失败/未测｜技术负责人。密码、token/cookie和验证码不写入该表。

## 七、当前结论、缺口与交付状态

- 功能需求、已知接口、应用名单依赖和新账号验收流程已整理；JSON每项保留未开通/未验标记。当前账号名/UID、各系统正式ACL节点ID/角色ID和资源范围仍待技术提供，不能从旧账号成功回执推定。
- 本轮只读盘点了活动源码工具名/路由及实际Nginx入口；读取现有模块合同；没有创建账号、改角色/名单、写价格、执行导入或启停自动化。新账号端到端读写全部未执行。
- 本单优先覆盖业务能力，不申请把业务身份变成能管理所有人的密码/权限、数据库root或任意SSH执行的身份；若技术让它兼任已有受控发布角色，按F16独立映射。业务功能所需字段/历史/读写/导出不会因此删减。
- 精确ACL名称、导出多阶段接口和少数模块当前端点只能由技术结合服务端路由/权限树确认。上述待映射项不是已完成；开通时请导出该角色的完整权限树/动作列表，与功能矩阵逐项交叉核漏。
- 当前活动服务的启动/健康问题与账号ACL分开；就算权限齐全，上游故障、数据定义或工具尚未注册也不会因此自动消失。新账号开通后再做真实验收，失败分网络/认证/ACL/数据范围/应用名单/注册/上游健康，不盲重试。

## 八、依据与版本

新确认业务规则优先于旧静态文档中的Order主源、只读申请限制及历史待批条目；旧文件仅作为当时接口合同证据，不恢复它们的过时限制。下面来源不含凭据或客户实例。

| 引用 | 来源 | 证据等级 |
|---|---|---|
| S1 | [docs/planning/admin-order-api-reuse-20261013/share/接口总表.md](../../../docs/planning/admin-order-api-reuse-20261013/share/接口总表.md) | 2026-10-13整理的源码/历史接口合同；本轮未逐接口实测 |
| S2 | [docs/planning/admin-order-capability-audit-20261014/DEEP-READ-CONTRACTS.md](../../../docs/planning/admin-order-capability-audit-20261014/DEEP-READ-CONTRACTS.md) | 既有静态合同及其标注的历史实测；非新账号实测 |
| S3 | [shared_backend_session/OCR-SESSION.md](../../../shared_backend_session/OCR-SESSION.md) | 当前8767 OCR登录与共享会话维护合同；新账号未验 |
| S4 | [docs/planning/fs-permissions-unification-20260930/role-contract-and-acceptance.md](../../../docs/planning/fs-permissions-unification-20260930/role-contract-and-acceptance.md) | 历史角色合同；实际当前名单须按活动策略核，不复制旧三管理员人数 |
| S5 | [docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md](../../../docs/planning/fs-business-baseline-20261021/BUSINESS-BASELINE.md) | 当前v3业务规则，源码SHA256 92058a31b3a30a6e0515df09379a2b882a663143b43833915bc3490a238686e2 |
| S6 | [docs/fc27-players/model-images-20261003/README.md](../../../docs/fc27-players/model-images-20261003/README.md) | 模块接口/执行合同；各记录按时点解释 |
| S7 | [docs/planning/hermes-v2-core-20261020/STRATEGY-DELIVERY.md](../../../docs/planning/hermes-v2-core-20261020/STRATEGY-DELIVERY.md) | 现有研究/学习合同及本轮活动源码盘点 |
| S8 | 2026-10-21本轮服务器只读盘点 | 32个活动源码文件路由/工具名及nginx -T已加载配置；未执行业务写入；不是接口或新账号权限实测 |
| S9 | [docs/planning/mmoexp-google-data-20260930/weekly-details-delivery.md](../../../docs/planning/mmoexp-google-data-20260930/weekly-details-delivery.md) | 现有Google账号/报告范围合同；外部授权另核 |

本版包含 **65项功能权限、66条已记录方法/路径、32个活动源码工具名称（含兼容别名）**；数量是本次盘点范围，不是已开通或已通过数量。当前知识发布版本PR269/26d2af588acd，权限清单本身不修改运行策略。
