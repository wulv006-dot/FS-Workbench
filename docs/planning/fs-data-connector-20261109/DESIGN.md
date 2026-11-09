# FS AI 数据连接器设计

日期：2026-11-09。状态：已实现本地候选服务，40 个候选读取操作；全量映射尚未完成，未发布或完成真实客户端验收。当前证据见 [ACCEPTANCE.md](ACCEPTANCE.md)。

## 目标与已确认需求

同事及主机／副机能够通过 AI 查询 FS 数据。用户已指定 ChatGPT 为主，同时支持 Codex 和 DeepSeek Harness。统一复用 FS 数据口径、原有权限与查询服务，不复制业务数据库或改变自动化调度。

## 推荐方案与取舍

推荐一套远程 MCP 服务，通过 HTTPS 提供工具，用 OAuth 授权绑定真实 FS 用户。ChatGPT 与 Codex 使用同一服务，各自完成授权；DeepSeek Harness 优先使用其原生 MCP 客户端，是否需要轻量本地适配须依据其实际版本与入口确认。

备选为每台电脑安装本地代理，适合仅本地客户端，但会增加安装和维护，并不能单独解决 ChatGPT 云端访问。仅提供 REST API 可复用现有接口，但仍需每种 AI 客户端自行适配，不满足主要入口的一次连接体验。以上取舍是实现建议，用户尚未确认完整设计。

## 用户体验与数据范围

用户添加 FS 连接，跳转现有 FS 登录并授权数据读取，返回 AI 客户端后直接提问。目录只展示其获准访问的能力；每次调用仍检查当前权限，撤权后旧连接不能继续取数。

用户已明确首批覆盖全部现有可读取数据，不以少数看板代替全量交付。以当前导航、模块权限、真实数据服务及发布映射交叉盘点，逐项标记已连接、待接入、不可用及原因；页面数量不等于数据接口数量。经营、用户、订单、定价、竞品、Ads、流量、SEO、活动、商品、游戏情报、日历、知识、报告、任务及各业务工作台已有可读取数据均在盘点范围。不能通过任意 URL、文件路径或 SQL 查询替代模块适配。详见 [覆盖清单](COVERAGE.md)。

结果保留来源、期间、时区、单位、截至时间、完整性与续页信息。金额和毛利直接遵循各模块现行合同，不由连接器重新定义。实时订单继续使用现有 20 条分页、28 天单窗口、365 天边界、共享并发与 partial/live_non_snapshot 语义；精确邮箱仅走受限 POST，保留 private 校验。缓存失败、上游拒绝和缺失均不转成零。

本需求是数据获取；不向新连接器加入改价、发券等业务写入工具，原系统已有写入与自动化能力保持。

## 实现边界

1. 使用标准 MCP SDK 的远程 HTTP 传输。工具显式声明输入结构及只读属性，服务端仍独立限制工具和参数。无需为查询桥接另建 OpenAI 模型调用或 API key。
2. 新增 OAuth 授权适配：授权码、PKCE S256、受保护资源和授权服务器元数据；客户端登记方式按实际 ChatGPT 管理页及 Codex 支持确定。精确校验回调、resource/audience、有效期和授权范围。授权码一次消费，刷新与撤销具备明确持久化语义；不将 FS Cookie 或 Admin/Order 凭据交给客户端。
3. 复用现有 FS 登录身份及 IAM 判断。客户端传入 owner/username 不构成身份。OAuth 授权不扩大原有资源和 private 权限。每位同事独立授权；主机／副机各自保存本机授权，不共享管理员凭据。
4. 数据服务适配必须复用原宿主查询及共享 Admin 通道，不能另起绕过原并发池的直接采集。Hermes 原工具还带任务绑定，不能伪造 conversation/turn 来调用；只提取必要的公共查询入口，保留原调用者校验。
5. 发布入口、反向代理路由和现役认证源需现场核验后列入具体发布清单。连接器独立服务，不修改 FC P0 调度及既有 183 RPG 服务。持久化只存必要 OAuth 状态与脱敏调用记录，不记 token、邮箱、订单正文或查询串。

## 已核查的源码与限制

- 起始检出：`3d07c69`；已通过允许联网的执行环境获取最新 `origin/main`，在 `0a1ef1e` 创建独立任务分支。起始环境的 HTTPS 连接失败不是 GitHub 凭据失效；同一远端访问已成功。
- `opt/auth-portal/auth_portal.py`：现有登录与签名 Cookie；已查看路由不是完整 MCP OAuth 服务。活动部署映射仍须现场核对。
- `releases/fs-dashboard/user-analytics-20261022/source/user_runtime.py`：可复用 `authorize` 和 `build`；目前 private 判断走现有管理员权限，不自行改为新的成员名单。
- `releases/fs-dashboard/hermes-conversation-20261018/source/conversation_user_data.py`：已有数据目录、分析和经营读取路径，但绑定原 Hermes 会话／任务，不能直接充当外部身份。
- [实时订单合同](../../../releases/fs-dashboard/tiered-data-access-20261101/LIVE-ORDER-PAGINATION.md)：协议与历史验收范围；不以该文档证明当前全部场景已验收。
- 用户确认 DeepSeek Harness 位于副机。已找到官方 `deepseek-ai/deepseek-harness`，2026-11-09 读取主分支客户端文档及配置源码：支持 stdio 与 Streamable HTTP，支持 headers 和凭据模板；所读配置未提供 OAuth 登录选项。副机无需迁移；优先复用现有 OAuth 客户端适配并核其兼容性，不能用手工反复复制短期 token 达成“轻松调用”。副机安装版本与端到端行为尚未验收，主分支不代表副机当前版本。历史不继续投入的记录不覆盖用户本次明确兼容需求。
- 用户提供的 ChatGPT Library 链接只返回登录页面，文件正文未读取，未将其当作已知要求。

## 影响范围与验证

预计涉及新增连接器服务、登录授权适配、数据服务必要的共享查询入口、客户端配置模板、发布清单及直接测试。不得修改原经营指标计算、价格参数、业务写入和定时计划。复用现有发布器与 pr-fast，准确登记新增代码的运行验证。

验收：MCP 初始化／工具发现／查询；正常授权与撤销；无身份、伪造身份、错误 audience、回调、过期及授权码重放拒绝；不同角色和 private 边界；分页、跨窗口、数据不完整及上游错误；原 Hermes 调用回归。183 隔离 Linux 验证先核资源，不能静默转到生产机测试。

交付终点：部署后分别从 ChatGPT、Codex、DeepSeek Harness 实际登录并查询，核对返回身份、来源与 FS 同范围结果；主机、副机与至少一位同事独立验收。未具备客户端或账号时标记该项未验，不以模拟通过代替。

## 待用户决定与实现方自行核实

- 已确认：首批为全部现有可读取数据；ChatGPT 为主，Codex 与副机 DeepSeek Harness 同时纳入交付。无需用户重新提供开源项目链接。
- 副机版本可在实际接入时读取；目前不阻塞通用服务设计。个人对话、客户私有字段、成员资料等仍按原本人／管理员权限，全部数据不等于全体同事拥有全量权限。连接器只访问 FS 已有合法读取面，不增加凭据导出接口。
- 实现方：核实当前认证部署、SDK／运行环境、可复用发布入口、端点及回调具体值，准备测试与可审查发布清单，不要求用户重新寻找仓库中的资料。
- 新增生产授权端点与对外数据访问的具体清单在准备完成后确认；已有开发授权继续有效。

官方依据：[MCP 认证](https://developers.openai.com/plugins/build/auth)、[自定义 MCP 连接](https://developers.openai.com/api/docs/guides/custom-mcp-server)，2026-11-09 查阅。

DeepSeek 官方依据：[客户端配置](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)、[配置源码](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/src/index.ts)。
