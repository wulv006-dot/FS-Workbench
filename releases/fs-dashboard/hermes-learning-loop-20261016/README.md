# Hermes学习闭环修复

负责人：吴律；施工：Codex。用户2026-10-16要求纠正规则自动发布、新FS任务采用并在报告留版本；以附件V2为施工依据，通用接线覆盖日报、周报、月报、经营目标分析和独立定价研究。

本目录source是依据当次活动源逐文件SHA建立的新维护源；旧归档、原生Desktop会话/记忆、原报告/证据和费用不改写。SOURCE-MAP.json给出精确基线及新载荷。原E仓库无Git写入。

- controller在检查旧稿复用前发布内容寻址知识快照并持久绑定request，PREPARING也具备版本。相同request_id先返回旧记录，更新知识不重放。运行中任务读取原快照。
- 已审核的专用业务profile MEMORY/USER与Desktop业务约定和文本方法显式进入任务系统提示。生产skip_memory=True只关闭共享home原生通道；显式业务加载必需、带来源和SHA。隔离False试验证明原生可读，但其共享home重载不能满足每任务冻结。
- worker验证组装输入，原网关在实际主模型/摘要消息发送前再次验证完整冻结知识，响应后留provider回执。prepared、assembled、provider_response_success与负责人质量认可分开。
- 单日主对照可解析，前日/同星期分列；当前图表可独立保留，参考率使用经原估算器验证的对应单日来源。中文原分析保留、正文默认展开，历史动作及全部复盘日期不因重开改写。
- 日报读取范围补到14完整日，缺日仍如实标明。经营研究high，调查/定价max；工具、权限、业务参数、模型路线和调度保持。

直接检查：`python -X utf8 -m unittest discover -s hermes_learning_loop_20261016/tests`。runtime_check.py只在固定官方镜像、独立home、禁网络中运行，不调用模型。check_original.py使用本地受限原证据，可重跑转换，不自动发布或调用模型。

受控发布沿既有release_navigation.py，只增加本范围精确目标映射；锁、数据库admission fence、CAS、备份、在途任务与回退保留。不重复apply成功operation，不覆盖新会话数据库。生产和真实验收状态见docs/planning/hermes-learning-loop-20261016/。
