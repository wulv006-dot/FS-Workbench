# FC Hermes：DeepSeek 官方直连候选

用户已明确要求必要时改官方直连，提供本机Desktop/DeepSeek.txt，并批准 `call_3de5325a32b8446fa4e81952251a09d4` 的具体Key安装、FC聚合/脱敏外发、高/max、最大规格、正式检查后受控发布和全新wulv任务验收。原Key文件没有复制进代码、CI、Hermes容器、聊天或归档。Library附件读取助手中途不可用；用户随后明确本机路径，使用该路径，不绕附件传输限制。

官方 `/models` 已由这枚Key真实鉴权成功（08:04:10 UTC），模型为 `deepseek-flash` / DeepSeek-V4.1-Flash，上下文1048576、最大输出393216、支持low/high/max；本试点仅high/max。证据DEEPSEEK-DIRECT-MODELS-20261014.json；GET不发经营数据、未生成文本。原FS生产Python3.9到官方/models使用系统CA连接通过，无凭据401（DEEPSEEK-DIRECT-PREREQUISITES）；无新网络护栏配置、无购买或扩权。

官方资料：[模型发现](https://api-docs.deepseek.com/api/list-models/)、[Chat请求字段](https://api-docs.deepseek.com/api/create-chat-completion/)、[价格及型号](https://api-docs.deepseek.com/quick_start/pricing/)、[Hermes接入](https://api-docs.deepseek.com/quick_start/agent_integrations/hermes/)。使用 `thinking:{type:enabled}`，不把百炼enable_thinking参数发给DeepSeek。上下文是输入和输出的共同容量；每次请求仍指定最大输出，不私设费用/轮数额度。

[官方用户协议](https://cdn.deepseek.com/policies/zh-CN/deepseek-terms-of-use.html)涵盖API/应用集成，并对合法数据权利和内容审核作要求。本次范围是用户授权的聚合/脱敏经营统计和待人工核验建议；无通用shell、业务写、个人敏感字段或非法有害内容目的，未发现普通统计分析落入其禁止用途。具体输入/输出仍受供应商规则约束；不关闭审核、不用编码/变体隐藏内容、不跨供应商重放被拒的旧请求。此为新的供应商集成和全新正常经营调查，百炼原错误/Request ID保持用于正常核查，不承诺直连必然成功。

候选只改现有FS/Hermes接线：独立direct_provider.py仅原FS进程使用受控Key，固定api.deepseek.com、无重定向、无自动重试；复用原provider锁、model_calls/任务账本、19个只读工具和同一profile。原共享ai_advisor_model.py、range/daily/deep/boss及Admin会话源不改。Hermes只接任务短期token，不获得直连Key。

费用只有Token回执有可靠来源，未核供应商实际金额或USD/CNY换算。直连成功回执cost_microcny为null、UI显示费用未知；现有NOT NULL reservation.microcny用-1表示未获取人民币金额，不改为0。历史百炼行不改；新行同turn失败/未知不重放、成功幂等缓存不重复扣用量，跨任务允许用户已授权的费用未知。此候选没有新增金额拦截或账单服务。

原publisher新增精确7-target scope `hermes-fc-deepseek-direct-20261014`：proxy_gateway、controller、fs_inprocess、hermes_worker、runtime-config、Hermes index和新direct_provider。沿用原锁内CAS、FS admission/SQLite/共享provider锁、保护依赖和备份/回滚；仅原FS和Hermes重启，Admin/boss/采集频率/价格写保持。新代码文件允许beforeSha256为空，6份活动源必须精确基线。Key安装独立于Git/发布manifest：目标 `/var/lib/fs-hermes-fc/fs/secrets/deepseek.key`，root:root/0600、父目录0700，不在容器mount内。

回退：使用本次原publisher备份恢复这7份代码/配置和原FS/Hermes，保留profile、FS任务、原账本/证据；删除这枚专用Key撤销持久访问。失败请求不重标成功/零费用，不部署旧整包，不恢复旧两小时全页快照或旧顾问生成。

准备基线PR131/main d3cf8f0ec892386cacccc73c44caa23bd098d812，独立候选 `.agent_runtime/hermes-deepseek-direct-qa-20261014/`。叶适配10项Windows测试已通过，新增5项账本/接线与3项精确发布范围测试。组合Windows243项=239pass/4实际POSIX门禁skip；正式Linux/固定官方SDK high/max、原摘要和真实新任务均按各自证据另验。初次旧百炼1M边界2fail、后续新测试类名/辅助fixture问题已修正，旧PR131冻结保持。独立复核发现原生请求多7字节边界问题后，已用同一prepare_request构建器在reserve前校验，精确10MB+7拒绝/0账本/0发送与扣7B后恰好10MB成功回归通过；不增大上限或记假0。未把本地准备或无费用GET当真实调查完成。
