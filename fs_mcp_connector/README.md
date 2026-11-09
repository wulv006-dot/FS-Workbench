# FS 数据连接器

通过远程 MCP 提供 FS 只读数据。每位用户在原 FS 登录后独立授权；查询复用原网关及权限，不把管理员身份、FS Cookie 或后台凭据交给 AI 客户端。

当前目录登记113个业务读取操作、36个范围记录；精确映射及剩余范围以 `catalog.json` 为准。目录不接入Hermes会话、代理和历史生成报告；客户追踪业务明细、活动统计及获准FS知识文本保留。当前AI获得数据和方法后自主分析，不要求固定报告模板。数量不证明所有数据已完整接通；部署、真实入口与客户端证据分别见 [验收记录](../docs/planning/fs-data-connector-20261109/ACCEPTANCE.md) 和 [真实验收](../docs/planning/fs-data-connector-20261109/LIVE-ACCEPTANCE.md)。本轮目录调整须单独发布后才生效。

## 本地验证

在仓库根目录，使用独立 Python 3.12 环境：

```text
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r fs_mcp_connector/requirements.txt
.venv/Scripts/python.exe -m unittest discover -s fs_mcp_connector/tests -v
```

Linux 将 Python 路径替换为 `.venv/bin/python`。测试使用临时数据库、模拟上游和本机 HTTP，不读取生产业务数据。

## 启动配置

通过服务环境设置下列变量，再从仓库根运行 `python -m fs_mcp_connector`。这里是运行契约，不是已经生效的生产配置。

| 变量 | 用途 |
| --- | --- |
| `FS_CONNECTOR_ISSUER` | 已验证的公共 HTTPS 授权服务地址，例如 `https://fs.example/connector`；示例域名不能用于生产 |
| `FS_CONNECTOR_ORIGIN` | 原 FS HTTPS 站点根地址，不能包含路径或凭据 |
| `FS_CONNECTOR_DATABASE` | 服务独占、限制访问的 SQLite 文件绝对路径；不得入库或放入公开目录 |
| `FS_CONNECTOR_PORT` | 已核实未占用的独立端口；进程只绑定 `127.0.0.1` |
| `FS_CONNECTOR_PORTAL` | 原 FS 认证服务的本机 HTTP 地址，默认 `http://127.0.0.1:8895` |
| `FS_CONNECTOR_KNOWLEDGE_ROOT` | 已发布知识根目录；现役为 `/var/lib/fs-hermes-fc/fs`，必须由真实用户匹配原FS/data路由；不配置时知识查询明确不可用 |

MCP 地址为 `FS_CONNECTOR_ISSUER + /mcp`。浏览器授权需要同站原 FS 登录 Cookie；对外反向代理应转发连接器路由及其 discovery 路由，并保留原 FS 登录入口。部署前必须核对现役登录、Cookie 范围、HTTPS 证书、端口及反向代理，不能仅启动进程即宣布可用。

数据库保存哈希后的令牌及授权状态，也保存服务端代持的 FS 会话，因此应按凭据文件保护和备份。原 FS 会话过期后需要用户重新登录授权；刷新令牌不会延长或绕过原 FS 登录有效期。授权页复用原FS主题；登录用短续接ID，完整OAuth参数留在服务器，适配原512字符返回地址上限。Players子会话仅服务器持有，复用原共享认证流程，不向模型返回CSRF或SID。部署需同时包含原UI三项共享资产、知识选择器及`tools/export_fs_space.py`，不可仅复制连接器目录。

## 客户端接入契约

- ChatGPT：添加远程 MCP 地址，选择 OAuth，实际回调地址以该账号或工作区的管理入口为准。个人账号与团队工作区分别验收可用入口和管理员分发；团队分发不代替成员自己的 FS 授权。
- Codex：登记同一远程 MCP 地址并完成 OAuth 登录。主机与副机各自保存授权，不能复制另一位成员的凭据。
- DeepSeek Harness：已查阅开源主分支支持 Streamable HTTP 和 stdio；副机实际安装版本待核对。若其版本没有 OAuth 登录流程，需验证标准 OAuth 本地桥接后再提供可安装配置；不能把手工复制短期 token 当作交付。

以上是接入契约；各真实客户端当前通过与未验项目以真实验收记录为准。

## 查询与扩展

`fs_list_data_sources` 返回当前用户可见的操作、参数、覆盖缺项与 `data_methods` 方法口径；方法中的操作引用同步按原权限过滤。月报等问题可按需发现原范围、选择汇总与补查详情，由当前AI自行分析归因，不触发Hermes任务或报告生成。`data_methods` 是可选方法导航，不强制全量拉取或固定报告结构；其中来源哈希为仓库方法版本，不是现网数据完整性证明。详见 [数据与方法](../docs/planning/fs-data-connector-20261109/DATA-METHODS.md)。`fs_query_data` 接受 `operation` 和 `arguments`。操作只能来自 `catalog.json`，不接受任意 URL、SQL 或身份覆盖。新增映射前核对当前源码、调用参数、现役路由、权限和是否触发写入，并补对应合同测试。

上游分页、206、部分覆盖及错误保留；连接器不将缺失补零，不将第一页当全量。实时订单的 20 条分页、28 天单窗口及 365 天边界只应用于该接口。客户精确邮箱只允许原受限 POST 请求体，不能加入 URL 或日志。

按2026-11-09用户修订，原权限范围内的邮箱、UID、原订单号和业务明细直接保留给模型继续查询；不强制匿名汇总。字段投影与文本处理只移除凭据和未核后台原始载荷，不把客户业务标识当作凭据。

官方参考：[OpenAI MCP 认证](https://developers.openai.com/plugins/build/auth)、[DeepSeek MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)。
