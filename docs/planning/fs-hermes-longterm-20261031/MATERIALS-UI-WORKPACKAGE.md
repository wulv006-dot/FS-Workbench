# 附件界面与材料分析交互工作包

沿唯一长期主方案阶段1，不另造路线。前包PR707已合并，merge为fb683f2d82d3b44595d866619bb6c880fd3852fb；同head922a9041的限定核心审查成功，两次必要CI通过。ready事件重复自动审查未完成，但同SHA成功回执保留，不冒充又完成了一次审查。

用户已明确主控自行判断可验收合并时自动决策并继续；不重复索取普通字段、测试、PR合并授权。生产部署、真实模型/业务API或费用、业务写、账号/凭据/权限与安全配置仍不在此范围。

## 本包终点

在既有会话页面选择CSV/XLSX，看到上传/未知/失败状态，显式选择附件并发送；刷新后沿原request_id和文件集合核对；用真实服务端元数据展示输入/派生版本及下载；新turn显式选择产物后继续追问。上包的文件工具/turn围栏保持。执行DOM事件测试、本机HTTP及脚本worker闭环，支持原无附件会话；真实worker/model/生产仍另验。

只交一个最终集成草稿，A给完整候选由Personal正常merge，包内修复更新同一PR。接口对齐、相关测试/CI及限定核心审查通过后，Personal自行决定转正式/合并，不按函数或单次进度拆PR。复用有效同输入证据，不扩大全仓门禁。

## 唯一维护者与接口

- A已认领`hermes-conversation-20261018/frontend/{index.html,conversation.js,conversation.css}`及其执行事件测试；必要files/http/store元数据接口亦由A独占。复用ui-system令牌、原主题和组件；不换业务规则或复制第二套共享样式。
- B业务主线为`hermes-v2-core-20261020/source/material_evidence.py`及B-owned `conversation_file_tools.py`接入：消费A分页回执，给模型实际已读覆盖及B1最小证据交接。另负责`test_material_evidence.py`、`test_materials_http_workflow.py`和既有test_core测试加载、最终跨层验收、工作包与主方案记录。不与A并改上述前端/后端文件，协调/评审不能替代B代码。
- shared controller、公共schema、迁移、发布清单冻结，未授权新并改。
- A发现并交接的`tools/pr_fast.py`精确CI接线由Personal/B唯一维护：在现有hermes-conversation分组两次units后调用原node入口`frontend/entry/test_data_handoff.cjs`，原generic-data调用保留，不新增workflow/依赖/全仓门禁。A在该原入口require新增DOM/fetch测试，整合后核实其实际执行。

A已确认`detail.turns[].files={inputs:[metadata],generated:[metadata]}`，每项为file_id/filename/mime/size/version/parent_id/expires_at/status，status为available/expired/damaged/missing/unavailable。终态可读最小元数据不授工具执行权，工具queued/running围栏不变。下载地址由原API和真实server file_id构造，不能从模型文本提取任意URL/file_id。没有表格正文或凭据进入元数据。

上传原ID核对：GET会话`/files?request_id=<原ID>`，沿原cid+request_id求确定file_id再检查身份。404不构成换ID重传许可；无原字节刷新后仅查询，需重选时核对先前内容SHA256，而非仅文件名/大小。未知上传/发送保持原请求与附件集合；切会话的迟到响应不得污染当前会话；活动任务补充不悄悄重新绑定附件。

## 验收分层

A负责实际执行原UI脚本的DOM/fetch事件测试和相关前后端回归，可运行时补本地Playwright主题/键盘/渲染观察，不能以静态正则或语法检查冒充视觉验收。没有实际运行的内容明示未验。

B新增真实loopback HTTP验收使用注入测试身份，沿真实HTTP适配、store、bindings及工具helper核对原ID查询、终态元数据、授权下载、显式追问以及损坏/过期/丢失状态；它不验证生产认证实现，也不替代浏览器DOM/视觉验收。A新接口候选未合入前，这些新用例不作为旧基线缺陷；集成后才挂入原Core入口。

原全局配额、任意隔离计算、夜间/孤儿清理、公开联网、真实模型和正式部署缺口保留，不因本UI包完成而称A1或阶段1/2整体通过。

## B本轮实际交付

- material_evidence记录本turn实际读回的file_id/sha256、sheet数和行区间，合并乱序/重叠/重复分页；selected_sheet完整不能冒充workbook完整，缺页/未读sheet明确保留。只有匹配请求、来源版本及覆盖尺寸的回执进入覆盖；unknown/无效回执不提升为已读证据，版本或维度冲突不混并。
- B文件工具每次读取把analysis_coverage交给模型，不改A coverage/next_offset，也不阻止基于明确局部范围给有效结论。静态file_prompt说明新字段和业务日期边界。新turn新book无继承覆盖。
- book.material_evidence.handoff_evidence()给B1既有handoff函数消费最小引用，含read-receipt时间、版本、覆盖及缺项，无整表/客户正文/原始聊天；该时间不是业务数据日期，引用仍须A鉴权/回源，不授权限。没有声称真实跨提供方切换已验。
- 8项直接测试通过，含真实A BoundFiles分页→B模型回执→B1交接，以及多sheet、乱序/重叠/重复页、未知/错误回执、版本/维度冲突、空sheet和新turn隔离。原Core入口共91项通过。B另有4项真实HTTP新接口验收候选，待A新接口合入后挂入Core，未把缺新接口的旧基线标回归或绿色完成。

共同联调顺序：UI显式选择→A绑定/鉴权/分页→B判断并交接观察覆盖→A不可变产物→UI真实卡片与下载→新turn显式绑定重新建证据。核心Codex审查在整包候选上进行，不能代替B实现；普通代码/测试修复继续本包一个集成PR。

CI接线本地自检通过；在A新候选合入前运行原node入口仅验证了旧handoff，不冒充新DOM测试执行证据。待最终候选后通过此入口实际执行新增用例并留CI回执。

## 最终候选集成与审查交接准备

Personal已正常merge A固定候选beacbcf693a5aa972b5f7c963ac2a33b2ccf692c，merge为8dc573a68d7a5812ea1bf564e166a900148dd2d9；未改A源。B的4项真实HTTP验收已挂入test_core.load_tests，现Core入口95项通过；conversation原入口28项通过。实际使用pr_fast的units/node运行器确认Core、conversation、Node原入口均通过；Node输出明确含新增DOM/fetch执行场景。pr-fast --selfcheck、git diff --check通过。

A候选的浏览器证据由A提供：原无附件/停止/补充/撤权回归、新Chromium交互、浅暗桌面和390px移动截图检查、合成XLSX点击下载实际落盘通过。Personal核对整个A包与固定候选无源码差异，复用这些证据，不声称自己重复完成视觉检查。API/模型响应仍模拟；下载使用测试期loopback字节夹具，非生产认证。

独立Business审查聊天已实际回复并回送“已就绪”，规则见REVIEW-WORKFLOW.md；握手不是PR审查。最终PR的CI、对应最新head的独立审查和合并仍待完成。知识统一收尾plan已尝试，但原knowledge-layering子检查字节相关失败未解决，不标完成，不改无关publisher。真实worker进程、跨模型运行时、真实模型、生产认证、部署以及整套A1仍未验。
