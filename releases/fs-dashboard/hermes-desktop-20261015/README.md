# Hermes Desktop 完整管理接入（2026-10-15）

状态：PR151/152 已合并部署，完整管理接入可用。用户明确取消先前“保留现有保护”的接入限制，允许官方完整管理后台、配置修改、终端与工具管理。

一个负责人吴律/当前 Codex，一个 PR、原导航 publisher 串行发布。新入口固定镜像 v0.21.7 / 71d34bad1045610252eda02ee79549436896e784，与现有研究进程共用 /var/lib/fs-hermes-fc/profile，使用其原生 REST/WS；本地已安装的 Hermes Desktop 通过独立 SSH 本地转发接入 8942。

管理容器为 root，开放官方工具及免二次确认执行，/profile、/fs、/fs-source 可写并使用现有 DeepSeek 模型凭据。这是完整管理授权，不是原先的只读身份；持有桌面连接凭据的人可修改研究配置、任务资料和源码。模型调用由官方原生会话记录，其费用不冒认为原 FS 任务账本中的已核验费用。没有匿名公网监听。

确认后的业务约定保存 /fs/desktop-business-context.md；新 FS 任务冻结文本及 SHA，模板身份包括其 SHA，contexts 回执保留 SHA。现有调查不变、不重放。源数据、消息、记忆与历史失败均保留。

首次发布载荷为 release/candidate 的五文件；release/release_navigation.py 仅扩展原 publisher 精确目标范围，复用锁、CAS、备份、回读和回滚。管理服务已 enable --now；SSH 专用身份由 configure_access.py 安装，加密私钥与 token 仅保存在本机忽略目录，禁止提交。

Connect-Hermes.ps1 由桌面「Hermes智体（服务器）」调用，按需启动单例连接守护，登录会话内每五秒检查连接，SSH 退出或连接连续三次失效后自动重建。Windows SSH agent 自动启动并保留加密身份。双击先验证凭据及后台再打开同一客户端；端口被无关程序占用会拒绝，启动失败显示提示。断线恢复不提交或重放对话、调查和业务动作。连接守护持续至 Windows 注销；电脑开机登录后仍由双击入口启动。

底部「后端 消息网关已停止」是官方客户端把可选消息平台 gateway 状态放在后端旁边；现有部署未配置 Telegram/Discord，这不表示桌面对话后端离线。未伪造 gateway 运行状态、未开启额外消息平台。

直接检查：test_context 四项验证约定冻结、真实 controller 的任务身份变化、publisher 拒绝篡改及公钥校验；Test-Connect.ps1 使用真实连接辅助函数验证进程归属、凭据拒绝、离线失败和可选 gateway 停止不阻塞连接，均由原 pr-fast 登记。Windows 真实快捷方式冷启动、重复打开与中断专用隧道恢复另验，不能把 Linux 离线测试当桌面输入验收。

回退：先停止/disable fs-hermes-desktop 服务并撤销专用 SSH 授权，再核对现场后用原 publisher 的 backup 与 manifest SHA 回退五文件；保留 profile、业务约定、数据库、任务、消息及费用记录。不要恢复旧 profile 数据库覆盖新会话。

旧受限适配文件保留在本地父目录作为未发布草稿，不进入本次 PR 或发布包。
