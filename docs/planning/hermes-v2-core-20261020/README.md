# Hermes V2 首批实施记录

执行范围按用户2026-10-20当前消息：先W0–W3，后W4–W6。当前分支实现受控学习、有效输入和模型配置回执；不包含供应商系统、Jev/Octop迁移、生产策略自动修改或写价。

代码沿用当前活动controller、任务SQLite、独立非root研究worker、模型代理/费用账本、报告归档及原发布器。候选和发布状态放在原任务数据库的向后兼容增量表，任务冻结后保持原知识版本。自由文本经验默认L1人工评审，正式研究和学习复盘都没有业务写入工具。复盘身份只有显式可见来源、独立事件/attempt，复用原代理发送无工具请求，不加载任何home或原生memory。

只读基线：主线初读c4e65661，后续已核361caad3（保留PR250修复）；活动worker UID9876、只读容器，现行方法manifest为950f429d…，报告方法v1.5.1保持。当前数据库有7张原表，没有同类学习注册表。私有基线与完整逐文件哈希存.agent_runtime/hermes-v2-core-20261020/。

W0原准入对账：原请求a27c149fe2ae3bdf8ea9e4154772ee60处于NEEDS_RECONCILE，原幂等键找到run_cff57ab074de4973aa9190bdcaaff9e6。ready=false、模型预留0；原stop返回409，官方代码说明无活动agent/task。FS仅将该原准入本地取消并绑定原run，保留原controller_HTTPError、原生持久queued及首次unknown回执。不重放、不称原生取消成功或业务成功。

接口沿原同源管理员POST入口，kind=hermes_learning，支持list、enqueue、review_model、review、publish、revoke、pause/resume。服务端绑定owner/FS scope；发布/撤销校验expected_manifest，使用原FS管理员身份与明确reason。review是候选写入；review_model是显式发起一次受控模型复盘，成功也不会自行发布。暂停仅影响新学习入队，原研究与已发布知识保持。撤销保留旧知识和受影响任务索引。

模型验证按四级状态记录。成功但未返回档位回显仅为accepted_no_effort_echo；实际后端版本未返回时写unknown。出站载荷hash、请求档位、模型别名、提供商响应ID与用量可追溯，不把推理正文写入知识库或普通审计。现有协议字段仍原样续轮。

本机检查：21项新增回归、23项原direct-provider回归，共44项通过。首个head CI因修改了旧固定字节对象而失败，已恢复全部历史对象原字节，独立V2候选head bc685194的正式pr-fast通过；随后补充可见正文提取与方法基线校验，须按新head复验。完整服务本机导入因Windows无fcntl未覆盖，不能称Linux集成通过。PR/CI、部署、真实知识任务、真实多轮模型、经验发布与撤销均须各自回执更新本记录；当前不能称上线完成。

现有任务基线报告只确认已完成，用户验收状态unknown；未把它冒称认可样本。附件在首次读取后临时路径消失，已保留主文件读取回执；不得把该读取回执中平台截断的部分当完整附件归档。

安全重跑：`python -B hermes_v2_core_20261020/test_core.py`。测试只使用临时库和合成响应，无生产写入。真实review_model会消耗既有模型额度，不重复提交运行/unknown事件；publish/revoke按原manifest核对，不盲重试。一次性旧准入对账脚本不重复执行。
