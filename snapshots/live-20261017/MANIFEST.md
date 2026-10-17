# 线上快照 · 2026-10-17（服务器重置前留档）

**来源机器**：`play187` = `47.85.224.112`（公）/ `172.18.108.187`（私）· CentOS 7.9
**采集时间**：2026-10-17 13:33（GMT+8）
**采集方式**：`md5sum` 清单比对 + `tar` 原样打包（保留文件 mtime），全程只读，未修改线上任何文件。

## 为什么要这个快照

重置服务器前发现**线上代码普遍比仓库 `main` 新**（例如 `core_gold.py` 当天 11:57 还在改动），
且部分模块**从未入库**（`opt/d4follow/net_util.py`、`opt/shugo-bot/kinah.py` 等）。
直接重置会永久丢失这些代码。本分支是「原样留档」，不是源码真源。

其中能在 CI 闸门下正常过检的部分（`opt/d4follow/**`、`opt/shugo-bot/**`、
`aion2_dd373_local_collect_20261006/**`）已在 **PR #201** 合并进 `main`；
本分支补齐其余**未被 `tools/pr_fast.py` 纳管**的路径，保证「一个字节都不丢」。

## 内容

| 分类 | 数量 | 还原目标 |
|---|---|---|
| `opt/<模块>/**` 源码与配置 | 238 | `/opt/<模块>/` |
| `opt/MODULES.md` 模块地图 | 1（含在上面） | `/opt/MODULES.md` |
| `etc/nginx/**` | 13 | `/etc/nginx/` |
| `etc/systemd/system/*.service|.timer` | 38 | `/etc/systemd/system/` |

覆盖 12 个模块：`auth-portal` `bot-console` `d4follow` `deploy-hub` `fs-access-policy`
`g2gfollow` `iggm-web` `mlb-online` `mmoexp-guardbot` `mmoexp-taskboard` `nba-reprice` `shugo-bot`。

## 刻意排除（重置后需另行重建）

- 依赖与缓存：`venv/` `.venv/` `node_modules/` `__pycache__/` `registration-runtime-deps/`
- 备份与归档：`_bak*/` `_rollback*/` `_archived*/` `backup*/` `*stage*/` `_patch_*`
- 运行数据：`logs/` `output/` `var/` `_tmp*/` `*.log`
- **`*.json` 全部排除**（含 `config.json` / `news_state.json` / 状态与令牌文件）→ 避免把
  Discord token、钉钉 webhook、会话密钥等写进仓库
- 按文件名排除：`*.pem` `*.key` `*session*` `.htpasswd*` `*credential*` `*secret*`

> **首次采集的疏漏（已修）**：第一版打包误入 3 个凭据文件 —— `opt/shugo-bot/token.txt`、
> `opt/nba-reprice/backend/.cookies.txt`、`.iggm.cookies.txt`。已在推送后 3 分钟内从提交中
> 剔除并重建分支，本目录另加 `.gitignore` 守卫。**仍建议轮换 Discord bot token 与
> 对应站点 cookie**（仓库为私有，暴露窗口约 3 分钟）。

> 因此**配置值不在本快照内**。重建时 `config.json` / `config.env` / `.htpasswd-*` /
> 钉钉与 Discord 凭据必须另取（本机 Windows 凭据管理器 / 服务器现网备份）。

## 关键漂移（重置前已核实）

| 文件 | 线上 mtime | 仓库末次提交 | 处置 |
|---|---|---|---|
| `opt/d4follow/core_gold.py` | 2026-10-17 11:57 | 2026-10-12 21:18 | 已入 `main`（PR #201） |
| `opt/d4follow/net_util.py` | 2026-10-16 23:09 | **未入库** | 已入 `main`；被 `aion2_watch` `core_front` `core_gold` `core_iggm` 引用，**缺失会导致启动即 ImportError** |
| `opt/shugo-bot/kinah.py` | 2026-10-15 19:39 | **未入库** | 已入 `main`（946 行，AION2 价格看板） |
| `opt/d4follow/app.py` + `templates/index.html` | 2026-10-13 02:17 | 2026-10-12 21:59 | 已入 `main` |
| `opt/d4follow/core_qd.py`(千岛) `core_iggm.py` `core_front.py` `engine.py` `aion2_watch.py` | 10-13 ~ 10-16 | 10-06 ~ 10-10 | 已入 `main` |
| `etc/nginx/conf.d/fs-ip-allowlist.conf` | 2026-10-16 21:26 | 未纳管 | 仅存于本快照；线上版本为 **v4**（IP 白名单 + IP 黑名单 + UA 黑名单三层），本地旧镜像 `opt/auth-portal/fs-ip-allowlist.conf` 是 v1/v2，**已作废** |
| `opt/auth-portal/fs_ip_alert.py` | 2026-10-16 18:15 | 未纳管 | 仅存于本快照（423 行）；本地那份 174 行是旧版 |
| `opt/fs-access-policy/access_policy.py` | 2026-10-09 07:59 | 2026-10-05 | 仅存于本快照；`ADMINS` 名单决定全站写权限 |
| `opt/mlb-online/mlb_writeback.py` `mlb_coins_rate.py` | 2026-10-12 | **未入库** | 仅存于本快照（498 / 228 行） |
| `opt/mmoexp-taskboard/green_plan.py` | 2026-10-09 | **未入库** | 仅存于本快照（261 行） |

## 还原方法

```sh
# 1) 单文件还原（例）
scp snapshots/live-20261017/opt/fs-access-policy/access_policy.py \
    root@<新机>:/opt/fs-access-policy/access_policy.py

# 2) 整目录还原（例）
tar czf - -C snapshots/live-20261017 opt/d4follow | ssh root@<新机> 'tar xzf - -C /'

# 3) nginx / systemd
rsync -a snapshots/live-20261017/etc/nginx/ root@<新机>:/etc/nginx/
rsync -a snapshots/live-20261017/etc/systemd/system/ root@<新机>:/etc/systemd/system/
systemctl daemon-reload && nginx -t && systemctl reload nginx
```

## 注意

- **本分支只用于留档与灾难恢复**，不做日常开发基线。日常基线是 `main`。
- 不要把本目录整体 rsync 覆盖到线上：其中的 nginx 配置是针对**旧机 IP 与旧目录结构**的，
  新机若改了端口/路径需先对齐 `/opt/MODULES.md`。
- 快照里的 `opt/d4follow/*` 与 `main` 中的同名文件内容一致（PR #201 已回灌），
  差异只会出现在「未纳管路径」上。
