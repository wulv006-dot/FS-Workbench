# FS 平台 · 访问来源白名单（IP allowlist）

> 建立于 2026-10-15。目标：只允许公司自有出口访问本平台，阻断「外部人拿到账号密码后直接登录」。

## 一、为什么要做

登录门户 `auth-portal` 已有防爆破（同 IP+账号连续失败 6 次锁 300 秒），但那只挡「猜密码」。
**一旦对方拿到正确密码，一次就能登录，锁定机制不会触发。** 白名单把「不在名单里的来源」在网络入口直接挡住，
连登录页都打不开——这是防「凭据泄露」最直接的一道。

## 二、组成与位置

| 文件 | 线上路径 | 作用 |
|---|---|---|
| `fs-ip-allowlist.conf` | `/etc/nginx/conf.d/fs-ip-allowlist.conf` | http 级：`geo` 定义白名单、`map` 组合出 `$fs_ip_block` |
| `fs-ip-allowlist.locations.conf` | `/etc/nginx/fs-ip-allowlist.locations.conf` | server 级：拦截判定 + 拒绝页 + 被拒日志 |
| `fs_ip_alert.py` | `/opt/auth-portal/fs_ip_alert.py` | 扫描被拒日志，新来源推钉钉（群「服务器及Github报警」） |
| `fs-ip-alert.service` / `.timer` | `/etc/systemd/system/` | 每 2 分钟触发一次告警 |

`iggm-web.conf` 的 server 块内以标记块引用：

```nginx
# >>> fs-ip-allowlist-20261015 >>>
include /etc/nginx/fs-ip-allowlist.locations.conf;
# <<< fs-ip-allowlist-20261015 <<<
```

## 三、白名单当前包含（2026-10-16 收紧）

放行口径：**只放「本公司机器」+「本公司脚本工具」两类**，其余全挡。

**A. 公司机器出口**（`/32` 精确；来源：`/opt/auth-portal/data/audit.log` 登录成功记录）

- `45.58.38.172` 主力出口（Atlantic.Net AS6364）· 人 + 脚本共用
- `90.96.180.210` 自动化采集出口（吴律工具，经 Cloudflare）
- `45.95.212.151` DY 代理出口
- `223.244.89.51` / `114.88.116.122` 家宽出口

**B. 脚本工具出口**（**放整段**，因为脚本 IP 会在同一 IDC 段内漂移）

- `43.228.212.0/24` Atlantic.Net AS6364（脚本实测 `.186` / `.158`）
- `173.249.200.0/23` + `173.249.209.0/24` tzulo AS11878（脚本实测 `.200.124` / `.209.90`）
- `152.175.0.0/16` ISIF OU AS209554（脚本跨 `.33` / `.66` / `.97` 漂移；该 /16 下全部宣告前缀均属它）

> 脚本漂到这些段之外被挡时：看钉钉告警或拒绝页回显的 IP，按其所在 `/24` 追加一行。

**C. 基础设施**：`127.0.0.0/8`、`172.16.0.0/12`、`10.0.0.0/8`、`192.168.0.0/16`、`47.85.224.112/32`

**D. 钉钉官方 Bot**（消息卡片链接预览）：`59.82.0.0/16`
（2026-10-16 修正：原 `59.82.21.0/24` 只覆盖发消息出口，而预览抓取实际来自 `59.82.83.x`）

> **总开关**：`fs-ip-allowlist.conf` 末尾 `map "$fs_ip_allowed:$fs_is_acme" $fs_ip_block` ——
> `"0:0" 1;` = 拦截开启（**当前**），`"0:0" 0;` = 全量放行（应急）。

## 四、两个不能碰的例外

1. **ACME 验证路径 `/.well-known/acme-challenge/` 对所有来源开放。**
   本机证书是 Let's Encrypt 短周期（`preferred_profile = shortlived`，约 6 天），
   由 `fc27-ip-certificate.timer` 每 12 小时用 webroot 续期，验证来源 IP 不固定。
   挡掉它 → 证书过期 → 全站 HTTPS 中断。

2. **拦截用专用状态码 418，不用 `error_page 403`。**
   本 server 内多个 location 会因权限不足返回 403（统一登录门户的 `auth_request`），
   直接改 `error_page 403` 会把「无权限」误显示成「IP 受限」。

## 五、怎么加白名单

编辑 `/etc/nginx/conf.d/fs-ip-allowlist.conf`，在「公司自有出口」区加一行：

```nginx
    1.2.3.4/32          1;   # 备注
```

然后：

```bash
nginx -t && systemctl reload nginx
```

被拦截的人会看到一个**回显自己公网 IP** 的页面，把该 IP 发过来即可。

## 六、怎么回退

```bash
# 删掉 iggm-web.conf 里的 # >>> fs-ip-allowlist-20261015 >>> 标记块
rm -f /etc/nginx/conf.d/fs-ip-allowlist.conf /etc/nginx/fs-ip-allowlist.locations.conf
nginx -t && systemctl reload nginx
```

## 七、验证

- 白名单内来源可正常访问；
- 白名单外来源得到 403 + 拒绝页，并出现在 `/var/log/nginx/ip-denied.log`；
- 新来源 2 分钟内收到钉钉告警；
- ACME 续期不受影响（`fc27-ip-certificate.timer` 下次运行正常）。

## 八、告警推送到哪个群

告警使用 **fc-ops 监控体系共用的那个钉钉机器人**（群「**服务器及Github报警**」，
即「服务器脚本运行情况 / Github 报警」所在群），凭据直接读：

```
/etc/fc-ops-readonly-monitor/hooks-bot.json   # root 私有 0600
```

读取时做端点校验：必须 `https://oapi.dingtalk.com/robot/send`、
`access_token` 为 64 位 hex、`group` 必须等于 `服务器及Github报警`，
任一不符即拒绝发送（避免误配把告警发到别的群）。该机器人**免加签**（`secret` 为空），
脚本已兼容：`secret` 非空时自动算 `timestamp` + `sign`。

> 2026-10-15 调整：原先复用 `/opt/d4follow/dingtalk.env`（AION2 金币价机器人），
> 现改为上面的 fc-ops 机器人。金币机器人不再接收本告警。
> `fs_ip_alert.py` 的旧版本留在 `/opt/auth-portal/fs_ip_alert.py.bak-20261015-aion2bot`。

## 九、已知未纳入自动检查项

按 `tools/pr_fast.py` 的后缀分流规则（第 374、378、391 行）：

- `fs-ip-allowlist.conf`、`fs-ip-allowlist.locations.conf`（`.conf`）与
  `README-ip-allowlist.md`（`.md`）—— 后缀不在第 378 行的
  `.py/.js/.cjs/.sh/.html/.css` 集合内，**直接跳过检查**，可安全入仓。
- `fs_ip_alert.py`（`.py`）、`fs-ip-alert.service` / `fs-ip-alert.timer`
  （`.service` / `.timer`）—— 会落进 `UNMAPPED` 桶导致 pr-fast 判红，
  **未入仓**，仅在服务器 `/opt/auth-portal/` 与 `/etc/systemd/system/` 维护。
  若要纳入版本管理，需在同一个 PR 里为 `opt/auth-portal/` 增加映射和最小离线检查。

因此 **pr-fast 不校验本次 nginx 配置**；实际接线验证以服务器上的
`nginx -t`、`systemctl reload`、真实授权入口读回，以及外部来源 403 探测为准。
