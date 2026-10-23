# 来源梯队：独立模拟模块

状态：只追踪、研究及模拟，不应用到真实业务。最新用户指令覆盖此前“新增来源直接参与改价”的准备方向。当前没有生成或发布 `fc27_quote_engine.py` / `automation_policy.py` 替换文件，未改模型、现价、原利润护栏或球员价格复验。

模块为 `fc_reference_tiers_20261023/source/reference_shadow.py`，不依赖生产报价、模型、推荐或写价模块。没有网络、文件写入、登录或调度逻辑；由主任务的独立observer选择调用，不接到原calculate/check_write链。

## 输入和输出

`simulate_reference_tiers(rows)` 接受同一个原run的完整旧12行或新15行观测，拒绝混站、重复、错平台、错游戏/商品或混run。核心Lootbar、第二层U7Buy/ItemD2R、第三层IGGM/U4GM均保留可见；分类比较优先最高可用参考层，不把第二和第三层混为等权。条件价不采用，ItemD2R来源URL若实际属于IGGM则不选，避免改名复用来源。

`experimental_scenarios(rows, *, now, storefront=None, maximum_age_seconds=900)` 用于三组独立加权实验。原12行与ItemD2R旁路3行只能在独立observer内合并，不能写回原runs；对应行的run_id须相同。now须带时区，观测必须不晚于该时点，最大年龄不得超过900秒；历史研究可使用原观测对应时点，不把旧价当作当前新价。

实验参数明确标为“示例研究参数，非用户指定，非生产规则”：Lootbar权重0.6/0.7/0.8；其余份额按第二层每站质量分2、第三层每站1，在本轮合格参考中归一化。这只是三组待比较模型，不代表已确定最佳权重或已证实经营收益。

每平台输出实验 `weighted_unit`（USD/实际交付K，包含赠送）、相对同期Lootbar和本店实际单价的百分比差异、实际参考权重及缺项原因。结果不输出生产售价建议；complete仅表示该次观测可比较，不表示业务改价获准。若核心缺失，不用其他站替代核心，也不生成加权候选；参考全缺失同样不臆造剩余权重。

错币种、负值、非100K规格、过期、未来、未带时区、条件价及未可比来源均拒绝或明确partial。IGGM缺失会明示，并且不会补历史价；部分参考合格时可以保留partial实验结果，本店价格缺失则本店偏差为空。本店比较也要求同run、USD、同平台、合格时间及含赠送实际交付量。

全部实验均标 `margin_redlines=not_evaluated_requires_original_prove_catalog`。没有调用利润红线证明，不能称加权候选已通过10%双红线、所有套餐/自定义数量、优惠结构或尾价约束。今后若要实际应用，必须另有明确授权，接回原完整证明及发布验收。

## 验证与边界

本地22项、Linux隔离临时目录22项通过，覆盖五站共存、完整旧12兼容、条件/错身份排除、同run覆盖、含赠单位、核心必需、三个情景归一化、缺IGGM、时效/未来、错本店平台/币种/时间，以及无生产I/O/模型/推荐/写价调用。域名回归使用本项目实际 `https://www.lootbar.com/game-coins/fc27`，没有放行未经核实的其他Lootbar域名。正式CI和长期真实样本效果由主任务另记，本子任务未声称完成。

只读核对生产源仍匹配最初活动基线：engine SHA `7c8980894a16b3a539d30ac0cc221df4d629a02edec00bdb4a00166544db36cb`，policy SHA `317b657817701965147068629d7a3c97605e537ecd969c7f6f8e13ef1995b9d2`。

本模块SHA `4e1763c6d83c0d127fa1f21cfe82d19820c2d0987dec04d81038f7995d09b7a1`，状态及实验参数见同模块 `SOURCE-MAP.json`。没有修改其他Agent负责的collector、snapshot、UI、prompt或publisher。
