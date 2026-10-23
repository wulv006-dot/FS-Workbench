# 二期最小后续确认清单

这是可审查的候选范围，**当前没有申请或执行上线**。本次只获离线补齐及只读隔离实测；用户另允许向“跟进 Hermes 知识迁移验收”仅回传结果，不包含施工、合并或发布指令。

| 具体动作 | 必须固定的范围与验收 | 当前状态 |
|---|---|---|
| Git版本 | 本分支完整patch/文件哈希，最终main组合及正式pr-fast；独立PR/合并 | 本轮未commit/push/PR/merge，基线冻结为26aab959… |
| 隔离原生镜像 | 精确原镜像8251bc53…及工厂源5e51f2b4…；三文件上下文，只改一处工厂接点并加入fs_native_entry；读取构建后的两源SHA | 构建/校验入口已写，缺实际Linux Docker构建证据；不使用未经源读回的镜像 |
| 四个主机载荷 | fs_readonly入口只加两行、新knowledge.py、保留所有非native策略字段、Desktop unit只替换镜像；原文件/缺失CAS及四个最终SHA | scope/离线完整失败恢复已通过，未批准或生成生产ready manifest |
| 服务操作 | 仅fs-hermes-desktop.service、hermes-dingtalk.service及必要daemon-reload；共享在途调用自然排空；短暂中断两原生入口 | 真实在途/lease/现行SHA须发布前读回；不重启worker/range/Nginx，不清锁或取消任务 |
| 新FS会话 | 确定当前实际profile、desktop/tui及一个空新session；固定原生task；只给测试实例两读工具，保持普通会话能力 | 真实路径/平台已核；未挑选或切换用户会话。示例disabled，不可直接覆盖运行配置 |
| 无计费真实入口 | 新会话实际tool snapshot、正式索引/模块/来源hash、原system prompt和task/use回执；实际调用方证据 | 官方运行边界9项已实测；用户UI与完整agent/provider初始化未验证 |
| 真实模型验收 | 只在上述通过且用户确认模型、总请求次数、输入/输出及美元预算，并有实际执行上限证据后进行一次复合题 | 本轮0调用/0预算；不自造费用承诺、不用max_iterations冒充费用上限 |

批准时可集中覆盖上表的具体选择、冻结源/前值、只读验证及允许的后续步骤；同一范围不重复询问。任何新凭据、权限、安全配置或增加外部消息范围仍独立核授权。本表不授权FC公式/利润底线/业务参数/教学/开关/调度、全局记忆、飞书消息/群、Notion写入或老D原任务变更。

回滚只使用原发布operation_id/journal、前值备份及CAS：恢复四载荷与旧不可变镜像，保留所有DB/消息/队列/知识/回执。启动结果未知或出现原生lease，必须先对原状态；不换ID重复发布、不取消活动任务，不停止业务服务来凑排空。模型使用与长期泛化另验。

详见[实现与真实隔离边界](PHASE2-OFFLINE.md)、[源映射](PHASE2-SOURCE-MAP.json)及[机器结果](PHASE2-RESULT.json)。老D/Notion只由原维护任务消费同一change_id候选，当前不新建第二维护任务。
