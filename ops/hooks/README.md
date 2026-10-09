# FC Coins / 经营快照 Hook 增量

唯一执行规则：[HOTFIX](../../docs/ops/HOTFIX.md)。这是单模块增量，精确映射见 [SOURCE-MAP](SOURCE-MAP.json)，禁止用本目录或 main 整包覆盖 FC。

已启用：原五分钟巡检的错误、worker 心跳、数据新鲜度、任务时限检测；自动发送前按平台读取独立控制，过期/不可读则拒绝新自动写入。原队列、业务锁、来源验证、账本、操作 ID 与人工入口保留。快照沿用实际 atomic_snapshot.validate 与原子切换，失败保留合法旧完整版本，缺失不补零，不串日期或权限。

固定恢复只有有界重读和解除本系统暂停原因：用户仍启用、当前配置版本、两次正常观察、无 UNKNOWN、独立安全检查全部满足；先标 AWAITING_CYCLE。已错价而无法保护售卖时标 ESCALATED 和 sales_protection_status=UNAVAILABLE，不宣称风险已隔离。

2026-10-08 北京16:24:08，原定自然操作 86e39e89-e96a-4bf8-af02-f187fc0c573f 三平台 confirmed，公开读回 verified。没有手动触发改价，业务节拍与服务 PID 保留。首次FC发布因旧任务专用球员条件自动回退四代码文件；限定 --hooks 验收后重新发布，原发布分支条件和失败证据保留。

17:30现有钉钉机器人接入服务器：真实隔离HTTP503及恢复 → 原检测/状态/outbox → 原发送器 → 钉钉，两条provider errcode=0；用户明确确认异常与恢复均收到，重复调用新增发送0。故障源为隔离服务，没有在生产制造故障。私有配置root:root0600，验收状态绑定实际配置哈希；凭据不进Git或报告。测试发送入口独立，安装真实机器人后运行检查也不会使用生产地址。直接Linux检查31项/0skip。

自然告警已接入原五分钟timer，服务器持续链路不依赖个人电脑；电脑实际关闭、整机失联外部心跳、前端DOM/日期脚本、准确区间逐查询事件、浏览器/缓存/worker修复、SKU停购/价格补偿未覆盖。无可用无头AI，AUTO_PATCH_ARMED=false，额外预算0美元。

直接复查：python3 -B -m unittest discover -s ops/hooks -p 'test_*.py'。pr-fast复用hooks分组。CI为隔离检查，对root所有权用合成输入；实际UID11027/group11028和只读控制绑定已用原writer镜像另验。

机器人配置位置 /etc/fc-ops-readonly-monitor/hooks-bot.json。配置轮换后必须重新验收该地址并更新私有bot-acceptance.json；仅配置存在不算实收。每轮最多两条，未知写入告警携带原操作ID，区分排队、provider accepted与用户实收；前次验收不保证每条未来消息已实收。签名沿现有钉钉接口，不挪用Aion2机器人。

RPG共享接口：collector.persist（状态/去重/outbox）、hooks_notifier.deliver_bot（已有渠道）、hooks.can_resume（纯恢复条件）。陈超按第二份方案接自己的scope、writer/锁、来源、原ID、读回、publisher、售卖保护。本次没有安装或修改RPG业务规则，FC路径和价格规则不能套用。

生产重跑先核现场SHA与原操作ID，发布不能盲重放；只沿原锁/CAS回退代码，保留DB、价格、队列、锁、回执与暂停状态。

2026-10-08后续评审修复：必需FC API/worker/gate及两个HTTP身份门禁失败或未知，service_unavailable错误码进入三平台写价阻断；独立图库/经营故障继续只影响自身范围。升级事务只回退本次已替换的代码，删除本次新增目标并清理自有临时文件；保护读回失败也进入回退。服务探测→report→controls→原writer guard和五次替换/最终读回中断共32直接Linux检查/0skip通过；故障仅注入独立临时目录，生产FC服务未停启。例外回退不提供进程被kill或断电时的事务恢复保证。

2026-10-09 中文告警和RPG只读接入：复用同一notifier、outbox、五分钟巡检和publisher。告警说明异常、业务影响、处理建议与北京时间，主动关闭的任务单列；恢复巡检不冒称改价恢复。09:23中文演练用户确认收到且能看懂，旧事件不重发。RPG接实际d4follow.service/p2pah-srv-exec.service和现有GET /api/state的当前任务失败；有已确认游戏字段才标D4/PoE2/Aion2，其余明确共享任务。35直接Linux检查/0skip通过；RPG源码、配置和PID不变，不改业务规则、价格、开关、调度或接入自动暂停/自愈。不覆盖进程重启前任务、逐行失败/未知写入和现价安全。既有08:11巡检HTTPS解释器修复的publisher一并按现场源码回补，单位本轮未再修改。实际收据与自然读回保持本地，生产上线与PR合并分别记录。
