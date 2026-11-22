# FC27 公开资料补抓

在「FC27 活动页周更运营台 → 本周活动 → 公开资料补抓」选择用途，每次输入最多四条公开链接。允许 EA FC27 新闻原文、FUTBIN 或 FUT.GG 的 FC27 卡片页、Weekly Scout、SBC Companions 和 Player Trio。每个回执保留原操作编号、原文 URL、请求和抓取时间、HTTP 状态、结构化字段及选择器或 JSON 路径。超时请读取原编号，避免重复发起。

改价复盘选「展示价旁证」。公开参考报价保留平台、USD 金额的最小单位及到期时间。活动 HTML 的初始模板可能保留旧报价，活动页证据以现役公开配置的发布编号和有效参考字段为准。缺报价和被来源拒绝的请求分别记录，证据不能成为自动写价输入。

入口由 FC Hermes 的 `fs-business-range.service` 承载。隔离工作进程使用 `/opt/fs-hermes-fc-public-research-0.5.1/bin/python3.12` 和固定 Scrapling 0.5.1。Python 3.12.16 用 Astral python-build-standalone 20261110 x86_64 GNU install_only 官方资产，SHA256 为 `c2f87d4b4e8db3abddb0f116c6ccfc503d0cbdbb9ee8faacddad1b679ec12e99`。在独立解释器下用 `python -m pip install --only-binary=:all: --require-hashes -r scrapling-requirements.lock` 安装校验过的依赖。HTTP Fetcher 直接读取公开 URL，保持 TLS 校验、无 Cookie、无跳转、无自动重试。已有周更采集、定时任务和写价链路照常运行。
