# FC Coins 旧机制退役与保留范围

## 10:55新增退役范围

| 已退出的能力/规则 | 当前替代与边界 |
| --- | --- |
| 拉新、积压、限时促销生产模式 | 当前只daily/revenue_sprint；拒绝旧计划重新激活，影子与教材同步两模式，历史结果保留 |
| ItemD2R礼包等值5K假设 | 原实际100K计算，不将礼包当105K；历史假设只作旧证据 |
| 多次基础价过渡写入 | 已移除，基础价每轮最多一次、必要地区各一次；原未发送操作保留并按原ID取消 |
| fc27-quote-cloud.js旧交互与自动请求 | 当前仅无请求的退役提示，实际页面只加载V3脚本 |
| 强制结束时间及隐式7日/72h/月末期限 | 两模式均可空；不延长现有计划原22:30期限 |

10:42真实轮已确认基础价一次、Saudi PS/Xbox各一次。当前代码3153b4a、本地239项检查；新知识6实际装载与统一PR正式CI分别记录，不能提前称生效。

2026-10-27 04:17北京时间历史核验。实际版本和原编号见[验收记录](ACCEPTANCE-20261027.md)；原调查清单在Git历史保留。

| 旧入口/行为 | 现行替代职责 | 实际状态 |
| --- | --- | --- |
| 80/15/5加权、临时ItemD2R钉价、baseline/hold/parity、尾价及回摆 | V3当前策略/原财务/显式分配 | 当前生产入口委托V3，旧代际不得新派发；旧算法仅隔离只读历史回放 |
| 逐轮Hermes审核及失联旧算法兜底 | 程序逐轮执行、Hermes每日效果建议 | 正常报价不调用模型；教材-4实际加载。旧审核保留当时来源 |
| 定价预算、预占、耗尽退出及机会成本硬限 | 实际折让/贡献追踪 | 原计划rev2有效额度删除，新首轮reservation0条；旧账本保留不控制新执行 |
| fc27-automation-tick.timer/service | 唯一fc-pricing-v3.service | 04:10:02已移出/etc/systemd/system并归档；均not-found/inactive |
| fc27-price-observer.path/service | 原耐久事件/游标及每日影子 | 同次归档原单元，均not-found/inactive，无第二套触发器 |
| /opt/fc27-price-observer四个py及缓存 | 当前必要来源及独立ItemD2R reader | 整目录移入可恢复备份，旧代码无当前消费者；原数据只读视图保留 |
| ELD/U4GM/IGGM/U7Buy的FC自动采集与旧观察UI | Lootbar无券、冲额ItemD2R、沙特Arab-UT普通 | 当前按策略采必要来源；旧页面脚本不再加载。历史与其他游戏保留 |
| 英国临时ID1/0.9100有效规则 | 三平台继承全球 | status1→0，04:07:37后台/缓存/公开确认；原行保留审计，其他英国规则不删 |
| 旧quote/迟到任务/旧generation | revision/epoch、资源所有权及原ID对账 | 旧代际新dispatch被拒绝；失败/UNKNOWN不清除。多自然周期无回摆待验 |
| 旧监控schedule/job语义 | V3薄投影及统一故障分类 | 共享监控读取当前V3状态，RPG/宿主/夜间/通知职责保留 |
| worker队列错误空转 | 原异常路径两秒退避 | PR518已发布，错误不删记录、不自动重发；207项回归含冲突控制流 |

备份`/var/backups/fc27-v3-retired-20261027/`的journal保存八文件原路径/SHA、移动与最终单元状态，四代码加四单元逐字节核实。历史`/var/lib/fc27-price-observer`、订单/报价/故障/UNKNOWN保留。清理没有重启业务服务。

回退先核当前generation、原操作、资源所有权和财务政策。精确备份可以恢复文件，但不自动重新启用旧定时器或授旧策略新写入权；代码回退沿原publisher对应release journal，不能整包盖回旧控制系统。

automation_tick.py保留现行队列锁与原ID恢复能力，pricing_v2.py保留V3兼容入口，reference_observer_view.py只读历史；不按文件名批量删除。SBC/Players/Packs原公式联动、Evolutions、其他游戏、共享会话及通知保留，球员售价日常抽查不恢复。

更多自然周期零重复、全部浏览器故障现场注入、长期收益及模型独立掌握仍待各自真实证据，不由本表推定。
