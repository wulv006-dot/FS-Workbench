# FS 客户端接入（待发布验收）

候选公共地址：`https://47.85.224.112/connector/mcp`。当前尚未发布，以下配置不能当作已接通回执。每个成员用自己的 FS 账号授权；主机、副机各自完成登录，其他电脑不会改变服务器数据权限。

## Codex

发布并验证 discovery 后运行：

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

## 数据验收

先调用 `fs_list_data_sources` 查看本人可见目录，再按operation/schema调用 `fs_query_data`。持续保留上游日期、币种、来源、覆盖状态、续页信息。销售快照续页携带首段snapshot_sha256，源更新时重新开始；实时订单沿原20条/28天/365天合同，不把第一页当全量。管理员、普通成员及private授权成员分别对照原FS页面；账号越权失败应明确报错。
