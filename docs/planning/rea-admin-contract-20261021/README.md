# Admin 查询合同 REA 与规则同步

最新结果（2026-10-21）：按月及退款混入修复已部署全局8767，真实34天159页完整查询通过，见[FINAL-ACCEPTANCE.json](FINAL-ACCEPTANCE.json)和[MONTHLY-FIX.md](MONTHLY-FIX.md)。旧独立登录仍关闭。下文前半保留早期REA与失败证据；v4同步历史见[SYNC-RESULT.json](SYNC-RESULT.json)，最新业务规则见[QUERY-RULE.md](QUERY-RULE.md)。本目录无凭据、token、客户或订单明细。

## 已观察事实

- `/admin/order.Order/index` 的 paytime=2026-09-17..2026-10-20 返回HTTP200/code0/data=null，文案为“下单时间查询范围不能超过一个月，请按月查询或缩小时间范围”。故原cohort_paid_contract并非JSON截断或密码错误。保留原错误，不把失败当空集。
- 9月17—30日和10月1—20日两个子窗口，各首批100行返回code1；只验首批，不冒充完整区间成功。不能凭两次对照确认精确滚动天数或所有跨月请求均被禁止。
- 保守候选按自然月分段，复用原逐页范围/完整性检查，共享300请求/850秒预算。5项本地及Linux候选检查通过，但真实完整读取93.924秒后失败cohort_paid_scope。原模块SHA e711cb9fcaf9c2cdc03af1d28619895dc7f391aaa7f8b4cc3846fca5fc6a3663，候选SHA 75622974fb53113fecd5ea22695f0003529e718e7d98c44b5f493dd2342b7491。未跳过异常行、放宽校验或安装候选。
- 候选试验94轮并发health/token全部ready，最大6ms，同一token且登录次数1→1。该证据只对应试验时运行状态；后续已观察Admin维护方更换镜像，不覆盖其当前服务。
- 原生汇总34/112天成功证据沿用[会话接续验收](../admin-session-continuity-20261021/README.md)，不将逐笔限制推广至汇总/ES导出/Order。

## REA 证据与边界

HAR是受控脚本生成的脱敏结构投影，body为无业务值的派生形状，非原响应字节；REA运行归属unknown，不冒充浏览器抓包。原请求使用现有全局会话，未发起密码登录。

| 本地材料 | REA evidence ID |
|---|---|
| first-shape.har | ev_1d6d2fc26aaef8f61b6d383a98c83676a1b9043ebaf70fa6a14e4a79c82435dc |
| rejected-month-window.har | ev_e0342412290932b1431fa0395ef6fa6609ff79acfff9a39de31b8ebd6726c3e9 |
| accepted-september.har | ev_3b2df137da03a7ef5bbf80f0c525e639d7523a5e59720bcfe505fbd671f23292 |
| accepted-october.har | ev_2d31abc7d8130570bb5b77b7aaa5a402acaa5f6e6f4f3f231413eed8fbeea62d |

公开交付前端index-247a3432.js SHA8294c60f5d24f8a734973b31d06d40c2b5a72067dea95aaa5a77ff267e84cca1，2273528字节，offset144570观察到工厂timeout=300000ms，具体请求可覆盖，不证明所有页面均300秒。REA部分分析ev_65db994314109d716394cce7c6c0c13085be2737998bff0b21f505cf9f241784，父证据ev_df5951d8491a8880cb286043fe3336c2fdb16eff651cabdd900c056e01536f58，语义阶段触及堆上限；未完整重建前端、未取得后端代码/数据库日志。凭据不能推出后端日志访问权限。

## 同步与剩余工作

PR276正式8项CI通过并合并d711d5d8ca2ef199361f269f84ccb6a69eec7312；业务基准及知识源合并后读回一致。Notion指定页面经用户单独批准后追加第17节并读回。服务器原publisher仅更新知识文件，1目标/402保护全匹配；原知识装配函数读到v4与范围边界，无模型任务，不声称掌握或迁移通过。

发布前核实并保留并行Admin镜像和报告方法文档，另建新manifest，不改历史保护记录。没有更新8767服务、订单reader、调度、凭据或价格，不恢复独立登录。后续需定位cohort_paid_scope的具体页/字段错配；原生查询曾发生的短时超时底因仍未知。


## 后续修复与真实入口验收

第67页仅付款状态错配，状态2的后台标签为Refunded，等号/IN/附加排除筛选均不能排除。现完整读取源分页、严格核游戏/站点/时间/身份/排序/已知状态，仅状态1进入付费投影，状态2单独计数排除；未知状态仍失败。REA脱敏结构投影证据ev_8571c0d6ff49de1ad660800fa6827a8bf708e09021d994368bdb7917df85d07a为historical-reference，HAR时间为显式占位，不作真实网络时序证据。

PR277正式13项检查通过并合并7f31f3e45ef4d205b4a8b1d56d740f8d1cdeef58，六文件读回一致；既有发布锁/CAS/备份与同一checkpoint完成切换，session服务本体SHA52577a17…不变，原OCR配置和会话挂载保留。真实8767接口34天查询201.431秒，159页完整，15872原始=15669付费+203退款，3367433字节长度完整。202轮并发ready/token相同，登录1→1。8767/8768最终ready，Sales timer active/enabled，旧dashboard-collect /dev/null masked/inactive。未改业务数据库、价格或调度。回退未实际演练，长期自然周期与先前短时上游超时根因未验，不据本次外推。
