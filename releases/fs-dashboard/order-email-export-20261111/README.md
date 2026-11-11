# 订单客户邮箱 Excel：现役接线与受限发布适配

## 当前修订（2026-11-11 19:31，待发布）

按用户最新要求，进度、状态、产品类型、区服四项置灰并从查询条件省略，停止读取对应被拒目录，使用Admin接口默认行为；不把结果标为已支付/已完成。站点、游戏多选、国家及其他原有筛选、跨月分页和XLSX保持。暂停补权，不改账号或Key。下文17点枚举与18:30全原生联动是历史方案，不恢复为当前默认。代码、发布和真实验收状态以施工记录最新章节为准。

## 范围

本目录把已合并的邮箱分页采集及真实 XLSX 文本单元格导出，增量接入已核对的生产页面与 API。只读订单，不发营销邮件、不写订单、不改变 FC writer、调度器或权限目录。

按用户17:34修订，当前 FS 面板默认订单进度1已支付＋订单状态11已支付，去掉操作人，其余按 Admin 实际字段筛选；站点、游戏等选项来自真实目录，多游戏串行遍历、最长28日分段、20条游标分页、原365日来源边界。Admin 标为“下单时间”的实际字段是 paytime，按原页面口径执行。浏览器内暂存及去重、暂停/继续/取消、完成后下载真实 XLSX。旧的主站/FC26/27缩减版曾部署，但不是原需求已完成的证明；本轮完整筛选仍待实际接口与全年名单验收。协议及接口阻塞见 ADMIN-FILTER-PROTOCOL.md。

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

17:40 本轮修订独立回归：tiered 全组191项、接线/真实补丁/组装20项、原 writer 适配及恢复15项、邮箱前端73项，共299项通过，diff检查通过。前端真实 FS 远程目录模式默认已支付组合，显式传入目录的旧 standalone API 保持原不限默认，不改变原调用的查询语义；真实远程目录测试验证默认组合随查询提交。以上不是 Linux/实际用户入口验收。

实际直连：站点、游戏、国家目录可读；历史5目录401未绕过。已支付组合和8个产品类型来自用户新截图，不再调用进度/状态/类型/操作人目录。选游戏后开放产品类型、请求服务区；仅上游服务区拒绝转为明确 unavailable 提示、禁用该项但允许其他条件查询，Schema/覆盖异常及本地权限撤销仍失败关闭。不得把未读取服务区当作完整目录。PR993已合并且主线CI通过，未部署。待执行：本默认组合补丁 PR/必需 CI/合并及 exact-main CI；main 包 staging 后原 writer plan/inspect/apply；真实鉴权 FS 页面动态导入及 XLSX 下载、拒绝权限、跨月/多游戏/中断恢复与真实全年覆盖。合并、模拟 systemd/锁测试或健康端口可用均不代表这些验收已完成。
