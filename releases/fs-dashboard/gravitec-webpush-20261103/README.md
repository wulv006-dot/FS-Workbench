# Gravitec Web Push · 2026-11-03

现有营销后台新增 Web Push 页签：`/dashboard/modules/marketing/#push`。实际提供平台配置、只读验证、服务器草稿、内容预览、指定 Token/别名/标签/一个现有分群/全部订阅者发送、定时发送、按活动ID查统计及订阅者别名/标签操作。

本次是可用接口的接入版，并非 Gravitec 全站完整复制。文档未提供订阅弹窗、自动化规则、套餐、订阅者全量列表及完整历史列表管理API，仍保留平台入口。图片参数可提交，通知预览当前仅核对文字/链接/按钮，最终设备外观未实测。逻辑标签组合 tags_segment 和 transactional 标记本版未暴露。

## 活动源码和权限

- `source/market_worker.py` → `/opt/marketing-worker/market_worker.py`，仅新增 `/api/webpush/` 分派。
- `source/webpush.py` → `/opt/marketing-worker/webpush.py`。
- `source/marketing.html` → `/opt/marketing-worker/web/marketing.html`，沿用原样式/主题；`panel.html`、`ui.js`为新增页面片段。
- `deploy/v2/release_webpush.py`复用既有冻结发布器、锁、CAS、备份和回滚，不新建服务、定时或网关路由。
- 后端每次通过原门户8895检查真实admin角色；POST同源请求头校验，不接受外传角色。
- `_webpush_private/config.json`只在服务器保存，目录0700、配置0600；浏览器不会收到原密钥。`push.sqlite3`保存草稿及发送账本，保留原ID和unknown，部署/回滚不覆盖业务数据。凭据不进入本仓库。
- 模块版本`gravitec-20261103-v1`指协议实现；v2发布仅修正隐藏的全部发送确认框被旧label样式覆盖。

## 验收和限制

Windows Python3.12与183 Debian12/Python3.11各14项测试通过；语法检查覆盖HTML内联JS。包含缺失对象拒绝、全体确认、并发/重启防重、超时不重发、草稿持久化、只读验证、日期/URL校验、权限失败关闭和CSRF。

生产发布后原chenchao会话确认Web Push入口、配置读取、官方只读alias验证200、草稿保存。客户推送未发送，标签/别名未写入，真实活动统计与最终浏览器送达未验。统计入口需要已有活动编号；不会伪造统计数字。邮件营销继续暂停。

默认SSH known_hosts的183旧条目不匹配；沿用已迁移验证的专用`known_hosts_rpg183`严格校验成功，没有删除/改写信任记录。测试在183独立临时目录运行，没有接触RPG服务。

## 回滚

先确认无后续修改，使用原发布适配器逆序回滚。始终保留私有配置和SQLite，不能用旧目录整包覆盖。

|批次|服务器stage|备份目录（/var/backups/fs-navigation-20261006/ 下）|manifest SHA256|
|---|---|---|---|
|v2|/opt/fs-release-stage/gravitec-webpush-20261103-v2|nav-20261103T112500Z|30d94d764ae79df34b9b2e968232fd2950bae4a864d3609279aca60c34bf6ff3|
|v1|/opt/fs-release-stage/gravitec-webpush-20261103|nav-20261103T112200Z|7b76203cda94842a4e60026048929111efb7e406090732a3bd333c2f2bb79721|

命令：`/opt/python39/bin/python3.9 <stage>/release_webpush.py rollback <完整备份目录> <对应manifest SHA256>`。只重启营销worker；不改其他业务服务。新部署必须从活动版本更新CAS，历史manifest不能盲目重放。

## API依据

[Server API Overview](https://scandalous-ferry-f93.notion.site/9-1-Server-API-Overview-35b439c3676842acb9fbf4adf09abcaf)与[V3](https://scandalous-ferry-f93.notion.site/9-2-Send-Push-Notification-V3-826b6c9a941d410593e871880f26aa65)：HTTPS Basic Auth，App Key为用户名，App Secret为密码；`POST /api/v3/push`；`GET /api/v3/messages/{id}`；alias GET/POST、tag POST/DELETE。
