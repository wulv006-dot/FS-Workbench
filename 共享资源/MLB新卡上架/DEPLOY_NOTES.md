# MLB 新卡上架工具 · 部署与交接说明

**上线时间**：2026-09-23
**线上地址**：http://47.85.224.112/mlb/
**账号**：wulv / （请向管理员单独获取）（与看板同一套 Basic Auth）

---

## 一、这套东西是怎么分工的

```
你的电脑（住宅 IP）                      服务器 47.85.224.112（阿里云机房 IP）
┌──────────────────────┐              ┌──────────────────────────────┐
│ 执行器 mlb_agent.py  │──心跳/领活──▶│ mlb-online 服务 (127.0.0.1:8897)│
│  · Playwright 起 Chrome│◀──任务下发──│  · 任务队列 (sqlite)           │
│  · 访问 showdd 抓卡价  │              │  · 静态网页 hosting            │
│  · 写 Excel           │──回传结果──▶│  · 产物落盘 /files/            │
└──────────────────────┘              └──────────────────────────────┘
         ↑                                          ↑
    必须在这边抓                          nginx 反代 /mlb/ + Basic Auth
   （能过 Cloudflare）                     （只托管，不抓取）
```

**为什么必须拆开**：服务器出口 IP 是阿里云机房段，访问 showdd.io 会命中 Cloudflare 的
JS 挑战页（`chl_page`）。实测**请求头完全一致**，本机住宅 IP 返回 HTTP 200 + 432KB 完整页面，
服务器返回挑战页。唯一变量是出口 IP —— 所以采集留在本机，服务器只管排队和托管。

---

## 二、服务器端部署（已做完，重装时看这里）

包结构：

```
MLB新卡上架/
├── server/
│   ├── mlb_server.py        服务本体（零依赖，stdlib http.server + sqlite3）
│   ├── server_config.json   汇率上限 / 价格下限 / 采样间隔等
│   └── data/mlb.db          队列数据库（运行时生成）
├── client/
│   ├── mlb_agent.py         本机执行器
│   ├── requirements.txt     playwright + openpyxl
│   ├── README.md            给使用者的说明（会打进 agent.zip）
│   └── 启动执行器.bat        Windows 一键启动
├── web/
│   ├── index.html           工作台网页
│   └── files/agent.zip      执行器压缩包（网页上下载的就是它）
└── deploy/
    └── install_mlb.sh       幂等安装脚本
```

部署步骤：

```bash
# 1. 上传整个包到服务器
scp -i <key> -r server deploy web root@47.85.224.112:/tmp/mlb_deploy/

# 2. 跑安装脚本（幂等，可反复跑）
ssh -i <key> root@47.85.224.112 'bash /tmp/mlb_deploy/deploy/install_mlb.sh'
```

脚本会做五件事：
1. 装到 `/opt/mlb-online`，静态根 `/var/www/mlb-online`
2. 写 `mlb-online.service`（`MemoryMax=180M`，只监听回环）并启动
3. 检查本机 `/api/health`
4. 在 `iggm-web.conf` 里插入带标记的 nginx 段（`# >>> mlb-online (auto) >>>`）
5. `nginx -t` 校验，失败自动回滚

> ⚠️ `nginx -t` 的判据是**退出码**。输出里出现 "syntax is ok" 不代表包含进来的 server 块没问题，
> 只看文字会误判（踩过一次）。

常用运维命令：

```bash
systemctl status mlb-online
journalctl -u mlb-online -n 50 --no-pager
systemctl restart mlb-online
ls -la /opt/mlb-online/files/          # 任务产物
```

---

## 三、本机执行器（同事要跑的就是这个）

1. 打开 http://47.85.224.112/mlb/ ，展开「没装执行器？」小节，下载 `agent.zip`
2. 解压到任意目录，双击 `启动执行器.bat`
   （或手动：`pip install -r requirements.txt` → `python -m playwright install chromium` →
   `python mlb_agent.py --server http://47.85.224.112 --user wulv --agent 我的电脑 --show`）
3. 首次会弹出浏览器窗口，**手动点一下 Cloudflare 验证**
4. 窗口别关，回去刷网页就能看到执行器在线、任务被领走

> **`--show` 不能去掉**：无头模式会被 Cloudflare 直接拦下。
> 验证通过一次后登录态存进工作目录的 `browser_profile/`，之后复用。
> 也可以双击 bat 让它常驻。

---

## 四、网页端怎么用

1. 上传 Excel 模板（可选，传了执行器就不用另外配 `--template`）
2. 填当期金币售价（USD / 100K Stub），提交任务
3. 页面上看：执行器在线状态、当前任务进度（第几轮采样 / 中位数 / 算出的价）
4. 跑完在「历史」里下载成品 Excel

**定价公式**：

```
售价 = (3 次采样中位数 / 100000) × 汇率 × 1.1     四舍五入到分
```

- 采样间隔默认 120 秒，**不要调小**（价差靠间隔拉开）
- 低于 $0.50 的卡自动过滤
- 口径：成本取 showdd 的 `Sell`（官方 Buy Now），**不要用 `Buy`**（Sell Now）

---

## 五、接口速查

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/mlb/api/health` | 健康检查 |
| GET | `/mlb/api/tasks` | 任务列表 |
| GET | `/mlb/api/tasks/<id>` | 任务详情（含 payload/progress/result） |
| GET | `/mlb/api/agents` | 执行器在线状态（150 秒无心跳算离线） |
| GET | `/mlb/api/stats` | 统计 |
| GET | `/mlb/files/<name>` | 下载任务产物 / agent.zip |
| POST | `/mlb/api/tasks` | 提交任务 |
| POST | `/mlb/api/heartbeat` | 执行器心跳 |
| POST | `/mlb/api/claim` | 领取任务（原子，不会重复领） |
| POST | `/mlb/api/tasks/<id>/progress` | 上报进度 |
| POST | `/mlb/api/tasks/<id>/result` | 回传结果（含 Excel base64） |
| POST | `/mlb/api/tasks/requeue` | 重排队 |
| POST | `/mlb/api/tasks/delete` | 删除任务 |

所有接口都要 Basic Auth。nginx 会把登录用户名注入 `X-Remote-User`，决定任务算谁的。

---

## 六、已知约束

| 约束 | 说明 |
|---|---|
| 采集只能在本机 | 服务器 IP 过不了 Cloudflare，非配置问题 |
| 必须带 `--show` | headless 会被拦；首次需人工点验证 |
| 任务产物存在服务器 | 在 `/opt/mlb-online/files/`，下载后可从服务器删掉省空间 |
| 内存限制 180M | `mlb-online.service` 的 `MemoryMax`，够用但别再加负载 |
| 无 HTTPS | 服务器还没有域名，目前 HTTP 明文（含 Basic Auth 凭据） |
| 单文件上限 40MB | `MAX_UPLOAD`，正常 Excel 远不到这个量级 |
| 所有路径都在 Basic Auth 之后 | 含 `/mlb/files/`。自动化脚本用 `urllib` / `curl` 取文件时**必须带凭据**，否则恒 401（浏览器里因为已登录所以看不出问题） |

---

## 七、踩过的坑（别重犯）

1. **`_send()` 会重复写 Content-Type** —— 调用方指定的 MIME 被静默忽略，
   已改为 `extra_headers` 可覆盖默认头。
2. **`file_url` 含中文未编码** —— 直接塞进 `<a href>` 会让 urllib 在请求行抛
   `UnicodeEncodeError`。已改为生成时就 `quote()`，GET 侧 `unquote()`。
3. **服务器构建 payload 时只挑固定字段** —— `template_b64` 被丢弃，导致网页上传的模板
   到不了执行器。已补上透传。
4. **`--server` 不带 `/mlb` 前缀会 404** —— 已自动补前缀。
5. **不要用线程看门狗包装 Playwright sync API** —— 会抛
   `greenlet.error: cannot switch to a different thread`。
   正确做法是 `page.set_default_timeout()` + 在 `_navigate` 里吞掉单次探测失败。

---

## 八、2026-10-05 故障修复（执行器始终显示离线）

一次「执行器检测不到」的报障，挖出**三个独立故障**，任一都会导致该现象。
详见同目录 `故障修复报告_20261005.md`。

### 8.1 服务器 SQLite 3.7.17 不支持 UPSERT（致命）

`mlb_server.py` 的 `/api/heartbeat` 原本写：

```sql
INSERT INTO agents(...) VALUES(...)
ON CONFLICT(name) DO UPDATE SET ip=excluded.ip, ...
```

`ON CONFLICT ... DO UPDATE` 需要 **SQLite >= 3.24.0（2018）**，而
**CentOS 7 自带 3.7.17**，直接抛：

```
sqlite3.OperationalError: near "ON": syntax error
```

→ 心跳接口每次 500 / `Empty reply from server` → `agents` 表恒空 → 前端永远离线。

**本地测不出来的原因**：开发机 SQLite 3.53 支持 UPSERT。
**教训：涉及 DB 语法/版本特性，必须在服务器上验一遍。**

**修法**：改为 `SELECT 1` 判存在 → `UPDATE` / `INSERT` 两步，
任何 SQLite 版本都能跑。

排查命令：

```bash
/opt/python39/bin/python3 -c "import sqlite3;print(sqlite3.sqlite_version)"
```

**禁止在服务器代码里使用**：UPSERT(`ON CONFLICT`) / `RETURNING` /
`json_extract` / 窗口函数 / `STRICT` 表。

### 8.2 门户已切换为 Cookie 会话，Basic Auth 作废

**2026-09-30 全站把 nginx `auth_basic` 换成 `auth_request` + 签名 Cookie**
（门户 `auth-portal.service`，127.0.0.1:8895，Cookie 名 `MMOEXP_AUTH`）。
MLB 执行器作为**非浏览器客户端被漏改**，仍在发 `Authorization: Basic`。

后果具象化：**未登录返回 302 → `/__auth/login?next=...`，不是 401**。
旧代码自动跟随 302 拿到 HTML，再 JSON 解析失败，报出
`Expecting value: line 1 column 1` —— 与真实原因（没登录）毫无关系。

**修法**：执行器改为

1. `POST /__auth/login`（form: `username`/`password`/`remember`/`next`）换 Cookie
2. 后续请求带 `Cookie: MMOEXP_AUTH=...`
3. **禁止 urllib 自动跟随 302**，把 302 显式判定为「认证没通过」
4. 会话过期自动重登一次（不死循环）

**写非浏览器客户端的正确姿势**（通用）：
登录失败也是 302（`?err=bad`/`err=locked`/`err=noperm`），
必须看 `Location` 才知道成败。`AUTH_MAX_FAILS=6`，别拿真账号试错。

### 8.3 `启动执行器.bat` 是 LF 换行，cmd.exe 解析不了

源文件 **0 CRLF / 39 裸 LF，UTF-8 无 BOM**。
纯 LF 的 .bat 在 cmd.exe 下会标签偏移、if 块提前闭合、
甚至**整段静默不执行** —— 正是「双击没反应、也没窗口」的直接原因。

**修法**：新增 `_normalize_bat.py` 统一转为 **CRLF + UTF-8 BOM**；
`_make_agent_zip.py` 入包前强制规范化，并在包内自检（裸 LF != 0 即中止）。

### 8.4 附带修复

| 问题 | 修法 |
|---|---|
| 缺密码走 `getpass`，双击场景静默失败 | 环境变量 → `.mlb_pass` 文件 → 交互输入；拿不到就明确报错退出 |
| 只认 `where python` | `py -3` → `python` → 扫 `%LOCALAPPDATA%\Programs\Python\Python3*` |
| 报错不可读（302/JSON 解析失败） | 401/403/404/5xx/302/非 JSON 各有说人话的提示 |
| bat 依赖 Python 隐藏输入密码 | bat 用 `set /p` 先取密码，再 `--password` 传入 |

### 8.5 本次线上变更

| 文件 | 备份 | sha256 |
|---|---|---|
| `/opt/mlb-online/mlb_server.py` | `.bak-20261005` | `d693cd2a...f8dd7` |
| `/var/www/mlb-online/files/agent.zip` | `.bak-20261005` | `bb32b870...d709` |

回滚：

```bash
cp /opt/mlb-online/mlb_server.py.bak-20261005 /opt/mlb-online/mlb_server.py
systemctl restart mlb-online
cp /var/www/mlb-online/files/agent.zip.bak-20261005 /var/www/mlb-online/files/agent.zip
```
---

## 九、2026-10-05 第二轮：bat 编码事故（同日用户实测后）

### 9.1 现象

用户双击 bat 后满屏乱码与命令回显：

```
C:\Users\Administrator\Desktop\脚本\mlb_agent>if not "%MLB_AGENT_PASSWORD!" == "" (
◆◆存到本目录的 .mlb_pass 文件里。
'etpass' is not recognized as an internal or external command,
```

### 9.2 根因：第一轮修复引入的回归

第一轮为「让 cmd 正确显示中文」给 bat 加了 **UTF-8 BOM + `chcp 65001`**，恰恰是错误做法。

**关键认知：cmd.exe 读 `.bat` 用的是控制台代码页（本机 936/GBK），不是 UTF-8。**

| 问题 | 机理 | 表现 |
|---|---|---|
| UTF-8 BOM | 首行 `@echo off` → `锘絖echo off`，cmd 找不到这条命令 | `echo off` 从未生效 → 每行命令带 `C:\...>` 回显 |
| `chcp 65001` | cmd 按字节读文件，中途换代码页 → 偏移与解码错位 | 文本被拦腰截断 → `setpass` / `'etpass' is not recognized` |
| bat 含中文 | 按 GBK 解析 UTF-8 字节 | `◆◆` 满屏 |

### 9.3 修法：bat 纯 ASCII 化

1. bat 全部改纯 7-bit ASCII，中文提示移交 `mlb_agent.py`
2. 删掉 `_normalize_bat.py` 的 BOM 逻辑（元凶）
3. bat 不再出现 `chcp`；代码页交给 Python 侧 `_setup_console()`
4. `mlb_agent.py` 新增 `_setup_console()`：`reconfigure(encoding='utf-8', errors='replace')`
   + 真实控制台下 `SetConsoleOutputCP(65001)`
5. `_normalize_bat.py` 改为**强校验闸门**：非 ASCII / 裸 LF / chcp / BOM 任一命中即
   `SystemExit` 拒绝出包
6. `_make_agent_zip.py` **取消 `try/except` 吞异常** —— 原来会把坏字节照打进包，
   这正是事故直接成因；改为出包后逐条复验三条硬约束

### 9.4 连带修掉的三个问题

| 问题 | 修法 |
|---|---|
| `goto` 在 `if (...)` 块内不可靠（报「系统找不到文件 .」） | 改用标志位变量 `PASS_SRC` 控制流 |
| **记事本自动加扩展名**：用户存 `.mlb_pass` 落盘成 `.mlb_pass.txt`，程序读不到 | `_password_file_candidates()` 展开 4 个变体；bat 同步识别；启动打印 `Password source:` |
| `"py -3"` 整体加引号 → cmd 去找名为 `"py -3"` 的文件 → 退出码 9009 | 改用 `python -c "import sys; print(sys.executable)"` 取全路径 |

### 9.5 验证（全部实跑，非静态检查）

| 项 | 结果 |
|---|---|
| bat 字节合规（纯 ASCII / CRLF / 无 BOM / 无 chcp） | ✅ 0 / 154 / False / False |
| 沙箱实跑 bat（`cmd /c`） | ✅ 无回显刷屏，中文正常 |
| 密码 6 场景（两种文件名 / 环境变量 / 交互 / 空文件 / 全空） | ✅ 全通过 |
| zip 解包到干净目录实跑 | ✅ 跑到认证步骤 |
| 线上 unzip 复验 + `py_compile` | ✅ 三项合格，语法 OK |
| 本地/线上 sha256 | ✅ `a7511edc...9198` |

### 9.6 线上变更

| 文件 | 备份 | sha256 |
|---|---|---|
| `/var/www/mlb-online/files/agent.zip` | `.bak-20261005b`（第一轮，即乱码版）、`.bak-20261005`（首版） | `a7511edc...9198` |

回滚（**注意：不要回退到 `.bak-20261005b`**，那正是乱码版）：

```bash
cp /var/www/mlb-online/files/agent.zip.bak-20261005b /var/www/mlb-online/files/agent.zip
```

### 9.7 `.bat` 编码铁律（务必照做）

1. 换行 **CRLF**
2. **绝不带 BOM**
3. **绝不出现非 ASCII 字符**
4. **绝不用 `chcp`**
5. **绝不在 `if (...)` 块内 `goto`** → 用标志位变量
6. 中文输出交给 Python，Python 侧自己 `reconfigure` + `SetConsoleOutputCP`

> 校验工具：`_normalize_bat.py`（不合规即拒绝）+ `_make_agent_zip.py`（出包后复验）。
> 改完 bat 一定要跑这两个，别手工目测。

### 9.8 传输注意（本次踩到）

`Invoke-Server187.ps1 -Action Upload` 对含中文/空格的本地路径会失败（ssh 退出码 255，
`Check` 却正常，说明是 scp 路径解析问题）。绕行方案：**base64 分块传输**
（4000 字符/块 → 远端 `printf '%s' >>` 追加 → `base64 -d`），传输后必须核对
sha256 与本地一致，再 `install -m 644` 覆盖并复验包内容。
