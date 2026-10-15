# Hermes Desktop 完整管理接入（2026-10-15）

状态：候选，未部署。用户明确取消先前“保留现有保护”的接入限制，允许官方完整管理后台、配置修改、终端与工具管理。

一个负责人吴律/当前 Codex，一个 PR、原导航 publisher 串行发布。新入口固定镜像 v0.21.7 / 71d34bad1045610252eda02ee79549436896e784，与现有研究进程共用 /var/lib/fs-hermes-fc/profile，使用其原生 REST/WS；本地已安装的 Hermes Desktop 通过独立 SSH 本地转发接入 8942。

管理容器为 root，开放官方工具及免二次确认执行，/profile、/fs、/fs-source 可写并使用现有 DeepSeek 模型凭据。这是完整管理授权，不是原先的只读身份；持有桌面连接凭据的人可修改研究配置、任务资料和源码。模型调用由官方原生会话记录，其费用不冒认为原 FS 任务账本中的已核验费用。没有匿名公网监听。

确认后的业务约定保存 /fs/desktop-business-context.md；新 FS 任务冻结文本及 SHA，模板身份包括其 SHA，contexts 回执保留 SHA。现有调查不变、不重放。源数据、消息、记忆与历史失败均保留。

发布载荷为 release/candidate 的五文件；release/release_navigation.py 仅扩展原 publisher 精确目标范围，复用锁、CAS、备份、回读和回滚。管理服务首次启动另行执行 enable --now；SSH 专用身份由 configure_access.py 安装，私钥与 token 仅保存在本机忽略目录，禁止提交。Connect-Hermes.ps1 可重复打开连接；SSH 已断时重开启动器，不能重跑旧业务任务来验连接。

直接检查：test_context 三项验证约定冻结、真实 controller 的任务身份变化和 publisher 拒绝篡改；正式 pr-fast 登记该组。真实 Desktop 多轮、断线恢复、状态读取和约定保存仍须发布后验证，不能以结构检查代替。

回退：先停止/disable fs-hermes-desktop 服务并撤销专用 SSH 授权，再核对现场后用原 publisher 的 backup 与 manifest SHA 回退五文件；保留 profile、业务约定、数据库、任务、消息及费用记录。不要恢复旧 profile 数据库覆盖新会话。

旧受限适配文件保留在本地父目录作为未发布草稿，不进入本次 PR 或发布包。
