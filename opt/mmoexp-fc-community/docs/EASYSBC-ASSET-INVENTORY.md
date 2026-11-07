# EasySBC 公开素材采集 — 2026-11-08

已用 REA 在独立临时 Chrome 中打开 https://www.easysbc.io/，等待 3 秒并记录公开页面网络资源；未使用登录态、未接触 Discord 标签页。采集到 **27 个素材文件：17 个原始图片/SVG + 10 个 Lucide SVG**，全部下载成功。此批素材尚未部署到生产。

素材目录：`../assets/easysbc-reference-20261108/`。`manifest.json` 包含每个素材的来源 URL、观察方式、尺寸、SHA-256、格式和许可状态；`collect_assets.py` 是有界下载与非执行式 SVG 提取脚本。

## 优先用于报价卡的候选

| 用途 | 文件 | 尺寸 | 说明 |
|---|---|---|---|
| SBC 彩色徽章 | images/sbc-purple.png / sbc.png | 463×483 | 已目视确认与用户提供的紫色三人徽章一致；两条资源路径保留原样 |
| 金币 | images/coin.png | 46×46 | 实际首页加载，用于小型价格标签 |
| 金币大图 | images/coin-large.png | 826×826 | 适合卡片缩略图 |
| OBJ | images/objective.png | 286×286 | 实际首页加载 |
| OBJ 小图 | images/objective-ea.png | 56×56 | 前端代码明确引用 |
| Packs | images/pack-tradable.png / pack-4.png | 291×423 / 252×366 | 通用可交易包外观 / FC27 包 ID 4；不要把特定包图当所有商品图 |
| SBC 套装 | images/sbc-set-108.png | 420×460 | 当前首页出现的 FC27 set 108；只对应实际套装，不是通用分类图 |
| 比赛要求 | images/ball.png | 56×56 | 进化卡比赛条件所用足球图 |
| 时钟 | lucide/Clock.svg | 24×24 viewBox | 与网站相同 Lucide 系列，可按品牌色渲染 |
| 进化 | lucide/Dna.svg | 24×24 viewBox | 网站导航 Evolutions 使用该形状 |
| 收藏馆 | lucide/GalleryVerticalEnd.svg、Images.svg | 24×24 viewBox | 网站 Gallery / Gallery planner 导航形状 |
| SBC 简洁图 | lucide/Puzzle.svg | 24×24 viewBox | 网站 SBC 导航形状 |
| 其他通用交互 | lucide/Target.svg、Gamepad2.svg、Newspaper.svg、Search.svg、ExternalLink.svg | 24×24 viewBox | 可用于目标/平台泛称/新闻/搜索/跳转；未证明全部出现在 Discord 小组件 |

其他原始资源包括赛季点数、FC Points、玩家选择包、默认 SBC、足球场 SVG、活动代币，见 manifest。

## 许可与实际可用范围

- **10 个 Lucide SVG**：公开前端相邻注释明确标记 `lucide-react v0.454.0 - ISC`。已保存上游版本许可证 `LUCIDE-LICENSE`，来源 https://raw.githubusercontent.com/lucide-icons/lucide/0.454.0/LICENSE 。这些是可复用的通用图标，分发时保留版权及许可通知。
- **17 个 EA/EasySBC 原始素材**：公开可下载，但此调查没有建立其开源/商业复用许可。manifest 明确标记 `production_ready: false`，素材保留用于研究；不要把网站可访问误报为可自由商用。
- 没有采集 EasySBC 品牌 Logo 作为 MMOEXP 标识。
- **PS / Xbox / PC 专用标识暂未确认独立图片地址**。首页运行网络未观察到；bundle 有平台文案，但有限搜索未确定对应 SVG 组件。不得猜 URL 或用 Gamepad2 声称是某平台商标。现有平台文字/Unicode 可继续使用，下一轮可在公开 SBC 详情页补充定位。
- 没有发现明确的独立 Gallery 彩色圆章或 Evo 彩色徽章图片；已找到网站确实使用的 Lucide 导航图形。
- 本次没有验证网站资源与 EasySBC Discord APP 卡片的所有素材完全一致，也没有采集整个球员数据库。

## 接入建议

1. 先将许可明确的 Lucide 时钟、DNA、Gallery、Puzzle、搜索/跳转图标渲染为透明 PNG，再上传为 MMOEXP 应用 emoji。Discord 按钮 emoji 不能直接塞任意 SVG URL。
2. 公共 Embed 缩略图可使用已有品牌头像；报价正文平台、时间、类别使用小 emoji。不要把整张品牌横幅重复放进每个私密报价。
3. 需要商品图片时优先使用 MMOEXP 自有商品图。EA/EasySBC 特定素材保持独立研究目录，确认来源授权后再选用。
4. 下载的 SVG 均保持原始或只重建字面量路径；本次未生成位图、未改机器人配置。

## 证据和边界

- REA evidence: `ev_73fce2447dddebcceb4967486222d7cb8a29b737fea3cb05b210e876fa5594cc`
- 保存在 `rea-evidence.json`；426 条网络事件，无 dropped，浏览器 cleanup 为 `terminated-owned-process`。
- 前端来源 `https://www.easysbc.io/assets/index-Dhfro0H2.js`，原文件保存在 source/。未执行下载代码；只读取 URL/导航映射和字面量 Lucide 图形数组。
- 运行观察是首页一次有界访问；bundle 中出现不等于所有组件已运行。远程当前包名和素材会变动。
- 当前连接工具目录没有 `reset_investigation`，因此无法调用该结束动作；证据已导出，独立浏览器已由 REA 终止，不影响用户浏览器。
