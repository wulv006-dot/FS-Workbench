# Admin ES D0–D3 发布交接

候选 `.agent_runtime/es-data-20261113-stage-v2` 绑定业务源码 `efeff5f95f94bde56cf7c721173475b4641cb1de`。`manifest.json` SHA-256 `3dc01f6e32c59b1c3c984b8221f23c0494000cf7d04738f681ccd6d0409a258c`，当前 `releaseReady=false`。24 个目标包括 14 个 range 模块、3 个 Hermes host 模块、6 个版本化静态资产及现有 Nginx formal 路由。18 个保护目标绑定现场哈希。业务写入和定时变更均为 false。

- range 与 Admin summary 基于当前线上源码三方合成，保留管理台游戏扩展、Hermes 对话及毛利连接、桌面 RPC、live orders 和订单邮件导出。`user_store.py` 仅移植本次读取需要的当前修订限期查询。现场缺历史修订索引，较旧修订的有界查询返回不可用，原历史重放调用保留。组合测试覆盖上海日期边界、历史不可用和数据库字节不变。
- D0 同批安装 host 的 `es_order_structure.py`、`order_attribution.py`，供 D2 的固定发布归档和标准化归因读取。现役范围服务沿用；退役会话 `fc27-p2pah-session.service`、镜像、定时和登录凭据均不在本清单内。整条 ES 收集自然周期与历史覆盖需各自证据。
- 三个经营入口沿现有 URL 切换各自 `business.js`，渠道页沿现有 HTML、JS 和 CSS URL 切换三个资产。版本 `admin-es-20261113-bf229232f385`。逐字节对照 formal 配置，只有六条 `alias` 替换，原鉴权、其他入口和业务 CSS 保留。
- 原 11 月 11 日 exact range adapter SHA-256 `683d5b4a6c52954383c998a98ad0963a361ca59a9983378f4d73b0fd4159c40a`。原冻结 writer `/opt/fs-release-stage/data-tools-query-fix-ui-20261018-v1/release_navigation_base.py` SHA-256 `5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357`。本清单通过原 publisher 的本地校验。原发布锁、目标与保护目标 CAS、Hermes 准入保护、备份、日志、`nginx -t`、range health 与回滚由该 writer 执行。

## 已验与待验

原 `pr_fast.units` 发布器回归 4/4。现场合成字节在 Windows 离线运行原 units 通过 30/30 和 58/58，日志 `.agent_runtime/es-data-20261113-composed-v2.log`。183 包 `es-data-20261113-composed-tests.tar.gz` SHA-256 `6958ebf11838b155a8c8b1f5f1299e24aa5cdefbf1945f688fc777ed984d1106`，对应 driver `es-data-20261113-composed-linux.py`，复制至同一测试专用目录并将包 SHA 作为 driver 参数。隔离容器使用已存在的 Python 3.9.18 镜像。真实 183 运行、正式 CI、生产 apply、服务及入口读回按主控记录更新。

## 串行发布

若独立 SEO 批次先修改同一 Nginx formal 配置，重取现场配置字节与 SHA 后写入新本地 capture 和 baseline，用 `prepare_es_data.py` 在全新输出目录重建，核对只改变六条别名。必要的生产发布清单在主控确认条件后用该 builder 的 `--release-ready` 生成，以新清单 SHA 为准。使用原 `es_data_release.py` 的 `inspect` 检查目标与保护 CAS，再沿同一清单 SHA 和 `nav-YYYYMMDDTHHMMSSZ` 原 ID 执行授权发布。结果未知时查原日志和回执。回滚使用该回执的原备份目录与原清单 SHA。

入口验收使用现有授权身份读回 Nginx 资产与 range health，检查经营三个入口同期间及细分复购范围、渠道聚合与当前结果 CSV、FC 详情快照导出，并确认既有 Hermes 和订单入口仍可读。用已付款 Admin 与固定归因修订分别核实来源，缺少成本、归因、复购覆盖时仍保留未知。应另保留无权限响应与版本对应证据。

## 183 与现场发布前核验

183 对上述固定测试包通过 30/30 与 58/58，零失败、错误、跳过，日志 `.agent_runtime/es-data-20261113-composed-linux-result.log`。range 与 user_store 是候选原始字节；两个 D0 host 模块仅包内 CRLF 与候选 LF 差异，规范化后哈希一致。此 88 项不包含六份 UI 及 Nginx 路由，不能代替实际入口验收。

已从正式提交 `ca770903912651f430eeb2345dc82d7c9191fa10` 重建 24 目标候选，manifest SHA `ad400f1f7f7a2e260eb608b63b00abfbd016e03412ae100c84958865f4e891a7`，包 SHA `c3fbac57140e0bf7f00bdf47c9a0d355bef7ddbf9f43be2cf5cebb6818f1c0ed`。现场暂存目录 `/opt/fs-release-stage/fs-admin-es-ca77090-20261113`。原发布器 inspect 已返回 sourceCAS/protectedCAS passed、releaseReady true、mutations false；尚未 apply。正式 CI 和发布后真实入口仍须分别确认。
