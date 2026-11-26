# `_p2pah_srv` — 服务端「直连改价后台」执行器源码留档

本目录是生产机 **47.85.224.112** 上 `/opt/d4follow/_p2pah_srv/` 的**源码留档**（只收运行态源码）。

- 采集时间：2026-10-12 09:00（北京时间）
- 采集原因：该目录原先**整个未纳入版本库**，而 `p2pah_local.py`（执行器主体）是线上唯一被改动的源码 —— 出现「代码未在仓库维护」的空档。
- 采集方式：**逐个下载白名单文件**（非整目录 copy），从物理上杜绝把凭据 / 会话 / 运行时产物带进仓库。

---

## 1. 文件清单

| 文件 | 用途 | 线上 md5 | 入库 md5 |
|---|---|---|---|
| `p2pah_local.py` | 执行器主体：读价 / 发写请求 / 写价 / 推送前端 / 清缓存。**2026-10-12 修复 ARC gid 解析的工作文件** | `444c0c5d42b686dd02d5545c27c95324` | 同左 |
| `srv_run.py` | 容器内 CLI 入口（`python /srv/srv_run.py writegold --plan ... --config ... --profile ...`） | `4f4a947c7f2fa38c8a182d44641d6032` | 同左 |
| `p2pah_autologin.py` | 两个后台的「会话过期 → 账号密码兜底自动登录」（含离线 OCR 认验证码） | `d52e7c8e2337e1ec4470f11963128e08` | `1c236578978ae20151d21f9a408db968` ⚠ 脱敏 |
| `admin_cache_local.py` | `admin.p2pah.cn` 清缓存（**必须本机执行**，后台有来源 IP 白名单） | `2724ac3d49589066d782e9905a419ffc` | `2833bc6093c019e5b11e37ac464557bb` ⚠ 脱敏 |
| `Dockerfile` | 执行镜像 `p2pah-srv:1`（叠在 `qd-render:1.47` 上装 ddddocr / pillow / numpy<2） | `a05f2d8ee50b813309aef4e953ffb10f` | 同左 |
| `_dump_by_cat.py` | 按登记类目抓后台清单（`refresh_d4_items.sh` 的运行依赖） | `feeec7283a1ccb53c99deaf9ce223aa3` | 同左 |
| `merge_backend_items.py` | 清单合并 + 闸一预演（`refresh_d4_items.sh` 的运行依赖） | `aabb17e684e3f28f1b837348a76d9460` | 同左 |
| `refresh_d4_items.sh` | D4 清单一键刷新（按登记类目抓，避免全量翻页截断） | `747dad3f15e7537613c9f3d0a3599c58` | 同左 |
| `build_cid_map.py` | 构建后台类目 ID → cid 映射 | `add36f23a6df08577a62ae4023f7565f` | 同左 |
| `fix_d4_registry.py` | D4 注册表修复 | `0c624ef01a21157801a2bc44717929a5` | 同左 |
| `p2pah_srv_trial.py` | 服务端直连试运行脚本 | `ca9c34fa1d678752db8d853ebc2e4291` | 同左 |
| `front_chan.py` | 前端通道联调脚本 | `82381ab771bbdc941d4eeef9e36c455d` | 同左 |
| `front_test.py` | 前端联调测试脚本 | `efb4cf4848095d669ef61b777e020062` | 同左 |

> 除 2 个标注 ⚠ 的文件外，**入库内容与线上逐字节一致**（md5 相同），可直接用于线上漂移核对。

---

## 2. 脱敏说明（入库前必读）

线上这 2 个文件含**明文凭据**，入库版已按凭据政策替换为占位符。**全仓库已扫描确认无凭据残留。**

### 2.1 `p2pah_autologin.py`

```python
# 线上（原始）：
FALLBACK = {"username": "<账号>", "password": "<口令>"}

# 入库（脱敏后）：
FALLBACK = {"username": "", "password": ""}
```

- 线上凭据优先级：`_accounts.json` → `_cfg/config.json` 的 `p2pah.账号` → 此处 `FALLBACK`；前两者**均不入库**。
- ⚠ **安全隐患（建议整改）**：把后台明文账号口令硬编码进源码，等于任何拿到该文件的人就拿到后台口令。建议把 `FALLBACK` 改为只从环境变量 / `_accounts.json` 读取，不再内置默认值。

### 2.2 `admin_cache_local.py`

- 第 311 行注释里的真实 token 样例 → 替换为 `"<redacted-uuid>"`（该 token 为历史值，但按政策一律不留）。

---

## 3. 未入库内容及原因

线上该目录共 77 MB，除上述源码外**一律不入库**：

| 类别 | 内容 | 原因 |
|---|---|---|
| 凭据 / 会话 | `_accounts.json`、`_admin_token.json`、`_admin_account.json`、`p2pah_cookies.json`、`_srv_profile/`、`_edge_p2pah/`、`_edge_adminp2pah/` | 账号口令、登录 token、浏览器登录态 |
| 配置 | `_cfg/`（含 `config.json`，1.3 MB） | 含账号与业务配置 |
| 运行时产物 | 上千个 `p2pah_write_result_*.json` / `p2pah_writegold_result_*.json`、`_jobs/`、`_shots/`、`_tmp_probe/`、`data/`、各种 `*.log` / dump json | 价格业务数据与临时产物 |
| 备份 | `_bak_p2pah_local_*.py`、`*.bak_*`、`_bak_verify_gid_20261001/` | 历史版本，非当前源码 |
| 一次性/侦察脚本 | `_evid_*.py`、`_mscw_*.py`、`_probe_pages.py`、`_test_fetch_needed.py`、`_dump_readonly.py`、`_gold_rows_readonly.py`、`_list_d4_keys.py`、`_verify_gid_20261012.py`（本次验收脚本）、`_new_core_dd373_cost.py`（另一条线待上线版本） | 一次性取证 / 探测 / 验证，非运行态源码 |

目录级 `.gitignore` 已把这些规则固化，防止将来误提交。

---

## 4. 与线上核对漂移

```bash
ssh -i No1.pem root@47.85.224.112 \
  'cd /opt/d4follow/_p2pah_srv && md5sum p2pah_local.py srv_run.py ...'
```

与本 README 表格中的「线上 md5」比对；不一致即说明线上源码已变更，需同步回本目录。
