# 新客复购观察期文案

用户明确指定两列：已满观察期新客、未满观察期新客。保留7/14/30日观察窗；同表复购率和空值说明去除“成熟”术语。增加分母说明，不改变观察锚点、成熟计算、客户范围或任何接口。

source/data-workspace.js 是新版本；原活动SHA afff372192a3c4bf7ff4dee2410a61b9f80a67e89b938a8b4632cf7545f39fcf，候选SHA 916087de9ef664ae09ffc0be279e431aec5850786d474834784ee378d2b15dab。保留原资源不覆盖，新不可变版本 workspace-native-20261006-916087de9ef6，只切数据工具页引用。路由沿用原同源session鉴权、方法限制和响应类型。

node tests/wording.cjs 覆盖表头、计数与百分比不变、未满和零客户状态；node --check source/data-workspace.js。
发布复用既有UIpublisher、锁、CAS、备份及独立读回。上线/验收状态见后续ACCEPTANCE.md。
