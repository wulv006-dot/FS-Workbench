# 当前改动来源与发布边界

工作分支 `codex/fs-data-connector-20261109`，起点 `0a1ef1e1cda8dfa1815f95720c684bfd8a1e35ca`。本表为开发候选，不代表生产生效；历史全仓SOURCE-MAP不覆盖本轮现场核验。

| 维护源 | 消费方/候选部署目标 | 变更 |
|---|---|---|
| `fs_mcp_connector/` | 新的独立Python3.12连接器服务 | MCP/OAuth、固定数据目录、原权限查询、响应适配、授权页 |
| `ui-system/tokens/fs-tokens.css`、`components/fs-ui.css`、`adapters/fs-theme.js` | 授权页精确静态路由 | 原文件不修改，部署载荷保留原相对目录 |
| `tools/export_fs_space.py` | 文档/业务自由文本凭据过滤 | 复用原SECRET/KEY_PATH/ASSIGNMENT正则，不复制EMAIL限制、不修改原工具 |
| `releases/fs-dashboard/knowledge-layering-20261023/source/knowledge_catalog.py` | 已发布知识选择 | 复用原selector，不修改原路由/知识规则 |
| `releases/fs-dashboard/hermes-conversation-20261018/source/conversation_http.py`及新增`conversation_readonly.py` | `/opt/fs-exact-range-20261001/` | 原owned权限下新增纯读材料元数据路由；原runtime_prepare/runtime_release打包及回退闭包补helper |
| `releases/fs-dashboard/hermes-customer-lifecycle-20261019/source/tracking_controller.py`及新增`tracking_readonly.py` | `/opt/fs-hermes-fc/` | 原管理员入口增加stored_only查询；保留原轮询/调度能力；原prepare_release/release_bridge/release_scope补helper闭包 |
| `tools/pr_fast.py`、`.github/workflows/pr-fast.yml` | 现有PR检查 | 为连接器单独准备Python3.12/SDK，保留旧模块解释器和离线外部调用拒绝；增补上述模块回归 |

## 用户撤销模型身份字段禁令

2026-11-09，用户明确要求删除旧客单追踪、实时订单合同中“邮箱、UID、原订单号不能返回模型”的限制。已同步AGENTS、实时订单合同、客单追踪README/方法/交接及相关权限说明；连接器保留原业务身份字段，原追踪tool_read和报告链也取消强制匿名及含邮箱拒绝。原认证、private与对象范围不变，凭据不返回。

原客单追踪维护源的`customer_tracking.py`与现役文件存在既有漂移，`research.py`也不能按旧全文件覆盖。生产发布必须基于最新现场SHA构造精确变更，保留其他在役能力；本分支测试通过不代表上述原服务已发布。`knowledge/reviewed/`下带哈希的历史审查快照保留为历史证据，其中旧禁令已被本次直接用户指令撤销，不再作为当前查询限制；不能篡改历史哈希假称旧证据已同步。

远端现役服务源码、哈希及只读路径见[REMOTE-SOURCES.md](REMOTE-SOURCES.md)。连接器经原HTTPS网关携带真实FS会话，身份头由原网关生成，不能按模型输入构造。仅登记源码和路径不等于查询验收。

新增服务及其持久化OAuth状态/公共路由须在具体发布清单批准后执行。原模块适配沿既有publisher，不恢复历史整包、不重启业务调度、不修改原成员角色或自动定价规则。账号overview/audit业务投影已本地实现，仍未部署或真实成员验收。

客单追踪当前/历史消费链本轮身份规则修订、现役方法SHA、源码漂移及最小发布合同见[TRACKING-SOURCE.md](TRACKING-SOURCE.md)。只读helper部署闭包和模型明细输出修订应按现场增量装配，不覆盖既有日常扫描、客户匹配、金额公式或退役报告状态。
