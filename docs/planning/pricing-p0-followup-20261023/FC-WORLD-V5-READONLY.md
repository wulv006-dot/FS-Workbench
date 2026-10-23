# FC v5：原健康分钟检查与零新增world联合验收

2026-10-23 独立只读验收通过本观察窗口：原自然分钟任务真实报告 healthy/transport=ok；随后102.901秒内，同一受控空闲页的16个旧utility world名称及unique context ID完全一致，新增0、移除0。没有换页、清world或启动Playwright观察器。只证明该窗口，不等于长期内存稳定。

脱敏数据见 [FC-WORLD-V5-READONLY.json](FC-WORLD-V5-READONLY.json)。其中页面身份和world集合仅存哈希，不含原target ID、world名称、cookie或业务URL。

## 必要版本与原失败区分

- 两个有效读点都核活动 `browser_lifecycle.py` SHA `71466a3169bf5448b68fea5dadaab4d8e683983544e42bc7c899b468a02dfb74`，`browser_probe.js` SHA `95e84ed02ad894d187e8777bccc32352f952c4e7ce7a1a23386ecbbcd767221f`，严格版本守卫通过。
- 同一原FC容器、StartedAt=19:15:21.542，两个点RestartCount均0；唯一普通页始终为原owned idle，未被替换。
- 主任务已确认旧v4的stdin入口未执行，19:30/31原tick曾IndexError，不能用其“world不增长”作健康验收。本子任务19:34:05的旧v4样本保留，明确排除。
- 第一次v5诊断包装脚本因混合CRLF heredoc在原只读子程序返回后报外层NameError，没有有效保存基线，单独保留并排除。已仅修独立诊断脚本换行，未改生产或执行业务写入；下面为之后成功保存的两个读点。

## 原自然任务与同页比较

原 `fc27-automation-tick.service` 自然日志：19:35:22.389、19:36:23.141、19:37:23.407均为browser_lifecycle healthy、transport=ok。已读回最后一次systemd Result=success、ExecMainStatus=0、开始/结束19:37:23；没有人为触发检查或采集。

| 北京时间 | 普通页 | 总执行上下文 | utility world | 原cgroup观察前→退出后，字节 |
|---|---:|---:|---:|---:|
| 19:36:39.391 | 1 | 17 | 16 | 300326912→301146112 |
| 19:38:22.292 | 1 | 17 | 16 | 300380160→301195264 |

两个点相隔102.901秒，中间明确包含19:37:23的原健康真实CDP检查。16个world的名字与unique context ID逐项完全相同，新增0、移除0；原集合没有被清空后重建。cgroup观察前两点相差53248字节；不把此短窗口外推为长期趋势。

## 观察器边界与冻结

使用原Node v24.21.0及现成utilsBundle.ws，直接连接原浏览器WebSocket。协议白名单仅Target.getTargets、Target.attachToTarget、Runtime.enable、Runtime.disable、Target.detachFromTarget；没有Playwright driver、Runtime.evaluate、world/page创建、页面关闭、导航、cookie读取、登录或采价。每次先核剩余至少256MiB、原container/StartedAt、唯一页身份及v5双SHA，独立短读有超时和退出保护。

私有独立观察脚本（未覆盖Order冻结版本）：

| 文件 | SHA-256 |
|---|---|
| `.agent_runtime/fc-world-readonly-20261023/raw_fc_worlds.js` | `d661a75630171cb5f45c8f325a99851ad0648d2d85ffd7464d75c32ab0369a5e` |
| `.agent_runtime/fc-world-readonly-20261023/run_v5_once.ps1` | `338777e7741d005f6c665ac6a7d9fbe587185fb7947fd75c5570c304e08d96c1` |

已通过raw JS语法、实际协议白名单、同页/world名称及unique ID包含比较、原健康日志配对检查。正式CI与主任务发布属于另一证据链，不以本次只读检查替代。原样本与分钟日志留私有独立目录，精确哈希在JSON。

本次未访问Order、未做其尚未发布候选的后验，也未新增生产修改、恢复或业务操作。旧world仍保留，修复后的原分钟连接在该窗口没有继续增加world；长期自然周期和内存仍由原观察继续验收。
