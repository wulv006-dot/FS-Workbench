# Hermes统一HTML报告方法

用户2026-10-17明确要求：FS提供合法只读数据、冻结历史与证据、提取和归档，Hermes自己分析思考并按认可范本生成完整可交互HTML。日报、周报、月报、区间、定价策略与现有自动报告共用同一当前方法；用户亲自验收内容、排版、交互后才合并PR。

`source/report_method.py`沿用原私密教学包的固定路径、SHA、root/权限、非链接、大小边界，加载新13份材料。范本HTML、财务原文及构建脚本只存私有服务器，不上传Git。`skill_bundle.py`替换旧报告技能正文；`business_context.py`移除旧报告方法条目、读取现行技能与记忆，保留业务事实、验证、竞品和定价护栏。`controller.py`对所有新任务应用方法，保留事实准备、工具/预算/幂等、未知结果核对与原文存档，删去旧固定五段/四章节/Markdown指令。已有自动任务经过同一入口，原采集和夜间时刻不变。

`brain.js`为薄阅读器：校验原稿SHA、在无同源权限的sandbox展示原始HTML、保留原始下载；不改造为FS组件。历史非HTML报告仍按原流程读取。模型HTML不得进入工作台父DOM。实际测试中可信外壳下载完整原稿可用，opaque子框架内的下载按钮存在浏览器限制；不承诺任意模型导航绝对离线。严格内容验证使用独立离线浏览器。

定价策略是只读分析，具体新报价仍要求有效成本及可比竞品当前实价，不执行改价或预算操作。历史报告和失败证据不覆盖。方法加载和技术完成不等于用户业务验收。

验证：`python -m unittest discover -s releases/fs-dashboard/hermes-report-method-20261017/tests -v`；`node releases/fs-dashboard/hermes-report-method-20261017/tests/test_viewer.cjs`。浏览器实测加`--browser`（需Playwright）。沿用pr-fast现有工作流。

发布继续复用既有锁、CAS、备份、durable journal和原服务重载。源码与私有包逐目标SHA见SOURCE-MAP，父commit只表示起点；本次候选实际字节绑定独立执行manifest。旧v2因换行差异在inspect阶段拒绝、未写活动代码；v3以Desktop实际字节发布。没有将Windows模拟、CI或部署当作用户验收。
