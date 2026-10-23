# Order 空白文档 utility world 累积：独立只读实证

2026-10-23 已证实：同4个长期不导航的 Order 空白页，每页旧57个 Playwright utility world 在22秒后全部仍存在，并各新增1个。观察器直接使用原有WebSocket库，没有启动Playwright driver、创建world、导航或改变页面。已确认具体的持续累积机制；它在18:43整次1GiB OOM中所占的内存比例尚未测定，不能据此把全部OOM归给它。

原始world名称、unique ID与页面目标ID仅留本机受忽略的私有证据目录。可共享证据为同目录 [ORDER-WORLD-READONLY.json](ORDER-WORLD-READONLY.json)，只含时点、计数、页面身份哈希、world集合包含关系及源/运行时版本，不含cookie、原业务URL或原world名称。

## 真实读取

| 北京时间 | 普通空白页 | 每页utility world | 合计 | 第二次对原集合的结果 |
|---|---:|---:|---:|---|
| 19:21:20.178 | 4 | 57 | 228 | 初始集合 |
| 19:21:42.579 | 4 | 58 | 232 | 每页保留原57、新增1、移除0 |

不只是名字再次出现：每页原57个 `Runtime.executionContextCreated` unique ID 也全部包含于第二次集合，证明原执行上下文仍在。原容器及StartedAt检查保持，四个页目标及about:blank状态未漂移。两次读取跨过原20秒探针周期，没有人为触发原探针。

观察协议严格限于 Target.getTargets、Target.attachToTarget、Runtime.enable、Runtime.disable、Target.detachFromTarget。没有 Runtime.evaluate、Page.createIsolatedWorld、Page.addScriptToEvaluateOnNewDocument、页面/浏览器context创建、导航、清页、cookie读取或登录。每次前置检查余量至少256MiB，内部10秒/-k1秒、宿主13秒保护；实际每次约0.4秒。原有ws库观察进程RSS约79MB，两次均自行结束，不是额外长期driver。

## 与源码及前段采样相互印证

安装版 Playwright 1.63.0 的 `lib/coreBundle.js` SHA为 `549070af3acabb3efcc4f55bfe6210f9f7c2fcf633cf7eaa59bfe60719969171`：

- L7969：createGuid采用16字节随机数；L13007与Page构造器L22295生成随机page GUID。
- L37280：utility world名称包含新Page GUID；L37606为原frame创建该随机world；L37626登记同worldName的空新文档脚本。它们位于noDefaults分支之外。
- L38474→L37331→L37683断连路径只清本地会话/监听；未见utility world显式移除。唯一的Page.removeScriptToEvaluateOnNewDocument位于L38077，处理另行登记的显式initScripts，不是前述初始空utility脚本。
- noDefaults=true确实跳过focus/media默认覆盖，但不会避开上述world初始化。CDP连接两种选项均带noDefaultViewport=true，因此也不能无证断言本次由默认1280×720 viewport backing造成。

此前三个短Playwright读点在19:08:54、19:10:32、19:12:10：同四页每页Docs1/Nodes4不变、全局Worker0，JSHeapUsed合计17.68→21.09→25.19MB，原cgroup探针前253.12→258.45→265.93MB。该阶段包含原周期和诊断连接自身开销，只证明观察到缓增，不能直接当单独泄漏速率。随后的raw读取避免再创建driver，确认旧随机world确实未回收。原18:43 OOM的全部原生分配/retainer构成仍未取得。

## 原镜像可复用入口与属性边界

- Python3.10.12中 websocket-client/websockets 均不可import；未安装依赖。
- 原Node v24.21.0内建WebSocket的typeof为function，仅核类型，未额外测试其网络连接。
- 现有 `/usr/local/lib/python3.10/dist-packages/playwright/driver/package/lib/utilsBundle.js` 的ws为function，本次raw读取已经实际使用；SHA `2d1ccc01d21b7d54ca99a6305991d7fb6e072ea4e725d7fec5eb6184188c52c9`。
- 仅require验证：`require('/usr/local/lib/python3.10/dist-packages/playwright/driver/package').request` 为object，newContext为function，实际入口为该目录index.js。本项0网络、0APIRequestContext、0浏览器连接，不是新认证链路验收。
- 静态CDP Cookie类型包含session/priority/sourceScheme/sourcePort及结构化partitionKey；partitionKey含topLevelSite与hasCrossSiteAncestor，另有partitionKeyOpaque。APIRequestContext cookie类型的partitionKey是字符串，两者不能视为完整双向同构。未读取任何cookie值；Set-Cookie、删除、Domain/Path、SameSite及分区属性、原身份/refresh与时限合同由后续候选独立回归，不能靠简单拷贝全CookieJar替代。

## 冻结与验证

观察脚本保留在私有独立目录 `.agent_runtime/order-memory-20261023/`，不属于生产发布：

| 脚本 | 冻结SHA-256 |
|---|---|
| raw_worlds.js | `cf19eff3a352af9ab823927d7bfe4057eb7a8ea15428f18a9e1f290284e38e85` |
| run_worlds.ps1 | `1c42e6c14a9998ce828a3fe809458312675575467c965d4fee5aa3b6416f59bd` |

已通过Node语法、PowerShell解析、实际协议方法白名单、四页原world名称和unique ID集合包含断言；两次原浏览器raw读取成功。没有正式CI、生产发布、页面释放、认证变更或故障注入。本子任务已冻结观察器，不再增加Playwright连接。

后续可用同一只读观察器验新机制原周期是否不再新增world，但前提是原container/StartedAt和四个页身份仍匹配；漂移应停止比较，不能把新页面的零world冒充旧页面已回收。单个周期新增0也不等于长期稳定或完整Cookie合同通过。
