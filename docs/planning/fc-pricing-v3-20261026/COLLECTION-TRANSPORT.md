# FC 采集第二阶段：受限 SSH 通道与真实影子

用户本轮“允许”后，已核最终 head/CI/可合并状态，将PR749合入main：`74f4ba938fbb2cb769408cac762ad5cf3461da68`。合并与产品上线分开记录。

本阶段以该main为基线，分支 `codex/fc-collection-transport-20261102`。沿用此前已读施工包、HOTFIX及FC合同，不改RPG，不复制业务身份，不改原价格规则或计划。

## 具体实施边界

- 复用已有187→183私网SSH方向和已有22端口；FC专用key和受限账号，禁止shell、PTY、端口/agent/X11转发。共享 `rpg183-link` 不重启或改参，不新增TCP隧道/安全组。
- 183专用低权限worker只接固定来源任务；代码root拥有，状态独立；通过本机Unix socket承接SSH受限转发的任务协议。专用服务限制0.25核/256MiB/64进程，拒绝RPG及后台身份目录。
- 187持有协调账本与FC专用SSH客户端身份；worker不拿协调DB、Admin/Order身份或原管理key。消息限长，方法白名单，服务端时间和认证node不取请求自报。
- 先补纯HTTP来源ArabUT：复用原普通交付、100000 coins、官方Console共享PS/Xbox、USD展示/SAR结算合同，不给PC复制价。先一轮影子、最多2个固定GET；不参与定价。403/challenge/401/429按原来源停发，不换IP冲撞。
- Lootbar复用187已验证reader/parser；先保持187现役链路，183浏览器与登录态独立准备。未知账号不在聊天索取，登录由用户在准备好的页面完成。

## 顺序和完成条件

- [x] 合并PR749并核合并SHA。
- [x] 补失败测试：消息上限、身份/方法边界、回执校验、有限请求完成释放、官方币种合同。
- [x] 实现最小stdio/Unix socket通道、SSH客户端、固定公共来源适配；183匹配Python兼容测试、完整受影响回归。
- [x] 核实际资源/端口/专用用户及目录冲突、私网方向；创建本阶段独立角色和访问材料，双端真实health验收。
- [ ] 一次2请求以内的真实影子，记录合法报价或确切失败。真实响应失败不当通过。
- [ ] 完成可关闭原入口接线；部署/消费前再列确切载荷和验证结果。未验来源保持原采集/缺价语义。

裁决：当前RPG隧道只转发看板和业务端口，不直接复用其Admin/Order接口作为FC API；复用已验证的SSH网络/运维能力，用独立受限SSH会话承载JSON任务/观察。这样无需重启或借用共享隧道身份。

普通隔离测试沿上一阶段183入口连续运行。新增实现仍需独立审查及当前head正式CI；代码、两机通道、真实影子、消费和自然轮分开验收。

## 当前可核证据（2026-11-02）

- Windows采集专项70项通过；完整FC回归585项通过，10项原有Windows平台跳过。
- 183既有固定Python3.9.18隔离测试入口68项通过，无跳过；网络关闭、低权限、只读挂载，0.25核/256MiB。
- 独立审查发现的旧boot待回执、无租约回放、时钟容差、无效/深层JSON、低权限代码目录与其他pending任务串单问题均先失败复现再修复。
- 安装脚本默认预览。当前尚未创建两机专用身份、账号或服务，真实源请求0次；原FC及RPG未部署变更。
- Linux测试包SHA256：`46932ee2534708da31e7de6459b9856d7231d65d3844fd955571efa3ce306b1c`。首次传错校验值被入口拒绝，随后使用实际校验值通过；拒绝运行未执行测试或访问来源。

## 现场安装与首轮失败（后续更新）

- PR750 head `8aab0d62c49e65614a1fff75cf352d8082b90875` 经独立审查、本地pr-fast及正式CI `41436014080` 通过后，合并为 `453c084a9217d9376782e7170f00749600077061`。
- 187控制代码 `/opt/fs-fc-control` 与专用访问引用已安装；新FC私钥仅留187。183新增 `/opt/fs-fc-collector`、独立state、低权限UID999和唯一新增service，实际0.25核/256MiB/64tasks限制及health通过。真实187→183受限SSH健康协议、时钟和版本通过，未改共享隧道及原业务服务。
- 首轮 `fc183-arab-shadow-20261102` 精确使用2次请求，返回 `adapter_contract_invalid`、0offers、`pricing_consumption=false`，不能称真实影子通过。未重采、未清账或重置预算。
- 只读187最近8份已有自然快照发现 `price_version` 是整数（最新2841），新adapter误限字符串。现役原函数没有此限制。新增失败复现后改为接受非负int64或原有长度上限字符串；布尔/浮点/无效类型仍拒绝，整数原类型参与证据hash。
- 修复后Windows完整586项通过（原10平台skip），183 Python3.9.18隔离69项通过无skip；独立补审未发现P0/P1/P2。修复仅离线通过时，不能说远端影子恢复。
- 初始安装脚本仅用于初次安装/同包对账；不同hash更新必须先核现役原字节、保留原code及访问配置并仅重启新增FC service。不得为方便删除setup回执或覆盖冲突继续安装。

## 一次追加复验（代码准备）

用户已明确允许修复后追加一轮，并补充“累计请求无需让我审批……别过度重试”。后续必要验证沿已有授权自主执行，有限预算、无新证据不重试、明确拒绝/限流不绕过；不把本次临时额度当生产永久额度。

- 本次仅追加固定`原ID-recheck`，单轮2请求、原账本累计最多4请求，不增加消费或定时器。要求首轮唯一已接受的parser失败回执、COMPLETED、一次attempt和两次permit；无原记录/非此失败/其他任务一律停止对账。
- 校验与策略generation2/max_requests4写入同一SQLite事务，原receipt、permit和blocked/cooldown保留；旧generation不能穿透。独立审查发现跨24小时窗口并发空档，已失败复现后改为同事务，并经补审通过。
- 76项采集专项通过；183固定Python3.9.18隔离74项通过、零skip。测试覆盖重复原ID、不刷新观察、跨窗口累计4次、第三ID拒绝、来源阻断保留、导出控制entry正确传递复验参数。
- 执行将使用已合并控制包在187 root私有暂存目录的一次性entry，复用现有access配置与同一collection-shadow账本；不更新183worker，不改持久服务、原业务入口或共享隧道。实际外站报价及原账本读回另记，当前不称影子恢复。

## 第二次失败与请求保真诊断

- PR752 head `c9ef59b99a1accf5b5231412418832b82d35371c`，正式PR fast `41440710899` success，合并`cad64bfbab6946a260eac30cd12a37ba94ae4227`。本地完整FC591项通过（原10平台skip）。
- 实际第二组仍`adapter_contract_invalid`，0offers、两请求，累计4，不消费。不能将整数兼容修复说成已恢复真实采集。
- 183实际安装manifest核验与187旧字段离线回放通过（2offers、0外站请求），排除仍运行旧整数限制。187最近已有自然快照停在11:09 UTC，不作当前站点正常证明。
- 已证请求差异：187现役warm Accept=`text/html`、quote Accept=`application/json`；新客户端原来混用`application/json,text/html`。现在严格复用原header；其是否导致现场差异仍待实测，不先宣布根因成立。
- 适配器新增白名单静态失败码，区分HTML、JSON、selection/amount/version/time，响应原文不入回执。401/403/challenge/429原分类与停止/冷却保持；control依赖仍通过函数内lazy import隔离。
- 手动诊断本次最多三组（共6请求），每组两请求/一次attempt；第三组必须逐一核验前两组原COMPLETED、唯一accepted generic parser失败与各两permit、固定ID链，同事务升代，不清账、不启用循环重采。78专项通过，独立补审无P0/P1/P2。真实第三组结果另记。

## 暖页响应实际差异与有限修复

- PR753 head `00145be6d1f5948bd7f742033edd4222049c2300` 正式CI `41442889526` success，合并`e03b136fb85e39b1de4e28476ed95ff88821b6c7`；完整FC593项通过（原10skip），183隔离76项通过无skip。两机限定角色更新预览、apply和manifest通过。
- 第三组实际只发暖页一次即`redirect_denied`，尚未发报价请求；累计5请求，0offers、不消费。原urllib opener会处理redirect，新客户端全拒绝，这一行为差异已证，不能把前两轮失败一概归为版本类型。
- 最小处理只针对ArabUT warm302/303：Location须HTTPS同hostname、root path、无userinfo/fragment，query无重复且键值都匹配已登记参数。只提取该响应的独立匿名选择cookie，warm体原本不使用；不请求Location目标，随后仍只访问固定quote API并核USD/SAR/100K/Console。其他跳转/来源不变，登录路径、外站、降级HTTP、额外token和不匹配币种均拒绝。
- 仅额外允许一个有新证据的暖页修复组：此前两组generic失败各2请求，第三组必须是唯一接受的redirect_denied且只用1请求。固定第四ID和一次attempt/2请求，总计最多7；第五组联网前拒绝。所有旧回执、permit、block/cooldown保留，未知请求占用待原超时及裕量结束，不退款或清状态。
- 80专项通过，正常/拒绝暖页、无跟跳请求、两次历史失败及第三次1请求保留、7请求终止、跨窗口重入均有回归。真实修复报价是否恢复须看后续现场读回。

## 已证语言入口与显式三请求组

- PR755最终对齐Hermes PR754后的head为`5aec7183e277ed3e12a452b7eabf54846841b42f`，正式CI`41447112867` success，合并`1247225eb2a051db427992a366fc2464ba7dbfb7`。初次因落后主线被405拒绝；批处理漏检后继续更新FC角色的顺序错误已明确报告并纠正，后续必须核`merged=true`才继续。
- 第四组仍仅暖页1次redirect_denied，累计6。未再盲猜，而是以独立`183-manual-diag`实例、同一协调DB预留第7次预算，183低权限0.25核/256MiB/64tasks/30s临时进程只warm一次采枚举元数据，不quote、不follow、不输出URL/cookie/响应体。HTTP前独立O_EXCL标记阻止重放，原4回执保留；收尾实验source off/gen6，不覆盖后续策略。
- 真实枚举为302/https/exact-host/default-port/language-path/query-match、无userinfo和fragment。language只可能已分类的/en、/en/、/ar、/ar/；这是语言跳转未登记的明确证据，不是403或账号失败。手工诊断不是正常worker报价成功。
- 固定语言模板由纯contracts常量统一，根暖页经同站/HTTPS/参数校验且提cookie后仅返回内部`WarmLanguageRedirect(template_id)`信号，原fetch不暗发第二请求。adapter最多接一次信号，再各自预算get(language)和get(quote)。语言响应仅接受root或同语言选择redirect并留cookie，不继续跟跳。
- `BudgetedTransport`对已完成且验证过的语言信号完成原permit后传播；预算不退款，后续GET重新reserve。回归确认root+language+quote恰3permit/3completion/2offers。未知/错误不释放占用；原拒绝与报价/币种/数量合同保持。
- 旧4模块Lootbar导出包新增独立子进程Worker导入检查，防止误引未导出的public_sources；红绿验证后常量落contracts，控制包仍无adapters依赖。81专项通过，183固定3.9.18隔离79项无skip通过，未执行额外外站请求。
- 下一次仅一个正常协议组，固定ID、单attempt、3请求预算、90s截止、原18s单GET硬界，所有已有7次和5份旧回执保留；同事务off/gen6→shadow/gen7与新job入队，总10硬界。preview先核持久诊断枚举，旧ID重入只读/补ACK，不另建job，不接生产消费。现场结果另记。

## 2026-11-02：真实影子通过与P3候选

- PR756合并 `17c00bf1ddbde93bcf21b5364ecde896880ec0bb`，正式CI41458772193通过。183普通worker于14:13:54.505789 UTC取得ArabUT PS/Xbox报价，固定三次GET，总专项累计10次；同job重读未新增请求，观察时间不变。6个原任务COMPLETED，失败及人工诊断回执hash保留，spool清空。保护的FC/RPG/共享隧道状态、PID及unit hash前后相同。
- P3候选新增 `fc_collection/client.py`，仅187控制角色导出；183仍不含客户端、协调器、业务源或凭据。`sources.py`两处ArabUT按原source_plan触发，已提供的原ArabUT结果优先、PC/其他来源范围不扩展，原local_collection钉住继续有效。
- `/var/lib/fc27-cloud/collection-access/routing.json` 缺省或 `remote_result_mode=off` 使用旧分支，不创建协调器、不执行SSH。`shadow`也使用旧输入；远端影子由已验证的独立限额驱动承担，不新增后台轮询器。模板为 `{"schema_version":1,"remote_result_mode":"off","assignment_generation":7}`，文件要求root所有、单硬链接、0600。
- 候选consume必须与同一原SQLite中的source mode/generation、adapter v2、origin及183首选节点一致。每原run钉住route/context，限定3次GET/1attempt，只领取本job；失败、403/429、未知请求不会转直采或换ID。丢ACK先对原spool；重读不刷新deadline/观察时间，不重新抓价。原报价下游缺价规则保留。
- v2携带且校验SAR原金额、priceVersion原类型、pricedAt；消费要求同一完整Console组。原v1影子可验签/补ACK，但不能作为完整v2生产报价；不改写原回执。
- 候选本机96项通过、完整FC611项通过（10个原Windows平台跳过）；183目标Python3.9.18无网络、0.25核/256MB容器94项通过，无跳过。证据在本地task目录routing-full-fc.log、routing-linux183.log；未新增外站请求，知识收尾候选无冲突。
- **本段是可关闭候选，尚未向原生产目录发布或开启consume。** 187本机自动接替与回切还在P6范围；在该能力完成和验收前不把候选宣称为生产可切换。原FC调度、定价、writer及RPG未改。原publisher受控增量发布、真实入口消费、自然轮和现场回退仍未执行。
- 独立审查99ae09f发现真实server_quote_job只传checked_at、未传collection_mode；新增真实构造→子进程回归先失败，修复为原checked_at建parent并透传原local模式/截止。无routing时直接原分支，不依赖控制包安装。
- 修复后完整FC613项通过（10个原Windows平台跳过）；183目标Python3.9隔离96项通过无跳过。最终Linux包3e751eac2504e677063cc12eda6d62d3744edee9c1913a14a5065f8ba5ec5722，routing-final-linux183.log。独立审查未发现其他P1/P2，同run并发仅1job/1attempt/1permit。
