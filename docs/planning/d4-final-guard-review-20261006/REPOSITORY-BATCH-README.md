# 第二独立批次：D4／PoE2／Aion2最终guard候选

本批只冻结最终29源，全部与d4-final-guard独立复核SHA一致；生产前轮5改1增＋旧numeric修复已合成在最终源，不加入旧candidate或旧补丁，不把只适用于numeric B的final-guard.patch当Git基线补丁。保持仓库opt/d4follow规范路径，owner陈超。**可审阅draft源码，releaseReady=false，未commit/push/merge/deploy。**不混NBA、UI/auth源码或全量生产资料。

基线main bc3b29531cec2fab3fc090385f3d7d126eb9ada7，与第一文档/NBA批次的代码路径不重叠；第一批先提交/合并后重新读main，保留其文档与NBA changes，重新比较D4逐路径before SHA，不用本包重建整个旧main树。21个基线不变D4源只是闭包，按外部base-delta只提交8源码差异（6改2增）与本批测试/说明。ZIP是增量，不得整目录覆盖服务器或他人dirty文件。

N-F1原始bool归一化与N-F2精度／六位writer序列化，在指定页面工单/服务器run_once路径候选层已闭合。四最终guard源必须一起纳入，helper需随三个消费者解析。Aion2允许有限负利润/负margin，0%保持；不加售价>=成本或利润>=0门禁，不改变D4/PoE2正常公式/折扣，不扩G2G游戏范围或选择新卖家。卖家／首屏100条／空适用游戏合同继续待陈超决定，不阻碍最小技术候选入draft，也不能据此关闭完整业务验收。

真实原始writer、容器／镜像／挂载Session/srv_run与共享源SHA、实际执行／成本单位／读回／未知结果／自然周期未验；手工CLI和陈旧本机队列不在覆盖范围。脱敏writer整文件不是可部署源，本包禁止包含它或真实config/groups/session/数据库/队列/工单/经营数字。只纳合成测试及无秘密说明。26既有测试记录已被独立复核，本任务另能运行包内不需writer的15项；后者不能冒称26整套新复跑。

## 测试及明确外部前置

在解压本ZIP的全新临时目录、现有Python3.10+标准库下运行：

```powershell
python tests/d4-final-guard/run_reviewed_tests.py
```

此入口在自身临时树构造原审阅candidate目录，复制包内29规范源及2份原样测试；只执行已审函数AST与合成夹具，不import Flask/业务启动模块、不运行switch helper、不启动Docker，不读真实配置。socket被原隔离测试拒绝。默认15项不需要外部文件，临时树自动清理，源码原件和冻结tests不改。

完整26需要此前**已脱敏本地审核writer夹具**，准确SHA为5765f759bf4e8e2e8ca27856270e01aef2228c8e11bc6dfcaa4b8ec35ffbceec；不在本包，不能从生产拉取或用未知writer补齐。若owner已有该批准夹具，可给入口 --recorded-writer 的本地路径；入口先核SHA，直接引用该文件、不复制/导出它，然后执行原闭包测试。缺失或SHA不同明确停止完整26，保留既有26记录，不能声称完整复现。实际外部writer/容器运行依赖仍需后续正式核验，夹具SHA不是当前线上SHA。

## 根协调提交步骤

重读远端base/branch，核当前D4 before blob与本包external frozen-manifest；逐项add/replace，保留所有非本模块blobs。主库新增第一批或同事新commit时先三方比较，不force更新旧head；用最新base tree生成准确commit，建立第二独立draft PR，读回blob/大小/SHA。陈超确认本模块行为，共享影响列具体路径/owner/批准依据；合并与生产验收分别记录。根协调才改共享状态册，不由本任务并写原AGENTS/HANDOFF/决策。
