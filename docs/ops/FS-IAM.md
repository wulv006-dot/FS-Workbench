# FS 访问控制（fs-iam）

> 2026-10-20 重做。替代原来的「路径里有没有 admin/deploy 关键词 + 4 个硬编码名字」。
> 模型参照 **阿里云 RAM / AWS IAM**：成员 → 角色 → 策略规则（资源 × 动作）。

## 一句话模型

```
成员 (subject)  --绑定-->  角色 (role)  --规则-->  允许访问的 (资源, 动作) 集合
```

- **默认拒绝**：没被任何规则命中就 403。
- **显式拒绝优先**：`bindings.<成员>.deny` 命中即拒，哪怕同时命中 allow。
- **最小权限**：角色只有显式列出的资源 × 动作，没有隐式继承。
- **可解释**：控制台「权限自检」和 `admin_cli.py check` 会说清资源、动作、命中哪条规则。

### 动作（只有 5 个）

| 动作 | 含义 | 典型触发 |
|---|---|---|
| `view` | 浏览读取 | GET / HEAD |
| `edit` | 改数据 | POST/PATCH/PUT/DELETE（非控制词） |
| `execute` | 触发采集 / 刷新 / 执行 | 路径段或查询串含 collect、run、refresh_now 等 |
| `deploy` | 部署通道 | `/deploy/*`、nginx 的 `group=deploy` |
| `manage` | 成员与授权 | `/__auth/iam/*`、`/admin*` |

## 文件构成（全部在 `/opt/fs-access-policy/`）

| 文件 | 作用 |
|---|---|
| `rbac.py` | 策略求值内核：资源表、动作判定、deny 优先、录制审计。纯计算，不碰凭据。 |
| `access_policy.py` | **兼容层**。`authorize(user, method, uri, group)` / `ADMINS` 契约不变，内部转调 rbac。策略坏了自动回落到改造前的旧逻辑。 |
| `iam_console.py` | 控制台后端（`/__auth/iam/*`）。CSRF + 乐观锁 + 校验 + 审计。 |
| `web/` | 控制台前端（零依赖、无外网）。 |
| `admin_cli.py` | 运维命令行，控制台能做的它都能做。 |
| `policy.seed.json` | 种子策略。只在**活策略不存在**时用来初始化。 |

**活策略**：`/opt/auth-portal/data/fs-iam/policy.json`（可写状态，不进 git；
每次保存自动留 `.bak` 和 20 份时间戳备份）。
**审计**：`/opt/auth-portal/data/fs-iam/audit.jsonl`（追加写，只增不改）。

> 为什么策略放 data 而不是代码目录：它是**状态**不是代码。部署代码时不能覆盖
> 线上已有的授权现状，否则每次上线都会把大家的权限重置回种子。

## 两个特殊资源

- `identity`（`/__auth/*`、`/verify`、`/`）：**已登录成员永远可读**。
  这是登录自举，防止一次错误策略把所有人锁在门外。写请求不享受这个旁路。
- `unbound_role`（默认 `Viewer`）：htpasswd 里有、但策略里没绑定的成员按它生效。
  置空则变成严格的 deny-by-default。**注册账号靠它拿到与改造前一致的只读权限。**

## 日常操作

```bash
cd /opt/fs-access-policy
/opt/python39/bin/python3 admin_cli.py status
/opt/python39/bin/python3 admin_cli.py check --user mmoexp --method POST --uri /d4/api/price
/opt/python39/bin/python3 admin_cli.py grant  --user zhang --roles PricingOps --by chenchao --note "接手 D4"
/opt/python39/bin/python3 admin_cli.py revoke --user zhang --role PricingOps --by chenchao
```

网页：`https://47.85.224.112/__auth/access/` —— 就是主入口导航栏里那个「账号权限」
入口，整页就是本控制台（页签：成员管理 / 角色与策略 / 权限自检 / 审计日志）。
**只有拿到 `admin:manage` 的成员能进**，其他人看到 403 说明页。

页面外壳和平台其他页面是同一套：左侧那条全站导航就是 `/var/www/hub/hubnav.js`
（nginx 给所有页面注入的那一份，唯一真源），**本页不自建侧栏**——登录且确认
是管理员后由 `app.js` 的 `mountSharedNav()` 挂载，版本号与 nginx `sub_filter`
里的 `?v=` 保持一致，共用浏览器缓存。页头右侧固定一个「返回平台」回
`/dashboard/`。

> 导航脚本的 `?v=` 一旦变了，`app.js` 里的 `HUBNAV_SRC` 也要跟着改，
> 两处必须同一个串，否则会各自缓存一份。

> 这个地址同时是全站未登录的登录落点（nginx `@auth_login` 就 302 到这里），
> 所以未登录时由页面自己出登录框，服务端**不 302** —— 否则会自己跳自己，
> 无限重定向，谁都登不进来。

老门户页（注册 / 我的申请 / 注册审批）已下线：`/__auth/account/` 现在 302 回
本控制台，页面不再提供。**改密码已并入本控制台**（见下）。

路由怎么接的：nginx 把 `/__auth/access/*` 内部改写到后端的 `/iam/*`，
因此 `iam_console.py` 里的路径常量仍是 `/iam`，后端不对外暴露。

## 改密码

入口：成员管理 → 点某个成员的「管理」→ 抽屉底部「修改密码」。

- **只有超级管理员**（绑定 `PlatformAdmin` 这类 `super` 角色）能改，其他人
  连输入框都看不到，接口也直接 403。
- **不需要原密码、不需要二次确认、不填原因** —— 填新密码点「更新密码」即可。
- 长度必须 **12–128 位**。这不是产品偏好：`auth_candidate.password_hash()`
  与 `password_matches()` 都硬校验这个区间，短于此写进去的哈希连自己都
  验不过，等于当场把账号锁死。
- 写入的是**密码的权威存储** `gate.db` 的 `account_state.password`
  （pbkdf2_sha256 覆盖值）。登录时 `Accounts.authenticate()` 是「有覆盖值
  用覆盖值，没有才回落 htpasswd」，所以改 htpasswd 无效。
- 写入同时：`version+1`（旧 token 失效）、删掉该账号的 `sessions`、
  追加 `account_events`（action=`password`）。改自己的密码会把自己登出。


## 安全闸门

1. 进控制台要 `admin` 资源的 `manage` 动作（= 超级角色）。
2. 所有写操作要 CSRF 双提交 Cookie + Origin 同站校验。
3. 写操作带 `revision` 乐观锁，两人同时改会 409 而不是互相覆盖。
4. 落盘前 `validate()`：未知动作、引用不存在的角色、把自己降级、删掉最后一个
   超级管理员 —— 全部拒绝。
5. 每次变更写审计（actor / 时间 / 前值 → 后值 / 策略版本 / 修订号）。

## 明确不在本系统里

- **注册审批 / 注册账号申请**。老页线下线后暂时没有界面入口；相关后端
  （`/access/api/*`、`account_management.decide`）仍在，数据不会丢。
  真要恢复，应当重做成控制台里的一个视图，而不是把老页拖回来。
- **门户会话**。Cookie 格式、`/verify` 契约没动。

## 已知遗留（下一步）

下面三处后端仍用**自己的硬编码名单**做二次判定，与新模型尚未打通。
网关层（nginx auth_request）已经按新策略放行，但后端还会再拒一次：

| 位置 | 现状 |
|---|---|
| `opt/nba-reprice/backend/api_security.js` | `ADMINS = ['wulv','chenchao','DY']`，缺 `fstech`；要求 `x-auth-role == admin` |
| `opt/bot-console/server.py` | 写操作要求 `X-Auth-Role == admin` |
| `opt/mmoexp-taskboard/taskboard_server.py` | `editor` 角色只接受 `reg:` 前缀 |

改这些等于扩大/收紧现网写权限，需单独一批。
`X-Auth-Role` 目前保持 `admin` / `readonly` 两值不变（taskboard 会对非 `reg:` 的
`editor` 直接 503，所以不能顺手改成 `editor`）。

## 回归保护

```bash
python3 tests/test_fs_iam_rbac.py     # 18 项：含「新引擎 vs 旧实现」逐格对照
python3 tests/test_fs_iam_console.py  # 13 项：控制台全链路接线
```

`test_matrix_equals_legacy` 会拿 5 个真实账号 × 30 条 URI × 5 种方法 × 2 条通道
逐格比对新旧判定，**任何一格不一致就红**。这是改这套系统的唯一安全绳。
