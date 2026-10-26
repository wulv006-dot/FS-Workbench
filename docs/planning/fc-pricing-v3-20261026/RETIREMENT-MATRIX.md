# 旧机制退役与共享保护

状态：调查/迁移清单；本文件不表示已停用。退役发生在新链通过相关验收并获得控制权之后，执行者须填实际版本、时间和读回。

| 入口/行为 | 当前依据 | V3处理 | 当前退役状态 |
| --- | --- | --- | --- |
| pricing_v2旧加权selector/临时ItemD2R parity/position上限 | 活动源码待逐SHA核定，附件及PR489/490合同 | 生产只留五策略入口；财务抽取，旧算法仅隔离历史回放 | 未执行 |
| 旧.99尾价/隐式额外降价 | 原pricing_v2 ending及调用方 | 新选定动作不再二次隐式改价 | 未执行 |
| worker apply_program_fallback | 活动worker及调用方待核 | 显式V3确定性路径或当前计划保持；不回旧selector | 未执行 |
| automation_tick.service/timer | 16:21运行，现源为automation_tick.py，每分钟due检查 | 受控切换为唯一V3协调服务，停用被替代旧timer/service；保留原采集与其他游戏调度 | 未执行 |
| price-observer.path/service | 16:21 active path；单元监听jobs目录 | 迁为耐久完成事件与游标；保留已证实的防重复修复及来源数据 | 未执行 |
| ItemD2R/ELD观察采集 | 旧独立观察来源 | 统一source registry，保留市场观察能力 | 未执行 |
| pricing_probe owner版本硬编码 | 活动pricing_probe.py待核 | 读稳定语义状态；保留共享RPG分支 | 未执行 |
| watch.py/repair hooks/browser lifecycle | AST已核watch写请求/通知；common当前SHA01e3e04f…435bf2，仅brain-theme/monitor-health固定修复配方；浏览器实际调用继续单核 | 同一incident/恢复责任，保留共享通知/夜间/界面修复，继承displayfd与共享会话保护 | 未执行 |
| 旧quote/preview/manual intent | 原账本与dispatch状态待核 | 禁新派发；未决原ID读回及迟到回执保留 | 未执行 |
| 旧策略知识/提示词/模式菜单 | 旧release及活动工具分别清查 | 当前入口指向V3；历史保留SUPERSEDED指向 | 未执行 |
| 自动回滚旧控制权 | 发布器/恢复合同待核 | 代码可回退已验V3；epoch/退役状态不倒退 | 未执行 |

保护范围：共享FS/RPG监控与通知、订单/报价/故障历史、已有优惠承诺、有效会话、SBC/Players/Packs原固定公式自动联动、Evolutions等其他FC业务、其他游戏及无关页面。只停止被V3明确替代的Coins控制分支，不按名称包含FC就批量停服务。

每项最终凭据须包含：源/目标、消费者、替代职责、停用方式、现场状态、历史保留位置、恢复办法。UNKNOWN及已派发资源不能因进程死亡、TTL或换generation释放。

共享告警的 `common.assess` 当前读取 `snapshot.coin.schedule/job` 及 `health.incomplete_executions`。V3须接通这些语义状态或明确迁移其FC消费者，不能只停旧tick而让共享探针持续读旧状态；也不能因旧字段不再适用而整体关闭监测。
