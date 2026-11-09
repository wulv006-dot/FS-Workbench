# FS 全量数据连接器实施计划

目标：同事、主机和副机通过 ChatGPT、Codex、DeepSeek Harness 读取 FS 全部现有可读取业务数据，权限与来源口径保持。

设计：[DESIGN.md](DESIGN.md)。用户已确认全量范围、个人与团队账号混用，并授权主代理把控方案／验收，子代理施工／测试。实现无需逐步骤重复确认；生产新增 OAuth 和对外入口在形成确切清单后确认。

## 结构与契约

- `fs_mcp_connector/auth.py`、`portal.py`：复用现有 portal 校验，OAuth 授权码／PKCE、令牌、撤销与持久化；`Principal(subject,session_cookie)` 只由可信校验产生。
- `catalog.py`、`catalog.json`、`backend.py`：固定命名操作及参数 schema，逐资源验证原权限，经原 FS 网关取数。查询返回 `{operation,status_code,data,provenance}`；模型不能提供任意 URL、SQL、用户名或 Cookie。
- `server.py`：官方 MCP Python SDK 的 Streamable HTTP、OAuth 路由、同意页和工具注册。`fs_list_data_sources`、`fs_query_data` 共用真实身份。
- `clients/`：ChatGPT 个人／团队、Codex 和 DeepSeek Harness 配置；后者必要时复用已有 OAuth 桥。
- `tests/`：身份、参数、目录、后端及真实本地 HTTP 协议测试。
- 发布接线及源映射：由主代理核对实际入口与原发布器，新增服务独立运行，不更改现有业务调度。

## 工作项

- [x] 核对本地／远端，独立工作树基于 `0a1ef1e`，保护原 Hermes 分支。
- [x] 用户确认全量读取和三类客户端；导航33项形成盘点起点，非接口覆盖证明。
- [ ] 身份与 OAuth 模块：正常登录、PKCE错误、回调／resource不符、过期、撤销、授权码并发重放、CSRF、原FS退出／改权的负例。
- [ ] 数据层：逐模块确认读取接口及现役来源，未知操作／参数拒绝，分页与206透传，原private与对象权限保留；登记缺项不伪装全量。
- [ ] MCP与客户端：官方SDK初始化、工具发现／调用、OAuth完整流程、错误语义、客户端配置及副机兼容适配。
- [ ] 主代理整合验收：逐任务审查、联调、全分支审查、相关pr-fast；Linux默认183隔离环境，受阻记录准确原因。
- [ ] 形成发布清单：原服务、认证边界、路由、持久化、备份／回退、各客户端及多角色真实验收；按具体授权执行并读回。

## 必须覆盖的失败场景

凭据误回显或越权数据返回；模块权不等于对象所有权；未知／partial不能补零或认全量；查询不能触发业务写入；回调重放与跨用户授权；网络重定向泄漏Cookie；服务重启后的授权状态；副机OAuth与刷新；客户端账号无自定义连接入口。

## 执行记录

2026-11-09：三位施工代理分别负责身份、数据、MCP。模型均为 GPT-6.1 Sol，高思考强度；主代理集中整合，不并行执行Git或发布。

初次知识收尾检查使用系统Python因缺少Asia/Shanghai时区数据失败；改用已安装的带时区数据Python重跑成功，未修改业务代码或放宽断言。无正式知识条目变更，不需Notion写入或业务重启。后续代码变更完成后重新核对适用收尾范围。

早期37测试/40操作阶段曾因账号额度中断，现已恢复原SSH/GitHub通道且完成后续扩展；该历史阻碍不再适用。当前124操作与身份字段授权修订、Linux/审查状态以 [ACCEPTANCE.md](ACCEPTANCE.md) 为准；不以旧阶段结果覆盖当前代码。
