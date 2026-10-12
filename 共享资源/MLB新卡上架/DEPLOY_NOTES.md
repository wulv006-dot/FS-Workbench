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

---

## 十、2026-10-12：打通「采集 → 上架」全链路（自动直写后台）

### 10.1 之前断在哪

```
执行器采集 → 三轮比价 → 写 Excel → 回传 ─┐
                                        └─→ ✂️ 人工：下载 Excel → 浏览器手动导入后台
```

`mlb_admin_import_20261012/` 那套直写脚本（逆向出的 `add`/`edit`/`shelves` 通道）
已经能把「执行器回传的 `cards[]`」直接写成后台的模型 + 主图 + 48 个产品，
但它只是个**命令行**，得人工把它跟采集接起来。

### 10.2 现在长这样

```
执行器采集 → 写 Excel → 回传 ─→ hub(/result)
                                  │ 闸门判定通过
                                  ▼
                        mlb_writeback.py（后台线程）
                                  │ 子进程 + 超时 kill
                                  ▼
            /opt/mlb-admin-write/src/mlb_write_cards.py
             ⓿ 写前基线存档 ① 上传卡图 ② 建模型 ③ 回读 ④ 写 icon/zh_title ⑤ 建产品
                                  │ 逐卡报告 JSON
                                  ▼
                       tasks.result.write_back → 网页展示
```

新增文件：

| 文件 | 作用 |
|---|---|
| `server/mlb_writeback.py` | 闸门判定 + 起线程 + 跑子进程 + 结论归并（**不碰数据库**，`update` 由 hub 注入） |
| `tests/verify_writeback_e2e.py` | 真起 hub 走完「建任务→回传→自动上架」的端到端冒烟（非 `test_*.py`，因为要起进程） |

### 10.3 三道闸门（任一不满足就不触发）

1. **任务级**：网页提交时勾了「自动上架」（`payload.write_back`）
2. **服务级**：`server_config.json` → `writeback.enabled`
3. **环境级**：写卡脚本与后台凭据文件都存在

再叠一层 `writeback.dry_run`：为 `true` 时全程只读（只登录+回读），
**要真正写入必须显式改成 false**。仓库里保持 `true` 作为安全默认，服务器上是 `false`。

> ⚠️ 改 `server_config.json` 后必须 `systemctl restart mlb-online` 才生效（配置是启动时读入的）。

### 10.4 为什么用子进程而不是 import

| 理由 | 说明 |
|---|---|
| 可超时 kill | 写卡要连外网 + 有 `sleep`，挂住时 hub 不受影响 |
| 依赖隔离 | 写卡要 `ddddocr`（实测峰值 RSS **86.9 MB**），hub 的依赖面完全不变 |
| 各自演进 | 边界就是一个 CLI + 一个 JSON 文件；两组各有独立离线回归，不构成跨模块耦合 |

### 10.5 可还原（本次重点）

- **写前基线**：每张要写的卡，在**任何写入之前**把后台 `GET /edit` 的完整表单
  落盘到 `writeback.archive_dir/<mid>.before.json`（148 个字段，全量）
- **只存第一次**：同一 mid 第二次跑**不覆盖** —— 否则会把"被写坏之后"的状态当基线
- **新建的模型**另记 `<archive>/_created.json`（它们没有 before，需人工判断去留）
- **一键回退**：
  ```bash
  /opt/python39/bin/python3 /opt/mlb-admin-write/src/mlb_write_cards.py \
      --cred /opt/mlb-admin-write/_cred.json \
      --archive /opt/mlb-admin-write/evidence/_archive \
      --restore --apply --confirm mlb26-players
  ```
  实测 4/4「保存成功」，写后只读核对与基线**逐字段差异 0**

### 10.6 服务器写权限（实证，勿再凭旧记忆断言）

`admin_api_client.py` 的 docstring 曾写「导入必须在本机跑」。**这条对 play187 不成立**：

| 项 | 结果 |
|---|---|
| 服务器 IP | `47.85.224.112`（旧记的 403 是 `47.253.252.55`，**另一台**） |
| 恒等写（原值回填 `POST /edit`） | `HTTP=200 code=1 msg='保存成功'` × 4 |
| 写后逐字段 diff | 内容字段变化 **0** |

存档/探针：`mlb_admin_import_20261012/evidence/_server_write_probe.py`，
基线留在 `/opt/mlb-admin-write/evidence/_archive_wprobe/`。

### 10.7 语义红线（接进主干后原样保留）

- `add` / `edit` / `shelves` **绝不自动重试**：超时 ≠ 失败，重跑可能建出重复模型
- 出现 `*-unknown(no-retry)` → 结论记 `needs_review`，网页弹黄条提示**不要重跑**
- 子进程超时 → `status=timeout`，同样不重试
- hub 重启时卡在 `running` 的记录 → 启动时统一改 `interrupted`（否则网页永远显示"上架中"）

### 10.8 本次线上变更

| 文件 | 说明 |
|---|---|
| `/opt/mlb-online/mlb_server.py` | v1.0 → **1.1**（`/result` 后触发上架；`/api/health` 暴露开关；启动清扫 interrupted） |
| `/opt/mlb-online/mlb_writeback.py` | **新增** |
| `/opt/mlb-online/server_config.json` | 新增 `writeback` 段（线上 `dry_run=false`） |
| `/var/www/mlb-online/index.html` | 勾选框 + 上架结果表 + 上架列 |
| `/opt/mlb-admin-write/src/mlb_write_cards.py` | 新增 `--archive` / `--restore` / `run_pipeline()` |
| `/etc/systemd/system/mlb-online.service` | `MemoryLimit` 180M → **512M**（写卡的 87MB 峰值要和 hub 同 cgroup） |

**备份/回滚**：`/opt/_bak_mlb_writeback_20261012_1528/`
（`mlb-online/{mlb_server.py,server_config.json,mlb.db.bak}`、`www/index.html`、
`admin-write/mlb_write_cards.py`、`etc/mlb-online.service`）

```bash
# 一键回滚
B=/opt/_bak_mlb_writeback_20261012_1528
cp $B/mlb-online/mlb_server.py     /opt/mlb-online/mlb_server.py
rm -f /opt/mlb-online/mlb_writeback.py
cp $B/mlb-online/server_config.json /opt/mlb-online/server_config.json
cp $B/www/index.html                /var/www/mlb-online/index.html
cp $B/admin-write/mlb_write_cards.py /opt/mlb-admin-write/src/mlb_write_cards.py
cp $B/etc/mlb-online.service        /etc/systemd/system/mlb-online.service
systemctl daemon-reload && systemctl restart mlb-online
```

### 10.9 上线验证（全部实跑）

| 项 | 结果 |
|---|---|
| 离线单测 `mlb-admin` | `{"testsRun": 34, "failures": 0, "errors": 0, "skipped": 0}` |
| 离线单测 `mlb-shelf-tool` | `{"testsRun": 50, "failures": 0, "errors": 0, "skipped": 0}` |
| 隔离门禁复现（`-I` + Popen 桩） | 两组均全绿 |
| 服务器 Python 3.9.18 端到端冒烟 | 17/17 |
| 线上真实链路（真登录 + 真后台往返） | 16/16，4 张全部 `skipped`（幂等，无写入） |
| `--restore` 回退路径 | 4/4 保存成功；只读核对与基线差异 0 |
| nginx 认证门禁 | 未登录仍 302 → `/__auth/access/`（未被破坏） |

---

## 十一、2026-10-12（第二轮）：写前人工确认 + 当期金币售价自动取价

老板原话两条：

> 「这个页面做完采集，在正式写入后台的时候，应该有一步是让人工确认上架的卡片步骤。
>   人工核对无误后才可点击放行，进行写入动作」
> 「当期金币售价这里也应该可以自动拉取后台的 MLB Stub 的实时单价。不需要人工手动填写」

### 11.1 需求 A：写前人工确认闸门（`awaiting_review`）

**改前**：`/result` 一进来就 fire & forget 起写卡线程 → 人在网页上看到的永远是「已经写完了」。

**改后**：采集回传后**只冻结快照，不写**；人逐条核对 → 勾选 → 点「确认放行」才写。

| 文件 | 说明 |
|---|---|
| `/opt/mlb-online/mlb_writeback.py` | 新增 `freeze()` / `read_pending()` / `approve()` / `cancel()`；`start()` 在 `require_approval` 下改停 `awaiting_review` |
| `/opt/mlb-online/mlb_server.py` | v1.1 → **1.2**；新增 `POST /api/tasks/<tid>/writeback/approve`、`.../cancel` |
| `/opt/mlb-online/server_config.json` | `writeback.require_approval`（缺省 **true**） |
| `/var/www/mlb-online/index.html` | 核对面板（逐卡勾选 + 「我已逐条核对」+ 放行/取消）；历史里可跳回待审任务 |

四条设计要点（都不是可选项）：

1. **冻结快照，不读 DB 里的 cards**
   `tasks.result.cards` 会被后续 `/result` 覆盖（任务重跑 / 执行器补传）。
   若人核对的是 A 而写的是 B，这道闸门就是假的。
   ⇒ 快照写 `<workdir>/<tid>.pending.json`（含 `sha256`），**放行只从快照取卡**；
     新结果**整份替换**快照 ⇒ 旧确认自动失效。
2. **只写勾选的**
   放行名单里出现快照外的 `product_name` ⇒ **拒绝**（防 UI 过期 / 人为构造），返回 `noop` + 原因。
3. **一次性的 `awaiting_review → running`**
   hub 是 `ThreadingHTTPServer`，双击「放行」会起两个写卡进程 → 建重复模型。
   `APPROVE_LOCK` 把「读状态 → 判状态 → 落盘 → 起线程」做成原子；第二次拿到 `noop`。
4. **审计留痕**
   `approved_by` / `approved_at` / `approved_cards`(计数) / `approved_names`(名单) / `sha256`。
   ⚠️ 名单与计数**都要**：只有计数回答不了「到底放行了哪几张」；
     只有 sha256 得把快照翻出来重算。留痕经 `run_once(extra=...)` 用 `setdefault` 合并
   —— **只做补充，绝不覆盖运行结论**。

`cancel` **只在 `awaiting_review` 允许**。跑动中不给取消：kill 掉写卡子进程会留下
"未知结果"的卡（比不写更危险），所以 `running` 时返回 `noop`。

### 11.2 需求 B：当期金币售价自动取价

来源（老板指定）：**订单后台** `order.p2pah.cn` → 游戏&产品 → 金币价格管理 →
所属游戏 **922**（MLB The Show 26）→ 该行 **`b2c`** 字段。
`b2c` 口径是 **USD/1K**，工作台 `rate` 口径是 **USD/100K** ⇒ `rate = b2c × 100`。

⚠️ 注意：这是**订单后台**，与商品后台（`admin-api.p2pah.cn`，GID 927 / CID 8233）**是两套系统，GID 不通用**。

| 文件 | 说明 |
|---|---|
| `/opt/mlb-admin-write/src/p2pah_price.py` | **新增**。纯标准库（服务端 `/opt/python39` **没有** `requests`/`urllib3`）；`ddddocr` 只在函数内惰性 import |
| `/opt/mlb-admin-write/_cred_order.json` | **新增**，`chmod 600`。订单后台账号密码 |
| `/opt/mlb-online/mlb_coins_rate.py` | **新增**。hub 侧桥接：子进程调用取价脚本，永不阻塞主链路、永不自动提交 |
| `/opt/mlb-online/mlb_server.py` | `GET /api/coins-rate`；`/api/health` 暴露 `coins_rate`（仅布尔） |
| `/var/www/mlb-online/index.html` | 表单自动预填 + 「重新取价」；人改过就不再覆盖 |

逆向时踩到的三个坑（写进代码注释了，别再踩）：

1. **菜单路径是「站点根相对」**（页面里 `WEB_ROOT = "/"`）。
   加 `/admin/` 前缀 → 404。正解 `/game/admin_game_price/index.html`
   （`/admin/index/index.html` 也能通，因为 `admin` 只是其中一个模块名，不是统一前缀）。
2. **筛选参数是 `?gid=922`**。写成 `?gid[]=922`（axios 风格）→ **HTTP 500**。
3. **表格里有 3 列被 `<!-- -->` 注释掉了**（`c2c` / `g2g.com` / `eldorado.gg`）。
   **必须先把 HTML 注释剥掉再解析**，否则 7 列变 11 列、列序整体错位。
   ⇒ `strip_comments()` 不是优化，是正确性前提。离线用例锁死了这条
     （`10 个 <td> → 剥注释后 7 个`）。

**两道防打爆后台的保护**（取价每次都要登录订单后台过验证码）：

- 前端：**不每 5 秒重试**，只在首屏 + 手动「重新取价」时调一次；
- 服务端：失败**负缓存 60 秒**（`FAIL_BACKOFF_SEC`）。
  否则页面 5 秒一轮 = 每小时 720 次登录 → 账号可能被锁。

取价失败**一律退回人工填写**，且**绝不影响**建任务 / 领任务 / 采集回传 / 上架。

### 11.3 本批文件清单

| 文件 | 变更 |
|---|---|
| `/opt/mlb-online/mlb_server.py` | 1.1 → **1.2** |
| `/opt/mlb-online/mlb_writeback.py` | 改（放行闸门） |
| `/opt/mlb-online/mlb_coins_rate.py` | **新增** |
| `/opt/mlb-online/server_config.json` | 加 `writeback.require_approval` + `coins_rate` 段（线上 `dry_run=false`） |
| `/var/www/mlb-online/index.html` | 核对面板 + 取价预填 |
| `/opt/mlb-admin-write/src/p2pah_price.py` | **新增** |
| `/opt/mlb-admin-write/_cred_order.json` | **新增**（600，订单后台凭据） |

### 11.4 上线验证

| 项 | 结果 |
|---|---|
| 离线单测 `mlb-admin`（Py 3.9.25） | `{"testsRun": 45, "failures": 0, "errors": 0, "skipped": 0}` |
| 离线单测 `mlb-shelf-tool`（Py 3.9.25） | `{"testsRun": 102, "failures": 0, "errors": 0, "skipped": 0}` |
| 门禁 `pr_fast.py`（3.9，main 基线 `7ae57b83`） | `{"result": "PASS", "affected_groups": ["mlb-admin", "mlb-shelf-tool"]}` |
| 端到端冒烟（真起 hub / 真发 HTTP / 真等子进程，Py 3.9） | **56/56** |
| 页面结构门禁（`frontend_structure`） | OK，41,450 B |

端到端里**刻意验的几条**（这是"闸门是真的"的唯一硬证据）：

- 回传后等 4 秒，`<tid>.writeback.json` **不存在** ⇒ 放行前确实没写；
- 放行名单里塞快照外的卡 → `noop` + 精确原因，磁盘仍无产物；
- 只勾 1 张 → 报告里就只能有 1 张；
- 连点两次「放行」→ 第二次 `noop`，报告仍是 1 张；
- 关掉闸门 → 回到旧的自动行为（加闸门不能把老路径弄坏）。

⚠️ 字段/接口名（后端与本机一致）：状态 `awaiting_review` / `cancelled` / `review_lost`；
端点 `POST /api/tasks/<tid>/writeback/approve`（body `{"names":[...]}`，`null` = 全选）
与 `.../cancel`（body `{"reason":""}`）。

### 11.5 线上（`47.85.224.112`）实测

部署方式：备份 → base64 分块上传 → **逐个 md5 回验** → `systemctl restart mlb-online` → 复核。

| 项 | 结果 |
|---|---|
| 版本 | `1.2`（`/api/health`） |
| 健康位 | `writeback{enabled:true, dry_run:false, require_approval:true, script_ok:true, cred_ok:true}` |
| 取价位 | `coins_rate{enabled:true, script_ok:true, cred_ok:true, gid:922, area:"PS 5", multiplier:100.0}` |
| 生产闸门自检 `_server_gate_check.py` | **37/37** |
| 服务器端端到端（Py3.9.18，用**已部署字节**跑 `_selftest/`） | **56/56** |

`_server_gate_check.py` 里**刻意验的**（生产环境、**全程零写入**）：

- `/result` 回传后 **10 秒**仍是 `awaiting_review`，且
  `/opt/mlb-online/data/writeback/<tid>.writeback.json` **始终不存在** —— 闸门在生产上为真；
- 放行名单塞快照外的卡 → `noop`；空名单 → `noop`；两者都不产生写卡产物；
- `cancel` → `cancelled` + 留痕，全程零写卡产物；
- 取价真跑（真登录订单后台 + 真过验证码）：耗时 **10.8 s**，
  `b2c=0.0429 (USD/1K)` → `rate_usd_per_100k=4.29`，`areas_consistent=true`
  （PS 5 / XBOX / Switch 三个区都是 `0.0429`）；
  不 `force` 时命中缓存 **0.0008 s**。

⚠️ 这里**没有**在生产环境做「放行 → 真写入」。上线的是 `dry_run=false` 的生产配置，
放行只在那 4 张「已存在且完整」的卡上才是幂等安全的，**前提是它们此刻仍在** ——
只要有一张缺失，放行就变成真实生产写入。所以「放行→写入」的完整链路改用
**同一台服务器上的独立临时 hub + 假写卡脚本**验证（就是上面那条 56/56），
用的是**同一批已部署字节**，不碰生产数据。

> ⚠️ 部署踩坑记录：`Path(remote).parent` 在 Windows 上给出 `\opt\a\b`（反斜杠），
> 丢给 bash 会被当转义符吃掉 → 在 `/root` 下建出 `optmlb-online_selftesttests`
> 这种垃圾目录。远端路径的父目录必须用**字符串切分**求。

**备份 / 回滚**：`/opt/_bak_mlb_20261012_gate/`
（`mlb-online/{mlb_server.py,mlb_writeback.py,server_config.json,mlb.db.bak}`、
`www/index.html`、`admin-write/p2pah_price.py`、`stale/verify_writeback_e2e.py`）

```bash
# 一键回滚
B=/opt/_bak_mlb_20261012_gate
cp $B/mlb-online/mlb_server.py      /opt/mlb-online/mlb_server.py
cp $B/mlb-online/mlb_writeback.py   /opt/mlb-online/mlb_writeback.py
rm -f /opt/mlb-online/mlb_coins_rate.py
cp $B/mlb-online/server_config.json /opt/mlb-online/server_config.json
cp $B/www/index.html                /var/www/mlb-online/index.html
systemctl daemon-reload && systemctl restart mlb-online
# ⚠️ 回滚后页面上的「当期金币售价」会退回人工填写（接口 404），不影响采集与上架
```

