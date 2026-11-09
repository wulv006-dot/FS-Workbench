# FS 客户端接入

服务已发布：`https://47.85.224.112/connector/mcp`。2026-11-09 Codex真实OAuth登录已通过，已通过目录、客户追踪及同一月范围查询；新版导航、模块口径、月度指标及明细分页也经原生模型确认无截断；ChatGPT手动配置的授权回跳通过，但云端令牌兑换返回503，尚未接通。客户端进度见 [LIVE-ACCEPTANCE.md](LIVE-ACCEPTANCE.md)。每个成员用自己的 FS 账号授权；主机、副机各自完成登录，其他电脑不会改变服务器数据权限。

## 先确认网络和账号

2026-11-09创建者确认：FS仅对白名单IP开放。连接器沿用这条网络边界，安装客户端不会自动增加白名单。

1. 在准备运行Codex/Harness的电脑上，用浏览器打开[FS首页](https://47.85.224.112/dashboard/)，确认能正常进入登录页或自己的工作台。网页403、无法连接或超时，先处理网络准入，不能靠重复OAuth解决；能打开登录页仍需下一步验证客户端所在进程的出口与代理配置。
2. 每位同事需要自己的FS账号及原有业务权限；没有账号或没有某模块权限时，由FS管理员按实际工作需要分配。主机/副机分别登录，不复制他人Cookie或令牌。
3. 本机Codex/Harness的连接请求通常由运行它的电脑发出；远程运行Harness时，则由远程Host发出，应核该Host的出口IP。ChatGPT云端发起发现、令牌兑换及工具请求，不沿用用户浏览器的出口IP。电脑和浏览器可达不证明ChatGPT可达。

当前白名单前提与此前ChatGPT浏览器授权回跳成功、云端token兑换失败相符；没有取得该次请求的具体拒绝回执，不能把503精确归到某一条规则。本次未修改白名单。

ChatGPT后续可选网络方案：仅对连接器及必要OAuth/发现路径允许OpenAI公布的ChatGPT连接器出口范围，保留FS逐人授权；或者评估官方Secure MCP Tunnel。前者需要具体网络规则变更，后者还需组织/工作区配置与OAuth可达性验收，均未实施。隧道不是安装后自动解决全部OAuth访问的承诺。

参考：[OpenAI出口范围](https://developers.openai.com/api/docs/guides/ip-addresses)、[Secure MCP Tunnel与OAuth限制](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels#oauth)。

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

副机已有Harness时无需重装FS或部署服务器，保留原模型设置，只增加FS连接。

1. 先完成上面的网络与FS账号检查。使用当前官方npm版新装Harness时，官方源码要求Node.js >=24.9.0；已有桌面版不为本连接器强制升级。该配置还需要本机`node`和`npx`可用。
2. 下载本目录的 [fs-mcp.patch.yml](fs-mcp.patch.yml)，放到副机一个自己能找到的目录。该文件只有服务器地址和桥接启动参数，不含账号或令牌。作为独立patch加载，不覆盖现有模型/插件配置。
3. 在该目录启动一个使用此patch的Harness实例：

```text
npx @deepseek-ai/dsh web --patch ./fs-mcp.patch.yml
```

已安装CLI的用户也可以在原启动命令追加`--patch ./fs-mcp.patch.yml`；源码版沿原`pnpm dsh web`启动方式追加该参数。不要同时再在Settings中添加同名fs，避免重复注册。

4. 第一次加载会由`mcp-remote@0.1.38`打开本机浏览器。在浏览器中使用**自己的FS账号**登录并允许读取；确认回到成功页后，再向Harness发起数据查询。必要时重载该实例以获取工具列表。远程/无浏览器Host不能直接套用此本机流程，须另核浏览器回调如何到达运行桥接的Host。
5. 让AI先调用`mcp__fs__fs_list_data_sources`；看到导航后，再按module读取参数与口径并调用`mcp__fs__fs_query_data`。工具未出现时先查看该MCP连接的启动错误；不要把未连接当空数据。

可选：当前Harness若提供MCP Settings，可新增stdio服务：名称`fs`、命令`npx`、参数按patch中的args逐项填写，作用等价；界面字段随副机实际版本核定。固定patch方案依据官方MCP client及insert模板，不依赖某个界面名称。

这里`http-only`仅表示使用Streamable HTTP传输，实际地址仍是HTTPS。OAuth由本机桥接器处理，令牌保存在该电脑；不要求复制FS Cookie，也不需要共享FS服务器密钥。此路径不经过ChatGPT云端，因此不依赖ChatGPT的503先恢复。

以上配置按2026-11-09官方源码核对，**副机实际安装及OAuth尚未验收**。Harness官方仍处于developer preview，旧版本的插件/启动参数需与其安装版本匹配。

参考：[Harness安装](https://github.com/deepseek-ai/deepseek-harness#run)、[MCP客户端](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)、[官方patch模板](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/preset/agent-preset/skills/cordis-plugin-development/templates/mcp/cordis.patch.yml)、[mcp-remote](https://github.com/geelen/mcp-remote)。

## 月报等分析的用法

连接器只提供本人可读的FS数据、调用参数、计算口径和覆盖说明。用户自己的AI按问题选择查询，独立分析、归因并生成报告；不连接Hermes会话或调用其报告生成。先通过`fs_list_data_sources`取得简短导航，再传`module`取得该模块完整参数与`data_methods`，然后用`fs_query_data`按真实参数查询。上述按模块导航和分块读取已随PR #938发布，实际验收见记录。口径包含销售/毛利来源、日期/网站范围、分页、缺口及归因限制；指南可选，不强制模板。

大结果返回字段索引时，AI继续按`data_path`读取所需指标、维度或明细；数组展示按`next_offset`续页，业务查询参数保持。所选来源的实际网站/时间/币种与上游覆盖说明必须一起核对；展示分页不会替代上游订单分页或修正原数据口径。

## 数据验收

先调用 `fs_list_data_sources` 查看本人可见目录，再按operation/schema调用 `fs_query_data`。持续保留上游日期、币种、来源、覆盖状态、续页信息。销售快照续页携带首段snapshot_sha256，源更新时重新开始；实时订单沿原20条/28天/365天合同，不把第一页当全量。管理员、普通成员及private授权成员分别对照原FS页面；账号越权失败应明确报错。
