> 首次目录状态补充：本文件原始时间点保留，后续条件入库/今晚自主推进与最终准备状态见CURRENT-STATUS.md及READINESS.json；源码基线可入库不等于可部署。

# Revision3最终整合状态与声明更正

本说明为冻结候选之外的最新读法，补充而不改写原审查/测试记录。双最终报告原件与机器证据同目录。candidate_revision3仍311文件/12,111,256字节，集合SHA `f1d7ce1d3cb2c73ccaae58744ef2ff2a34cef69070d098193b2cac86b7ae532c`；对C2为282不变/19改/10加/0删，原C1/C2目录保持原库存。

安全结论：原R2-01/02/03三个P1的指定漏洞机制在本有限静态/主方合成记录层已修，无新增已证实P1。功能结论：R2-F1～F3在同层闭合。两者均未执行候选测试、未验生产或全部17模块，不授权发布。两项新P2保持OPEN；FC静态与动态范围、NBA无人值守批准方案、真实运行验收继续阻断。`releaseReady=false`、`uploadApproved=false`，生产/推送/角色授权阻断保持。

## 收窄现有表述

- “持久pending / durable before first upstream effect”：现实现同步临时文件内容再rename，没有同步receipts目录及新目录父级。可确认普通进程异常且回执仍存在时，同ID不再次执行；不能承诺突然掉电后pending必存、跨重启不会重放。候选write_contract.py:107注释及旧说明中的durable应按此更正理解，代码因冻结未改。上游已发生但回执写失败属于unknown/可能部分成功，不能表述为零写入。
- “幂等”：只覆盖相同requestId/hash/actor且现存回执的检查，当前正常UI不发送/保留稳定ID，HTTP成功不完整返回ID/hash、失败detail丢失。重新确认会生成新ID，不在现保证内。前端失败会暂停是缓解，不能说正常UI重试已经贯通。
- “客户端政策相同”：以Python通用换行读取后完整政策文本与SHA头一致；policy为LF、client嵌入为CRLF，不能声称原始字节子串相同。HTML/JS内容检查仍启发式，不是任意秘密检测/同源沙箱。
- “全平台可运行 / 全套通过”：311只是精确源码清单；主方实跑47目标Python（46pass/1Windows skip）、3Node，以及182PythonAST/34JS语法。独立报告核了来源、断言/摘要及库存，未独立重跑；不能把旧170和新47拼成217新版全套，也不称191全跑。没有本轮独立观察到的逐次原始测试输出，现记录是主方工具结果与摘要。完整check_candidate登记新组不等于它已执行。

## 下一次仅两P2小修计划（未执行）

R3-01：发请求前生成并保留本次确切计划ID；批准的价格计划不变时复用ID，新计划才新ID。贯通UI payload、后台成功/失败响应的requestId/hash/operator/state，unknown保留详情与核对入口；先只读核对原ID，未消除unknown前禁止用新ID再次写。身份从现有合法认证取，不新增凭据。验收以实际doApply payload/handler响应、延迟/断线/重试/新旧计划合成矩阵，mock上游，确认同计划最多一次fake执行及审计绑定。新增核对接口仍需明确角色/范围合同，不在此文直接定路由或架构。

R3-02：在生产Linux运行根/receipts预创建并确认目录持久性；新建目录同步其父级，临时文件fsync→replace→目标父目录fsync，完成回执同样同步。pending耐久确认失败时必须在执行前拒绝；上游后落盘失败标unknown并暂停。验收覆盖调用顺序、文件/目录fsync及rename失败注入和同ID重启读取；全部用隔离目录/fake副作用，随后另做受控Linux多进程/文件系统条件验收。其他OS合同明示差异；普通kill/进程异常不冒充突然掉电试验。本轮不改冻结代码或实施故障试验。

## Astra架构交接范围

实际原件、171/227/301/311四阶段、778全文件处置及17模块232路径+79支撑路径、外部运行依赖入口：`../review-notes/architecture-evidence-index.json`；短FC/NBA方案：`../review-notes/decision-note.md`。原MODULE-RUNTIME-MAP中taskboard前缀计0仅索引错误，实际opt/mmoexp-taskboard四源已存在；外部补充索引已纠正，冻结文件未改。

未纳入完整候选运行闭包：FC gate和activity-api后端仍留raw/外置；旧FCops日采集/分析/API后端不迁回新采集链；Gallery/Madden未识别可部署源码闭包，仅定位到归档unit声明；Ponytail具体保护未独立核实。有效nginx/systemd/drop-in、服务UID、容器/CDP/镜像、媒体后端、真实会话/角色/DB/外置rev25/当前六后台三公开页和实际敏感配置/日志/订单均未纳入发布验收。raw运行产物、九历史Players目录、历史安装/权限/价格脚本和退役dashboard-collect/publisher被刻意排除，不能因其“缺失”恢复旧链。真实只读账号不可用，不新建或降级补测。

四FC静态alias仅修加载；exact-range-client仍请求内部range.json，需后续FC27固定范围只读合同和授权/合成验收，不开内部全站JSON。NBA方案只建议现有服务身份执行管理员批准的有限策略、每轮计划与回执绑定，不替用户选策略、不伪造admin、不建新长期token。Astra任务只写方案，模型/基础设施/数据权限/价格频率不由本交接变更。
