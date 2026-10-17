# 游戏价格抓取 · Web 版（无账号 · 全局队列 · 三站）

把竞品价格抓取做成网页：**不用注册、不用登录**，打开就能用。
所有人共享同一条任务队列，谁提的、抓哪个站哪个游戏、进度到哪，一屏全看得见。

支持三个竞品站，按域名自动识别：

| 站点 | 域名 | 抓取方式 |
|---|---|---|
| IGGM | iggm.com | 隐藏 JSON API（items/golds/boosting 三模板） |
| AOEAH | aoeah.com | POST /api/goods（Items/Gold/CarryRun/Boosting 四品类） |
| U4GM | u4gm.com | HTML 列表分页 + 金币档位离线复算 + boosting 子页基准价 |

三站均为**纯 urllib 抓取，无需浏览器**，服务器不需要装 Playwright/Chrome。

## 核心规则

| 规则 | 说明 |
|---|---|
| 免登录 | 打开网页直接能用，没有账号体系 |
| 全局队列 | 所有人提交的任务排成一条队，**同一时间只跑一个**，避免请求过密被目标站限流 |
| 任务卡片 | 每个任务显示：站点徽章、游戏名、品类数、提交人、提交时间、实时进度 |
| 独立下载 | 每个任务的 CSV 单独下载，文件名 `{站点}_{游戏}_{时间戳}_{任务ID}.csv` |
| 提交人可选 | 顶栏填不填都行，只是个备注，存浏览器本地，不注册不校验 |
| 谁都能停 | 队列是共享的，任何人都能停止/取消任意任务（带二次确认） |

## 目录结构

```
iggm-web/
  app.py           Flask 入口：页面、API、下载、可选访问口令
  sites.py         站点路由：按域名分发到三个抓取器
  core.py          IGGM 抓取核心（桌面版原样复制）
  core_aoeah.py    AOEAH 抓取核心（POST /api/goods）
  core_u4gm.py     U4GM 抓取核心（列表/金币/boosting 形态自动识别）
  db.py            SQLite：任务表（单表，无用户表）
  runner.py        任务队列（单 worker 串行）+ 进度/取消回调
  requirements.txt flask + gunicorn
  templates/       index.html（主界面） / gate.html（口令页，仅开启口令时用到）
  static/          style.css / app.js
  deploy/
    setup.sh       一键部署（Ubuntu）
  本地预览.bat      Windows 本机双击预览
  .env             部署脚本自动生成（SECRET / 数据目录 / 端口）
```

## 服务器上部署

```bash
# 1. 本机打包上传（Windows 用 scp 或任意 SFTP 工具）
scp -r iggm-web root@<服务器IP>:/opt/

# 2. 登录服务器执行
ssh root@<服务器IP>
bash /opt/iggm-web/deploy/setup.sh

# 3. 浏览器打开 http://<服务器IP>/
```

部署前先测连通性（决定方案是否成立，建议选美国/香港机房）：
```bash
for u in https://www.iggm.com/arc-raiders/coins \
         https://www.aoeah.com/arc-raiders-coins \
         https://www.u4gm.com/arc-raiders/coins; do
  curl -o /dev/null -s -w "$u  HTTP:%{http_code}  耗时:%{time_total}s\n" "$u"
done
```
期望三个都是 `HTTP:200`、耗时 3 秒内。阿里云安全组需放行 TCP 80。

## 可选：一次性访问口令

默认完全开放。想挡住公网扫描，在 `.env` 里加一行：

```bash
echo 'IGGM_ACCESS_CODE=你们团队的口令' >> /opt/iggm-web/.env
systemctl restart iggm-web
```

生效后打开网页要输一次口令，记住 **30 天**（cookie）。
更彻底的做法是阿里云安全组只放行团队 IP，连口令都不用输。

## CSV 字段（三站统一）

| 列 | 说明 |
|---|---|
| site | IGGM / AOEAH / U4GM |
| page_type | items / golds / boosting / Gold / CarryRun 等（各站原始品类名） |
| platform | PC / PS / XBOX 等 |
| category | 档位名或分类路径首段 |
| title | 商品名 / 档位标题 |
| quantity | 数量（金币为档位值） |
| unit | 单位（K / M 等） |
| unit_price | 单价 |
| total_price | 总价（美元）。导出时统一清洗为纯数字并固定 3 位小数（去掉 `'`、`$`、千分位逗号，消除浮点精度尾巴）；小数位可在 `runner.py` 的 `PRICE_DECIMALS` 调整 |
| sales | 销量（IGGM items 有，其余站多数为空） |
| goods_no | 站点内部商品 ID |
| image / updated / source_url | 图片 / 更新时间 / 来源页 |

## 环境变量（写在 .env）

| 变量 | 默认 | 说明 |
|---|---|---|
| `IGGM_ACCESS_CODE` | 空 = 不启用 | 团队访问口令，设置后开启一次登录（记住 30 天） |
| `IGGM_SECRET` | 部署时随机生成 | Flask 内部密钥 |
| `IGGM_DATA` | `/opt/iggm-web/data` | SQLite 库位置 |
| `IGGM_EXPORTS` | `$IGGM_DATA/exports` | CSV 导出目录 |
| `IGGM_PORT` | `8787` | 本地监听端口，nginx 反代到此 |

## 关键约束

- **gunicorn 必须 `-w 1`**：任务队列在进程内存里，多进程会让队列分裂、看不到运行中的任务
- **`--timeout 600`**：解析品类在站点慢时要重试多次，单请求可能接近 100 秒
- 服务重启时，上次遗留的 queued/running 任务会被标记为「服务重启，任务中断」，不会永久卡在队列里
- AOEAH 服务器偶发 chunked 断流（SSL record layer failure），抓取器已内置 4 次重试

## 常用运维命令

```bash
systemctl status  iggm-web
systemctl restart iggm-web
journalctl -u iggm-web -f          # 实时日志
ls -lh /opt/iggm-web/data/exports  # 导出文件
```

## 从旧版升级

数据库自动迁移：旧的 `username` 列搬到 `submitter`，新增 `site` 列（老任务 site 为空，前端显示「?」徽章，不影响使用）。
代码更新后重跑 `bash deploy/setup.sh` 即可。
