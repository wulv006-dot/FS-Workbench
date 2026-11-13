# SBC / Packs：实际 100K 档位取价

维护目标 `/opt/fc27-sbc-tool/pricing.py`，沿原 `fc27-sbc-tool.service` 与 publisher 发布。维护源从已有本机 `E:/WorkBuddy/大超服务器/sports_cf_worker_20261017/source/opt/fc27-sbc-tool/pricing.py` 取得；2026-11-13 主机只读哈希确认与现役完全一致：`22d8d80084f61e353cf83ecaaefcd544773dbc1a9af8c7290fc312fd37340e3e`。没有导出先前被拒绝的完整 SBC 源码。

Admin 仍使用调用者已有 client，通过 GET 读取主站 266 对应平台 Coins 的完整商品行。购买 100K 档实际售价 / 100 得到 USD/K，/100000 得到 USD/枚；不取顶层兼容单位价，不混入大段赠币或优惠。公开站解析也取实际 100K 档。商品加成、固定费、人工覆盖、自动调度均保持。

复用 `fc27_cloud_browser/fc_purchase_rate.py`，发布时须先落到 `/opt/fc27-cloud-browser/fc_purchase_rate.py`，并与 Evolutions、捆绑包依赖一起核对。旧标量缓存没有本轮 `rate_basis`，不当作新档位缓存使用；文件保留，首次刷新生成新口径。平台读数缺失不替换为旧 Order 价。

验证：本地回归先复现 100K 实际价 8.62、旧顶层单位价算出 7.00 的差异；4 项针对测试通过。183 Python 3.11.2 隔离测试包含共享读取 3、Evolutions 40、本模块 4、捆绑包 43，共 90 项通过，无生产请求或端口。正式 CI、部署与真实入口验收尚待完成。
