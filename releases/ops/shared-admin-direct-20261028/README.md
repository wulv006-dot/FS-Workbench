# 旧共享 Admin 传输兼容迁移（候选，2026-10-28）

只替换 `/opt/fs-order-session/fc_shared_admin.py` 内部传输，不改RPG业务、定价、工单、计时器、Order浏览器或FC独立adapter。现场原文件SHA为 `a676388f0011b5f0ca116b0bfb2a1d428c8782e5538f8402e8734a5405beaa42`，与 `order_global_session_20261021/fc_shared_admin.py` 完全一致；后者保留历史维护记录。本包接替该一个生产目标，不能覆盖 `/opt/fc27-cloud-browser/fc_shared_admin.py`。

源码复用本轮FC独立adapter的标准库HTTP实现，新增旧构造兼容：空config及显式 `https://admin-api.p2pah.cn` 归一为宿主8912／Docker8913；显式8911、8912、8913继续支持，`FS_ADMIN_API_BASE`可显式指定。旧 `FS_ADMIN_SESSION_URL` 不再参与连接。没有实际公开HTTPS、8767、BATOKEN、凭据文件、登录/刷新或验证码请求。

原外部接口保留：`HEADERS`、`read_private_config()`、`allowed_admin_usernames()`、`SessionManager(config)`、`ensure()`/`.token`、`request(path,data=...,token=...) -> (HTTP status,bytes)`。身份只认可实际API账号wulvapi/chenchaoapi，不依赖root。`ensure`保留8秒，普通请求保留15秒；每次只发送一次，无跨口自动重发；HTTP拒绝保留原响应，传输失败继续抛给原调用方判定UNKNOWN。

## 现役调用及加载边界

- D4原 `admin_cache_local.load_token()` 使用空构造；`clear_cache()` 使用显式旧HTTPS构造及 `request(data,token)`。真实原客户端纳入Mock回归，不在服务器执行清缓存。
- 现场 `p2pah-srv-exec.service` 的readgold和工单两个docker启动点将该共享文件bind到 `/srv/fc_shared_admin.py`，网络为fc27-cloud-net；Docker默认选8913，因此原启动命令无需改变。真实启动列表及SrvSession类片段带来源SHA保存在 `tests/fixtures/actual-d4-callers.json`；测试只分析表达式，不执行docker/浏览器/工单。
- `rpg-cache-retry.timer` 当前仍启用，原8911不可用时的旧共享调用也经新传输；其重试预算、回执及业务逻辑均不改。
- 新RPG子进程/新容器导入时读取新文件，不需要为了此文件改业务调度。替换前仍应核当前在途RPG容器；已bind的旧inode及已导入模块不会因宿主替换自动更新，不能在未核这些在途进程前宣称8767全局退役。

## 验证与状态

9项离线回归覆盖实际D4客户端、原两启动点/reader、空/旧HTTPS构造、API账号绑定、8/15秒预算、无凭据文件、HTTP拒绝、单次POST及UNKNOWN。命令：

```powershell
python -X utf8 -B -m unittest discover -s releases/ops/shared-admin-direct-20261028/tests
```

候选以socket仅允许8911/8912/8913，在内存执行的只读身份验收：

- 宿主8912：ensure成功，HTTP200/code1，wulvapi/superfalse。
- 宿主8911：ensure成功，HTTP200/code1，chenchaoapi/superfalse。
- 既有桥接容器默认归一8913：ensure及原request读身份均HTTP200/code1，wulvapi/superfalse。容器仅作网络命名空间验证，未调用8767、未登录、未写文件或改容器。
- 最初宿主探针在ensure成功后多读一次身份时发生15秒超时；未因此扩大等待或重发业务写入。随后采用每账号一次ensure读取元数据，三路必要身份验收通过；不据此声称真实RPG清缓存或写价验收。

脱敏实读证据在项目 `.agent_runtime/admin-recovery-20261028/p1_shared_{primary,backup,bridge}_evidence.jsonl`。当前仅候选源码和本地/只读验收，不证明正式CI、合并、上线或RPG自然周期。由主代理统一沿原发布流程核CAS、部署和退役8767，不在本包新增publisher或后台服务。
