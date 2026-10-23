# 重启释放、零改动误报与重复失联修复

用户已明确授权修复并上线；生产调度、原工单/恢复事件ID、原登录profile、120分钟与v15双10%规则保持。下列发布复用原publisher、备份、空闲锁及逐文件CAS，未为验收触发采集、模型、写价、重放UNKNOWN或制造重启。

FC重启后原来只检查连接，startup打开的商品文档和浏览器级Worker会留下。修复在原恢复事件和新StartedAt下，复用现有“同context准备受控idle再关闭旧商品页”的释放器，验真实浏览器级Worker0；旧事件成功不再替新事件背书，未知先按原ID读回。原17:15事件0e74258c-4d9e-405d-b543-5fcf24fcdb84于18:50:07核实释放；19:15事件624b76be-b9fb-4fee-8bf4-e8113f70573e于19:16:17同ID核实。没有重放原失败事务。

另查实周期检查本身会积累执行环境：安装版Playwright1.63每次connectOverCDP按随机page GUID创建isolated utility world，断开后旧world在长寿命文档中保留。Order纯raw观察19:21:20→42，同4页各57→58且旧unique ID全部保留，恰逢原20秒检查；这证明持续增长机制，不证明18:43整个1GiB分配都由它独占。当前FC V5（19:34:15）正常检查改为原Node24原生CDP，默认执行环境读取，不注入world/binding；仍验证真实CDP、唯一页面、受控idle DOM和全局Worker，不降为HTTP200。

FC V5 55项Linux及原Node离线协议检查通过；19:35/36/37原分钟tick均healthy/transportok/Exit0，同idle目标19:36:39→19:38:22的102.901秒16→16 world、旧名称/unique ID不变、新增0、同container/StartedAt不变。详FC-WORLD-V5-READONLY.md/json。V1 helper端口不符、V2异步页首次未确认、V4 Node stdin入口未执行等原失败均保留，不计通过；V5显式入口及空响应防误绿已回归。

FC原自然轮d789b510-bdd3-4f80-89bc-fe38a57c9772于19:03:15创建、19:06:43完成，三平台no_price_change/无blocked，Hermes19:06:40 completed。该轮发生在V2，不冒称V5新自然或新写价证明；后续原周期继续核。原collector4d19、tick5749、startd646保持。

RPG 18:52:14仅修物品cmd_write的结果元信息：零实际写入且全目标复核成功保留wanted意图，新增noop/clearcache_required=false/原因，cache结果仍null而非虚构成功。监控必须同ID done/confirmed、完整finished phase、严格整数write_attempts/ok/fail全0、无mismatch、非空目标才解除该单缓存误报；UNKNOWN/partial/缺证/真实缓存失败均保留。基于现场3ade函数级生成1992，保留他人readgold/main/金币改动。原J20261023163848、J20261023173949未改DB/outbox、不补缓存、不重放。原链18:52恢复，实际飞书回执om_x100b628788befca0c09e57cc3a38c58官方GET code0/同群。当前监控06eb（19:09:56）并入Order原分钟RSS/cache/OOM读取，70% RSS预警，未加第二通知或timer；44 Linux通过。新原物品轮待验。

17:14残留依赖已定位并修正：原事务collector的3个Order reader仍在FC容器连接9226，而9226只是socat→同一FC Chrome9225。17:14:04原事务启动，17:14:38真实CDP失联；17:15:43原恢复restart才导致reader137。19:14原轮再次按同顺序复现，并记录browser_connection_timeout:connect_over_cdp，非DOM失败、无新增3GiB OOM。137是恢复连带结果；Chrome内部具体阻塞函数尚无堆栈证据，不能冒称已经逐分配定位。

19:16:52已把3个Order reader隔离至原Order浏览器的独立临时进程容器，不再接触FC浏览器/内存组，复用原镜像/socket/UID/会话，不新建Chrome、profile或登录。原参数、来源、900/600/可选利润预算和120分钟timer不变；内外超时仅清理本次唯一runner并验证消失，失败不吞。collector891990/runner4f694，15 Linux及无Chrome/cookie环境烟测通过。19:14轮发生在发布前且已失败保留，第一新自然轮为21:14，未人为重跑。详TRANSACTION-BROWSER-ISOLATION.md。

Order独立容器18:43:13发生真实1GiB RSS OOM，不能与FC17:14混为一谈。19:00:46仅受控恢复原容器一次，同profile、不登录，19:01:08原身份ready/login0。19:07:21为原20秒probe补内部33秒TERM+1秒KILL、外35秒期限，避免宿主超时留下容器内子进程；该缺口不是已证OOM唯一原因。进一步worldless于19:53:29实际上线/native ready/login0，原浏览器及profile未变、原空闲executor已恢复；同ID首次新文件发布前失败和精确对账后的续接完整保留。实现与验收见ORDER-WORLDLESS-PROBE.md、ORDER-WORLDLESS-DEPLOYMENT.json及模块SOURCE-MAP；37项隔离Linux和真实原新文件publisher合同通过，同页world后验与长期趋势另记。

当前精确SHA、原回执和来源见SOURCE-MAP。PR405首head e8dded96正式CI93项通过仅为首版，当前最终代码须更新并通过新的正式CI，不据旧CI冒称通过。至少12个原周期覆盖昼夜的内存验收、至少7天权重策略比较继续OPEN；不会凭短时回落或无变价轮称长期稳定/利润提升。


20:12兼容收尾：主Agent独立补齐合法父域Cookie参与原请求Jar/刷新/删除，原输出仍exactOrder根路径，避免将当前ready冒充轮换兼容。最终helper0368/service35b950，44Linux/0skip及原native ready/login0通过；最终同4页110.082秒/两轮原upkeep world144→144/新增0，原name/uniqueID集合连首版19:57也完全相同。详ORDER-WORLDLESS-PARENT-POSTCHECK.md/json及当前SOURCE-MAP，首版后验不冒用为新版本。
