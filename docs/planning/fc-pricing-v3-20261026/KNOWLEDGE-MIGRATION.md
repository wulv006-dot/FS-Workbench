# V3 知识与消费入口迁移清单

本轮是用户明确授权的FC定价规则替换。迁移须随实际V3发布和控制权接管生效；本清单尚不代表服务器知识已加载。不改无关FS规则，不新增Notion或外部消息写入。

## 本轮定位

| 当前入口 | 已核内容/风险 | 迁移要求 |
| --- | --- | --- |
| 活动 `hermes_pricing_bridge.py` | 105–136一段同时含baseline/hold/parity、80/15/5、owner ceiling和临时ItemD2R追加覆盖指令 | 重写为一份五策略工具合同；保留审核身份/会话；不能在旧段尾再叠一层V3覆盖 |
| 活动 `pricing_state.py` | 导入POSITION_VERSION，按旧decision_receipt版本判有效 | 使用V3明确schema/控制权和证据状态；旧历史仍可读 |
| 活动 `pricing_simulation.py` | 核核心SHA并重算baseline与原quote result整段比较 | 迁入V3快照与模型/策略版本pin；保留历史模式隔离；不能关闭版本核验来通过 |
| `knowledge/index.json` 的 `fc.pricing.reference-weighting` | 本轮远端读取仍为current/effective，revision `fc-reference-weighting-20261024-v2` | 控制权切换时转archive/retired，新增唯一V3生产经营合同及supersedes；保留旧来源哈希与历史证据 |
| `fc.pricing.constraints`/`fc.pricing.decision-v15` | 当前双红线与2026-10-22决定 | 财务规则保留；V3地区重放补充有独立版本，不将其标为已废除 |
| `fs.pricing.parameter-identity` | 指向旧business-baseline §6，其中可能含旧尾价等经营要求 | 区分参数身份与已替换决策段；保留身份来源，移除生产消费中的旧选择器/尾价控制 |
| 全量业务基准装配 | 完整基准可能绕过分段index进入实际模型输入 | 只更新FC已替换段落及其原兼容哈希，不替换共享取数、归因、其他游戏规则；读回实际任务加载的文本/版本 |
| 本地/远端AGENTS及旧FC合同索引 | 含80/15/5保持、旧临时策略生效的历史时点 | 当前入口加V3精确指向，旧材料以历史时点保留；不能仅改Git就称服务器教学已更新 |

`knowledge/index.json` 明示候选与published索引分离。应沿现行 `tools/knowledge_closeout.py plan` 准备差异/哈希/冲突检查，实际服务器装入沿原publisher和既有授权；不得直接把候选状态改成已发布。

## 分层验收

1. Git：当前索引无两个同时有效的生产选价合同，旧决定和财务证明保留。
2. 文件：服务器活动源/实际装配版本匹配本次载荷。
3. 真实模型：本轮真实审核任务使用V3五策略及地区信息，未夹带旧钉价覆盖。
4. 持续应用：后续自然周期另验；文件存在、装配成功或一次模型答复均不代替长期学习效果。

## 2026-10-26候选装配核验

以服务器实际完整基准（原始SHA `c0b867d19e5316e77d3042d1437724c30742723a85f8355e11ac7e143f423a56`）为主，候选位于`fc_pricing_v3_20261026/source/knowledge/`，具体当前SHA见`MIGRATION.json`。保留共享取数、Aion2/PMax更正、客户、产品、逐单财务和互斥优惠；原全文归history，生产旧尾价、固定Astra、加权和回摆条款从有效正文撤下。十个索引条目改指新完整基准，旧加权归档，新增独立V3教学条目；候选索引仍为candidate，RELEASED未变。

独立教案使用ES下单时新客标记，订单按已核创建时价格窗口绑定；最终正常积压为2026-10-26 18:49只读5单/4950K上界，旧Admin单源287单/55275K不能再当当前供给压力。生成、逐段保留检查和索引selector检查通过，尚待实际publisher、兼容哈希、published索引、worker加载与模型真实使用。
