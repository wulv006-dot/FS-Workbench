# FS 全局 Order 会话服务与 FC 恢复

用户授权：统一所有活动 Order 后台消费者，优先恢复 FC 自动改价；Admin 服务恢复由另一 AI 处理。随后明确 FC Admin 身份允许 `wulv`、`chenchao`，另外两个账号尚未指定，不提前加入。

| 后台 | 全局名称 | systemd 服务 | 地址 |
|---|---|---|---|
| Admin | FS 全局 Admin 会话服务（8767） | `fc27-p2pah-session.service` | `127.0.0.1:8767` |
| Order | FS 全局 Order 会话服务（8768） | `fs-order-session.service` | `127.0.0.1:8768/health` |

8768 的 HTTP 接口只返回脱敏健康信息。凭据通过受 Linux 对端 UID 校验的 Unix socket 在现有消费者之间传递，不通过 HTTP 发放，不记录 cookie、不写密码、不创建账号。

源码和测试：`order_global_session_20261021/`。详细发布与真实验收见 [DEPLOYMENT.md](DEPLOYMENT.md)，长读取限制与已上线/未上线边界见 [LIMITS.md](LIMITS.md)。本目录只保存脱敏资料与哈希；原服务器源码备份和运行账本留在服务器。

## 会话行为

Order 唯一会话所有者是现有 `fc27-cloud-browser` 的已登录上下文。全局服务用轻量受保护首页验证身份后，才发放该上下文的 Order cookies；20 秒内合并重复验证，验证失败即停止发放，不用旧 cookie 兜底。没有新增独立密码登录、验证码识别或登录重试。登录态过期后需在这个唯一入口完成认证；消费者不会自行重登。

客户端 socket 仅允许 root、现有浏览器 UID 11027 和 FC API UID 994。外部 HTTP 无凭据接口。已有容器用原有挂载目录中的 socket 别名接入；新 FC 临时容器只挂载服务代码及 socket 目录，不开放浏览器 profile。

FC 的 Admin 适配器只从既有 8767 取 token，不登录、不刷新、不读取密码。账号白名单存放于服务器 `/etc/fc27-cloud/global-admin-principal.json`，只含 API 地址和本次批准的两个用户名；后续扩展账号需用户指定后更新这个名单。没有改写另一个 AI 正在维护的 Admin 服务或镜像。

## 已迁移范围

- FC Coins：成本采集、后台预览、实际写入、恢复入口及 Order 探测脚本。
- FS：准确区间、FC Order、交易快照、每日利润、品类读取；间接消费这些读取器的经营页和周报沿用原合同。
- sales：Order 登录和取数入口；原 Admin 补丁及另一 AI 的凭据修订保留。
- RPG（D4/Aion2）：宿主客户端、服务器工单浏览器和 Order 自动登录入口；不打断正在执行的工单，不改变价格/派单/未知写入规则。
- Madden：Order 成本采集；MLB：当前 Coins 取价；NBA：当前采购价读取。
- FC Packs 的 Order vendor；已退役 dashboard 利润采集入口也不再独立认证，退役调度不恢复。

历史备份、冻结 release、离线 QA 副本和人工登录浏览器不作为活动生产调用方迁移。未启用的本机 FC 只读扩展仍是历史实现；本次核实的活动 FC 配置为服务器模式 revision 3，未切换来源位置。其他来源、成本口径、竞品降级、毛利、锁/CAS/UNKNOWN 与球员价格复验退役范围保持。

## 验证边界

本地及服务器通过会话/身份/导入/部署漂移检查；真实 Order 受保护页面、FC 三平台成本、NBA 读取和 RPG 全局身份已验证。RPG 商品列表为空的独立问题没有冒充业务写入通过；登录判据改为全局身份，商品行与写入校验保留。

其余游戏未为验收人为触发改价、发货或其他业务写入。FC 原自动周期失败、人工补完与后续自然周期分别记录，不能互相替代。
