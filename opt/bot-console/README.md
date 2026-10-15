# Discord 机器人控制台

服务器 `47.85.224.112`（play187）上的可视化控制台，用来管两个 Discord 机器人。

**入口：** https://47.85.224.112/bots/ （走全站统一登录门户；只有登录后可见）

---

## 一、它管哪两个机器人

| Key | 名称 | 服务单元 | 目录 | 运行时 | 干什么 |
|---|---|---|---|---|---|
| `guard` | **MMOEXP GuardBot** | `mmoexp-guardbot` | `/opt/mmoexp-guardbot` | Node.js 18 | 防冒充守卫：名字前缀命中即处置 |
| `shugo` | **Shugo-bot** | `shugo-bot` | `/opt/shugo-bot` | Python 3.9 | AION2 迎新面板 + 官方资讯推送 |

两个机器人互相独立，各用各的 Token、各进各的服务器。控制台只是"遥控器"，
不改变它们自身的运行方式。

---

## 二、能做什么

### 共通
- **状态**：运行中/已停止、开机自启、运行时长、内存、PID
- **操作**：启动 / 停止 / 重启 / 查看日志（实时读 journalctl）
- **凭据**：替换 Bot Token（Token 永不回显，只能整体替换）
- **风险体检**：自动读出应用开关状态（Code Grant / Server Members Intent）与
  机器人角色层级，把"会导致防护失效"的配置直接标红
  > 连接状态以**机器人自己的运行日志**为准（服务日志里的证据），
  > **不**依据应用 flags 的位判断 privileged intent —— 那个位的语义容易搞反。
  > 分析时只取「本次运行」窗口（以最后一条 systemd ` Started ` 为界），
  > 避免旧会话的失败日志把当前健康的服务误报成故障。

### 守卫机器人（GuardBot）
- 处置规则：处罚动作（踢出/封禁/禁言/只记录）、禁言时长、**演练模式开关**
- 识别规则：匹配模式（严格/宽松）、品牌词正则、额外前缀字面量
- 白名单：**角色多选**（推荐）或用户 ID
- **名称测试器**：粘贴一批名字，用服务器上验证过的同一套判定逻辑即时跑结果

### 迎新机器人（Shugo-bot）
- 频道：迎新面板频道、资讯推送频道（下拉选择，不用手填 ID）
- 资讯：抓取板块（公告/补丁/官方影像）、轮询间隔、首次回溯条数
- 角色按钮：阵营与职业的按钮名称、图标、对应角色
- 排版：每行按钮数、目标行宽、各类按钮颜色、等宽开关
- 文案：卡片标题/正文/页脚、私信标题/正文

---

## 三、安全模型

```
浏览器 ──https──> nginx(443)
                    │
                    ├─ auth_request /__auth_verify ──> auth-portal 127.0.0.1:8895
                    │        （未登录 302 回登录页；写操作还要 X-Auth-Role=admin）
                    │
                    └─ proxy_pass ──> 127.0.0.1:8936  (本服务，仅监听回环)
```

- 后端**只监听 `127.0.0.1`**，公网不可达，必须经 nginx。
- 身份唯一来源是 nginx 注入的 `X-Auth-User` / `X-Auth-Role`，客户端自带的同名字头会被覆盖，无法伪造。
- 读操作：任意已登录用户；**写操作（改配置、启停服务）：要求 admin**。
- POST 额外校验 Origin 同源 + `X-Requested-With` 头（防 CSRF）。
- **Token 永不回传浏览器**，接口只返回 `hasToken` 布尔值。
  项目文件里也没有硬编码任何凭据。
- 每次改配置都先备份到 `data/backups/`，改动明细写入 `data/audit.log`。

---

## 四、文件与路径

| 路径 | 说明 |
|---|---|
| `/opt/bot-console/server.py` | 后端（纯 Python 标准库，单文件） |
| `/opt/bot-console/static/index.html` | 前端（单文件，零外部依赖，暗色主题） |
| `/opt/bot-console/venv/` | 运行用虚拟环境 |
| `/opt/bot-console/data/backups/` | 配置自动备份 |
| `/opt/bot-console/data/audit.log` | 操作审计 |
| `/opt/bot-console/_test_classify.py` | 判定逻辑自检（36 用例） |
| `/opt/bot-console/_smoke_test.py` | HTTP 层冒烟测试（44 项） |
| `/opt/bot-console/_e2e_browser.py` | 真实浏览器端到端（26 项，需 playwright） |
| `/opt/bot-console/_e2e_nav_control.py` | 与既有页面对照，分辨失败请求是否本次引入 |
| `/etc/systemd/system/bot-console.service` | 服务单元 |
| `/etc/nginx/bot-console.locations.conf` | nginx 片段 |

---

## 五、⚠️ 一个必须注意的坑：解释器要选对

**`/usr/bin/python3` 的构建漏了 `_ssl` 模块**，urllib 发不出 HTTPS，
所有 Discord 角色/频道查询都会报 `unknown url type: https`。

所以服务单元里写的是：

```
ExecStart=/opt/bot-console/venv/bin/python -B /opt/bot-console/server.py
```

`venv` 的基座是完整的 `/opt/python39`。**别把这一行改回 `/usr/bin/python3`。**

代码里另有一条 `curl --config -` 兜底路径（Token 走 stdin，不进 argv），
属于第二道保险 —— 即使解释器换错，控制台也不会整块失灵。

---

## 六、常用运维命令

```bash
# 状态 / 启停
systemctl status bot-console
systemctl restart bot-console
journalctl -u bot-console -n 50 --no-pager

# 健康检查（本机）
curl -s http://127.0.0.1:8936/healthz

# 自检（改代码后跑一遍）
/opt/bot-console/venv/bin/python /opt/bot-console/_test_classify.py
/opt/bot-console/venv/bin/python /opt/bot-console/_smoke_test.py

# 真实浏览器 E2E（需 playwright，建议在本地机器跑，指向服务器）
#   第 1 步：签发一个短时效会话令牌
cd /opt/auth-portal && set -a && . ./config.env && set +a
TOK=$(/opt/python39/bin/python3 -c "import sys;sys.path.insert(0,'/opt/auth-portal');import auth_portal as ap;print(ap.make_token('chenchao',['dashboard','deploy'],900))")
#   第 2 步：本地用 playwright 解释器跑
#   python _e2e_browser.py "$TOK"

# nginx
nginx -t && systemctl reload nginx
```

### 回滚

```bash
# nginx 配置回滚（2026-10-14 备份）
cp /root/_bak_botconsole_20261014/iggm-web.conf.before /etc/nginx/conf.d/iggm-web.conf
nginx -t && systemctl reload nginx

# 导航注册表回滚
cp /root/_bak_botconsole_20261014/navigation.json.before /var/www/dashboard/fs-home/navigation.json

# 停用控制台（不影响两个机器人本体）
systemctl disable --now bot-console
```

### 恢复某个机器人的历史配置

```bash
ls -t /opt/bot-console/data/backups/ | head          # 看最近的备份
cp /opt/bot-console/data/backups/guard-config-<时间戳>.json /opt/mmoexp-guardbot/config.json
systemctl restart mmoexp-guardbot
```

---

## 七、开发约定

- 后端只用标准库，**不引入第三方依赖**（与 `/opt/mmoexp-taskboard`、`/opt/auth-portal` 一致）。
- 前端单文件、零外部资源（办公网封 CDN，页面必须自包含）。
- 改完先跑 `_test_classify.py` + `_smoke_test.py` 再部署。
- 前端所有请求必须走 `apiUrl()`（它会把 `/bots` 前缀拼上）。
  直接写 `fetch('/api/...')` 会落到站点兜底服务上、返回 404。
- 部署后核对 md5：`md5sum /opt/bot-console/server.py` 应与本地一致。
