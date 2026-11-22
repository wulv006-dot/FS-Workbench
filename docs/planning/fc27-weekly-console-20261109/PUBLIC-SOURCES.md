# FC27 公开资料补抓

点击「按当前规则取品并生成草稿」和每周定时更新时，Hermes 先用既有 Search/Fetch 取数。资料覆盖不足时，自动用 Scrapling 读取 EA FC27 新闻索引、链接到的 Ultimate Team 官方新闻原文，以及已发现的 FUTBIN、FUT.GG FC27 卡片原文。不需要填写链接或单独触发。对应卡片的公开指标只有在卡片页的姓名、评分和版本均对应后台商品时才用于选卡。

沿原草稿编号读取回执的 `evidence_coverage.scrapling`，可查原文 URL、请求和抓取时间、HTTP 状态及字段出处。来源限制或无对应字段时，保留现场结果。改价复盘按需调用的公开页面证据仅供展示价旁证，包含平台、USD 金额最小单位及到期时间，不进入现有采集和写价链路。活动页的展示价格证据取自现役公开配置的发布编号和有效参考字段。

入口由 FC Hermes 的 `fs-business-range.service` 承载。隔离工作进程使用 `/opt/fs-hermes-fc-public-research-0.5.1/bin/python3.12` 和固定 Scrapling 0.5.1。Python 3.12.16 用 Astral python-build-standalone 20261110 x86_64 GNU install_only 官方资产，SHA256 为 `c2f87d4b4e8db3abddb0f116c6ccfc503d0cbdbb9ee8faacddad1b679ec12e99`。在独立解释器下用 `python -m pip install --only-binary=:all: --require-hashes -r scrapling-requirements.lock` 安装校验过的依赖。HTTP Fetcher 直接读取公开 URL，保持 TLS 校验、无 Cookie、无跳转、无自动重试。已有周更采集、定时任务和写价链路照常运行。
