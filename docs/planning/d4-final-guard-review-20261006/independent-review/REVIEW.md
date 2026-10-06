# D4／Aion2最终数值增量：独立只读复核

2026-10-06，独立取证时间00:42:01 UTC。主工程01a0f1c0仍是唯一写负责人。本报告仅写审查人自身工作区，未修改候选、原件、生产或主工程记录。

结论：**N-F1与N-F2在本轮指定候选的原始输入、页面出单及服务器队列执行路径上已闭合，可将精确增量纳入draft PR。仍不可部署，不能泛称全部执行入口或生产执行链安全。** 当前原始容器writer／现场SHA未验；手工CLI和历史本机队列消费未纳入此修复。合法Aion2亏损与0%保持；卖家、分页、空游戏范围决定继续开放。

## 范围、冻结及证据真实性

- C：`E:\WorkBuddy\大超服务器\d4_final_guard_review_20261006\candidate`，下文源码行号以`C/opt/d4follow`为根。
- B：`E:\WorkBuddy\大超服务器\d4_numeric_guard_review_20261006\candidate`，上一轮冻结28源。
- P：`E:\WorkBuddy\大超服务器\docs\planning\d4-final-guard-review-20261006`，读取REVIEW、source-manifest、validation、完整tests.log和closure-synthetic-evidence。
- T：`E:\WorkBuddy\大超服务器\d4_final_guard_review_20261006`，读取final-guard.patch、两份测试及verify_delivery.py文本，未执行它们。
- W：`E:\WorkBuddy\大超服务器\docs\planning\d4-live-readonly-audit-20261006\sanitized-live\opt\d4follow\_p2pah_srv`，仅读取既有脱敏writer相关函数及srv_run.py；未接触真实账户、配置、数据库或生产服务。

已读适用AGENTS、.gitignore和当前OPEN-DECISIONS中的D4条目。遵从任务明确只读约束，不更新E盘HANDOFF、清单、决定或候选。审查仅枚举、文本阅读、哈希、AST静态解析及审查人标准库脚本的纯内存patch重建；没有import／执行候选、测试、应用或CLI，没有安装依赖、联网、Git写操作或任何真实业务动作。

独立核验：C共29源逐项字节／SHA匹配清单，零失败／零额外／零缺失；B全部28源仍与上一轮冻结清单相同。仅修改app.py、core_gold.py、srv_exec.py并新增gold_numeric_guard.py，其余25源不变、无删除。前轮独立报告／证据SHA与validation引用一致。

补丁SHA：`93fcb11f2922b581746f671b9203deb5f5b967120a22ba6b697da65ec0c6bf14`。独立验证所有hunk上下文与增删计数，2＋8＋1＋1个hunk在内存重建四源逐行文本与候选完全相同；没有执行git apply。该补丁只适用于B，不能直接套到旧Git基线或未知线上版本。

| 本轮源 | 最终SHA256 |
| --- | --- |
| app.py | `655503d5b352e22d26cf256c978c88c330f13c0c4570138b8ad5b57a26923bb7` |
| core_gold.py | `d588f4da02d3a77f3ea76de9839725c0fc14c579b59941c29dbd6803db441947` |
| gold_numeric_guard.py | `6498e8dd08e491dd0f8f5c4add3d607a98b979568c235c7a154f3641b77316b9` |
| srv_exec.py | `1c74a40a4b053cc8e33a43610c788743c62298444e4a5942fd179b7c1087e4a6` |

## N-F1：原始bool与归一化

**指定问题已修复。** core_gold.py:280–288的旧_f现在转换前拒bool并捕获OverflowError，True不再成为1.0。:142–150的_tier_count先验证有限正数、再验证整数等值；:570–574的真实fetch_front_gold响应解码调用它，缺失／空数量才沿旧规则用key，bool、零负、非整数或超大溢出数量不会假借key变成合法档位。报价仍经_f，bool变None；:136–139以及:590、612、626的per_m／biggest_tier／iggm_biggest_tier再检查原始或外部注入档位价格与数量。

这包含实际解码路径与计算消费者，不是只新增未被调用的helper。无效档位被排除，仍有其它合法档位时可用它们；不等于某一坏档位必然阻止整区。没有合法前台每M时，新模式原有正数门禁令该区hold。

成本声明值：core_gold.py:126–133在旧默认／归一化前检查显式成本除数、两处汇率、全局／该游戏前台系数以及服务区利润率；:991–1005实际build_plan在g2g_cheapold模式下把无效声明转_div=None并hold。bool、非有限字符串／浮点和转换溢出不能通过默认回退抹掉类型。利润率只检查有限数，负值合法。

这是N-F1的原始类型／非有限输入关闭，不是新增所有配置字段的正数合同。缺失／空值仍走旧默认；有限零或负的成本配置值仍按旧cost_divisor_of／front_factor_of默认和派生规则处理，最终_div及成本需正；未把利润率当正价格检查。其它模式未新增相同raw_cost_inputs_valid的强制hold规则，但共享_f／档位消费者也会拒其异常bool。正常有限输入的公式、单位及默认值未重写。

既有测试证据：test_closure.py:94–101测真实per_m／biggest_tier与_f；:102–116抽取真实fetch_front_gold函数、模拟原始JSON响应，再接per_m；:117–123测实际build_plan的显式成本除数／汇率／前台系数异常转hold，并直接验证负利润／bool利润的raw helper。该游戏覆盖、顶层汇率、利润异常的每种组合未都单独走完整计划测试，不能扩写成所有配置结构与字段的穷举。

## N-F2：计划、工单与当前消费精度

**指定问题在页面出单及服务器队列路径已修复。** gold_numeric_guard.py:9–16拒bool／非有限及转换异常；:19–31读取当前配置采购成本小数位，保留0／空默认6及合法负位数的既有语义；:34–46同时检查原数有限正、原Python round结果有限正，以及记录writer的`%.6f`字符串转回数值有限正。返回原数，不改目标、不把配置计算一律强制成6位；合法数字字符串可转换，错误／非有限字符串拒绝。

实际调用点：

| 路径 | 文件行 | 实际结果 |
| --- | --- | --- |
| G2G成本计划 | core_gold.py:121–123、998–1014 | 检查准备写入的round成本，也核六位格式；失败清目标后hold |
| 历史snapshot生成工单 | app.py:2376–2379 | keep前按当前cfg检查，不再只看cost_target有限正 |
| 工单JSON边界 | app.py:2500–2505、2513–2519 | allow_nan=False先完整编码；反序列化后再验每个成本，之后才打开该工单文件及入队 |
| 陈旧服务器队列 | srv_exec.py:195–207 | 读取当前cfg，严格JSON往返并validate_ticket；无效标记任务失败、state归idle、failed增1，拒绝Docker和业务执行 |
| 外部业务动作的顺序 | srv_exec.py:209–260 | 数值检查在Docker info、复制config、计划落盘和Docker run之前 |

gold_numeric_guard.py:49–61与记录writer的`采购成本_新`／`new`回退一致。配置8位且成本0.0000004即便round仍正，六位writer字符串为零，也会被拒；1e-12等旧极小快照同样不会进入页面keep或服务器Docker。非法精度bool／非整数／溢出会拒绝出单；完整计划前段对任意畸形配置的容错未全面穷举。

“执行前无业务副作用”不能说成完全无副作用：srv_exec.py:173–184已先认领数据库任务、设running并写状态；数值失败仍需记录任务失败。正常main在:339–347刷新最终状态。严格编码保证的是**当前单个工单文件**不会因NaN元数据写半张，不提供跨游戏整个批次事务原子性；app.py按游戏逐张出单，先前游戏已成功入队后后续游戏出错的批次行为未被本次单游戏用例覆盖。

既有测试：test_closure.py:124–131覆盖2／6／8／0／−1位与六位格式边界；:132–136实际task_gold_apply拒旧微小／bool／非有限成本，无工单无队列；:137–147执行完整task_gold_apply，验证合法成本保留负利润、严格序列化，以及单张工单非法元数据在文件／入队前报错；:158–163执行实际run_once，陈旧异常成本无Docker／文件动作且任务失败。它们不是只调用write_cost。

## Aion2亏损、0%与保留项

core_gold.py:732–733保留有限负利润率；本轮raw验证不加利润率≥0或售价≥成本。cost_divisor_of的原公式仍为汇率×(1−利润率)÷前台系数，目标仍按此前G2G基准×(1−下浮比例)。discount_display:116–118及0%策略没有本轮回退。app汇总负毛利计算与筛选未改，前轮3项亏损记录仍作为历史独立证据，不能加到本轮26的数量。

test_closure.py:172起实际build_plan使用AION2、0%下浮、利润率−0.2、基准2 USD/M，成本15.96 CNY/M；按6.65换算2.4 USD/M，实际毛利为负而计划follow_up。随后实际task_gold_apply和run_once通过内存模拟，记录writer发送`15.960000`。:164–171另验证成本15.4812发送`15.481200`。该测试证明支持路径的合成损益保留，不表示这些fixture为真实生产配置或业务结果。

25不变源包括core_g2g、core_front、engine、gates、store、模板及switch工具；前六项同步保留，D4／PoE2正常公式与折扣路径沿此前回归，未扩大G2G适用游戏、不选择新卖家、不改原排序／分页。共享类型守卫会拒异常值，这不等于其它游戏利润政策获新增授权。FS经营Aion2 Order826／Admin891及FC原生榜合同由此前独立FS报告覆盖，本轮金币writer gid不替代它们。

## 26项记录与writer边界

测试源码SHA：test_isolated.py为`2790db595a5729761fbc9e9ddceb81e25efe458cf9647a356eedde68ae29c45e`；test_closure.py为`d55992b1e0a34e5cd92234e4801cbc69b2a0354a1484749297c2ad934ce1d366`，均与validation匹配。审查人静态核对15个旧测试方法AST完全不变，另11新方法，共26；tests.log为一次26项OK，实施方记录testExitCode=0、patchCheckExitCode=0。审查人未复跑，既有SyntaxWarning也不被包装为审查人运行结果。

测试抽取实际函数AST、去decorator，阻断socket；配置、文件、数据库、队列、Docker、Session均内存模拟。完整task_gold_apply与run_once语句确实被纳入，不再只测试keep段。但Docker替身直接桥接抽取的writer函数，未实际运行镜像／srv_run.py／真实Session。

记录writer SHA `5765f759bf4e8e2e8ca27856270e01aef2228c8e11bc6dfcaa4b8ec35ffbceec`独立匹配validation，来源是W的**脱敏审核副本**。p2pah_local.py:1240–1252读取成本并float转换，:1350以`%.6f`交Session.set_gold_cost；W/srv_run.py:43、68–71静态显示替换Session后调用P.main。该调用关系有记录源码证据，不能当当前原始容器SHA。脱敏writer整文件不是可部署源码，不应直接拿去编译／打包／部署。

## draft PR范围与部署前必验

可入draft PR：相对精确B的四源增量、两份隔离测试、非秘密说明／清单／既有测试证据；gold_numeric_guard.py必须与三个消费者一同包含。此前六项同步可沿前轮独立通过范围纳入，生产时点源码与本地增量SHA需分开说明。不得把脱敏writer当新增部署文件，也不宣称这四源与当前线上相同。

部署前仍必须在明确授权范围内完成：

1. 获取当时真实源码／共享源／镜像与挂载writer、srv_run、Session依赖SHA，确认当前writer仍使用所审核的六位序列化和字段合同；与旧冻结基线、本轮候选及并行UI／鉴权改动三方核对，避免app.py被互相覆盖。确认helper可随应用及srv_exec导入、服务更新时序有效。
2. 明确受支持入口：本轮覆盖新页面工单及服务器run_once；手工writer CLI、其他生成器、陈旧本机队列消费未改。若发布范围包括这些入口，先核其原始源码并补独立同边界审查；不能用页面闸门推导它们已受保护。
3. 在受控验收中核实真实当前精度、配置与币种／单位、数据库与队列失败状态、开关／确认／仅检测、实际Session协议、写后读回／推送／缓存及未知结果处理。合成Session收到合法字符串不代表后台接受、真实落值或任务业务成功；本轮无生产运行或写价授权。
4. OD-D4-G2G-BUSINESS-BOUNDARIES-20261006保持OPEN：固定cheapold或配置卖家、首屏100条／重复卖家／前两有效报价、空适用游戏语义仍待业务决定。它们不阻碍这个不改选价算法的最小技术增量进入draft PR，但完整G2G策略验收不得据此关闭。

本轮未发现该最小增量新增需先于draft阻断的严重源码遗漏；N-F1／N-F2关闭仅限上述路径和记录writer合同。releaseReady=false保持，线上／原始容器／手工与本机入口、完整并发和自然周期均未验。
