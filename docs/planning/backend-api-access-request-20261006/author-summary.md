> **2026-10-06当前合同（优先于本文历史段落）：** 首批干净源码已入私库 main bc3b29531cec2fab3fc090385f3d7d126eb9ada7。本批只增加文档与已独立复核 NBA receipts 候选；未提交、推送或部署。FC使用既有全局登录与角色，旧FC-only独立资格/fallback已被最新用户决定退役；当前已观察全局门户策略4管理员为wulv/chenchao/DY/fstech，来源为统一auth独立审阅及policy SHA b02e38348212c82879859cfd5db3c13c1e7506c33515c9e018b6290616f62017，不是本次新增账号。仓库旧C3政策/部分模块仍有三管理员代码，未随本批改动，禁止部署它覆盖四管理员现场。NBA api_security.js仍保留原三管理员模块守卫，其真实代理/角色适配未验，不因此擅授fstech NBA写权限。D4/PoE2/Aion2归陈超；球类归吴律；共享入口吴律主导陈超协作；其它owner待定。NBA R3-01/R3-02只在指定候选/合成证据层关闭，真实运行未验，releaseReady=false。D4/UI/auth源码均不在本批。文中旧权限、未push、FC专用桥与readiness状态是历史依据，不能作为当前发布指令。自助注册默认介绍/申请的业务方向已批准，实际入口/审批未实现。

# v1.1增量说明：FS全业务

正式转发文档已补D4/PoE2/Aion2、NBA/MLB和其它现有球类的通用接口+项目差异；新增ORDER-GOLD-EDIT仅工单说明证据，不称实际executor已验。修正旧“仅Order genre1成本”泛化：genre1限实际Order订单成本，千岛/DD373/定价costprice另列；FC K/赠送/利润规则不得跨项目。PoE2专用align已有源码，完整映射与部署/成本仍待大超确认。Aion多模式及旧注释冲突不选择策略；所有调度只列源码/归档声明，不声称live频率。以正式v1.1为准。

# 给接口需求文档作者的已核实摘要

本资料是脱敏、只读代码提取，不是向后台申请成功或生产验收。2026-10-06北京时间归档，依据冻结 candidate_revision3 的精确源文件；没有请求真实接口、读取会话/配置凭据或改生产。接口矩阵每项关联 source-evidence-index.json 的文件SHA及行号。候选运行映射和历史代码注释不能当当前线上事实。

## 需要开发支持的最小目标

经营数据稳定由云服务器读取，Order为主源、Admin补缺；每120分钟统一版本快照、前端60秒检查版本。所有网站总览与ARPG/球类/FC自身筛选并存。准确日期范围直接取原生汇总，付款人数和比例不叠加每日值；跨源保留各自读取时点，不能宣称两个后台事务一致。

Order四核心：订单数量、订单金额、单均价、利润率。其余两边都有也优先Order。Admin缺字段补充：paid_payments付款人数、new_people新客、new_amount新客金额、repeat_rete复购率等。新客占比固定Admin new_people/Admin total×100，零分母不可计算，不除Order订单数。Admin amount不是new_amount；pure_amount不是利润。Order利润率原值有百分号，但毛/净、成本/汇率公式未公开，不能据此杜撰利润金额。

## 本轮确切定位的上游入口

Order主源目前GET /stats/admin_order/index.html，读取HTML卡片/图表，而不是公开JSON。请求status/gid/tid/start_paytime/end_paytime；FC分类reader还有aid=0。请开发给等价稳定JSON接口，不能由作者杜撰URL。

Admin补源路径 /admin/order.Order/orderStaticsDetailByEs，由SessionManager data调用推断POST；受控SessionManager实现不在冻结包，所以正式method/编码仍需开发确认。参数包含pay_status=1、order_status、game、site、date、country_code/client/pay_type/time_unit/cid/discount_code/product_type。网站范围空值、日期边界及状态字典需要官方说明。

FC商品排行GET /admin/stats.productSalesByEs/index，gid1327、paytime RANGE、page/limit/order，列表pid/sale_total/order_count/paytime/goods.id/cid。sale_total是原生销售量，未证实USD或金币单位；order_count是商品分组次数。分类树GET /admin/goods.GoodsCategory/categorySelect?gid=1327，Players9627/Packs9629/SBC9625通过祖先树分类，禁止用代表行标题或平台猜分类。当前分页同值顺序不稳定，客户端读完整批次并核total；需服务端稳定cursor/一致性批次。

Order订单发货采购成本GET /order/admin_delivery/index.html：FC gid1322/cid1/genre1，明确只订单发货，排除采购打款、销售补发/赠送；分PS/XBOX/PC读取最新有效记录。NBA现源用gid1306/cid1/genre0，只有一页和宿主本地时间；这是待明确差异，不能当genre1已统一，文档请求官方合同但不修改运行。

Order FC价表GET /game/admin_game_price/index.html?gid=1322。同步表单 /game/admin_game_price/saveprice.html 使用GET却有写副作用，必须按敏感写处理。成本单元格保存XHR没有在本輪源代码定位，不猜URL。D4默认列表 /game/admin_game_price/index_item.html，默认写POST /game/admin_game_price/goodsEdit；受控配置可能覆盖默认路径，真实现用路径待官方核准。

Admin商品/模型/标签/导入/图片/缓存路径均逐项列矩阵。GET和POST同名edit必须分开授权；Goods库存、Coins价格、模型上下架/tid/icon分别最小字段scope；recalcFc27Price必须明确模型IDs，源码存在id=[]类目级历史函数不意味着授全类目。图片上传独立 https://b2c-api.p2pah.cn/upload/file；需要官方有限上传授权，不能把公开signer素材写进需求或当安全长效身份。

## 鉴权合同：明确长期运行，不索取永久Cookie

Order目前人类验证码+Cookie会话，Admin目前batoken；Players有POST /api/common/refreshToken原语，但本轮未确认长期无人值守可用。Players POST /admin/index/login与NBA POST /admin/login响应结构不同，要求开发给权威统一版本，不混写。

请求官方机器主体、最小读scope与写scope分离、短期access token、安全可轮换且可撤销的续期。OAuth client_credentials/批准的rotating refresh/短时服务签名只是由开发选择的候选，未知真实token URL/scope名称不编造。不要求永久Cookie、不共用root/admin、不在聊天收集密码、不新增账号/token/安全设置。身份执行者与人类批准者分开审计；认证刷新不能盲重放写。

## 指标、维度与字典

机器矩阵保留已确认全部原始字段和单位，以及10个profile的Order/Admin分系统ID和状态。MMOEXP旧key实际表示所有网站合计，不是site266。FC Order1322/Admin1327，Aion2 Order826/Admin891；Aion167/Classic512不得替代。Order tid1/2/4与Admin目录根1/0/2不同。

Order来源图表可取金额、订单状态/产品类型原生series。Admin site_rank是网站来源，不能写成已支持广告UTM渠道；country_rank与chart_pay_device可用，设备只有订单数；chart_pay_style有单数/金额。coupon输出未提供，尽管请求discount_code存在；逐渠道profit和地理利润没有证据。需要开发明确真实业务/获客channel字段而非编造。

汇率当前仅Order定价表6.65守卫和NBA RATE默认6.65，未确认实时FX API。要给币对方向、来源/有效时间、历史结算vs定价汇率、费用/舍入；不能用常数当实时市场汇率，也不能把CNY收款货款差直接标USD利润。

## 读写分权与最低安全验收

FC沿用既有全局登录与角色，已获批准普通同事可读全部FC销售/成本/利润/排行，匿名拒绝；旧FC独立资格/fallback已退役，既有全局合法范围按中央策略，真实角色验收另列。改价/上架/权限管理仍admin，并受具体操作批准与范围守卫限制。请求上游服务身份不等于本站新增角色。

控写最小合同：无副作用preview、指定ID和字段、before/version CAS、requestId+payloadHash、持久pending/confirmed/partial/unknown回执、只读状态查、独立后台GET回读和公共价格/缓存传播核验。HTTP成功不是业务生效；未知结果不能换新ID或自动重传。历史GET副作用要让后台改为明确受控写协议。

开发还需提供配额/Retry-After/超时/错误码、稳定分页total/cursor、scope字典、历史与迟到修正、TLS/云端出口白名单、维护窗口、无私密payload审计、sandbox和可选签名callback/告警。完整清单R01–R13在机器矩阵中。TLS不应沿用历史D4 CacheRefresher关闭验证做法。

## 排期与未定位能力

P0：主补源精准只读、官方机器鉴权、稳定分页/时间/字典、FC正式读写和既有写操作安全基础。D4列表/有界改价正式合同同列；Aion专属商品写未定位。MLB候选仅任务队列/Excel服务，缺完整agent/后台创建闭包，商品上新能力应请求开发定义，不虚构商品创建API。

NBA近期以稳定能简单用为主；有限自动策略架构后置。不能绕过已发现的写安全门槛，但NBA整模块不能拖住其它已验证模块的入库/发布评估。原运行不停止、不被候选替换。Google营销自己GA4/GSC/Ads来源，消费统一经营事实，不是Order主源；其09点/300秒不变。本轮不动Ponytail、Gallery/Madden不完整闭包、任何价格/调度。

Owners已明确：吴律球类FC/NBA/MLB；陈超D4/PoE2/Aion2；共享登录首页导航吴律主导，陈超可协作设计。经营供数/Google/其它owner留空，不从仓库write权限反推模块owner。

## 给后续作者的交付顺序

先写“希望后台交付什么/最小权限”，再附真实已定位接口与待确认字段表，随后鉴权生命周期、读写合同、sandbox验收、排期。区分现有调用证据、请求的未来合同与未知事项。正式全文可根据本矩阵撰写；不粘Cookie/响应业务数字/公共signer素材。不把需求文档当上线授权。

私库首次干净源码上传已条件批准，但本轮没有commit/push。主协调先审准入白名单/扫描/最新远端/既有安全认证/职责；另外准备非技术owner流程和双方AI模板，不能把冻结rev3或原工作树整目录init/push。生产仍独立人确认、限定模块发布与读回回滚。
