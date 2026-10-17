# FC 已确认写价后的清缓存恢复

负责人吴律；执行规则仅 `docs/ops/HOTFIX.md`。修复原 helper 把会话失效统一报为清缓存拒绝的问题，并让 worker 保存脱敏响应。生产身份端点无会话只读实测返回 HTTP 200 / code 302 / data.routePath=/admin/login，权限拒绝为另一类，不能直接重试泛化错误。

每次维护仍要求原 execution ID 对应 CONFIRMED、sync_confirmed=true 和 changed 非空。精确会话失效再核身份端点同一合同后，沿原 SessionManager 续原账号会话，再验 code=1、username=chenchao；最多续一次。原明确中文限频仅等待31秒一次，重试前重验身份。总清缓存请求最多三次，原容器160秒/worker175秒预算保持；权限拒绝、未知/格式错误和身份不符停止。无写价重放、账号/凭据/权限、业务系数、队列/timer、workflow或额外费用变化。

只替换映射中的两份活动源码，复用原 worker publisher 的队列锁、写价锁、CAS、备份、原子替换及空闲重载。允许固定worker+helper范围并兼容原worker-only范围；替换中途失败逆序恢复所有尝试过的目标，包含rename后fsync失败。尚在公开价核对的已确认任务仍判非空闲。保留mode/owner并清理本次创建的临时文件，原失败账本/锁/数据库/配置不回退。

直接检查：9项cache合同、11项worker公开价消费者、8项publisher回退/元数据；服务器Linux3.9共28项通过、无skip。Windows业务20项通过，publisher6项通过/2项POSIX跳过，不冒充Linux验收。PR沿现有pr-fast执行这三组，无新增workflow。

两份源码于北京时间2026-10-12 11:14受控发布，19项保护哈希保持，服务健康。下一原11:50:30自然周期等待实际自动清缓存及同周期公开价读回；部署/隔离续会话测试不代替实际使用验收。09:49旧拒绝原始响应未保存，历史原因仍unknown，不据新规则倒推；当前原账号真实清缓存成功说明现在并非持续无权限。

`SOURCE-MAP.json` 只记录局部活动映射，其余FC保持legacy-unreconciled。不能从旧根目录worker或main整包覆盖生产。重跑只读检查；再次发布或回退须重新取现场基线和空闲状态，经原publisher，不重放原失败业务操作。配置/运行数据/凭据不入Git。
