# 最新映射入口（2026-10-09）

FC最新非核心来源应急与固定自愈已按11个活动源码核对生产；本次精确回补见 [冻结增量](../releases/fc-coins/noncore-emergency-20261009/SOURCE-MAP.json) 与 [当前共享接口](../ops/hooks/SOURCE-MAP.json)。后者区分生产字节与仅Git修正：图库误阻断、RPG提前消警和独立运维入口参数修复本次未重新部署。其余FC仍未全面接管，旧release保持，不从main整包覆盖生产。下方10/8记录保留其原时点。


本轮Git观察main `7154ba13288accff164b717f1f3ad86a4e25ad31`；生产未重新连接。活动source/artifact/runtime必须按模块和证据时间读取。下面历史revision2表格保留当时背景，不作为当前全站部署清单。

- 当前归属见 [OWNERS](collaboration/OWNERS.json)：business-snapshot/exact-range为吴律负责、陈超分类参与；SOURCE-MAP旧modules行保留历史，后续ownerAssignmentEvidence/_currentGovernance有明确归属，不按旧“待指派”回退。
- FC六活动源已随 [PR30](https://github.com/wulv006-dot/FS-Workbench/pull/30) 合并，见 [SOURCE-MAP.json](collaboration/SOURCE-MAP.json) 的 fcPlayerPriceVerificationOff20261007；其余FC未全面接管。10/8 02:13自然验收只记录Coins与Player请求保护，不复验球员售价。
- 注册source commit2152c8c、artifact及机器绑定见 [REGISTRATION-INDEX](collaboration/REGISTRATION-INDEX.md)。文案已生产修订，新SHA与原21目标映射分列，不把main原HTML认成最新活动文案。
- 原生首页3a650日期v2与利润12/12自然轮见 [CURRENT-STATUS](collaboration/CURRENT-STATUS.md)。历史v7/source表不能覆盖这些后来窄发布。
- PR4/12已关闭历史候选；PR1/2/3的独立未合入改动保留。Git源码、归属记录与现场验收不互相替代。

---

> 历史证据：下文结果/来源只属于各自对象和时点，不构成当前全仓QA、上传或另批门槛。当前执行规则只见 [HOTFIX](ops/HOTFIX.md)；先验直接影响，资料后补，不把旧绿或旧失败冒充新候选结果。



> 历史revision 2覆盖及外部依赖以 [integration/README.md](integration/README.md) 为准。下文保留v2阶段历史背景；portal/任务台/Players/NBA/MLB已补源码，不等于运行验收通过。

# 规范源与来源冲突

完整相对路径、输入 SHA、候选 SHA、线上目标和只读核对时间见 provenance/source-manifest.json。候选源保留既有目录；下列映射只发生于候选，不覆盖原工程。

| 模块 | 历史候选源 | 当时目标与依据 |
| --- | --- | --- |
| 首页 app | fs_home_live_20260930/app.js | 来自 taskboard_card_deploy_20261001/new/app.js；与 /var/www/dashboard/fs-home/app.js 的 e3373785…一致。tasks 进入模块白名单，保留 marketing/weekly/ops |
| 首页 registry | fs_home_live_20260930/module-registry.json | 来自同目录 new/module-registry.json；与线上726592d9…一致，含任务台卡片及原FC工具入口 |
| 经营 collector | fs_transaction_snapshot_20260930/collector.py | /opt/fs-transaction-snapshot/collector.py，含已核实Aion2与FC扩展 |
| 活动准确区间 | mmoexp_google_data/weekly_report/range_parser_release_20261005/source/range_api.py | /opt/fs-exact-range-20261001/range_api.py；SHA0a03f8027af56cb1448299c1009b4f7c03c1ac34f92fd44e1ed9121a50c31aea |
| FC运营HTML | fc27_ops_cloud/index.html | /var/www/sites/wulv/fc27-ops/index.html；保留当前原生产品数量榜及主题/列表行为 |
| FC收藏器代码 | fc27_cloud_browser/collect_competitor_browser.py、collect_fx_browser.py | 真实容器fc27-cloud-browser内 /opt/fc27-collector/ 路径；宿主同名旧代码不作为当前基线 |
| FC价格/降幅范围 | 根 engine/quote JS/HTML、fc27_cloud_browser 与 repricing_logic.js | 最新降幅发布的8源逐项与线上一致；根引擎与部署别名路径分开记录 |
| Google与周报 | mmoexp_google_data 内已筛选代码 | /opt/mmoexp-marketing、/opt/mmoexp-weekly-report 的逐文件映射；无实报表输出 |
| 受控发布网关 | fs_dashboard_overwrite_20261003/release_gateway.py | /opt/fs-dashboard-release/release_gateway.py；仍保留实际SHA/版本/依赖/锁校验 |

2026-10-05历史经营HTML为20261005-restore-v7，生产/账本/规范源SHA1d6a6084…一致；本候选以dashboard.template.html保留全部代码，只分离PROFIT私有历史JSON。完整source与template双SHA、精确重建合同见provenance/restored-v7.json。incident e53eccb3…仅在原工程忽略的raw证据保留，没有导入候选。当前漂移已恢复，具体旧上传者仍未查明。

before_engine.py 和 range_parser_fix_20261005/baseline/range_api.py 仅是经过扫描的最小回归代码对照，不是活动规范源，不含实际订单或日志。3个本地一次性辅助入口没有作为活动线上路径验证，只供现有测试依赖，不能用其触发生产。配置模板/schema不等于已核实生产配置。
