# FS 客户端接入

服务已发布：`https://47.85.224.112/connector/mcp`。2026-11-09 Codex真实OAuth登录已通过，已通过目录、客户追踪及同一月范围查询；响应过长的显示修复仍在验收；ChatGPT手动配置的授权回跳通过，但云端令牌兑换返回503，尚未接通。客户端进度见 [LIVE-ACCEPTANCE.md](LIVE-ACCEPTANCE.md)。每个成员用自己的 FS 账号授权；主机、副机各自完成登录，其他电脑不会改变服务器数据权限。

## Codex

首次配置运行（已添加过fs则只需登录，不重复添加）：

```text
codex mcp add fs --url https://47.85.224.112/connector/mcp
codex mcp login fs
```

浏览器中登录 FS 并确认授权。验收必须包含工具目录、一个获准查询、一个无权限查询、原 FS 会话失效和重新登录。不要手工复制 FS Cookie 或其他成员令牌。

参考：[Codex MCP 配置](https://learn.chatgpt.com/docs/extend/mcp?surface=cli)。

## ChatGPT

在有自定义 MCP 功能的账号或工作区中，通过 Plugins 的新增自定义 MCP 入口填入上述 HTTPS 地址，认证选择 OAuth，再以自己的 FS 身份登录。团队管理员分发只分发入口，不代替成员授权。

Business/Enterprise 工作区与个人账号分别现场验收；个人账号是否显示该入口由其实际套餐、客户端及平台开放情况决定，不能用工作区测试结果代替。如果个人账号没有远程自定义 MCP 入口，连接器服务器本身无法开启该平台功能，须另验该账号支持的插件/桌面入口。

参考：[ChatGPT 自定义 MCP](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt)。

## DeepSeek Harness（副机）

开源 MCP 客户端支持 stdio 与 Streamable HTTP，但尚未确认副机安装版本及其 OAuth 能力。若该版本没有原生 OAuth 登录，用现成 `mcp-remote` 的 stdio/OAuth 桥接；无需新建另一套数据接口。下列是配置结构，版本应在副机安装前核定已发布版本并固定：

```yaml
- id: mcp-fs
  name: '@deepseek-ai/dsh-mcp-client'
  config:
    serverName: fs
    transport: stdio
    command: npx
    args:
      - '-y'
      - 'mcp-remote@0.1.38'
      - 'https://47.85.224.112/connector/mcp'
      - '--resource'
      - 'https://47.85.224.112/connector/mcp'
      - '--transport'
      - 'http-only'
```

这里的 `http-only` 是桥接器的 Streamable HTTP 传输选择，URL仍为HTTPS，不关闭TLS校验。首次调用会打开本机浏览器登录，OAuth令牌由桥接器保存在该电脑；不放进共享仓库。副机安装及真实登录尚未执行。

参考：[DeepSeek Harness MCP 客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)、[mcp-remote 参数](https://github.com/geelen/mcp-remote)。

## 月报等分析的用法

连接器只提供本人可读的FS数据、调用参数、计算口径和覆盖说明。用户自己的AI按问题选择查询，独立分析、归因并生成报告；不连接Hermes会话或调用其报告生成。先通过`fs_list_data_sources`取得简短导航，再传`module`取得该模块完整参数与`data_methods`，然后用`fs_query_data`按真实参数查询。按模块导航的发布状态见验收记录，勿在旧版本猜测参数。口径包含销售/毛利来源、日期/网站范围、分页、缺口及归因限制；指南可选，不强制模板。

大结果返回字段索引时，AI继续按`data_path`读取所需指标、维度或明细；数组展示按`next_offset`续页，业务查询参数保持。所选来源的实际网站/时间/币种与上游覆盖说明必须一起核对；展示分页不会替代上游订单分页或修正原数据口径。

## 数据验收

先调用 `fs_list_data_sources` 查看本人可见目录，再按operation/schema调用 `fs_query_data`。持续保留上游日期、币种、来源、覆盖状态、续页信息。销售快照续页携带首段snapshot_sha256，源更新时重新开始；实时订单沿原20条/28天/365天合同，不把第一页当全量。管理员、普通成员及private授权成员分别对照原FS页面；账号越权失败应明确报错。
