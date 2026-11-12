# 订单客户邮箱 Excel：现役接线与受限发布适配

## 当前修订（2026-11-12，已发布，待页面验收）

恢复实际Admin进度、状态、产品类型和区服目录；进度支持数字键对象及0，状态跟随进度，类型与区服跟随游戏，多游戏区服取共同ID。默认不限、空条件省略、无操作人；不恢复paid默认。35项邮箱后端及81项邮箱前端回归通过。PR1011合并main `7e48408ffcfe1a936da12a732666a91f6d97c212`，精确main CI `43185213406`成功，原受限publisher发布 `nav-20261112T084500Z`；11目标/5保护哈希与nginx/range/FC active读回通过。真实共享API的现役解析器验证进度13（含0）、进度1状态2、类型8、FC26/27区服各1。真实HTTP角色、页面点击与本轮下载尚待登录后验收，不把目录解析当页面验收。知识同步状态见施工记录。

## 历史修订（2026-11-11，已发布并真实验收）

按用户最新要求，进度、状态、产品类型、区服四项置灰并从查询条件省略，停止读取对应被拒目录，使用Admin接口默认行为；不把结果标为已支付/已完成。站点、游戏多选、国家及其他原有筛选、跨月分页和XLSX保持。暂停补权，不改账号或Key。下文17点枚举与18:30全原生联动是历史方案，不恢复为当前默认。代码、发布和真实验收状态以施工记录最新章节为准。

## 范围

本目录把已合并的邮箱分页采集及真实 XLSX 文本单元格导出，增量接入已核对的生产页面与 API。只读订单，不发营销邮件、不写订单、不改变 FC writer、调度器或权限目录。

业务与调用链知识源：[订单邮箱导出](../../../knowledge/order-email-export.md)目前仍为11月11日生产知识基线，尚未同步本次恢复。当前四项可选、空条件省略，去掉操作人；多游戏串行、28日分段、20条游标、365日边界，日期为paytime。浏览器内去重、暂停/继续/取消，完整遍历后下载真实XLSX。不要恢复历史paid默认或静态类型枚举。

## 现役基线与补丁

- `integration/fixtures/` 是只读取得的三个非敏感生产源码基线，不含凭据或客户数据。纯转换函数逐文件核验完整 SHA，只替换指定锚点；保留线上折扣渠道、优惠版本及成熟复购文案等既有差异。
- API 复用已鉴权的 `/dashboard/users/live-orders.json` POST，以严格 `kind=order_email_export_page|order_email_export_options` 分派；原查询、Cookie/真实 actor、私有范围、会话复核及共享 admission 保持。
- 四个新 JS 通过复制现役精确静态路由获得原会话鉴权；不开放静态目录通配符，不新增公开邮箱接口。
- `integration/package.py` 的 `build(sha, read_git, nginx_source)` 是纯组装，不验证 GitHub、不写包、不发布。调用者必须先取最新 main、核验同一完整 SHA 的必需 CI 成功，再由 `git show <sha>:<固定路径>` 提供全部输入；禁止用工作区字节伪称 main 包。

## 原 writer 与精确十一目标

`publisher/adapter.py` 只加载 SHA 固定的现役导航 writer：

`/opt/fs-release-stage/data-tools-query-fix-ui-20261018-v1/release_navigation_base.py`

SHA256：`5548d9c8411eb5bb888672b0e58246bfd9043a5e519decb1f8407d2da9e71357`。

十一目标为：range API、邮箱后端及专用 source/worker、既有 page/data-workspace、四个邮箱 JS、原 nginx include。精确路径由代码固定；清单需全部候选内容 SHA、现役 beforeSha256（新文件必须不存在）、五项不变保护文件与 range 服务状态。冻结的测试副本仅供离线验证，不替换现役 writer。

保持原发布双锁、collector/provider 锁与 Hermes admission fence、每文件 CAS、持久 intent、备份、journal 与原失败恢复。只在原数据库锁释放流程后重启 range 服务；nginx 先语法检查再 reload。失败时由原 writer 在锁内恢复，UNKNOWN 不盲重发。没有通用 shell、HTTP 服务、新凭据或新端口。

服务器本地受限入口：`adapter.py plan|inspect|apply --manifest <本次清单>`；apply 还必须给 `--approved-manifest-sha <完整SHA256>`，仅 Linux 允许变更。恢复仅接受原 `/var/backups/fs-navigation-20261006/nav-<时间>` 的本次备份与原清单 SHA。入口本身不提供 SSH 传输，也不将清单中的 sourceCommit 当作 CI 证明。

## 验证状态

PR999 main158ddab93103695ef13917bbd5368bbbe5c7b179 / exact-main CI43013389232成功，nav-20261111T113950Z已由原十一目标publisher发布，所有目标及五项保护哈希、nginx/range/FC服务读回通过；79前端/194后端回归通过。真实FS默认条件MMOEXP+FC26/27：2026-11-10共16页/2窗口导出282唯一邮箱；2026-10-31至11-01共40页/2窗口导出725唯一邮箱，XLSX独立读回纯文本、零公式。PR1000审计记录已合并。旧年度399仅历史paid范围，不代表当前默认全年验收。当前默认全年、营销APP实际导入、183及多角色撤权未验收；未更改权限、Key、FC writer或timer，未发送邮件。
