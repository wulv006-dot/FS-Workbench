# 经营管理台：参考布局重建与每日 Hermes 分析

状态：经营管理台新入口已发布，15 项目月累计核心数据及当日 Hermes 建议已手动读回。首次自然夜间运行仍待观察。

## 范围

由 dot 云端独立施工，参考用户提供的经营管理台静态页面。保留总览、15 项目详情、一级/二级目标、周拆解、逐日图、半年趋势、健康度与本地目标沙盘。正式目标采用现有 DY 目标。原样例的实际值、演示密码及固定“10/11”时间进度不进入生产计算。

新后台只通过已部署的 FS 汇总读取器读 Admin/Order，不新增凭据，不获得写订单/写价/修改目标能力。已有 FC 报告入口、技能、模型供应商和费用账本继续复用。管理台任务以冻结的全项目汇总为输入，使用原生 Hermes runtime、高档推理与已有受证据约束的计算器。

## 数据与时点

- Admin 主站金额、订单为主；其他 Admin 指标保留原统计范围标签。
- 参考利润率来自 Order。预估利润 = Admin 主站金额 × Order 参考利润率。不是实结利润，也不能作为自动改价采购成本。
- 缺失不置零；来源过期、日期/网站/项目合同不匹配不用于填充。
- 等待尚未完成的 Order 补源有界进行；未完成时保留已证实的部分事实，不编造利润。
- 月预测为“已过完整日均值 × 月天数”的线性情景；不冒充生命周期预测。
- 逐日图和每周实际采用已读取的 Admin 主站逐日事实；缺失日期断开，不强凑周合计。历史日缓存保留各源采集时间，可能与最新 MTD 水位存在差异。
- 目标过期不自动复制到新月份。目标版本不同不混算。

## 每日链路

北京时间 00:20，原 management timer 执行事实采集；事实完成后，现有 Hermes 夜间调度器派发 management 任务（最早 00:35）。日报/周报/月报原有时间继续保留。全部自动模型任务仍受 06:59 停止、07:00 前终态约束，白天不自动补跑。

事实采集有 run.lock、业务日 journal；Hermes 使用已有请求幂等/任务账本/模型用量账本。未知结果不能换 ID 重跑。建议必须绑定同一 snapshotId 和 businessDate，午夜自动隐藏；刷新页面仅检查已发布结果，不产生模型调用。

真实自然夜间触发与手动验收分别记录。配置完成、服务 active 不能代替自然触发证据。

## 路径与发布

- 原入口：/dashboard/management/，已切换到本版；原不可变文件和回滚备份保留。
- 保护预览：/dashboard/__preview/management-v2-20261015/index.html。
- 事实：/var/lib/fs-boss-workspaces/management-v2/facts/<snapshotId>.json。
- 展示：/var/lib/fs-boss-workspaces/public/management-v2.json。
- 事实服务：/opt/fs-boss-workspaces/backend/management_v2_runner.py。
- Hermes 接线：/opt/fs-hermes-fc/management_context.py、controller.py、nightly.py。
- 后端备份：/var/backups/fs-management-v2-backend/<releaseId>。
- 静态备份：/var/backups/fs-management-v2-static/<releaseId>。

发布扩展复用已核 SHA 的现有发布基础、共享发布锁、provider 锁和 Hermes admission fence。先确认没有进行中或待对账模型任务，再停止必要的 FS controller、CAS 写文件、恢复服务并独立读回。静态仅换固定文件及原 Nginx 路由，不改变认证策略。新静态版本永不覆盖旧版。

## 回滚

使用该批原包中的 publish_backend.py 或 publish_static.py：rollback --backup <上述对应批次目录> --approved-manifest-sha <该批原 manifest SHA>。先读现场与 journal，不清锁、不删除账本、不覆盖其他人的新版本。后端回滚同样等待 provider/admission 空闲。原文件逐项恢复；新增但不再引用的 helper 和不可变静态历史保留，不恢复旧整包。

## 验收

离线测试覆盖来源/空值/等待补源、时区和跨月、证据绑定计算、建议到期、每日幂等、并发和夜间截止、发布 CAS/故障回滚。Node 覆盖数字展示、空值、业务日、原 demo 去除与浏览器脚本语法；共享导航覆盖新页面样式隔离及旧页面保持。

手动验收：15/15 项目月累计核心数据，真实 high Hermes 分析、数值汇总核验、建议投影、原入口/筛选/指标切换/项目详情/沙盘平账与复位、浅深主题均已读回。Python 47 项管理台测试及 30 项共享 UI 测试通过。历史日图有缺日，未补零；月累计独立接口读取，不因缺日图而认定少算。模型计算工具此前有参数错误，已改为可纠正的结构化参数诊断；后续模型主动纠正调用尚未观察。自然夜间和午夜到期的真实运行未观察，代码测试不替代该证据。GitHub CI 单独确认。

## Repository policy
Only implementation code, synthetic tests, deployment contracts and hashes are archived in Git. Runtime targets and business observations stay on the existing protected server. The static publisher reads a pinned existing same-server target file; no operational dataset is bundled.

## Final release
Backend: management-v2-07ac5252c4a5, manifest 20ba9b97f40a782558119ac5ee647c89032354b806e7df98867221baa79db9f1.
Static: workspace-native-20261006-66ec73f42a1d, manifest 66491dabfb06d2b7052c331f08b0aef97695ceaf0ed24742aa8ff90fb3b4ea2a.
Completed immutable model output was re-projected after bounded format parsing repair, with original artifacts retained and separate backup/receipt. No model call or task replay was performed by this recovery. Desktop context and its service/profile were preserved.
