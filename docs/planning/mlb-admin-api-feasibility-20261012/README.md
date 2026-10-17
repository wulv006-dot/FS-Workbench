# MLB 新卡上架「后台直连」可行性研究（2026-10-12）

> 起因：老大问「数据都获取好了，怎么写入？执行器怎么不给我写入？后台也没看到对应的产品模型生成」。
> 结论先行：**执行器写入 Excel 已成功**（`/opt/mlb-online/files/20261012_091006_*.xlsm`，
> `added=4`）。缺的是「xlsm → 后台商品模型」这一段。本报告研究该段能否自动化，
> **结论：技术上可行，且项目里已有一套现成的、经过生产验证的后台接口客户端可复用。**

---

## 一、现状链路（缺口定位）

```
[本机] showdd 采集 → 三轮比价 → 算价 → 写 Excel → 回传服务器
                                                     ↓
                                          【网页「下载商品导入表」】  ← 到此为止
                                                     ↓
                              【人工】mmoexp 后台 → 商品导入 → 上传 xlsm → 生成产品
                                                     ↑
                                            ★ 缺的就是这一段
```

**关键澄清**：网页上的「准备写入」是**状态标签**（HTML 里是 `<span class="pill">`，无 onclick），
不是按钮。执行器的合同就是「只读抓取 + 写本地 Excel」，
服务器侧只做排队与文件暂存 —— **它本来就不负责写后台**。

---

## 二、核心发现：项目内已有可复用的后台接口客户端

`fc27_players_cloud/球员维护工具/admin_client.py`（33 KB，2026-09-28）
**已经把 `admin.p2pah.cn` 的登录与商品模型接口全部逆向出来并跑在生产上**。
这与「MLB 商品导入」是**同一个后台、同一套接口族**（`goods.GoodsMould`）。

### 2.1 后端基本信息

| 项 | 值 |
|---|---|
| JSON API 基址 | `https://admin-api.p2pah.cn` |
| 页面基址 | `https://admin.p2pah.cn` |
| 鉴权 | `Authorization` **Bearer token**（非 Cookie），登录返回 `data.userInfo.token` |
| token 保管 | **仅进程内存**，不落盘、不写日志（源码强制） |
| 刷新 | `POST /api/common/refreshToken`，**不自动重试** |

### 2.2 已核实的接口清单（源码 `_ALLOWED` 白名单，逐条静态证据）

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/admin/index/login` | 取登录配置（含 `data.captcha`） |
| GET | `/api/common/captcha?server=1&id=<captcha_id>` | 取图形验证码（PNG） |
| POST | `/admin/index/login` | 登录（`username/password/captcha/captcha_id/keep`） |
| POST | `/api/common/refreshToken` | 刷新 token |
| GET | `/admin/goods.GoodsMould/index` | **模型列表**（分页 `page/limit/search`） |
| GET | `/admin/goods.GoodsMould/edit` | **模型详情** |
| GET | `/admin/goods.GoodsMould/importPlayersProgress` | **导入进度查询** |
| POST | `/admin/goods.GoodsMould/importPlayers` | **★ 批量导入（multipart，字段 `xlsFile`）** |
| POST | `/admin/goods.GoodsMould/singleEdit` | 单条编辑（模型/产品） |
| POST | `/admin/goods.GoodsMould/edit` | 模型字段编辑（`more/status/auto_off/tid`） |
| GET | `/admin/goods.Goods/edit` | 产品详情 |
| POST | `/admin/goods.Goods/edit` | 产品编辑（当前仅开放 `total` 库存） |
| GET | `/admin/goods.GoodsTag/tagSelect` | 标签下拉 |
| POST | `/admin/goods.GoodsMould/recalcFc27Price` | 触发价格重算（仅 FC27） |

**注意**：未知路径在**本地就被拒绝**（`_ALLOWED` 白名单 fail-closed），这是很好的安全设计。

### 2.3 导入接口的确切形态（可直接照搬）

```python
def upload_players(self, path, *, gid, cid):
    _check_scope(gid, cid)                     # 当前硬编码只允许 1327/9627
    content = Path(path).read_bytes()
    body, content_type = _multipart_body(
        {"gid": gid, "cid": cid},              # 表单字段
        "xlsFile", source.name, content)       # 文件字段名 = xlsFile
    return self._request_json("POST",
        "/admin/goods.GoodsMould/importPlayers",
        body=body, content_type=content_type)
```

- **文件字段名固定 `xlsFile`**，另带 `gid` / `cid` 两个表单字段
- 返回里含 job 标识 → 用 `importPlayersProgress` 轮询进度

---

## 三、"产品模型生成"的实际发生位置

老大问的「后台也没看到对应的产品模型生成」——**答案就藏在导入接口的名字里**：

- 端点 `/admin/goods.GoodsMould/importPlayers` → **GoodsMould = 商品模型**
- 导入完成后，后台**自动**按模板行生成模型 + 产品（多平台）
- 查询进度接口 `importPlayersProgress` 印证：导入是**异步任务**，不是同步完成

⇒ **产品模型是导入的产物，不是单独一步。** 只要导入成功，模型自然出现。
现在「没看到」纯粹因为**还没执行导入**。

---

## 四、MLB 接进来需要解决的三件事

### ① 确认 MLB 的 `gid` / `cid`（当前唯一硬缺口）

- 现成客户端 `SUPPORTED_GID=1327 / SUPPORTED_CID=9627` 是 **FC27 Players** 的
- MLB 在 xlsm 里只体现 `分类ID=8233`（第 16 列），**这是产品分类 ID，不等于模型的 gid/cid**
- ⇒ 必须先取得 MLB 在后台的 **模型 gid + cid**（可登录后台，看 GoodsMould 列表页 URL 参数）

### ② 放开 scope 校验

`_check_scope()` 硬编码拒绝非 1327/9627。需参数化为按业务传入
（**切勿直接改成"任意值"** —— 保持显式白名单，只增加 MLB 一组）。

### ③ 登录方式差异

| | order.p2pah.cn（D4 用） | admin.p2pah.cn（球员/MLB 用） |
|---|---|---|
| 鉴权 | Cookie（`PHPSESSID`+`user`+`admin_username`） | Bearer token |
| 验证码 | `/new_captcha.html?...` 图形码 | `/api/common/captcha` 图形码 |
| 登录 | `POST /admin/public/dologin.html`（form） | `POST /admin/index/login`（JSON） |
| 会话 | 可落盘复用（`session.json`） | **仅内存，不落盘** ⇒ 每次要重新登录 |

⇒ MLB 若走 admin-api，**每次都需过图形验证码**。
两条缓解路径：
- **a. 人工过码一次**（推荐起步）：弹验证码图 → 人工输入 → 建会话 → 后续同进程复用
- **b. 验证码识别**：项目里已验证 `ddddocr` 可用（统一看板 p2pah 采集用它自动过码）
  ⇒ 可复用同一套 OCR，做成全自动

---

## 五、推荐实施方案（分三步走，风险递增）

### 阶段 0：先跑通「人工点一次」（当天可完成，零风险）

不改任何现有代码。写一个**独立命令行脚本**：

```
1. 取 captcha → 存 PNG 到本地 → 人工看图输入
2. 登录 → 拿 token（只在内存）
3. 上传 20261012_091006_*.xlsm → gid=MLB_gid, cid=MLB_cid
4. 轮询 importPlayersProgress 直到完成
5. 打印逐项结果（成功/已存在/字段错误）
```

**验收**：后台出现 4 个新模型，与 xlsm 4 行一一对应。
**权限**：只需现有后台账号，**不新增任何写入权限**。

### 阶段 1：把 xlsm 回传链路接到导入（半自动）

在 MLB 执行器（`mlb_agent.py`）跑完写 Excel 后，**不直接写后台**，
而是新增一个「**提交导入**」动作，由**人工在网页点确认**后才调用阶段 0 的脚本。
好处：保留人工闸门，符合项目「写入必须走明确授权」的既有纪律。

### 阶段 2：全自动（需单独授权）

- 采集 → 写 Excel → 自动导入 → 轮询 → 回读后台模型价格 → 比对
- 前提：`ddddocr` 自动过码稳定 + **幂等键**（防重复导入）+ **未知结果不自动重试**

⚠️ **阶段 2 属生产写入，按项目铁律必须单独授权 + 测试环境验收后再切**，
不能因为「技术上可行」就直接开。

---

## 六、风险与红线（必读）

| 风险 | 说明 | 对策 |
|---|---|---|
| **重复导入** | 同一 xlsm 传两次可能生成重复模型 | 幂等键 + 先查 `importPlayersProgress` / 模型列表去重 |
| **未知结果重试** | 请求超时后状态不明，重试可能双写 | **未知一律不自动重试**，转人工核对（项目铁律） |
| **token 泄露** | 后台 token 权限大 | 仅内存、不落盘、不写日志（现成客户端已如此实现） |
| **scope 扩大** | 误改 FC27 或全站商品 | 保持显式白名单，MLB 单独一组，绝不改成通配 |
| **图形验证码** | 自动 OCR 有失败率 | 失败转人工，不硬重试（防盗号锁定） |
| **生产写入** | 影响线上在售商品 | 写入前必须 `dry-run` + 人工预览确认 |

---

## 七、给老大的决策点

1. **是否要我做阶段 0 的脚本？**（只读登录 + 一次人工确认的导入，零风险）
2. **MLB 的 gid/cid 从哪拿？** 需要您登录后台看一眼 GoodsMould 列表页的 URL 参数，
   或我写个只读脚本去列出来（同样是登录一次、人工过码）
3. **要不要一路做到全自动（阶段 2）？** 这需要单独授权，且要先有测试环境验收

---

## 八、复用清单（给实现者）

| 直接复用 | 位置 |
|---|---|
| 后台客户端（登录/列表/导入/进度） | `fc27_players_cloud/球员维护工具/admin_client.py` |
| multipart 构造 | 同文件 `_multipart_body()` |
| token 安全边界范式 | 同文件类文档字符串 |
| OCR 过码 | 统一看板 p2pah 采集的 `ddddocr` 用法 |
| 幂等/不重试纪律 | 项目 `AGENTS.md` + `core_p2pah.py` 安全边界注释 |
| MLB Excel 生成 | `共享资源/MLB新卡上架/client/mlb_agent.py` `write_output()` |

---

## 九、证据索引

| 证据 | 位置 |
|---|---|
| 今早任务结果（added=4） | 服务器 `mlb.db` `tasks.id=6a00fe7dd5f6` |
| 成品 xlsm | `/opt/mlb-online/files/20261012_091006_mould-create_gid927_20261005102322.xlsm` |
| 后台接口白名单 | `fc27_players_cloud/球员维护工具/admin_client.py` L246-271 |
| 导入实现 | 同文件 `upload_players()` L554 |
| 登录协议 | 同文件 `login()` L362 |
| scope 硬限制 | 同文件 `_check_scope()` L762 |
| order.p2pah 客户端（对照） | `d4_final_guard_review_20261006/candidate/opt/d4follow/core_p2pah.py` |
| 后台 API 需求文档 | `服务器统一后台API能力需求_给运维_20260928.md` §五、§十 |
