# FS / Codex / Hermes 知识分层与自动收尾

状态：**方案与代码完成、24项离线及正式CI通过、PR367/370已合并、批准的10文件已部署、实际代码隔离装配通过、Notion三页写后读回通过。** [交付与剩余项](DELIVERY.md)及[机器回执](../../../knowledge/RELEASED.json)分别列明证据。普通FS／飞书新路由、真实模型运用、老D自然采用及旧块无损折叠仍待验；业务原文维持原模块归属。

## 最小改造

1. [W0现状](W0.md)分清Git正式知识、服务器发布物、原任务实际输入和Notion项目记录。用户已确认PMax以FC维护源和服务器基准为最新权威，旧通用说法保留历史，见[决定](../../../knowledge/decisions/pmax-authority-20261023.md)。
2. [知识入口](../../../knowledge/README.md)及[index.json](../../../knowledge/index.json)只保存五层、稳定ID、模块、版本、状态、来源和替代关系，不搬目录、不复制第二份可写规则。当前条目读唯一原文的明确段落，候选不进入生产，历史必须显式请求。
3. `knowledge_catalog`核索引、模块、状态、内容哈希及来源，再选择条目。`freeze_learning`沿原快照固定内容和版本；原有效输入回执增加条目ID、revision和内容哈希。方法/偏好/技能仍沿现有入口，原经验manifest和执行程序保持。
4. 新读取接线先限明确选择的报告请求，未配置的原请求继续原路径；FC改价/原教学/普通会话不自动切换。已部署及隔离装配不等于普通入口或模型已经采用新索引。若要扩大到更多消费方，先核其调用方及适用模块，避免把共享profile当所有入口均已验收。
5. [统一收尾](CLOSEOUT.md)进入现有AGENTS/HOTFIX及pr-fast。工具生成影响与确切文件清单、测试、一个change_id及恢复账本；Codex按一次具体批准连续使用Git、原发布器及Notion原生工具并读回。脚本本身不持有凭据，也不另造发布器。

## 交付导航

| 交付 | 入口 |
|---|---|
| 权威/维护/消费/版本与缺口 | [W0](W0.md) |
| 按需读取、五层及唯一来源 | [知识索引](../../../knowledge/README.md) |
| 文件与源→活动目标映射 | [SOURCE-MAP](SOURCE-MAP.json)；完整差异见本PR |
| 发布、读回和回滚 | [DEPLOYMENT](DEPLOYMENT.md) |
| Notion迁移及人工内容保护 | [NOTION-MAPPING](NOTION-MAPPING.md) |
| 每日复盘模板与老D衔接 | [MAINTENANCE](MAINTENANCE.md) |
| 一次批准、恢复和去重 | [CLOSEOUT](CLOSEOUT.md) |
| 验收范围与未执行项 | [ACCEPTANCE](ACCEPTANCE.md) |
| 本次已获批准的具体动作 | [APPROVAL-CHECKLIST](APPROVAL-CHECKLIST.md) |
| 本批实际发布、加载与Notion读回 | [DELIVERY](DELIVERY.md)；[RELEASED](../../../knowledge/RELEASED.json) |

本次不引入Obsidian、全文/语义检索、向量库或付费平台。没有修改FC维护源、公式、利润底线、参数、教学、原开关或调度；没有新建定时任务。已有技能及持续学习能力不因单任务固定知识版本而被冻结。
## 二期候选入口与隔离实测

**最新增量见[发布环境SQLite兼容修复](PHASE2-SQLITE-COMPAT.md)**：复用服务器已有私有库，新增精确运行时固定和schema/并发/异常回归。下列PHASE2-RESULT/APPROVAL/NATIVE-RUNTIME是09:14旧冻结快照，不能据其旧哈希或批准状态执行新候选。用户已批准原分支PR/正式CI和隔离镜像准备；生产切换与模型仍未获批。最终进度以对应实际Git/CI/构建回执为准。

[FS新会话接线、只读边界及native-only发布scope](PHASE2-OFFLINE.md)已完成离线补齐，并有真实原生容器9项隔离只读实测；[后续集中确认清单](PHASE2-APPROVAL.md)、[精确源映射](PHASE2-SOURCE-MAP.json)与[结果](PHASE2-RESULT.json)分别列范围和证据。仍未提交/合并或部署二期，未切换真实用户会话、触发模型、接飞书或改Notion/凌晨维护；上文一期已发布记录保留，不把二期隔离实测称为生产验收。
