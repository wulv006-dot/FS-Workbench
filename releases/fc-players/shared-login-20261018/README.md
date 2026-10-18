# FC27 Players 共享后台登录

本 PR 回补已上线的 `2026.10.18-cloud.11.1`：FS 管理员使用服务端默认 Admin 共享会话，省去球员页重复密码/验证码登录。旧客户端读取登录配置即 HTTP 403；共享请求头与本机受限会话通道已验证。

后台密码不复制，token 仅在服务端内存和受限 Unix socket；原 Players UID 992 / GID 987、只读容器与价格锁挂载保持。socket 使用 Linux SO_PEERCRED 校验 UID 992，失败关闭。每次请求读取当前 token；重定向/目标白名单/未知写入禁止重传保持。前端只收到连接状态，退出仅断开该工具会话。

原全局/自动写关闭；手动上新、图片及已有模型开启推荐沿原开关、完整预览和人工确认执行，不增加业务范围。

## 检查与现场证据

- 原 Linux 断网候选 40 项通过，覆盖共享会话/原上新图片推荐合同。本 PR 对新共享测试复用现有 fixture，不改运行逻辑；通过既有 pr-fast 执行新的共享认证/本机通道测试及原推荐/确认检查，不新增 workflow。
- 2026-10-18 13:34:06 北京时间，真实 Chrome/FS wulv 新查询生成 e67a1282，完整读取 873/873 模型与 6 标签。最终 HTML 显示修正后浅暗/身份状态及禁用确认通过，运行 46 源逐 SHA 读回一致。
- 13 executions / 156 items / 0 active_scope / 22 legacy / 819 execution events 的摘要前后完全一致；本轮业务写入 0。真实 UID 992 身份通过，非 Players UID socket 请求拒绝。
- 共享服务原 Requires 依赖导致 FC worker 于13:32:56联动重启；后验 API/worker/browser/session 均 ok、queue及未确认执行0。未改 worker 代码/规则/调度。共享服务下一原有5分钟健康检查仍 ready。
- 未验收长期 token 续期、整机重启、其它真实角色或真实业务写入；CI 和读取成功不替代这些结果。

`SOURCE-MAP.json` 对应实际维护源、容器、服务路径和 SHA；`publication/` 保留两个历史精确差量清单。原私有日志、数据库/配置备份、浏览器截图留项目 `.agent_runtime/players-shared-20261018` 与 `docs/fc27-players/shared-login-20261018`，不上传本 PR。

## 发布约束

此次只回补源码和合并，不重发生产。历史 apply/manifest 不可重放：活动基线已改变，须重新取证/CAS。原球员发布器与共享准入/发布/采集锁、备份和回退保留，不恢复旧DB/账本/队列/锁。共享伴随发布器的原冻结依赖不重复入库：如需准备独立审核包，将 `releases/fs-dashboard/admin-data-tools-20261018/publisher/release_navigation_base.py` 的精确字节复制至包内 publisher/，须匹配 SHA256 `1d070ee806caf850ffbbd4f4a884acd2d98a39b6f464f562c1fbb3548707f2de`。此说明不授权重放旧发布。
