# FS连接器生产变更候选

尚未执行。本文件用于审阅具体影响范围，不是已上线回执。身份字段禁令删除已由用户直接授权；新增公共OAuth服务的生产接线仍按本清单确认。

## 已核现场

- FS原HTTPS入口为`https://47.85.224.112`，正常TLS校验与原登录跳转通过。
- 原门户本机8895，独立候选8937在核验时未占用；发布前再次检查。
- 187已有`python:3.12-slim`容器镜像；不升级原业务Python3.9。发布构建须固定实际基础镜像digest和最终镜像ID，不能把浮动标签当版本回执。
- 知识根`/var/lib/fs-hermes-fc/fs`为root:root 0700；原policy路径与published索引已核。此目录不能为新服务改成全员可读。

## 新服务与对外范围

独立容器只绑定`127.0.0.1:8937`，issuer为`https://47.85.224.112/connector`，MCP为同路径`/mcp`。沿原FS域名证书和门户；不新建SSH通道、改防火墙或接触183/187原RPG服务。

原FS nginx虚拟主机新增`/connector/`及精确发现路由`/.well-known/oauth-authorization-server/connector`、`/.well-known/oauth-protected-resource/connector/mcp`到8937。OAuth登录前的发现/注册/授权入口不能套“必须先有FS Cookie”的全局auth_request；MCP请求仍必须通过Bearer和原FS会话逐次验证。代理保留Host、关闭缓冲及包含授权query的访问日志，不提供其他任意代理路径。

服务配置：

```text
FS_CONNECTOR_ISSUER=https://47.85.224.112/connector
FS_CONNECTOR_ORIGIN=https://47.85.224.112
FS_CONNECTOR_PORTAL=http://127.0.0.1:8895
FS_CONNECTOR_PORT=8937
FS_CONNECTOR_DATABASE=/var/lib/fs-data-connector/oauth.sqlite3
FS_CONNECTOR_KNOWLEDGE_ROOT=/var/lib/fs-hermes-fc/fs
```

容器根文件系统只读，代码载荷只读，知识根精确只读挂载，仅独立OAuth目录可写；目录0700、数据库0600，包含代持FS会话，不入仓库/公开目录。使用现有root权限读取0700知识根时，容器不挂宿主根、父目录或Docker socket，drop全部capabilities并启用no-new-privileges。host网络仅为访问原loopback门户所需，同时意味着容器仍能连接宿主其他环回端口；应用固定路由及无任意URL/SQL工具是必须复核的边界，不能将capdrop宣称为网络隔离。

载荷包含连接器、原UI三项共享资产、原知识selector及`tools/export_fs_space.py`；不打包`.venv`、`.git`、测试凭据、生产数据或日志。运行依赖沿`requirements.txt`，镜像在隔离环境测试后固定。资源上限与已有P0服务预算发布前核对，不能通过降低原自动化能力腾资源。

## 原服务必要增量

沿既有publisher及发布锁，基于新鲜现场SHA备份与组装：

1. conversation HTTP与新增readonly helper：纯读附件清单/材料元数据。原UI清理、材料执行和停止/恢复行为不变。
2. 客单追踪controller/readonly helper：stored_only分支，不poll/queue。
3. 用户要求撤销身份输出禁令：tracking工具、报告绑定和提示、pool报告及对应规则内容；原权限保留，报告聚合容量和调度不退化。

tracking的customer_tracking/research等源已知存在现场漂移，必须按实际函数最小差异组装；不能把20261018/19历史全包覆盖现役服务，也不能以仓库同名文件推定活动来源。正式Git/CI与生产包版本分别读回。

## 验收及回退

先验证nginx语法、仅loopback监听、公开discovery、无token拒绝；再用真实FS身份完成授权、目录和数据对照。管理员、普通成员、private及对象归属分别验证允许/拒绝，原会话失效和撤权不可被refresh绕过。邮箱/UID/原订单号应在获准结果中保留，凭据不得返回。

ChatGPT个人/工作区、Codex主机、DeepSeek Harness副机分别验收，入口或版本未具备时如实标未验。检查原业务服务/定时任务保持原状态，HTTP200不代替业务结果。

失败时停新连接器、回退新增nginx条目与必要原模块精确文件；保留OAuth数据库及原业务DB/账本/任务/回执，不重放业务操作，不用旧整包回滚。只有新版本读回和真实入口通过才标对应阶段完成。
