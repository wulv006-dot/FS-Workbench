# 仓库与模块状态快照

2026-10-17局部更新：已上线修复回补及剩余清单见 [SERVER-GITHUB-BACKFILL](SERVER-GITHUB-BACKFILL-20261017.md)。PR #193/#64/#110已按最新组合CI合并；当前FC浏览器、结果页、今日经营刷新、Players cloud10与FC运营前端在本次独立回补中归档。Hermes交原聊天，不在此页宣称其最终验收；下方10/8为历史快照。


更新：2026-10-08 01:13:40 UTC；本轮Git观察基线 `7154ba13288accff164b717f1f3ad86a4e25ad31`。GitHub refs/PR本次直接读取；生产结果引用下述既有验收，不是本轮重新连服务器。执行规则只见 [HOTFIX](../ops/HOTFIX.md)，状态不是授权。

## GitHub与候选清理

- PR #32已合并，merge `7154ba13288accff164b717f1f3ad86a4e25ad31`，2026-10-08 08:45:57北京；仅注册索引文档。
- PR #30已合并，merge `56021e9d2b7c7214a1edca185d09d02182680c60`；仅回补六活动源，不重复部署。
- PR #4旧注册v5与PR #12旧FC v4.1已按用户指令关闭归档。旧候选、head与测试历史保留，不宣称其全部文件合并或生产验收通过。
- PR #1、#2、#3仍draft/open：分别有main尚未接收的RPG数值保护、NBA回执修复、候选checker修复。本次未合并业务代码或删除独立成果。
- private、PR＋pr-fast＋最新base、0人工Approve、禁强推/删除、无bypass为现有规则合同。本轮未改变或独立重新审计设置、免费余额或预算；0美元额外预算保持，无人值守SLA通知仍未配置。

## 模块最近有据结果

| 模块 | 证据时间（北京） | 结果与限制 |
| --- | --- | --- |
| 原生首页/准确日期 | 2026-10-06 22:59:49最终读回 | workspace-native-20261006-3a65044a25f8已发布，16目标/52保护与管理员PC通过；普通只读未验 |
| 利润两源补丁 | 2026-10-07 11:19:25–11:26:57自然轮 | 新补点12/12成功，原seed利润率与null缺值保持；该快照37缺日，不声明当前余量或90天全齐 |
| 注册runtime v3 | 2026-10-08 00:36切换、00:51–00:58独立读回 | 21目标与基础TLS/入口/账本/管理员读回通过；合法readonly/editor、其他管理员逐账号与真实申请/审批/撤销未完整验收 |
| 注册生产文案 | 2026-10-08 01:18:21发布、01:19HTTPS读回 | 十处文案已修；新HTML SHA256 5082417db16b5ce2154ec95317c29edb463b256532a48fe4f951e0a02b35eeb2，46文件检查通过；活动文案与Git原HTML分开 |
| FC Coins/Player | 2026-10-08 02:13取证 | 目标自然轮11检查通过，Coins三平台后台/公开100K一致；Player accepted/confirmed、disabled/sample0只证明请求成功，不复验球员售价/公式/同步生效 |
| 周报 | 2026-10-05人工补跑材料 | 原02:00自然失败保留；人工9/28–10/4成功不算自然成功，下一自然成功/Aion2范围仍按原记录待验 |
| RPG数值候选 | 2026-10-06停止记录 | 用户停止后未发布；公开Lumiel单行未确认与候选验收分开，当前现场未重新核查 |
| Workbench CLI | 2026-10-08原接入记录 | v1.0.1已安装；本人安全验证暂停、创建结果未知、未授权/未连通，maintenanceReady=false |

注册源码、artifact及本地证据键见 [REGISTRATION-INDEX](REGISTRATION-INDEX.md) 与 [机器索引](registration-runtime-v3-index.json)。FC六源见 [SOURCE-MAP](SOURCE-MAP.json) 的 fcPlayerPriceVerificationOff20261007。原始收据保留本地，不上传凭据、运行数据库或完整现场输出。

## 历史失败与观察范围

注册专用增量运行37623684963、37630588766的真实失败保留。后续QA run37645305282为completed/success；311/311数量沿用已有用户/交接证据，本轮未重取完整日志或重跑，不用driver静态绿替代集成验收。

[此前状态快照](https://github.com/wulv006-dot/FS-Workbench/blob/7154ba13288accff164b717f1f3ad86a4e25ad31/docs/collaboration/CURRENT-STATUS.md)的正文观察为2026-10-07 13:50 UTC/ee8f36b，早期“修复进行中”不覆盖本页后续结果；旧failed/unknown与原manifest仍按对象和时点保留。


## 2026-10-18 FC27 Players 共享登录回补

已上线 cloud.11.1 与真实873模型/6标签读取验收；保留原写入范围及人工确认。本 PR 仅回补代码、相关CI与活动来源，合并不再发布。当前共享会话服务在本批增加UID992本机通道，其它HTTP业务方法保持；后续基于本批活动源合并，避免旧Admin工具文件整包覆盖。详见 [交付](../../releases/fc-players/shared-login-20261018/README.md) 和 [SOURCE-MAP](../../releases/fc-players/shared-login-20261018/SOURCE-MAP.json)。
