# sales 复用 8767 会话：离线补丁

日期：2026-10-21。最新状态：用户后续明确授权部署及统一Admin凭证，sales与本次盘点的Admin入口已部署；8767和sales同步保持冷却停服，无后台登录。下文离线交付段落保留原阶段边界，最终状态见同目录 `DEPLOYMENT.md`。

## 模块与范围

sales 为独立销售看板，程序 `/opt/sales-dashboard`，采集入口 `collector/fetch_all.py`，调度入口 `run.py`；原定时器每30分钟同步，发布数据 `/var/www/sales/data/dashboard.json`。本次只修改认证依赖，不改统计、优惠归因、数据缓存、发布门禁及调度频率。

原故障链按用户提供的核查结论记录：同一后台账号被会话服务及 sales 重复登录顶号，并遭账号级限流。当前环境不存在用户指定的 `D:\共享资源\服务器\后台会话503排查_20261021\说明.md`，未独立复现其历史日志或登录结果。不得为复现触发登录。

服务器首次只读核对：`fc27-p2pah-session` 为 failed，`sales-dashboard-sync.timer` 为 inactive。检查未启停任何服务。服务配置指向 `fc27-cloud-session:single-owner-20261021-v1`，镜像 ID `sha256:7ddaedd58e03eef14156d6eccf245a762cb7875042578aa4cbba17c1e8b5d892`；旧 `/opt/fc27-cloud-browser` 源码不能作为这个镜像的接口依据。

## 现场并行修改与基线

核对过程中发现 `p2pah_auth.py` 被其他执行方修改：原 SHA `0c61a967ed2a42d13d693be7a2cbff08599c240d8a1a4ce793fa20ea0f804a04` → 当前 `b3f5b93de88a9f38584ea14a96208bc315d9d75aea73e8b1571a7822c8bae231`。新现场版本已改为读取 `GET http://127.0.0.1:8767/session/admin-token`，并禁用 `admin_login`。本补丁基于后者增量收口，不覆盖这份并行修改，不声称该修改由本轮上线。

`fetch_all.py` SHA：`40b10656b8ece6521de3211fbaddc99ce3daaa2fce0a61e4b7488af372edcb91`。全部 Admin 调用为 GET：

| 用途 | 原后台路由 |
|---|---|
| 销售订单 | `/admin/order.Order/index` |
| 折扣码 | `/admin/market.Discount/index` |
| 会员 | `/admin/user.Member/index` |

消费模型是通过8767只读取当前 token，再由原采集器请求上述后台接口，并非新增通用后台转发代理。8767读取使用固定回环地址，禁用代理及跳转，一次请求，无重试；响应大小和 token 类型/长度/控制字符均校验，错误不带响应正文、密码或 token。

经用户明确允许，在服务器内离线读取目标镜像（未运行容器），确认该路由存在，委派至 `manager.admin_token`；该方法无函数调用，只访问 `lock/status/token`，不执行login、refresh或ensure。原始镜像及源码没有传到本机，返回仅含调用名/属性名。最初源码正则脱敏回读及镜像检查曾被自动审批拒绝；前者改用全部字符串删除的AST结构检查，后者得到本次明确允许后执行；无绕过拒绝或秘密导出。

移除缓存 Admin token 回退与后续落盘；保留原 Order cookie 及 Order 登录行为。Admin 不可用时在进入 Order 登录及采集前失败并关闭 Session；Admin 独立登录函数始终拒绝。移除独立认证脚本的探测入口，避免运行文件时输出会话信息。用户名/密码保留既有环境变量名，去掉所有源码默认值；Order 缺凭据明确失败。

## 交付与验证

补丁目录：`sales_shared_session_20261021/`。

- `prepare_patch.py`：读取确切基线，在新目录生成候选；不覆盖输入，不操作服务。基线变化即拒绝，不允许通过改 SHA 强行使用。
- `shared_admin.py`：8767读取客户端；生成后与 `p2pah_auth.py` 同放 `collector/`，适配既有脚本目录导入方式。
- `test_patch.py`：5项离线测试，含成功响应、503/错误JSON/不合法token/超大响应、网络错误不重试、拒绝跳转、认证失败前置停止、禁用独立登录、Order流程与缓存字段保留、源码默认凭据移除。
- `sales-dashboard-sync.service.conf` / `sales.env.example`：环境配置交接模板，未安装。

本地测试命令：

```powershell
python -m unittest discover -s sales_shared_session_20261021 -p test_patch.py -v
```

结果：5/5通过。另在服务器进程内存中对真实基线执行转换和编译，不导出原始源码、不写候选文件、不发网络请求。候选 SHA `f6a90024e5ac648fce96978cc31b3292768676669b1404aa466ed8227fb175b4`，编译通过。没有把本地合成测试称为真实登录或数据采集验收。

## 后续应用条件（本轮不执行）

1. 保持停服；在服务器隔离候选目录使用其 Python 3.9+运行 `prepare_patch.py /opt/sales-dashboard/collector/p2pah_auth.py <全新候选目录>`。脚本及同目录helper须一起交付。当前原文件若变化，重新审查差异。
2. 实际Order凭据仅在服务器配置到 `/etc/sales-dashboard/sales.env`，root所有、0600；不要放入报告/聊天/仓库。将交付drop-in安装为 `/etc/systemd/system/sales-dashboard-sync.service.d/shared-session.conf`。模板是占位，不能直接用于生产。不要用 `systemctl show Environment` 输出值。系统服务默认权限与文件可读性需应用时核对。
3. 后续明确发布授权后，在输入SHA仍匹配时备份原文件，将两份候选文件受控替换到collector；仅执行必要配置加载，不因安装补丁启动服务或定时器。原session状态文件含敏感值，不导出；下一次成功save会去掉旧Admin字段，本轮不提前改写它。
4. 本次不批准恢复。按用户冷却要求，2026-10-22 11:30（上海时间）之后，另行确认允许验证，再做一次登录及身份校验；这个时间仅为最早考虑验证点，并非已证实的后端解封时刻。不得启动自动循环来充当单次验证。
5. 单次通过后，再按授权恢复唯一会话服务和sales同步；真实数据读取、发布门禁和自然30分钟周期另验。回滚不得恢复独立Admin登录后同时运行两个消费者；回滚代码时仍保持sales停用。

会话服务重试/退避、账号级冷却策略、健康错误字段由已有单owner版本及后续独立任务负责，本补丁不重建镜像、不修改后端策略或新建账号。新文件不在 `server_187/manifest.json` 中，不触发无关副本重建。
