# Hermes V2 首批生产验收 · 2026-10-21 北京

PR #251 已合并，merge `dffb16550733b4ae038df973c441821e3ad96b6d`。用户明确批准九目标后，原发布器于2026-10-20 23:57:45北京执行；manifest SHA256 `a07f62eabb1c13fce157f34f20f8add9e8a88c693536bfa6ea6a6365ea3a7674`。九目标活动哈希全部匹配，两服务active。备份 `/var/backups/fs-navigation-20261006/nav-20261020T155745Z`，保留原journal/intent/锁/CAS/回退；未改价格、业务策略、调度或开关。

真实已登录Chrome的wulv入口刷新后显示“已连接云端 Hermes”和本次任务。后端同一管理员路径及学习接口200、auto_publish=false。私有详细回执均在 `.agent_runtime/hermes-v2-core-20261020/`，不加入Git。

| 验收 | 真实结果 | 边界 |
|---|---|---|
| 正确知识与事实 | 请求 `5046e58a04ea0cb200e55840591897ac` 完成；显式冻结当前方法1.5.1、owner/FS、知识及工具hash；重新查询10/18和10/19平台经营结构并绑定证据计算 | 原稿仍有无依据的65美元观察线，以及将PS降幅与主盘分母混比的问题，不能直接当经营质量全部通过 |
| max与多轮工具 | 上述任务2次真实模型调用，6次工具；追问 `7315baecd5306b5df83ee7a208643893` 为7次high模型调用、多轮read_evidence/calculate | 所有提供商回执为accepted_no_effort_echo；实际后端版本unknown，不宣称精确内部推理档位已独立证实 |
| 经营修订 | 追问用同一冻结支付明细复算PS对明细净降额的贡献104.9%，保留PC/Xbox抵消；删除无依据65观察线，游客身份与原始新老客标记分开 | 原始失败判断及原稿保留；修订未执行策略、优惠或写价，收益未验证 |
| 经验发布 | 经验 `7774e2446aaa9b37c3925b0e928f75b21c600d032906dd2811701c95787401b1` 经显式管理员审核及manifest CAS发布；追问实际输入含其ID/hash | 是人工审核的方法候选，不是模型自动发布；未保存业务现值 |
| 撤销 | 同一经验通过原接口CAS撤销；新任务 `c5579ee06e84be764f3a1ecd51dc8450` 完成且正式经验列表为空；旧追问仍保留原经验引用 | 旧任务、原知识版本和来源不删，不把撤销当修改旧报告 |

学习模型试验事件 `1aa47ab29f5f3f1094e7e6c6e29269dac6595a81bfd3eff18031225a1c4ff3cf`：一次high模型请求成功结算，随后因applies_to返回数组而非文本被候选校验拒收。事件保留failed，未重放。该失败不影响已完成研究；不得把这次模型候选生成记为成功。后续修复位于 `hermes_v2_review_repair_20261021/`：明确字段类型，保留脱敏已结算回执，允许认证审核者在原failed attempt上人工修订候选，仍不允许unknown绕过对账或自动发布。

代码验证：PR251最终head `635fa71f9cb7600982e8f99b3b97f2a469e9032d` 的正式pr-fast run39451875865成功；45项本机测试通过。修复候选5项回归通过，部署状态另记；不能用本记录替代其发布。

未完成：独立持续会话、自然夜间周期、真实取消/进程中断及长上下文压缩验收尚未完成。W4已核实际价格引擎、策略和快照读取路径，草案/模拟工具未上线。用户已重新提供 Downloads ZIP，完整 W4–W6 及原包已恢复到 attachment/；后续实施见 STRATEGY-DELIVERY.md。

安全重跑：本地 `python -B hermes_v2_core_20261020/test_core.py` 和 `python -B hermes_v2_review_repair_20261021/test_review_repair.py` 只用临时库及合成响应。真实模型/发布/撤销均非普通可重跑检查；先按原请求、event、attempt和manifest核对，禁止盲重试。

## 同期真实失败修复回执

PR #252最终head `d9bf768dd07c446036ca2b684fc4bba76b46ffc4` 的pr-fast run39456694573成功，5项定向及原45项核心检查通过；正常合并 `d9276b8ccebe6412de725cd6a621f2e0c4360732`。单文件learning_service修复沿原发布器上线，manifest `7b21aeba345cd305a4a06ca99081e7f2165ff9fd5f7b310f2115f60f6ce1fff1`，活动SHA256 `6ce14f11825de4c97449352e6d0aac456e1cdd10d5326ba6cc14348e01664ef4`，备份 `/var/backups/fs-navigation-20261006/nav-20261020T162706Z`。独立读回1目标+385保护对象全匹配，两服务active，无业务worker/timer操作。

真实原failed学习事件经认证人工修订：保持原attempt `9c4a1fcf8434b73c1b20694ea18b04f9`、previous_review及原模型账本，原模型调用数仍1；仅候选，未发布。新学习事件 `2efc4fbce49971def0b800bab760eff48cdd837d5baa090ecdc25790fba348b5` 用修复后明确字段类型的提示，经一次真实high请求成功生成L1待审候选；提供商ID `672e0bbb-bff8-4c8f-b66a-bbbe7387633c`，5057 tokens，accepted_no_effort_echo，未自动发布。当前正式经验manifest恢复为空，三条候选保留，收益均unverified。

第一批用户指定终点已取得真实证据；不等于W0–W6全部验收。其余未测项及 W4–W6 另行实测。
