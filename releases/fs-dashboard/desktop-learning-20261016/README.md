# FS 读取 Hermes Desktop 学习成果

范围：只替换 business_context.py。原 controller/worker/模型/权限/桌面 profile 均不覆盖。新任务读取现有 Desktop 业务约定及固定清单中的技能方法文档，生成包含每份文件 SHA 的完整上下文，沿用原任务的 desktop_business_sha256 冻结与缓存键。运行中任务不改写；后续更新在下一任务生效。

读取经营汇报、日报周报月报体系、数据闭合检查、任务验收、竞品监控、定价策略，以及 PPT/表格的方法说明。只读取白名单 Markdown 与报告 HTML/CSS 模板，不运行脚本、不加载样例 JSON、不授予工具能力，不将模板中的样例当业务事实。现有 Humanizer/Marketing 加载继续保留。

文件必须为当前服务身份所有、非组/全局可写、非链接的普通文件；单文件 128 KiB、合计 256 KiB；读取期间变化拒绝。方法资料缺失会在实际加载清单中体现。Git 只保存加载器、测试和部署合同，不保存用户训练文档正文、业务数据或凭据。

发布：desktop-learning-8641c3d1a740；manifest SHA 5fb607b94143665b0b0cab899d6ceedb0d257efd34ad9d1dd8c65518faa0a341。复用已核哈希的发布基础与 admission/provider 闲置检查。只重启 FS controller，不重启 Desktop 或 Hermes research runtime；保护当前 controller SHA，避免覆盖并行部署。失败恢复原模块并读回。

验收分层：6 个离线用例通过；服务器候选实际读到 17 份文档。还需部署读回、真实任务加载回执和学习应用效果。文档被载入不等于分析质量通过，也不等于模型微调。
