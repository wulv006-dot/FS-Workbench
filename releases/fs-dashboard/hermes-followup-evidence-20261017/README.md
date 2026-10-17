# 冻结证据追问兼容与学习补充候选

仅本地候选，未发布、未调用模型。旧 e947 冻结源和已完成报告不改。SOURCE-MAP.json 列出三个实际目标的活动 before/候选 after SHA。

`source/continuation.py` 基于活动 `d453b3…bba0`，与历史规范副本逐 SHA 一致后单独接管。只增加当前 ResearchBook 已注册的六个精确来源标签映射；真实任务新增的13条证据覆盖其中五类，另补现有 market 工具标签。未知来源仍拒绝，原 calculate/capability/native 等分支保持。`cache_rank` 对未知捕获时间使用独立排序标志，保留原 null；先比较终态，再在同状态下优先已知时间，未知时间同类以原 evidence_id 确定排序。已知时间仍须包含时区。全部原始证据、ID、日期和权限保持，缺失工具查询只登记原冻结集合不包含，不重新读取。

`source/learning-loop.md` 与 `source/ops-report-family/SKILL.md` 分别复制已发布6589包的精确原字节；现场只读 SHA 和原18文件清单已核一致。末尾追加 Astra 审定的“同假设/同窗口迁移”“事件/发布/获知/行动四日期”两条规则，以及用户纠偏要求的经营销售主线、履约售后与问题单队列定义；日期标签为2026-10-17。现有 business_context 加载器已包含这两个实际路径，测试证明两追加内容进入知识文本且改变知识SHA；原18路径和引用保持，不新增读取源或定时任务。methods-addendum.md 仅为审阅索引，实际生效依赖上述两目标未来受控发布及新任务的知识加载回执。

验证：`python -m unittest discover -s releases/fs-dashboard/hermes-followup-evidence-20261017/tests -v`。本地8项通过；另用环境变量 `FS_FOLLOWUP_PRIVATE_EVIDENCE` 指向受控本地原74bb任务evidence.json完成同一测试中的真实34证据读回：全量对象/ID/四个null逐值不变，13条新source均可映射。原件未进入此目录。owner、period、hash、settled状态四个守卫函数的AST逐项与活动原件一致。

尚未进行线上追问、模型复测或真实日报/周报业务验收。后续与报告分类兼容统一受控发布，由父任务协调；不单独发布主题模板。

本次同步修订的两份真实教学报告仅保存在获准的私密目录并传入既有FS学习路径，不在代码库内；发布清单独立绑定其SHA。真实样稿及新任务产出需独立验收。
