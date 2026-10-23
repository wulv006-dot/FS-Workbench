# Order worldless 发布后独立只读验收

2026-10-23 北京时间19:57:09.539至20:00:59.144，真实原4页的 utility world 每页144→144，全部旧名称与unique ID保留，新增0、移除0。观察期间健康接口证实至少两次原20秒 upkeep 实际完成；原容器、StartedAt与发布双SHA保持，ready=true、login_attempts=0。该窗口已通过原自然探针不再新增 world 的验收。

本子任务只读取，未发布代码、触发probe、启动Playwright driver、创建world/页面、导航、读取cookie或执行业务。脱敏机器证据见 [ORDER-WORLDLESS-POSTCHECK.json](ORDER-WORLDLESS-POSTCHECK.json)；原target/world名称和unique ID仅留受忽略私有目录。

## 版本与身份

主任务发布回执：`order-worldless-probe-20261023-v1`，19:53:29已验证。独立读取每次均核对以下精确来源及原容器身份，任一变化即停止比较：

| 对象 | SHA-256／状态 |
|---|---|
| /opt/fs-order-session/service.py | `35b950f23ba45d662b755ef33f415e7ca22c749331baad4fd43de04aa59e76b0` |
| /opt/fs-order-session/raw_node_helper.js | `53ee945adbafde58140f2d2705b488ad83d99b7dab30d138d1c6082997713425` |
| 原容器StartedAt | 2026-10-23T11:00:46.269976722Z（北京时间19:00:46） |
| RestartCount／cgroup failcnt | 全部读取均为0／0 |
| 观察器运行时 | 原Node v24.21.0、原utilsBundle.ws |

## 原自然周期确实推进

health没有checked_at字段。独立脚本按宿主读取时点记录verified_age_seconds、checking、ready、last_error和login_attempts，不把缺字段判为空成功。8个健康读点的age分别为1.3、9.3、17.4、3.1、11.1、19.1、5.6、13.6秒。

| 北京时间（后读点） | 前age→后age（秒） | 结果 |
|---|---:|---|
| 20:00:09.730 | 17.4→3.1 | 原upkeep已完成并重置验证年龄 |
| 20:00:33.791 | 19.1→5.6 | 再一轮原upkeep完成 |

8点均ready=true、login_attempts=0、last_error=null。首raw读前后另观察到21.3→0.1、checking=true→false；该次自然完成未用来替代上述两次跨读点证据。第二raw读后age=7.9、checking=false、probe_seconds=3.054。

## 原页面与内存

两raw点相隔229.605秒。4个相同about:blank目标每页145个上下文（其中144个utility world），对每页检查名称和unique ID集合完全相等；不是通过替换页面、清空上下文或重建浏览器获得零增长。公开JSON只含页面身份哈希与集合哈希。

| 字节口径 | 首raw读后 | 次raw读后 |
|---|---:|---:|
| cgroup usage | 372424704 | 371695616 |
| cgroup RSS | 317808640 | 317042688 |
| cgroup cache | 54616064 | 54652928 |
| cgroup limit | 1073741824 | 1073741824 |

首raw读前恰逢原upkeep执行，usage=460136448、RSS=405520384；该瞬时峰值与读后下降不可当成旧world回收量。旧144个world仍保留，此次证明后续原周期不继续增加；没有证明此前1GiB OOM的全部构成或长期无OOM。

## 观察器冻结与检查

观察器只用Target.getTargets、Target.attachToTarget、Runtime.enable、Runtime.disable、Target.detachFromTarget。每次前后核源与容器，前置余量至少256MiB；原容器内10秒/-k1秒、宿主13秒有界退出。两个raw点、8个缓存health读点以及原集合相等、协议白名单、两次真实年龄回落断言均通过。

| 私有独立脚本 | SHA-256 |
|---|---|
| raw_worlds.js | `cf19eff3a352af9ab823927d7bfe4057eb7a8ea15428f18a9e1f290284e38e85` |
| run_snapshot.ps1 | `82cca878b9d5dcf4c38fee41d106708c5ee7165c60a6e81e9f9bd7f420a12a93` |
| run_health.ps1 | `6ecd8481f0b085a56e969dc6eafd0cd2688420e4da247a04609537a6e86dccd6` |

脚本与原始读点保存在`.agent_runtime/order-worldless-post-20261023/`，未改变早期只读证据。没有执行正式CI；完整Cookie属性、Set-Cookie差分、删除及原身份/refresh合同由主任务原回归证据单独验收。本短窗口不能代替长期内存观察。
