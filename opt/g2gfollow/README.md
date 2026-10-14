# G2G 金币改价系统（AION2 Kinah）

把**本店 G2G 店铺（Loot_Supply / seller_id `1003767531`）**的 AION2 金币挂牌价，
按「DD373 进货成本 × 加价比例」自动算价并（经人工放行后）批量改价。

与 `d4follow`（RPG 游戏改价系统）**完全隔离**：

| 维度 | d4follow | 本系统 g2gfollow |
|---|---|---|
| 目录 | `/opt/d4follow` | `/opt/g2gfollow` |
| 进程 | `d4follow.service` | `g2gfollow.service` |
| 端口 | 127.0.0.1:8900 | 127.0.0.1:8903 |
| 数据库 | 自己的库 | `data/g2gfollow.db`（独立） |
| 页面 | `/d4/` | `/g2g/`（nginx 共享配置，见下） |
| 抓谁 | 竞品价（cheapold 等） | **本店后台**（要登录 token） |

运行时**不读也不写** d4follow 的任何文件。唯一联系是 `vendor/core_dd373_cost.py`
——它是从 d4follow **复制**过来的成本抓取模块（快照），不是软链。成本口径因此天然一致，
但 d4follow 改这个模块时本系统**不会**自动跟着变，需要手动 `tools/sync_vendor.sh`。

---

## 定价口径（2026-10-10 定案）

```
目标挂牌价 $/M = DD373「买满 1 亿基纳的订单簿加权均价」$ × 加价比例（1.30）
货源不足 1 亿基纳 / 无有效报价        →  闸门价 $19.9/M
现价落在「保护占位价」（默认 9.99）   →  占位保护 · 不动（见下）
```

**为什么有「占位保护」**：实测店里 33 个区常年挂 $9.99，远高于成本价——那是
「不想卖」的占位价。若无脑按 `成本×1.30` 下调，会把这些区一把压到 $1~4，等于主动放量甩货。
故现价 ∈ 保护占位价 时一律出「占位保护·不动」。

- 要改这些区：把 `config.json` → `定价.保护占位价` 里的 `9.99` 去掉（**清空数组即关闭保护**）。
- 匹配带 ±0.011 容差（店里有条现价是 `9.9999`，精确相等会漏出保护）。

---

## 铁律（写入侧，不可绕）

1. **采集只出 dry-run 工单**，绝不碰价格；
2. 工单要**逐行人工放行**（看板勾选）才可能被执行；
3. **执行默认 dry**；真写必须显式 `confirm=true`（前端会二次确认）；
4. 每条写完**回读校验**，校验不过的进流水标红。

---

## Token 通道（关键）

G2G 后台接口要 `authorization: <accessToken>`（裸 token，无 Bearer 前缀），
token 寿命 **15 分钟**，且登录被 Akamai + 邮箱 OTP 拦得很死（详见侦察记录）。

本系统的做法：**不碰登录**。
由本机（Windows）常驻保活器 `g2g_session_keeper.py` 维持一个专用 Chrome 会话，
靠 G2G 前端自己的 refresh cookie 自动续签，再把有效 token 推到服务器：

```
本机 保活器 ──ssh/scp──> 服务器 /opt/g2gfollow/var/token.json
```

不开公网写端点。`POST /api/token` 只是登录后的**人工排障入口**（备用）。

看板右上角常显 token 剩余秒数；过期会标红，此时采集会直接报「token 不可用」。

---

## 目录

```
/opt/g2gfollow/
├── app.py              Flask 应用（看板 + API）
├── pricing.py          定价引擎（口径 + 占位保护）
├── core_self.py        本店货架读 / 改价写（G2G seller API）
├── store.py            独立 SQLite（快照 / 建议单 / 写入流水）
├── vendor/
│   └── core_dd373_cost.py   ← 从 d4follow 复制的成本抓取快照
├── config.json         独立配置（86 个 AION2 服务区 + 汇率 + 定价参数）
├── templates/index.html 看板（自包含，零外链）
├── tools/
│   ├── snapshot_config.py  从 d4follow config 抽本系统 config
│   ├── sync_vendor.sh      同步 vendor 快照
│   └── selftest.py         逻辑自测（离线）
├── data/g2gfollow.db   运行时生成
├── var/token.json      保活器推来的 token
├── logs/               服务日志
└── systemd/g2gfollow.service
```

---

## 部署

```bash
# 0) 同步代码（在本地仓库）
rsync -az --delete -e "ssh -i No1.pem" opt/g2gfollow/ \
      root@47.85.224.112:/opt/g2gfollow/

# 1) 独立 venv（隔离，不共用 d4follow 的）
#    ⚠ 基础解释器必须用 /opt/python39/bin/python3（带 _ssl）。
#      系统 python3 指向 /usr/local/python39，**缺 _ssl**，用它建的 venv
#      跑 gunicorn 会 ModuleNotFoundError: No module named '_ssl'。
ssh root@47.85.224.112
/opt/python39/bin/python3 -m venv /opt/g2gfollow/venv
/opt/g2gfollow/venv/bin/pip install -r /opt/g2gfollow/requirements.txt

# 2) 装服务
cp /opt/g2gfollow/systemd/g2gfollow.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now g2gfollow
systemctl status g2gfollow --no-pager

# 3) 自验
curl -s http://127.0.0.1:8903/api/health
```

nginx 的 `location /g2g/` 属于**共享配置**（吴律主导），改动需先出方案确认；
本仓库只保存建议块（见交付说明），不在本仓库直接改 nginx。

---

## 日常使用

1. 打开 `http://47.85.224.112/g2g/`（走统一登录门户）。
2. 点 **① 采集并生成建议单** → 等 1~3 分钟（DD373 逐区回溯订单簿）。
3. 看建议单：`区服组 | 服务区 | 阵营 | 当前G2G价 | DD373成本 | 可买量 | 够1亿 | 目标价 | 差额 | 动作`。
4. 勾选要放行的行（或「批量放行『需变价』」）。
5. **② 预览工单（dry-run）** 复核一遍 → **③ 执行真实写入**（会二次确认）。
6. 「写入流水」里核对「读回」列是否等于新价、校验是否通过。

## 排障

- **token 不可用** → 看本机保活器是否在跑；没跑就重启它，等它把 `var/token.json` 推上来。
- **采集很慢 / 超时** → DD373 单区回溯可能吃掉几十秒，属正常；超时上限 900s。
- **改价返回 4002 unit_price not a valid number** → 价格必须是字符串（本系统已按 `"%.2f"` 发送）。
- **想看服务日志** → `tail -f /opt/g2gfollow/logs/service.log`。
