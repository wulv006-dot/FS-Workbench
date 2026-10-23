# FC双向定价修复

当前状态：候选已实现；本地核心和调用方回归通过，正式CI、生产切换及新自然周期分别验收。当前线上仍为旧版，不能称已恢复跟涨。

## 原因及修复

原默认价为`max(floor,min(hold,anchor))`，当前价hold构成上调上限。Hermes可通过原evaluate提出更高价格，但原提示仅要求在hold高于baseline时解释差异，形成保持偏向。

候选改为`max(floor,anchor)`，当前价回到可选hold，不再当上限。原baseline/hold/parity及全目录evaluate保留；Hermes可以选择保持、对齐或核验后的中间价。原.99尾价仍独立核预算，最终涨跌方向按实际目标而非主方案文字记录。

程序只证明执行可行性，不证明利润最优。Hermes必须比较同轮Lootbar、U7Buy和有效ItemD2R，按USD每实际交付K、赠送、抓取时点和条件优惠核可比性；Lootbar核心、U7Buy/ItemD2R第二梯队、IGGM/U4GM第三梯队用于定性判断。本任务不把0.6/0.7/0.8或质量分等研究权重用于生产，不给未经校准的固定涨幅或等待阈值。

ItemD2R原来在原任务完成后由observer读取，审核时来不及使用。本次复用原reader，在同一原采集工单内、报价前读取一次；原observer后续复用该原始记录，不重复抓取。缺失、失败、错run、条件优惠、错误币种/商品/数量、过期或捕获跨度超过5分钟时列为不可用，不补旧价，不停原合法采价链。

## 程序、模型及学习的边界

1. 程序核验本轮成本、汇率、优惠与商品数量，形成候选与全目录双红线证明。
2. Hermes比较保持/涨/跌，说明依据、反证和经营效果缺口；较小调整使用原evaluate核验后提交evaluated。
3. 原worker再核建议、来源、当前策略、预览与锁内CAS，沿原写价/清缓存/公开读回执行。模型无有效结果或建议被拒绝时，使用回执中的`model_unavailable_fallback_usd`，保持原`max(floor,min(hold,anchor))`及尾价/全目录证明的兜底，不因模型失联机械追高；成本保本上调和正常降价继续。有效Hermes建议可涨可跌，不受该失联兜底限制。
4. 学习用于复盘决策及错误；不自动改代码、红线、权重或权限。新规则、运行生效、模型掌握、自然变价和经营增利分开验收。

PS/Xbox共同池最新有效成本、共同基础价，PC独立；两条10%红线继续覆盖全部赠送、套餐、整数K及舍入。原120分钟、开关、来源server/revision3、原ID、UNKNOWN、锁、旧失败和暂停的本对话跟踪保持。

## 已有证据及待验

本次用户要求的新鲜核验只创建一次固定collect工单；没有auto_cycle、模型审核或业务写价。原observer取得同run三平台ItemD2R，原snapshot哈希不变。原始业务价格/成本/回执保存在忽略目录`.agent_runtime/fc-bidirectional-20261024/`，不提交Git或Notion。

本机候选源在`fc_bidirectional_pricing_20261024/`；Git维护为原`releases/fc-coins/fc-pricing-v2-20261022/`和原observer trigger源的本次增量。六活动目标与SHA见[SOURCE-MAP](SOURCE-MAP.json)。旧本机维护源保持，不能整包覆盖。只改这六个目标；模拟器同步pin新核心，不放宽版本检查。当前Hermes共享业务知识现场与旧本地副本不同，未用旧全文覆盖；每轮可信审核输入明确新双向规则。

生产切换前按现行HOTFIX提交确切清单并取得当前授权；沿原publisher、备份和CAS实施。正式CI、真实模型只读验证、部署、原自然周期及真实变价单独记录。用户指定后续自然周期手动验收，不恢复跟踪、不制造变价工单。
