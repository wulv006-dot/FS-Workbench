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

网页：`https://47.85.224.112/__auth/iam/`（左侧菜单：成员管理 / 角色与策略 /
权限自检 / 审计日志）。**只有拿到 `admin:manage` 的成员能进。**

## 安全闸门

1. 进控制台要 `admin` 资源的 `manage` 动作（= 超级角色）。
2. 所有写操作要 CSRF 双提交 Cookie + Origin 同站校验。
3. 写操作带 `revision` 乐观锁，两人同时改会 409 而不是互相覆盖。
4. 落盘前 `validate()`：未知动作、引用不存在的角色、把自己降级、删掉最后一个
   超级管理员 —— 全部拒绝。
5. 每次变更写审计（actor / 时间 / 前值 → 后值 / 策略版本 / 修订号）。

## 明确不在本系统里

- **密码**。仍在 `htpasswd`（`/etc/nginx/.htpasswd-dashboard` /
  `.htpasswd-deploy`）与注册库 `account_state` 表；自助改密仍在
  `/__auth/access/`。凭据属红线动作，逐项另批。
- **门户会话**。Cookie 格式、`/verify` 契约没动，nginx 一行没改。

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
