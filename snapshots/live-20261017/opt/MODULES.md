# FS 平台运营管理中心 · 模块地图（唯一真源）

> 服务器：阿里云 ECS `47.85.224.112`（公）／`172.18.108.187`（私）· hostname `play187` · CentOS 7.9
> 入口：`https://47.85.224.112/` → 301 → `/dashboard/`（经营数据看板主页 + 顶部全局导航条）
> SSH：`ssh -i D:\共享资源\服务器\No1.pem root@47.85.224.112`
> 本文件维护于 2026-09-29。**改任何东西之前先读本文件的一节，别整份读。**

---

## 一、阅读礼仪（省 token 的关键）

| 场景 | 你该读什么 | **别读什么** |
|---|---|---|
| 改某个模块的功能 | 只读该模块那 1~2 个 py 文件 | 别把 `/opt/d4follow/*.py` 全读一遍 |
| 加/改接口路由 | `app.py` 的「路由」段（约 2275 行之后） | 前 2274 行的业务逻辑 |
| 改控制台页面 | `templates/index.html` | 后端 py |
| 改离线看板 | `build_dashboard.py` | 服务端 py |
| 查跟价业务规则/踩过的坑 | 技能 `competitor-price-follow` 的 `references/` **对应分册** | 别读整份技能 |

---

## 二、模块总表（nginx 路由 → 端口 → 目录 → 服务）

| # | 模块 | 入口 URL | 后端 | 目录 | 服务 | 鉴权 |
|---|---|---|---|---|---|---|
| 1 | **经营数据看板**（主页主体） | `/dashboard/` | 静态 | `/var/www/dashboard` | — | 登录页 |
| 1b | 　└ 看板**采集器**（P2PAH 9 目标，**本机采集，已于 2026-10-05 从办公 PC 迁到服务器**） | — | — | `/opt/dashboard-collect` | `dashboard-pipeline.timer` 12:15<br>`dashboard-fallback.timer` 18:15 | — |
| 2 | 　└ 只读数据接口 | `/dashboard/api/` | 静态 | 同上 | — | `X-Api-Key` |
| 3 | **部门手册**（腾讯文档 iframe 活引用） | `/docs/` | 静态 | `/var/www/docs` | — | 登录页 |
| 4 | **自动改价系统**（D4/全游戏跟价） | `/d4/` | 8900 | `/opt/d4follow` | `d4follow.service` | 登录页 |
| 5 | 　└ 服务器端执行器 | 内部 | — | `/opt/d4follow/srv_exec.py` | `p2pah-srv-exec.service` | — |
| 6 | **顶部全局导航条**（全站注入） | `/__hub/hubnav.js` | 静态 | `/var/www/hub` | — | 无 |
| 7 | MLB 上架工作台 | `/mlb/` | 8897 | `/opt/mlb-online` | `mlb-online.service` | 登录页 |
| 8 | 自助部署通道 | `/deploy/` | 8898 | `/opt/deploy-hub` | `deploy-hub.service` | 登录页 + `deploy` 组 |
| 9 | FC27 只读门禁 | `/fc27/` | 8896 | `/opt/fc27-gate` | `fc27-gate.service` | auth_request |
| 10 | FC27 运营看板 | `/s/wulv/fc27-ops/` | 静态 + 8899 api | `/opt/fc27-ops` | `fc27-ops-api/worker` | 门禁 |
| 11 | FC27 活动日志 | `/dashboard/fc27-activity-api/` | 8878 | `/opt/fc27-activity-api` | `fc27-activity-api.service` | 登录页 |
| 12 | FC27 云采集 | `/api/fc27/cloud/` | 8879 | `/opt/fc27-cloud-browser` | `fc27-cloud-api/worker` | 登录页 |
| 13 | FC27 玩家工作台 | `/tools/fc27-players/` | 8901 | `/opt/fc27-player-tool` | `fc27-player-tool.service`(docker) | FC27 门禁（302 → `/fc27/login`） |
| 14 | FC 赔率工具 | `/s/wulv/fc-odds/` | 静态 | `/var/www/sites/wulv` | — | 登录页 |
| 15 | MMOEXP 抓取主站 | `/`（兜底 8787） | 8787 | `/opt/iggm-web` | `iggm-web.service` | 无（已无正式入口） |
| 16 | P2PAH 会话容器 | 内部 8767 | — | docker `fc27-cloud-session:1` | `fc27-p2pah-session.service` | — |
| 17 | **NBA 2K27 改价控制台**（VC 金币 · 三端） | `/nba2k27/` | 8765 | `/opt/nba-reprice/backend` | `nba-reprice.service` | 登录页 |
| 18 | **G2G 金币改价系统**（AION2 Kinah · 独立于 d4follow） | `/g2g/` | 8903 | `/opt/g2gfollow` | `g2gfollow.service` + `g2g-token-refresh.timer` + `g2gfollow-auto.timer` | 登录页 |
| 19 | **Discord 机器人控制台**（MMOEXP GuardBot 防冒充 + Shugo-bot 迎新/资讯） | `/bots/` | 8936 | `/opt/bot-console` | `bot-console.service` | 登录页（写操作需 `X-Auth-Role=admin`） |

> **Discord 机器人控制台（2026-10-14 新增 · `/bots/`）**
> 纯 Python 标准库单文件后端 `/opt/bot-console/server.py`，只监听 `127.0.0.1:8936`，对外统一走 nginx
> `/bots/` + 统一登录门户 `auth_request`（片段 `/etc/nginx/bot-console.locations.conf`，
> 以 `# >>> bot-console-20261014 >>>` 标记块 include 进 `iggm-web.conf`）。
> 管的两个机器人：`moexp-guardbot`（Node，`/opt/mmoexp-guardbot`，防冒充守卫）与
> `shugo-bot`（Python，`/opt/shugo-bot`，AION2 迎新面板 + 官方资讯推送）。
> ⚠️ **必须用 `/opt/bot-console/venv/bin/python` 启动** —— `/usr/bin/python3` 的构建漏了 `_ssl` 模块，
> urllib 发不出 HTTPS，Discord 角色/频道查询会全部失败（`unknown url type: https`）。
> venv 基座是完整的 `/opt/python39`；代码里另有 `curl --config -` 兜底（token 走 stdin，不进 argv）。
> 权限：读操作任意登录用户，写操作（改配置 / 启停服务）要求 `X-Auth-Role=admin`；
> 配置写入前自动备份到 `/opt/bot-console/data/backups/`，全部写操作审计到 `data/audit.log`。
> Token 永不回传浏览器（前端只拿 `hasToken` 布尔）。

> **NBA 2K27 改价控制台（2026-09-30 新增，部门同事 DY 交付的部署包落地）**
> 前端静态 `/var/www/nba2k27/`；后端 Node.js 单文件 `server.js`（`/usr/local/node` 用的是
> **glibc-217 变体** —— CentOS 7 的 glibc 2.17 跑不了官方 Node 18 二进制）。
> 验证码识别走独立 venv `/opt/nba-reprice/venv`（ddddocr + **numpy<2**，⚠️ 别升 numpy 2.x，onnxruntime 1.16 会 ImportError）。
> 后端只监听 `127.0.0.1:8765`（`BIND_HOST`），对外统一走 nginx `/nba2k27/` + 统一登录门户。
> ⛔ `location /nba2k27/api/` 的 `proxy_pass` 必须写成 `http://127.0.0.1:8765/api/`（写成 `8765/` 会把
> `/nba2k27/api/health` 译成后端 `/health` → 404，因为 nginx 只替换匹配到的那段前缀）。
> `WRITE_READY=false` 时只读；改成 `true` 才会真实写入 admin-api.p2pah.cn。凭据在 `/opt/nba-reprice/backend/.env`（chmod 600）。

> **G2G 金币改价系统（2026-10-12 · token 供应链搬到服务器）**
> 原本 accessToken（900s 寿命）靠本机 Windows 上的专用 Chrome 续签后 ssh 推到服务器 ⇒ **本机一关就断供**。
> 现改为服务器自持：`/opt/g2gfollow/tools/g2g_token_refresher.py` + `g2g-token-refresh.timer`（每 3 分钟）
> 直接 `POST https://sls.g2g.com/user/refresh_access`（body 只需 `user_id` + 三个长期令牌，
> **不需要 Cookie 头、不需要 accessToken、不需要浏览器**），原子写 `var/token.json`（schema 与旧保活器逐字一致）。
> 长期凭据在 `/opt/g2gfollow/var/g2g_session.json`（chmod 600，⛔ 不进 git）；失败/即将到期会推钉钉（复用 `/opt/d4follow/dingtalk.env`）。
> 本机保活器与计划任务 `G2G-Token-Keeper` **已停止并禁用**（定义保留可回滚）。
> ⚠️ **登录无法自动化**：G2G 强制邮箱验证码。长期令牌失效时需人工登录一次，再跑
> `G2G改价系统_20261010/脚本/g2g_export_session_to_server.py` 回迁凭据。详见 `发布_20261012/README_服务器托管续签.md`。

> **G2G 金币改价系统（2026-10-12 · 15 分钟全自动轮 + 人民币换算看板）**
> 在此之前 G2G 货架**没有任何自动调度**，全靠人工在看板上点「① 采集」→「③ 执行真实写入」。
> 现新增 `g2gfollow-auto.timer` + `tools/auto_cycle.py`：**每 15 分钟**跑一轮
> 「采集（DD373 成本 + G2G 货架）→ 按 `最小变动百分比` 自动放行 → 真实写入」，
> 走的是与看板按钮**完全同一条 HTTP 链路**（127.0.0.1:8903 的 `/api/collect`、`/api/release_all`、`/api/execute`）。
> - 三道安全闸（任一不过 ⇒ 本轮只记日志、不改价）：① 建议单必须比本轮新（防拿旧单执行）；
>   ② 闸门价区数 > `自动.闸门价区上限`（默认 20）⇒ 疑 DD373 采集中断；③ 无成本数据区数 > `自动.无成本数据上限`（默认 15）。
> - **关掉自动**：`systemctl disable --now g2gfollow-auto.timer`；或把 config `自动.启用` 置 `false`。
> - ⚠️ 本机 systemd 219 的坑：定时器**只用单调时钟目标**（`OnActiveSec` + `OnUnitInactiveSec=15min`）。
>   照抄 `d4follow-collect.timer` 的 `OnBootSec=6min` + `Persistent=true` 时，因开机已久，
>   OnBootSec 会被算成**过去**的时间点 ⇒ `list-timers` 的 NEXT 显示为两周前、定时器持续空转重触发（实测多跑一轮）。
> - 成本口径同步调整：DD373「买满量」由 **1 亿 → 1.5 亿**基纳（config `定价.买满量_万基纳`）；
>   **`定价.够量闸门_万基纳` 刻意保持 1 亿不动** —— 实测提到 1.5 亿会有 12 个区、提到 3 亿会有 30/74 个区
>   从竞争价跳到 $19.9 保护价（见 `G2G_15分钟自动与人民币换算_20261012/说明.md`）。
> - 看板新增**人民币换算**（`$/M → 元/万基纳`，与 DD373 同口径）+ **毛利率 / 净利率**两列 +
>   「平均毛利率 / 平均净利率」指标卡；净利率扣 `费用.G2G综合费率`（默认 0.15 = 佣金 9.99% + 提现 2.99% + 换汇 ~3%）。

nginx 配置：**单一 server 块**，全部集中在 `/etc/nginx/conf.d/iggm-web.conf`。

> **鉴权（2026-09-30 17:07 起已全站切换）**：全站从 nginx Basic Auth（浏览器原生弹框）
> 换成 **`/opt/auth-portal`（端口 8895）+ 统一登录页 `/__auth/login` + `MMOEXP_AUTH` Cookie 会话**。
> 上面表格里的「登录页」= `auth_request /__auth_verify`；`/deploy/` 另走 `/__auth_verify_deploy`（`deploy` 组）。
> 账号口令**没变**，仍读 `/etc/nginx/.htpasswd-dashboard`（5 人）与 `.htpasswd-deploy`（4 人）。
> 旧的 `.htpasswd-*` 仍是唯一凭据源，只是不再由 nginx 自己弹框。
> ⚠️ **真正决定“能不能发布/改价”的不是 htpasswd 文件**，而是
> `/opt/fs-access-policy/access_policy.py` 里的 `ADMINS = frozenset(('wulv', 'chenchao', 'DY', 'fstech'))`。
> 把用户写进 `.htpasswd-deploy` 只会让状态页多出一个人数，**实际仍被 403 拒绝**（已实测：2026-10-05 加入 fstech 时暴露此行为）。
> 当前架构里 **“能发布” ≡ “是管理员”**，没有中间档：加进 ADMINS 会连带改价/发钉钉推送/清缓存等全站写权限。
> 改动 ADMINS 后必须 `rm -f /opt/fs-access-policy/__pycache__/access_policy.cpython-*.pyc` 再 `systemctl restart auth-portal`（.pyc 缓存不会自动失效）。
> 另：服务器上**没有 `htpasswd` 命令**，加账号要用 `/opt/python39/bin/python3` 导入 `auth_portal.apr1_md5()` 现算摘要（与校验端同算法）。
详见 `统一登录门户_20260930/说明.md`。

> **gzip（2026-09-29 起）**：在 `nginx.conf` 的 `http` 块统一开启，且必须带 `gzip_proxied any`
> （不设它，反代响应默认**不**压缩，等于白开）。**⛔ 不要在 location 里写 `gzip off`** ——
> `/d4/` 曾因一行 `gzip off;` 把首屏载荷 447KB 全量明文发出去，跨境要 4~5 秒。
> SSE 实时日志是 `text/event-stream`，不在 `gzip_types` 里，天然不会被压缩/缓冲，无需关闭。

---

## 二之二、看板采集器（`/opt/dashboard-collect`，2026-10-05 从办公 PC 迁上云）

**入口**：`/opt/dashboard-collect/p2pah_unified.py --days 90 --no-manual` → `publish_to_server.py`
**定时**：`dashboard-pipeline.timer` 12:15 · `dashboard-fallback.timer` 18:15（均 `Persistent=true`）

⏰ **这台机器的 IP 已在 `admin-api.p2pah.cn` 白名单内**（2026-10-05 实测
`GET /admin/index/login` → 200 且回显 `"ip":"47.85.224.112"`）。
旧文档里「服务器不在白名单、采集必须留本机」的说法**只对已停用的 `47.253.252.55` 成立**，已作废。

| 文件 | 职责 | 备注 |
|---|---|---|
| `p2pah_unified.py` | 登录 → 9 目标抓取 → 原子落盘 → 重建看板 | 登录三级降级见下 |
| `publish_to_server.py` | 发布到 `/var/www/dashboard` | ⭐ **已改**：ssh/scp → 就地 `copyfile`+`os.replace` |
| `ensure_today_published.py` | 兜底判断 | ⭐ **已修**：见下方「老缺陷」 |
| `captcha_solver.py` | ddddocr 识别 4 位数字验证码 | `/opt/python39` 里**已装 ddddocr**，可直接用 |
| `health_check.sh` | 健康巡检（数据新鲜度+定时器+登录链路） | 退出码 0=健康 1=需人工介入 |
| `_orig_windows/` | ⭐ 改前 Windows 原版（回滚点） | 回滚：`cp _orig_windows/publish_to_server.py .` |

**发布语义**：先写 `.tmp` 再 `os.replace` 原子替换，访客永远读不到半个文件
（等价于原服务器端 `mv -f`）。用 `copyfile`+`replace` 而非直接 `os.replace`
是因为跨文件系统（`/opt`→`/var`）`rename` 会抛 `EXDEV`。

**登录三级降级**（`ensure_token`）：本地 token → `refresh_token` 续期 → ddddocr 重登。
实测「复用本地会话成功」。`.session.json` 含明文 token，**不要外发**。

### ⛔ 已修的老缺陷：兜底时段恒定误判（2026-10-05）

`ensure_today_published.py` 原靠 HTTPS 拉 `public_url/series_POE2.csv` 判断"当天是否已发布"。
但 2026-09-30 全站鉴权已换成 `auth-portal`(8895) 的 **Cookie 会话**，匿名请求只得到
**302 → `/__auth/login`**；原实现把"读不到"当"需要执行" ⇒ **每天傍晚白跑一次 90 天全量采集**
（09-16/09-17/09-18 执行记录里反复出现的"误判"）。

**已改为三级探测，本地文件最权威**：
① `/var/www/dashboard/series_POE2.csv`（已发布成品，最权威）→ ② `<HERE>/data/series/POE2.csv`
→ ③ 公网 HTTPS（仅前两者都不可用时兜底）。

### ⚠️ 环境坑（本机 systemd 219）

- **`StandardOutput=append:` 不生效** —— 那是 systemd **240+** 的特性，CentOS 7 是 **219**，
  会报 `Failed to parse output specifier, ignoring` 且日志全丢。用 `journalctl -u <unit>`。
- `p2pah_unified.py` 全量 9 目标约 **15s**，发布 22 文件约 **11s**，整链 ~27s。
  9 个目标 = MMOEXP 全站 / POE2 / D4 / NBA2K27 / NFL27 / MLB26 / CFB27 / FC27 / FC26。

### ⚠️ 办公 PC 上还有两个同款自动化（尚未停）

本机 `D:/共享资源/MMOEXP统一看板` 下仍绑着两个 WorkBuddy 自动化
（`dc947779…` 12:15 采集+scp 推送、`b6cc9842…` 18:15 兜底），
**未停会造成双写：本机 scp 会覆盖服务器刚采到的新数据**。需切到那个工作区手动停。

---

## 三、自动改价系统代码地图（`/opt/d4follow`）

这是本平台**最大、改动最频繁**的模块。2818 行的 `app.py` 是单体，改之前先看下表定位。

| 文件 | 行数 | 职责 | 改什么时看它 |
|---|---|---|---|
| `app.py` | 2868 | Flask 在线看板与操作台：23 个路由 + 任务系统 + 数据组装 + 配置读写 + 后台折扣 | 改接口 / 开关 / 页面数据 |
| `engine.py` | 1205 | **跟价引擎**：逐行评估该涨该降、闸门判定 | 改跟价策略 / 闸门 / 人工调价保护 |
| `build_dashboard.py` | 965 | 自包含看板 HTML 生成器（零外链，手写 SVG） | 改**离线**看板版式 |
| `store.py` | 730 | SQLite 存储层：IGGM 价 / 我方前端价 / 千岛成本 / 决策台账 | 改表结构 / 查询 |
| `core_qd.py` | 856 | 千岛采购成本抓取（DWC 折算） | 改千岛采集 |
| `core_p2pah.py` | 631 | `order.p2pah.cn` 后台客户端：登录 / 只读列表 / 改价写入 / 清缓存 | 改后台接口 / 写价 |
| `core_gold.py` | 743 | **金币跟价专线**（与物品分开的一条链路，**多游戏**：暗黑4 / AION2） | 改金币链路 |
| `core_front.py` | 592 | 我方前端价抓取（MMOEXP 自营站） | 改前台采集 |
| `core_iggm.py` | 382 | IGGM 竞品价抓取（D4 items + 多游戏） | 改竞品采集 / 新增游戏 |
| `tracker.py` | 349 | 跟价系统主流程编排 | 改轮询编排 |
| `srv_exec.py` | 344 | 服务器端执行器（宿主侧常驻） | 改服务器执行 |
| `templates/index.html` | 1755 | 控制台首页模板（**改完必须 `systemctl restart d4follow`**） | 改控制台 UI |
| `config.json` | ~1.0 MB | 商品映射 / 参数 / 折扣（**活的配置，程序会就地打补丁**） | 改配置（用脚本，别手改） |

**`app.py` 内部段落边界**（便于局部跳读，不必读全文）：
`1–57` 导入与常量 · `58–517` 后台折扣 · `518–777` 配置读写 · `778–887` 任务系统 ·
`888–1243` 数据组装 · `1244–1348` 改动记录 · `1349–2321` 任务实现 · `2322–2868` **路由（23 个）**

**金币专线（`core_gold.py`）多游戏要点**（2026-10-01 AION2 接入后）
- 抓取参数按游戏收敛在 `core_gold.GAME_PARAMS`，可用 `config.金币.游戏参数.<游戏>` 覆盖；
  取参数统一走 `game_param(cfg, game)`，服务区归属走 `server_game(cfg, sv)` / `game_names(cfg)`。
- **不要再读 `金币.挂载游戏` 单值**（那是单游戏时代的字段，现仅作兜底）。
- 每个服务区有 `游戏` 字段；`仅检测: true` = 照常采集与出报告，但 `app.task_gold_apply` 会跳过、不进工单。
- 展示倍率按游戏：暗黑4 `100000`（每 10 万 M）、AION2 `1`（每 M）。前端表头与单价换算都读
  `/api/gold` 每行下发的 `unit` / `unitLabel`，**禁止**再乘全局常量 `GOLD_UNIT`。

**AION2 三源（G2G/ELD/IGGM）可见化**（2026-10-01 验收通过）
- 基准口径：`基准 = min(G2G, ELD)`；IGGM 更低才取 IGGM；两站没数据的区用**同大区均价**兜底；
  目标每 M = 基准 × (1 − 让价%)。逻辑在 `core_multi.py`，只在 config 有 `金币.多源基准` 段时启用（**暗黑4 不启用**）。
- ⛔ **坑（已修）**：`rec["多源明细"]` 在内存/日志里一直有，但 `store.save_gold` 原来只写 24 列、
  `gold_price` 表也没有多源列 ⇒ **落库即丢**，页面看不到 G2G/ELD。
  现 `gold_price` 加 6 列 `src_g2g / src_eld / src_igmm / src_base / src_base_v / src_fallb`，`save_gold` 同步写。
  **以后给金币行加字段，必须同时改：建表 + `_MIGRATE` + `save_gold` 的 INSERT，三处齐改。**
- 前端 `renderGold` 的 `THEAD_COST` 用 `_hasMulti` 判断「该游戏有没有 src 数据」才加 G2G/ELD 两列
  ⇒ 暗黑4 表格逐字不变。单元格走 `msCell()`，基准源头那列加绿字「← 基准」。

**货架自检（`shelf_check.py`）· 核对按钮**（2026-10-01 修复）
- `shelf_check` 的 S1/S2/S3 比对 = **我方前端(mmoexp)价快照 vs config** ＋ **后台行名 vs key 装量**，
  即「前台名称/装量 ↔ 后台行 ↔ 映射」三方。数据源：`store.our_latest` + `_p2pah_srv/_read_*.json`。
- ⛔ **三个坑（已修）**：
  1. `#shelfPatchWrap` 原默认 `display:none`，且零漂移时 `renderShelfBar` 又把它关掉 ⇒ **按钮永远看不见**。
     现改为**常显**，零漂移显示绿色「✅ 货架与系统一致」条。
  2. `renderShelfBar` 内 `const esc=...` 与全局 `function esc`（第 630 行）同名 ⇒ **TDZ**，
     整函数抛 `Cannot access 'esc' before initialization`。**别再在函数内重声明 esc，直接用全局的。**
  3. 按钮 `fetch("/api/shelf_patch")` 绝对路径 → 404 HTML（应报 JSON）。页面内接口**一律相对路径**
     （`api('api/gold')` = `/d4/api/gold`），已改 `fetch("api/shelf_patch")`。
- ⚠ **教训**：`catch(e){...}` 静默兜底会把接口/语法 bug 完全藏住。**涉及页面渲染的改动必须过真实浏览器**
  （脚本 `D:\共享资源\服务器\G2G_ELD列与货架按钮_20261001\验证\check_aion2.py`），不能只看 curl 200。

**前台价抓取（`core_front.py`）· 精度护栏**（2026-10-01 修复）
- 口径：物品页展示价来自 `ITEM_CARD` 的 `data-price`；另有「精确价 = 标价 × 折扣」
  （`EXACT_PRICE_RE` 按 `data-id` 关联 `data-price` + `data-discount`），命中则**覆盖**展示价。
- ⛔ **坑（已修）**：MMOEXP 对 Corrupted Roots 这类商品的 `data-id` 会挂到**另一个 sku 的标价**上，
  导致精确价与同卡片展示价**差 10 倍**（2.83 → 0.283），且旧逻辑**无条件覆盖** ⇒ 引擎读到假亏本
  （`margin = (0.283 − 1.1895)/0.283 = −320%`），会**反向跟价**（误判亏损而停跟/抬价）。
- ✅ 现加**护栏**：精确价与展示价比值须落在 `0.5 ~ 2.0` 才采信；超出则**回退展示价**并打
  `[前端价护栏] ... 相差 N×，回退展示价` 日志。比值阈值 2.0 —— 拦 10 倍错位、不误伤 2 位小数舍入（≤1.3 倍）。
- ⚠ **识别真错 vs 舍入**：`probe_all_pages.py` 只比「展示价 vs 精确价」，会同时报出**舍入类**（差 1.0~1.3 倍，
  精确价反而更准、**不应改**）。判「真错」看**差 ≥2 倍**。终检用 `final_check.py`（跑真实 `scrape_page`、
  按 `_price_src` 分类：`exact` / `display(guard)` / `display`）。
- 改动文件：`core_front.py`；`_price_src` 字段会带 `"exact"`、`"display"`、`"display(guard)"` 三态，
  排查抓取问题时**先看这个字段**。

---

## 四、目录约定（`/opt/d4follow`）

| 目录 | 用途 | 可否动 |
|---|---|---|
| `_collect/` | ✅ **定时采集脚本 + 单元文件**，`d4follow-collect.timer` 依赖 | ⛔ 别动 |
| `_patch/`、`_patch_20260925/` | 历史补丁脚本（留档） | 只读 |
| `_p2pah_srv/` | P2PAH 会话相关（20M） | 谨慎 |
| `_qd_render/` | 千岛渲染容器相关 | 谨慎 |
| `_history/` | **历史备份/回滚产物归档区**（2026-09-29 整理，66 项） | 只读 |
| `data/` | SQLite 库 + 快照（122M） | 改前必须备份 |
| `logs/`、`output/`、`out_align/` | 运行日志与产物 | 可清理 |
| `venv/` | Python 3.9 虚拟环境（163M） | 别动 |
| `templates/` | 控制台模板 | 见上表 |

**规则：新产物放 `output/` 或 `_scratch/`（不存在就建），不要再往项目根目录堆。**

---

## 五、定时任务（全部 systemd timer，无 crontab）

| 定时器 | 周期 | 作用 |
|---|---|---|
| `d4follow-collect.timer` | 启动后 5min，此后每 1h | 跑一轮采集（IGGM + 我方前台 + 千岛），等价页面上点「采集一轮」 |
| `fc27-automation-tick.timer` | 每 1min | FC27 自动化心跳 |
| `fc27-player-collect.timer` | 启动后 5min，此后每 60min | FC27 玩家数据采集 |
| `fc27-storefront-monitor.timer` | 每 1min | FC27 店面监控 |
| `fc27-ops-collect.timer` | 每天 04:00 | FC27 运营数据采集 |
| `fc27-ip-certificate.timer` | 每 12h | FC27 IP 证书 |
| `dashboard-pipeline.timer` | 每天 **12:15** | P2PAH 统一看板采集+发布（9 目标，约 27s） |
| `dashboard-fallback.timer` | 每天 **18:15** | 同上兜底：当天已发布则跳过 |
| `g2g-token-refresh.timer` | 每 **3 分钟** | G2G accessToken 续签（服务器自持 · 纯 HTTP）：剩余 >480s 自动跳过，否则调 `user/refresh_access` 写 `var/token.json` |
| `g2gfollow-auto.timer` | 每 **15 分钟**（上一轮跑完 +15min） | G2G 金币货架全自动轮：采集 → 按变动阈值自动放行 → 真实写入（`tools/auto_cycle.py`）。关：`systemctl disable --now g2gfollow-auto.timer` |

---

## 六、已知问题 / 待办（本次体检发现）

| # | 问题 | 位置 | 影响 | 建议 |
|---|---|---|---|---|
| 1 | **死路由** `/dashboard/fc27-quote-api/` | nginx → `127.0.0.1:8877` | 该端口**无进程监听**，访问必 502 | 确认是否已废弃，是则删 location 块 |
| 2 | 僵尸单元 `steam-web.service` | `/etc/systemd/system/` | `is-enabled` = disabled 但 unit 文件还在；`/opt/steam_web` 41M | 确认弃用则归档 unit + 目录 |
| 3 | `/opt` 历史残留 | `_d4test13`(35M)、`iggm-web.snapshot-20260905`(23M)、`fc27-chrome-desktop`、`_patch_d4items_20260926`、`IGGM抓取工具_Web版部署_2026-09-04 (2).zip` | 目录脏 | 归档到 `/opt/_archived_20260929/`（mv，不删） |
| 4 | `/d4/` 与 `/dashboard/` 等 6 页已统一亮色主题，但**源码真源有两份** | 线上 `/opt/d4follow/templates` vs 本地 `D:\共享资源\` | 不一致时**必须以线上为准改** | 每次改完同步本地镜像 |
| 5 | **旧机 `47.253.252.55` 已停用**（2026-09-29 15:04 全停业务） | 旧机 | ✅ 2026-09-29 已处理：①活配置（`server.json` / `deploy_hub.json` / `deploy_client.py`）全部切到新机；②旧机页面曾注入「已迁移」横幅；③本地文档/技能加「机器身份」警示块；④**业务服务全停 + 禁用开机自启**（`d4follow`/`deploy-hub`/`iggm-web`/`mlb-online`/`fc27-gate`/`fc27-activity-api`/`nginx`），端口仅剩 ssh(22)+dns(53)，外网不可达。**⚠️ 根因：两台共用同一把 `No1.pem`、目录结构完全相同 —— 命令里 IP 写错即改错机器** | 旧机已停用；若要彻底省成本需在**阿里云控制台释放实例**（停用本身不省钱）。恢复：`systemctl enable --now <svc>` |
| 6 | **`/d4/` 首屏 4~5 秒**（根因：gzip 全程关闭 + 首屏三接口串行 + 无 TLS 会话复用；**后端本身只花 120ms**） | `nginx.conf`（http 块）、`conf.d/iggm-web.conf`（`/d4/` 与 `/__hub/`）、`templates/index.html`（`loadState`） | ✅ 2026-09-29 已修复：①http 块开 gzip（含 `gzip_proxied any`，否则反代响应不压缩）；②删掉 `/d4/` location 里**误伤**的 `gzip off;`（本意护 SSE，但 `text/event-stream` 不在 `gzip_types` 内、本就不会被压）；③`hubnav.js`（`sub_filter` 注入全站）加 `max-age=600`；④首屏 `/api/state`+`/api/gold`+`/api/local/jobs` 并行发起；⑤TLS 会话复用。**效果：首屏载荷 447KB→85KB，冷启动 4.94s→3.20s、切页 1.92s→1.45s，渲染逐字节等价、JS 零报错** | 产物/诊断脚本/回滚步骤：`D:\共享资源\服务器\改价系统性能优化_20260929\说明.md`。⛔ **别把 `gzip off;` 加回 `/d4/` location**。仍可做（未做）：开 HTTP/2（需先验证 SSE 日志不被缓冲）、后端三接口合并、`/api/state` 瘦身（单次 247KB）、`renderLocal` 轮询 5s→10~15s |
| 7 | **自助部署通道全程发不出新站点**（`POST /deploy/api/deploy` 一律 500：`OperationalError('near "ON": syntax error')`） | `/opt/deploy-hub/deploy_server.py` `publish()` 里的 `INSERT ... ON CONFLICT(owner,name) DO UPDATE` | ✅ 2026-09-30 已修复。根因：该 UPSERT 语法需 **SQLite ≥ 3.24**（2018-06），而**本机 sqlite3.sqlite_version = 3.7.17**（CentOS 7 自带 libsqlite3；`/usr/bin/python3` 和 `/opt/python39/bin/python3` 都链到它）。改为「先 `UPDATE`，`rowcount==0` 再 `INSERT`」的等价写法。**最后一次成功发布是 09-23 10:56**，之后一周每次发布都失败 | ⛔ **别在 `/opt/deploy-hub` 里用 `ON CONFLICT` / UPSERT / `RETURNING` 等新语法**，这台机器的 sqlite 是 2015 年的。要升级得换带新 libsqlite3 的解释器（`sqlite3.sqlite_version` 才是准的）。产物与验收：`D:\共享资源\服务器\deploy通道修复_20260930\说明.md` |
| 8 | **自助部署通道的接入包在鉴权切换后失效** | `deploy_client.py`（`Authorization: Basic`）+ `/deploy/` 落地页文案 | ✅ 2026-09-30 已修复：客户端改为「先 `POST /__auth/login` 换 `MMOEXP_AUTH` Cookie，再带 Cookie 调 `/deploy/api/*`，会话过期自动重登并重试一次」；默认地址同步改成 `https://`（Cookie 带 `Secure`，且账号密码不该走明文）；落地页的 `curl -u …` 与「会弹输入框」文案也改掉了 | 同事手里的**旧客户端必须重新下载**：`curl -o deploy_client.py https://47.85.224.112/deploy/api/client.py`（这个地址免登录）。账号口令不变 |
| 9 | **u4gm 竞品价在服务器抓不到**（Cloudflare 挑战页 403，服务器 IP 被风控；同一 URL 在办公网正常返回 200） | `/opt/nba-reprice/backend/server.js` 的 `fetchU4gm()` | 竞品对比缺 u4gm 一列，推荐价按 iggm/u7buy 最低价计算 | 需浏览器（Playwright）或代理出口；服务器目前**没有**浏览器二进制。iggm 已于 2026-09-30 修复（先 GET 商品页建会话 Cookie，再带 sort/goods_name/tag/page 调 goods_ajax） |

---

## 七、本地镜像与备份约定

- 本地真源目录：`D:\共享资源\服务器\`
- 每次改动产出：`D:\共享资源\服务器\<主题>_<日期>\`（含 `改前源/` `改后源/` `验证/` `说明.md`）
- 改动记录追加到：`D:\共享资源\服务器\服务器项目清单_<日期>.md`
  （**注意：该文件已 44 KB / 497 行，属流水账。新记录请写进本文件第六节级别的「当前状态」表，不要再无限追加**）

---

## 二十、全站访问来源 IP 白名单（2026-10-15 新增 · 2026-10-16 收紧启用 · 全站前置）

> **改任何 nginx 配置前先读这一节。** 这是全站最外层的访问控制。

> **✅ 当前状态（2026-10-16 起）：拦截已启用** —— 总开关 `"0:0" 1;`。
> 总开关在 `/etc/nginx/conf.d/fs-ip-allowlist.conf` 末尾的
> `map "$fs_ip_allowed:$fs_is_acme" $fs_ip_block` —— `"0:0" 1;` = 拦截开启（**当前值**），
> `"0:0" 0;` = 全量放行（应急用）。
> 历史：2026-10-15 18:35 ~ 2026-10-16 16:35 曾临时全量放行。

> **放行口径（2026-10-16 定）：只放「本公司机器」+「本公司脚本工具」两类。**
> - **A. 公司机器出口**（`/32` 精确）：`45.58.38.172`（主力·人+脚本共用）、
>   `90.96.180.210`（吴律自动化工具·经 Cloudflare）、`45.95.212.151`（DY 代理）、
>   `223.244.89.51`、`114.88.116.122`（家宽）。
> - **B. 脚本工具出口**（**放整段以覆盖 IP 漂移**）：`43.228.212.0/24`（Atlantic.Net AS6364）、
>   `173.249.200.0/23` + `173.249.209.0/24`（tzulo AS11878）、`152.175.0.0/16`（ISIF OU AS209554）。
>   ⚠️ 脚本 IP 会在这些 IDC 段内漂移；**若被挡，看钉钉告警 / 拒绝页显示的 IP，按其所在 `/24` 追加一行**。
> - **C. 基础设施**：`127.0.0.0/8`、`172.16.0.0/12`、`10.0.0.0/8`、`192.168.0.0/16`、`47.85.224.112/32`。
> - **D. 钉钉 Bot**：`59.82.0.0/16`（**已修复**：原 `59.82.21.0/24` 只覆盖发消息出口，
>   而钉钉抓链接预览实际来自 `59.82.83.x`，曾导致群里贴链接无预览）。

> **白名单是 server 级拦截，会一并覆盖所有 location**（含未单独挂 `auth_request` 的兜底
> `location /` → 8787、`/deploy/api/client.py`、`/dashboard/api/`）。
> 实测：非白名单来源访问上述路径**一律 403**（此前它们分别返回 200/200/401，属可绕过旁路）。

> **两个必须保留的例外**（删掉会出事故）：
> ① `/.well-known/acme-challenge/` 对**所有来源**开放（Let's Encrypt shortlived 约 6 天，
>    挡掉会在数天内导致全站 HTTPS 中断）；
> ② 拦截用**专用码 418**，**别**改成 `error_page 403`（本站多处 location 因门户鉴权正常返回 403，
>    改了会把「无权限」误显示成「IP 受限」）。

| 项 | 位置 |
|---|---|
| 白名单定义（http 级 `geo` + `map`） | `/etc/nginx/conf.d/fs-ip-allowlist.conf` |
| 拦截与拒绝页（server 级） | `/etc/nginx/fs-ip-allowlist.locations.conf` |
| 挂载方式 | `iggm-web.conf` server 块内 `# >>> fs-ip-allowlist-20261015 >>>` 标记块 include |
| 拦截告警 | `/opt/auth-portal/fs_ip_alert.py` + `fs-ip-alert.service/.timer`（每 2 分钟扫日志，推**群「服务器及Github报警」**，凭据 /etc/fc-ops-readonly-monitor/hooks-bot.json） |
| 被拒日志 | `/var/log/nginx/ip-denied.log` |
| 仓库归档 | `opt/auth-portal/fs-ip-allowlist*.conf`、`README-ip-allowlist.md` |
| 回滚点（本次收紧前） | `/etc/nginx/conf.d/fs-ip-allowlist.conf.bak-20261016-before-reenable` |
| 回滚点（整块移除） | `/etc/nginx/conf.d/iggm-web.conf.bak-20261015-ipallowlist` |

**加白名单**：编辑 `fs-ip-allowlist.conf` 的「公司自有出口」区加一行 `IP/32  1;`，
然后 `nginx -t && systemctl reload nginx`。被拦的人会看到一个**回显自己公网 IP** 的页面，
把该 IP 发过来即可加白。

**两个必须保留的例外**：

1. `/.well-known/acme-challenge/` **对所有来源开放** —— 证书是 Let's Encrypt
   **shortlived（约 6 天有效期）**，由 `fc27-ip-certificate.timer` 每 12 小时用 webroot 续期，
   验证来源 IP 不固定；挡掉它会导致证书数天内过期、**全站 HTTPS 中断**。
2. 拦截用**专用状态码 418** 转 `@fs_ip_denied`，**不要**改成 `error_page 403` ——
   本 server 内有多个 location 会因统一登录门户的鉴权返回 403，
   直接改会把「无权限」误显示成「IP 受限」。

**回滚**：删掉 `iggm-web.conf` 里的标记块 + 两个 conf 文件 →
`nginx -t && systemctl reload nginx`。
