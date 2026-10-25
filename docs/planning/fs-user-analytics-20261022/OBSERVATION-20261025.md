# 用户分析页头及观察规则修复 · 2026-10-25

状态：PR #459 候选，尚未合并或部署。当前线上仍按原 SOURCE-MAP；本文件不作为上线证明。

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
- 尚未执行：合并、生产发布、真实登录入口及真实数据的两套新规则验收。新规则实际效果与长期应用不由离线检查推定。

PR：[459](https://github.com/wulv006-dot/FS-Workbench/pull/459)。
