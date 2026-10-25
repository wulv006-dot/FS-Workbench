# 用户分析页头及观察规则修复 · 2026-10-25

状态：用户已明确同意合并上线验收。PR #459 已合并为 `900d2746a8703c9bfd767e031c66b533eecb651e`，本次八文件已发布并经正式 wulv Chrome 入口及实际冻结数据核对通过。证据见 [验收记录](OBSERVATION-ACCEPTANCE-20261025.json) 与 [活动映射](SOURCE-MAP.json)。

## 本次改动

- 去掉页头重复的 FS / MMOEXP 链接。“跳到主内容”正常浏览时视觉隐藏，键盘聚焦时显示并可进入主内容。
- 页面阶段规则替换为“短期效果：7 / 14 / 30 天”“长期追踪：14 / 30 / 60 天”，默认短期效果。数字依次为沉默、流失、长期流失的进入天数，沿北京时间日历日距末次有效购买计算；不表示营销因果归因。
- 新规则分别为 `short-term-v1`、`long-term-v1`，整体、站点、系列、项目及项目比较沿用所选阈值，切换范围不再重置规则。二购观察 H 保持独立的原 7/30 天功能。
- 原 `common-v1`、`fc-v1` 及旧快照、未传规则的原接口默认行为保持。旧快照不重算、不迁移订单或身份；明细、导出和两 Hermes 工具读取同一冻结证据。

## 精确发布范围

维护源仍为 `releases/fs-dashboard/user-analytics-20261022/`，仅以下八个活动文件：

| 源文件 | 现场目标 |
|---|---|
| source/user_config.json | /opt/fs-hermes-fc/user_config.json |
| source/user_contract.py | /opt/fs-hermes-fc/user_contract.py |
| source/user_lifecycle.py | /opt/fs-hermes-fc/user_lifecycle.py |
| source/user_query.py | /opt/fs-hermes-fc/user_query.py |
| source/user_tools.py | /opt/fs-hermes-fc/user_tools.py |
| ui/index.html | /var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/index.html |
| ui/users.css | /var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.css |
| ui/users.js | /var/lib/fs-navigation-formal-static/user-analytics-20261022-v1/users.js |

沿原模块 publisher、空闲检查、锁、CAS、备份及精确回退，不触及用户事实库、订单、密钥、会话、权限、FC定价/采集/调度或历史 UNKNOWN。发布前刷新本批活动SHA及保护清单，不能重放10月23日旧manifest。受影响常驻读取服务须在原空闲门禁下重载，原任务不可取消；其他服务是否需要重载按实际加载核对，不为UI改动扩大重启范围。

## 验证与待验

- 首次候选 `39929fe23d94929f25c30037322cda6049ffd5b1` 正式 pr-fast 40171829043 成功，91项、0失败、0错误、0跳过；包括全部新阈值边界、项目比较、趋势、名单/导出、Hermes同快照及旧快照保持。
- 随后的局部筛选宽度调整已完成本机浏览器复查，最终head的正式CI另记实际回执。
- 本机离线浏览器采用当前导航字节、实际页面源码及模拟目录/失败响应：1920桌面与390手机、浅暗主题、键盘跳转、两规则选项、范围切换保留、查询实际发送版本和无横向溢出均通过。截图含“离线界面预览”标记，不是生产或真实客户查询证据。
- Windows 无法满足原模块 Linux 私有权限断言，未放宽校验；阶段计算以正式 Linux CI为准。
- 上述候选后续已合并、发布并完成真实入口及两规则冻结数据验收；长期经营效果、跨日自然应用和真实模型生成不由本次通过推定。

PR：[459](https://github.com/wulv006-dot/FS-Workbench/pull/459)。

## 正式发布与真实验收

主线更新后源 `0005e16959b9d1d69e05f0a160f44807cce8ff94` 的正式 CI `40174868332` 通过，91项、0失败/错误/跳过；八文件字节与用户批准的 `66e8090` 一致。发布 `nav-20261025T080257Z` 沿原锁/CAS/备份，仅重启读取服务并重载原路由；八目标与158保护SHA匹配，当前原生镜像0a6b8e71保持，业务worker/timer操作数为0。

正式已有wulv Chrome实际查询同一期间 2026-09-25—10-24、数据版本999、17,197名购买客户。短期与长期分别按原末购日独立重算，项目规则、明细/导出、工具响应和旧快照一致。当前普通IAM聚合200/私有403、匿名401；普通账号独立浏览器登录未新增验证。页面最终回到短期规则且已查询，未留待查询条件。

原publisher的 `applied-awaiting-actual-http-role-acceptance` 回执原样保留，后续实际HTTP/角色/页面通过记录在独立验收文件；不改写原日志。本次未触发采集、付费模型、客户联系、发券或改价，既有历史回补失败与UNKNOWN均不改写。
