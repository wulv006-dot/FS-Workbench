# 8767会话接续、90秒读取与锁分离

2026-10-21，Asia/Shanghai。用户明确授权尽量保留当前登录态、部署补丁并做真实长读取验证，独立登录入口继续废弃。

## 已上线与已验收

- 16:34左右完成全局8767切换，服务仍是`fc27-p2pah-session.service`，地址和所有消费者接线保持。
- 活动镜像`fc27-cloud-session:continuity-read90-20261021-v1`，镜像ID `sha256:e9670223999fca9fbd0402202823e5e1a7cd404f219ec251ea765fdcdfecf64e`。
- 活动服务源码SHA256 `52577a17418f05c1fe4adfb9a672595f39258e8750cfbfcc8154d127b1ffca01`，原源`27ab5e9b…`；旧FC通用读取入口SHA256 `665ccceb4d2dcfbb93e0ef3cb1e2ba62b40b5d0c5fb97cd579f1c0dc1d70efed`。
- 四个汇总分支默认读取超时90秒，慢网络读取移出会话锁；两种能力查询及旧FC通用查询也移出collect，能力本身原预算、参数、数据校验保持。
- 当前访问token通过同机受限临时文件接续，切换前真实身份预检通过；切换后又做了一次受控重启，token完全一致、ready=true、累计密码登录次数仍为1，新增密码登录0。
- 真实34天汇总在90秒后失败期间，90轮并发health/token检查全部ready，最慢0.004秒/0.002秒。证明长查询不再把凭据读取和健康状态一起堵住；不证明长查询取数成功。
- 本地与Linux服务器5项接续测试通过，原锁分离16项检查保持；正式CI、合并与逐文件读回见本机GIT-RESULT.json。

## 会话接续边界

旧服务只提供访问token，没有刷新token导出接口。本次没有扫描/注入进程内存，也没有重新提交密码或恢复独立登录。

服务将访问token存于服务器`/run/fs-admin-session-state/session.json`，目录root0700、文件0600，只有现有全局服务挂载。该目录在临时内存文件系统中；不进入Git、日志、报告或本机。

启动时检查文件类型/属主/权限/大小/API地址/时效和真实身份，再恢复ready。不因缺刷新token而在20分钟阈值强制丢弃仍有效的访问token。后续现有全局认证或合法续期取得的完整会话会检查后保存，供下一次进程重启使用。

**本次未保留旧刷新token。** 当前访问token未来失效后，仍需唯一8767入口完成原有人工认证；机器重启会清空`/run`，本方案不宣称跨机器重启免登录。拒绝的/过期的接续文件不能作为有效会话使用；运维应先核原失败记录，再移除失效临时接续文件并按唯一入口恢复，不盲重启或恢复旧认证探针。

## 真实长读取结果：两种汇总通过，逐笔能力未通过

1. `cohort_paid_orders`，FC27、2026-09-17至10-20：返回原数据合同错误`cohort_paid_contract`，HTTP400；未放宽分页或完整性校验，未发布部分数据。
2. 原生经营汇总，FC27、09-17 00:00至10-21 00:00：约90秒后HTTP503；本轮并发会话与健康全部可用。
3. 营销09-17至10-20：约90.23秒，会员/折扣/优惠券各部分均unavailable，不能认定经营数据已取齐。
4. 单日原生ES对照：约43秒后503。小页订单读取在10—20秒内仍超时；更换为Sales相同User-Agent也未改变结果。

随后原读取逻辑的同token对照恢复available（0.428秒）；在同一已上线源码、同一token下重新验证：

- FC27闭日34天（09-17至10-21 00:00）汇总available，0.453秒，13169字节；区间与Content-Length完整校验通过。
- 全游戏闭日112天（07-01至10-21 00:00）汇总available，0.801秒，39514字节；同样完整校验通过。
- 并发health/token均ready，token完全一致、login_attempts仍为1。最终8767/8768均ready。

之前的90秒超时记录原样保留，故障恢复期间没有再改运行代码，短时上游/网络异常的底层原因未确认。单次汇总成功不代替长期稳定性验收。

逐笔分页复验仍HTTP400/cohort_paid_contract；其cohort_paid_source.py在原镜像和本次镜像字节完全一致，本次未修改或放宽该reader的数据合同，不宣称该能力已修复。后续需源侧返回合同证据单独处理。

## 发布、失败保留与回退

操作`fs-admin-continuity-20261021-v1`，原发布锁`/run/lock/fs-admin-session-unify.lock`。受限备份/脱敏回执位于`/var/backups/fs-admin-continuity-20261021-v1/`。准备阶段的本地Docker镜像引用与隔离Python导入路径失败均发生在切换前，沿原ID修正和预检后才切换，原服务未因此停止。

回退镜像`fc27-cloud-session:continuity-baseline-20261021-v1`保留接续能力，仅撤回本次长读取变更，避免回到无法读接续文件的旧镜像。服务器staging中的`deploy.py rollback`先核当前回执/单位文件SHA，再以当前合法会话保存、原子切换及重启；重启后必须读回确认。该回退路径未实际执行，不宣称回退演练通过。

源码位于`admin_session_continuity_20261021/`，复用已合并`order_global_session_20261021/admin_read_patch.py`。只同步脱敏生成器、测试和记录，完整生产源码仅留服务器。没有修改Sales/SBC源码、队列、策略、账号名单或业务数据库；旧`dashboard-collect`仍masked/inactive，原Sales timer保留active/enabled。
