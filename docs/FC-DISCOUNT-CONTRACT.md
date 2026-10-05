> 首次入库更正：以下为冻结候选的历史记录；当前批准/owner/FC业务类别/NBA后置与未验状态见 `docs/collaboration/CURRENT-STATUS.md` 和 `READINESS.json`。旧upload声明不代表当前条件授权，静态/合成记录不代表生产放行。

# FC Coins 降幅范围功能

已验收依据为原工程 docs/fc27-coins/discount-config-release-20261005/README.md 与source-sha-verification.json。本候选纳入该发布8个最终源，逐文件SHA已与当前线上重新核对；不收该档案的真实报价、读回、日志或完整ZIP。

降幅按分档min/max约束原选值，不随机；默认保留旧行为。保留10%成本毛利保护、PS/Xbox/PC与赠送口径、写入确认guard、管理员写限制、配置revision与schedule_revision、busy禁止修改、同值no-op、冲突/失败不覆盖。quotes保留归一化规则及规则SHA。不得由候选准备触发改价、清锁或重放任务。

原交付记录126项隔离后端、210行Python/JS、浏览器交互和中文布局，以及原自然周期成功。这是原验收记录，不等于本轮重新跑过这些全部检查；本轮独立Windows验证结果见TESTING。真实登录后生产点击保存没有在该交付中实施；Linux权限/文件锁未由Windows模拟冒充实测。回归before_engine仅用于验证默认完整结果保持一致，不是部署输入。
