# FS 平台 · 白名单外来源观察报告

生成时间：2026-10-17 13:00:40

> 观察模式（observe-only）下，本报告统计**所有白名单外来源**的访问，
> 不区分是否曾被拦截。目的是找出「被漏掉的友军脚本」与「真实扫描器」。

## 一、总览（37 个来源）

| 判定 | 来源数 | 请求数 |
|---|---|---|
| 疑似友军 | 4 | 4 |
| 探测(待观察) | 6 | 7 |
| 未知 | 1 | 16 |
| 扫描器 | 26 | 248 |

## 二、按来源明细

| # | IP | 归属（国家 · AS） | 次数 | 首见 → 末见 | 请求路径(样本) | UA类型 | 判定 | 建议 |
|---|---|---|---|---|---|---|---|---|
| 1 | `5.226.140.91` | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | /mcp/ | 浏览器 | **疑似友军** | → 核实后加白 |
| 2 | `188.240.59.59` | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | /api/mcp | 浏览器 | **疑似友军** | → 核实后加白 |
| 3 | `81.19.219.232` | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | /mcp | 浏览器 | **疑似友军** | → 核实后加白 |
| 4 | `89.37.172.157` | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | /sse | 浏览器 | **疑似友军** | → 核实后加白 |
| 5 | `170.231.237.214` | Switzerland · GRUPO PANAGLOBAL 15 S.A | 2 | 10-17 03:54 → 10-17 04:20 | /robots.txt | 其他UA | **探测(待观察)** | 继续观察 |
| 6 | `69.5.169.150` | Germany · Hydra Communications Ltd | 1 | 10-17 06:55 → 10-17 06:55 | / | 浏览器 | **探测(待观察)** | 继续观察 |
| 7 | `185.216.145.180` | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | / | 浏览器 | **探测(待观察)** | 继续观察 |
| 8 | `5.226.140.114` | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | /favicon.ico | 浏览器 | **探测(待观察)** | 继续观察 |
| 9 | `81.19.219.237` | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | / | 浏览器 | **探测(待观察)** | 继续观察 |
| 10 | `170.231.236.98` | Switzerland · GRUPO PANAGLOBAL 15 S.A | 1 | 10-17 09:36 → 10-17 09:36 | /robots.txt | 其他UA | **探测(待观察)** | 继续观察 |
| 11 | `172.18.108.183` | ? | 16 | 10-17 07:29 → 10-17 11:55 | /<br>/favicon.ico<br>/mcp/ | 浏览器 | **未知** | 人工判断 |
| 12 | `160.250.132.238` | Vietnam · EZ TECHNOLOGY COMPANY LIMITED · proxy · 机房 | 49 | 10-17 09:57 → 10-17 09:58 | /cgi-bin/.%2e/.%2e/.%2e/.%2e/.%2e/.%2e/.%2e/.%2e/.%2e/.%2e/bin/sh<br>/cgi-bin/%%32%65%%32%65/%%32%65%%32%65/%%32%65%%32%65/%%32%65%%32%65/%%32%65%%32%65/%%32%65%%32%65/%%32%65%%32%65/bin/sh<br>/hello.world?%ADd+allow_url_include%3d1+%ADd+auto_prepend_file%3dphp://input | 其他UA | **扫描器** | 无需处理 |
| 13 | `50.116.58.253` | United States · Akamai Connected Cloud · 机房 | 48 | 10-17 05:38 → 10-17 05:41 | /<br>/index.php/catalogsearch/advanced/result/?name=e<br>/en/products?query=123 | 浏览器 | **扫描器** | 无需处理 |
| 14 | `186.182.105.49` | Paraguay · Techtel LMDS Comunicaciones In | 47 | 10-17 08:50 → 10-17 08:50 | /hello.world?%ADd+allow_url_include%3d1+%ADd+auto_prepend_file%3dphp://input<br>/?%ADd+allow_url_include%3d1+%ADd+auto_prepend_file%3dphp://input<br>/index.php?%25ADd+allow_url_include%3D1+%25ADd+auto_prepend_file%3Dphp://input | 其他UA | **扫描器** | 无需处理 |
| 15 | `50.221.56.52` | United States · Comcast Cable Communications,  | 19 | 10-17 04:21 → 10-17 04:21 | /hello.world?%ADd+allow_url_include%3d1+%ADd+auto_prepend_file%3dphp://input<br>/?%ADd+allow_url_include%3d1+%ADd+auto_prepend_file%3dphp://input<br>/index.php?%25ADd+allow_url_include%3D1+%25ADd+auto_prepend_file%3Dphp://input | 其他UA | **扫描器** | 无需处理 |
| 16 | `185.73.23.161` | Germany · Ruhr-Universitaet Bochum | 17 | 10-17 03:23 → 10-17 12:56 | / | 扫描器UA | **扫描器** | 无需处理 |
| 17 | `213.209.159.175` | Germany · Feo Prest SRL | 11 | 10-17 06:30 → 10-17 06:30 | /site.zip<br>/<br>/ts218j0ertyuw1 | 浏览器 | **扫描器** | 无需处理 |
| 18 | `78.153.140.147` | United Kingdom · HOSTGLOBAL.PLUS LTD · 机房 | 10 | 10-17 03:15 → 10-17 08:43 | /.env<br>/ | 浏览器 | **扫描器** | 无需处理 |
| 19 | `185.73.23.162` | Germany · Ruhr-Universitaet Bochum | 10 | 10-17 08:55 → 10-17 12:21 | / | 扫描器UA | **扫描器** | 无需处理 |
| 20 | `185.191.236.38` | Switzerland · GRUPO PANAGLOBAL 15 S.A | 7 | 10-17 03:54 → 10-17 09:36 | /<br>/.well-known/security.txt<br>/dashboard/ | 浏览器 | **扫描器** | 无需处理 |
| 21 | `78.153.140.93` | United Kingdom · HOSTGLOBAL.PLUS LTD · 机房 | 6 | 10-17 08:28 → 10-17 12:21 | /.env<br>/ | 浏览器 | **扫描器** | 无需处理 |
| 22 | `78.153.140.251` | United Kingdom · HOSTGLOBAL.PLUS LTD · 机房 | 4 | 10-17 04:56 → 10-17 08:12 | /.env<br>/ | 浏览器 | **扫描器** | 无需处理 |
| 23 | `5.61.209.106` | The Netherlands · Amarutu Technology Ltd | 4 | 10-17 07:35 → 10-17 12:34 | /SDK/webLanguage | 浏览器 | **扫描器** | 无需处理 |
| 24 | `78.153.140.250` | United Kingdom · HOSTGLOBAL.PLUS LTD · 机房 | 2 | 10-17 09:19 → 10-17 09:19 | /.env<br>/ | 浏览器 | **扫描器** | 无需处理 |
| 25 | `66.132.186.185` | United States · Censys, Inc. · 机房 | 2 | 10-17 12:03 → 10-17 12:04 | /<br>/wiki | 扫描器UA | **扫描器** | 无需处理 |
| 26 | `205.210.31.31` | United States · Google LLC · 机房 | 1 | 10-17 04:44 → 10-17 04:44 | / | 扫描器UA | **扫描器** | 无需处理 |
| 27 | `147.185.133.66` | United States · Google LLC · 机房 | 1 | 10-17 05:03 → 10-17 05:03 | / | 扫描器UA | **扫描器** | 无需处理 |
| 28 | `188.166.68.252` | The Netherlands · DigitalOcean, LLC · 机房 | 1 | 10-17 06:25 → 10-17 06:25 | / | 扫描器UA | **扫描器** | 无需处理 |
| 29 | `40.124.123.165` | United States · Microsoft Corporation · 机房 | 1 | 10-17 07:27 → 10-17 07:27 | / | 扫描器UA | **扫描器** | 无需处理 |
| 30 | `52.186.171.170` | United States · Microsoft Corporation · 机房 | 1 | 10-17 08:39 → 10-17 08:39 | / | 扫描器UA | **扫描器** | 无需处理 |
| 31 | `134.33.97.60` | United States · Microsoft Corporation · 机房 | 1 | 10-17 08:52 → 10-17 08:52 | /manager/html | 扫描器UA | **扫描器** | 无需处理 |
| 32 | `4.148.17.94` | United States · Microsoft Corporation · 机房 | 1 | 10-17 09:06 → 10-17 09:06 | /mcp | 扫描器UA | **扫描器** | 无需处理 |
| 33 | `205.210.31.131` | United States · Google LLC · 机房 | 1 | 10-17 10:19 → 10-17 10:19 | / | 扫描器UA | **扫描器** | 无需处理 |
| 34 | `4.150.200.23` | United States · Microsoft Corporation · 机房 | 1 | 10-17 11:21 → 10-17 11:21 | /owa/auth/logon.aspx | 扫描器UA | **扫描器** | 无需处理 |
| 35 | `20.55.101.61` | United States · Microsoft Corporation · 机房 | 1 | 10-17 11:39 → 10-17 11:39 | /developmentserver/metadatauploader | 扫描器UA | **扫描器** | 无需处理 |
| 36 | `92.118.39.86` | United States · UNMANAGED LTD · 机房 | 1 | 10-17 11:58 → 10-17 11:58 | /op/7_md/9/1/2/3/4 | 扫描器UA | **扫描器** | 无需处理 |
| 37 | `205.210.31.194` | United States · Google LLC · 机房 | 1 | 10-17 12:49 → 10-17 12:49 | / | 扫描器UA | **扫描器** | 无需处理 |

## 三、按 /24 网段聚合（脚本 IP 漂移视角）

| /24 网段 | 来源数 | 请求数 | 该段归属 | 判定 |
|---|---|---|---|---|
| 160.250.132.0/24 | 1 | 49 | Vietnam · EZ TECHNOLOGY COMPANY LIMITED · proxy · 机房 | 扫描器 |
| 50.116.58.0/24 | 1 | 48 | United States · Akamai Connected Cloud · 机房 | 扫描器 |
| 186.182.105.0/24 | 1 | 47 | Paraguay · Techtel LMDS Comunicaciones In | 扫描器 |
| 185.73.23.0/24 | 2 | 27 | Germany · Ruhr-Universitaet Bochum | 扫描器 |
| 78.153.140.0/24 | 4 | 22 | United Kingdom · HOSTGLOBAL.PLUS LTD · 机房 | 扫描器 |
| 50.221.56.0/24 | 1 | 19 | United States · Comcast Cable Communications,  | 扫描器 |
| 172.18.108.0/24 | 1 | 16 | ? | 未知 |
| 213.209.159.0/24 | 1 | 11 | Germany · Feo Prest SRL | 扫描器 |
| 185.191.236.0/24 | 1 | 7 | Switzerland · GRUPO PANAGLOBAL 15 S.A | 扫描器 |
| 5.61.209.0/24 | 1 | 4 | The Netherlands · Amarutu Technology Ltd | 扫描器 |
| 205.210.31.0/24 | 3 | 3 | United States · Google LLC · 机房 | 扫描器 |
| 170.231.237.0/24 | 1 | 2 | Switzerland · GRUPO PANAGLOBAL 15 S.A | 探测(待观察) |
| 5.226.140.0/24 | 2 | 2 | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 探测(待观察) |
| 81.19.219.0/24 | 2 | 2 | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 探测(待观察) |
| 66.132.186.0/24 | 1 | 2 | United States · Censys, Inc. · 机房 | 扫描器 |
| 147.185.133.0/24 | 1 | 1 | United States · Google LLC · 机房 | 扫描器 |
| 188.166.68.0/24 | 1 | 1 | The Netherlands · DigitalOcean, LLC · 机房 | 扫描器 |
| 69.5.169.0/24 | 1 | 1 | Germany · Hydra Communications Ltd | 探测(待观察) |
| 40.124.123.0/24 | 1 | 1 | United States · Microsoft Corporation · 机房 | 扫描器 |
| 52.186.171.0/24 | 1 | 1 | United States · Microsoft Corporation · 机房 | 扫描器 |
| 185.216.145.0/24 | 1 | 1 | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 探测(待观察) |
| 188.240.59.0/24 | 1 | 1 | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 疑似友军 |
| 89.37.172.0/24 | 1 | 1 | United Kingdom · Hydra Communications Ltd · proxy · 机房 | 疑似友军 |
| 134.33.97.0/24 | 1 | 1 | United States · Microsoft Corporation · 机房 | 扫描器 |
| 4.148.17.0/24 | 1 | 1 | United States · Microsoft Corporation · 机房 | 扫描器 |
| 170.231.236.0/24 | 1 | 1 | Switzerland · GRUPO PANAGLOBAL 15 S.A | 探测(待观察) |
| 4.150.200.0/24 | 1 | 1 | United States · Microsoft Corporation · 机房 | 扫描器 |
| 20.55.101.0/24 | 1 | 1 | United States · Microsoft Corporation · 机房 | 扫描器 |
| 92.118.39.0/24 | 1 | 1 | United States · UNMANAGED LTD · 机房 | 扫描器 |

---

**加白名单建议**：把上表判定为「疑似友军」的 IP 逐一核对归属（是否本公司出口），
确认后在 /etc/nginx/conf.d/fs-ip-allowlist.conf 对应区加一行 `<IP>/32  1;`。
