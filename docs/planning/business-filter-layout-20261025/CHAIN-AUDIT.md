# 调用链影响核对

本次逐项核对活动服务器文件与私库源；“保持”指接口/参数/缓存兼容经代码及回归证明，不表示每个业务已重新运行模型或自然调度。

| 调用方 | 原入口与选择来源 | 处理与验证 |
| --- | --- | --- |
| 全局/工作区/旧版经营页面、链接状态与CSV | 三份business JS、shell；summary与actual-profit | 同一个b_site；显式网站传到原接口；实际毛利独立缓存元数据在PR474补齐兼容，旧链接、五站切换、锁定/解锁、八卡、逐日毛利、失败/权限、主题/手机均回归 |
| FC27明细与导出/日报事实 | range?mode=fc-detail，site_group | 补齐顶部all/main联动，主站限制时禁用网站细分；旧范围结果在绘图前检查；后台接口及独立商品/订单参数保持 |
| 经营管理台、负责人工作区 | management_facts.py、management_daily.py、boss_daily.py -> summary；不传网站 | 保留Admin全站、原Order参考及原归档身份；未把顶部选择传播到共享报告，避免全站降成MMOEXP |
| AI解读与Hermes服务器证据 | ai_advisor.py、/opt/fs-hermes-fc/fs_evidence.py -> summary；仅原日期/游戏 | 同上保持旧语义；无模型调用、无报告重写 |
| Hermes原生统计工具 | fs-readonly fs_query_native_statistics -> /range，不带mode=summary；目录固定snapshotId | native分支及native归档键均未改；不新增浏览器状态依赖或默认网站 |
| Admin原生与通用订单/产品/优惠工具 | 共享8767原/business/summary及各自原生接口 | 原接口未改；新site_summary仅在显式MMOEXP分支复用同一token读site266，不新登录；已实际读回网站与24小时标签 |
| 渠道效果、用户分析、客单追踪 | 原channel-effects/users/tracking接口 | 各自合同与快照保持；actual-profit原路由的范围/币种/覆盖回归通过，未传播b_site |
| 夜间归档/历史校验 | archive_jobs.py -> summary；未传网站 | 原归档身份保持；新显式网站另加admin_site隔离，旧全站参考不能用于新主站；原时间/频率不动 |
| RS当前积压 | 原rs-backlog，rs_site/类目/区服，不带支付日期 | 复用顶部网站；未支付上游明细冲突仍未知；不填零 |
| 流量页面、FC改价与其他业务工具 | 各自模块、会话/产品ID与合同 | 未改调用/参数/权限；shell仅经营模块版本和状态白名单变化，Google版本与重试检查保持 |

活动文件读回：range_api d1272749；daily_archive 5b664e3c；summary_bridge ad096146；management_facts 5449d1c5；management_daily 3547bef9；boss_daily 9b102d43；fs_evidence bd44a2f4；ai_advisor 7846fac3；archive_jobs cd2ba7d6；native fs-readonly 1faa15a6。完整源哈希与发布目标见SOURCE-MAP，诊断日志在本机忽略的.agent_runtime目录。

规则同步：正式业务基准新增本任务范围/兼容说明；服务器完整基准从活动4c1a2911版本追加，knowledge-load-policy只替换原wulv/FS/fs的retain_full_baseline兼容哈希。目录、角色、其他任务路由和已审技能不变；Git候选目录不冒称已发布目录，文件装配也不称模型掌握。

最终现场：五站销售、RS三站实际毛利和锁定/解锁已读回；原summary全站合同、Hermes原生工具available及完整规则装配通过。发布矩阵共12文件分两批，精确SHA见SOURCE-MAP。
