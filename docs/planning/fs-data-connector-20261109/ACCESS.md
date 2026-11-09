# 已有通道与正式入口

2026-11-09 本轮复核。以下是访问路径与源码证据，不包含凭据，不代表连接器已部署。

## 历史任务与当前结果

已读取历史任务《排查并修复自动改价》（`01a1b020-377b-73c3-ad16-3728cbdfbb05`）：其 2026-11-06/07 生产只读检查、发布与回执核验均通过现有 `server_187/access/Invoke-Server187.ps1`，使用 `Run` 和 `InputFile` 将任务脚本送入原解释器。不需要新建 SSH 通道或重配 GitHub。

本轮复用原工作目录 `E:\WorkBuddy\大超服务器` 中的该封装，`Check` 成功返回预期主机 `play187`；保留封装现有主机信任与身份配置，不复制密钥、不修改凭据。183 测试沿同目录 `server_183/access/Invoke-Server183.ps1`，与生产角色分开。

用户确认正式入口为 `https://47.85.224.112/dashboard/#overview`。2026-11-09 02:57 UTC，匿名 HEAD `https://47.85.224.112/dashboard/` 经正常证书校验返回 302，进入同站 `/__auth/access/?next=/dashboard/`。`#overview` 是浏览器页内路由，不发送给服务器。该结果证明公开入口和登录跳转可达，不代表登录后业务数据已验收。

此前 `events-origin.p2pah.cn/dashboard/` 的404来自另一虚拟主机。现役 nginx 配置表明 FS 与该域名分别匹配不同站点；不能据该404推断FS故障。后续连接器 origin 按正式 IP HTTPS 入口核验，不能继续使用猜测域名。

## 原登录接线

现役 `/opt/auth-portal/auth_portal.py` 加载 `/opt/auth-portal/registration-runtime/20261007-ca6258ad`。已现场读取该版本的 `portal_bridge.py` 函数 `try_reg_login`：已批准的注册用户经原 store 登录后，设置原 cookie 并重定向至 `next_q`。本地旧 `registration_approval_runtime_v3_20261006/portal_bridge.py` 缺少该函数，不能据此判定现网缺陷或覆盖现网。

连接器必须同时支持原 native 与注册会话 Cookie，沿原 portal 校验真实身份。仍需在实际客户端授权时验收原登录回跳、成员权限和撤权；不创建固定管理员身份代替用户。
