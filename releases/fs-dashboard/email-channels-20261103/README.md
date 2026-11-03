当前版本及平台阻碍以 [STATUS.md](STATUS.md) 为准；下文为初始配置版本范围。

# FS 邮件通道配置 · 2026-11-03

在既有营销页面启用“邮件营销配置”，接入 Aurora SendCloud 与 MambaSMS 账户配置和指定单邮箱测试。复用原营销 worker、门户登录和实时管理员角色，不改站内广告接口、共享导航及定时任务。

## 当前交付范围

- 两个平台分别保存发件人、回复/测试邮箱及密钥；密钥只写服务器私有目录，读取接口只返回是否配置。
- Aurora 使用按账户地区选定的官方域名；Mamba 使用官方邮件批量接口但测试仅传一个指定邮箱。
- 发送必须显式确认；持久化唯一请求标识，超时或未知结果不会自动重发。平台受理与送达分开，部分成功不得被误认整批成功。
- 未接入客户群发、客户筛选、共享抑制、回调、定时/灰度调度和订单归因。这些仍属于附件后续需求，不以本次配置接入冒充完成。

## 维护与验证

可编辑源码为 source/ 下的 market_worker.py、email_channels.py 和 marketing.html。页面脚本已包含在HTML中。market_worker.py 基于2026-11-03实际活动文件，仅增加邮件路由分发。

10项隔离测试在Windows与生产同版Linux/Python3.9通过；既有pr-fast调用source/test_email_channels.py。新增脚本Node语法检查通过。线上入口的管理员配置读取、配置保存、密钥保留、匿名403及三个文件SHA读回通过。平台真实投递仍须以测试记录和收件结果为准。

运行入口：/dashboard/modules/marketing/#mail。服务：marketing-worker.service。现有广告功能继续沿用原路径。

## 凭据与数据

生产运行配置在 /opt/marketing-worker/_email_private/channels.json（目录0700、文件0600），测试账本同目录tests.sqlite3。不得复制进Git或交付包。网页登录密码未保存。此仓库不含真实API密钥。

## 发布与回退

沿用既有冻结publisher及双发布锁，deploy/release_email.py只适配三个精确目标，保留版本比较、备份及原子写入；重启仅marketing-worker.service。deploy/manifest.json保存本批三个文件SHA及受保护首页版本。

本批正式暂存：/opt/fs-release-stage/email-channels-20261103-v1。
备份：/var/backups/fs-navigation-20261006/nav-20261103T083000Z。
清单SHA：96be18ff6505fee6e4688322ea5d446b67115b1b70e0e8fe3013d9bfa225d2ce。

回退前核对本批版本无后续改动，然后执行：

    /opt/python39/bin/python3.9 /opt/fs-release-stage/email-channels-20261103-v1/release_email.py rollback /var/backups/fs-navigation-20261006/nav-20261103T083000Z 96be18ff6505fee6e4688322ea5d446b67115b1b70e0e8fe3013d9bfa225d2ce

回退保留私有配置与测试账本，避免丢失凭据或发送幂等记录。不得直接重放本批清单覆盖后续版本。