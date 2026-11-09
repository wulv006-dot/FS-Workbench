# FS 连接器验收记录

本文件保留2026-11-09的开发期证据；后续合并、部署及真实入口状态以 [LIVE-ACCEPTANCE.md](LIVE-ACCEPTANCE.md) 为准。下文“未部署”等描述对应当时快照，不代表后续现场。

## 当前版本

独立工作树`D:\codex\FC27\fs-data-connector-20261109`，分支`codex/fs-data-connector-20261109`，基线`0a1ef1e1cda8dfa1815f95720c684bfd8a1e35ca`。当前124个候选操作、39项模块覆盖记录，均不标为生产验收完成。源码/部署边界见[SOURCE-MAP.md](SOURCE-MAP.md)，实际剩余范围见[DATA-SOURCES.md](DATA-SOURCES.md)。

开发版本已推送[PR #929](https://github.com/wulv006-dot/FS-Workbench/pull/929)，合入最新main后的测试目标为`9c1fac9c4e6c49ef40b4c58cabe75a71e01159b5`；未合并或部署。正式CI已通过，最终183环境回执补充记录如下。

## 已验证

- 原GitHub读取/fetch及187/183 SSH正常。正式FS地址`https://47.85.224.112/dashboard/`通过正常证书校验并跳转原登录页；先前另一域名404不是FS故障。额度审批阻碍已解除，详见ACCESS。
- Windows独立Python3.12连接器154项测试：153通过，1项POSIX文件权限测试仅在Linux执行。涵盖OAuth授权码/PKCE/刷新/撤销、跨用户/对象/参数拒绝、原会话失效、临时故障、完整官方SDK OAuth客户端流程及真实本机HTTP MCP调用。业务上游为替身，不能冒充生产业务验收。
- 授权页采用原FS样式与主题，5项模板测试、真实ASGI资产/CSP/错误分流通过；现有Chrome在320/375/1280/1920宽度、浅/暗主题和禁用JS下验证，未横向溢出，原生表单/折叠可用。没有新增前端依赖。
- 登录短续接支持1800字符state，完整参数服务器保存，短ID300秒一次性有效。原登录512字符限制可保留，不需改门户。
- 原知识收尾`plan`完成：104项相关检查，97通过、7项原环境条件跳过；无受影响正式条目、无新增权限、无重启/Notion发布。回执保留在`.agent_runtime/connector/knowledge-closeout.log`。
- 本轮差异空白检查通过；现有pr-fast加入连接器独立Python3.12和直接受影响测试，没有取消原禁止外网/子进程的检查。

## Linux与正式CI

较早100操作/66测试的冻结快照已在183 Python3.12.16完成全部测试及完整pr-fast，0跳过；测试容器移除且没有修改业务服务。证据`D:\codex\FC27\connector-linux-20261109\final-pass.log`，包SHA256`452dec8e0355702ef8a00747434087115c81631c1b902e69a2531d5023c6ca9a`。

最新代码`9c1fac9c4e6c49ef40b4c58cabe75a71e01159b5`的[正式GitHub PR fast](https://github.com/wulv006-dot/FS-Workbench/actions/runs/42560720107)已成功：799项Python检查全部通过、0失败/错误/跳过，另有原UI检查通过。范围包括customer-lifecycle、fs-mcp-connector、hermes-conversation、hermes-customer-tracking、tiered-data-access及self；连接器154项全通过。该证据包含最新主分支HTTP兼容改动及完整publisher分区，不使用早期快照替代。

同提交183最终冻结包SHA256为`912179ebeae1e15db0079d179948b131673b2b34d889d859d76e1c4a32f194c2`，3187个源码/测试/必要资产均取固定提交规范Git字节；154项连接器、Hermes核心285项、完整publisher108项（HTTP另11项）、旧追踪45项、当前生命周期28项及原private-client2项等Python检查均通过，0失败/错误/跳过。183实际CLI最后的原追踪前端脚本因未安装Playwright而未执行；不宣称183整CLI全绿，同提交该前端已由正式GitHub CI通过，复用其证据而未重复安装浏览器。

## 用户撤销身份输出禁令与审查修复

用户已明确删除旧客单追踪/实时订单的模型身份字段禁令。当前规则、连接器、原tool_read/报告绑定/提示链都保留获准邮箱、UID和原订单号；原权限不扩大，凭据仍剔除。原追踪45项及当前生命周期30项通过，并覆盖1000条正常长度订单号不使原聚合报告突破容量。

独审发现并修复：原附件清单会删除过期文件，改走owned纯读connector/files；自由文本凭据识别补齐标准头/短密码/JSON凭据，并在通用Backend和Players最终响应统一处理。相关回归通过，不能据此声称生产从未含此类信息。

## 未通过或未执行

- Windows早期publisher回归出现5项未修改桌面文件CRLF/Git LF固定哈希不符；随后使用规范Git字节，正式CI完整publisher已通过。没有修改期望哈希或放宽断言。此项为已解决的环境差异，不是当前阻碍。
- 新服务Python3.12运行时、OAuth持久化及公共路由未部署。187原Python3.9与业务调度保持。
- 原Hermes材料/客单追踪纯读helper未部署，目录已明确其依赖；不能直接调用未生效入口并宣称可用。
- 实际FS账号、普通成员/private/对象隔离、撤权、原数据对照，以及ChatGPT个人/工作区、Codex、DeepSeek Harness副机均未真实验收。个人账号入口及副机版本需在实际客户端核实。
- 尚有数据缺项；没有把所有导航模块出现候选等同于全量覆盖，也没有因查询副作用关闭原自动化。

## 接续验收

冻结当前代码并完成相关Linux回归/独立审查，准备可审阅发布清单；具体新OAuth入口及持久化范围确认后沿原发布器执行、读回版本，再从上述真实客户端和身份逐项验证。客户端操作见[CLIENTS.md](CLIENTS.md)。

本地重跑：`.venv/Scripts/python.exe -m unittest discover -s fs_mcp_connector/tests -v`。
