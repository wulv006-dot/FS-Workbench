# FC成本共享会话重复取用修复

恢复原自然周期P2PAH/Order成本读取，不重新登录、补采、改价或重放5fc4c884。原120分钟、ON/auto/rev40、80/15/5、v15、共享身份及UNKNOWN保持。

## 证据与根因边界

原2026-10-25 15:14工单因P2PAH RuntimeError于15:16 collection_incomplete，无报价/模型审核/写入。原文件p2pah-cost-2zbjzzZt.failed.json只有missing/RuntimeError，精确底层码及发生在首次还是第二次取会话已不可从该原件追溯，不能说已证登录过期或供应商故障。只读缓存健康当前ready、broker无新登录，不据此冒称历史也正常。

代码可验证缺陷：isolated_backend.open_backend创建私有context并通过fs_order_client.apply取得已验证共享身份；collect随后login(tab,{})重复调用相同apply。后者抖动会丢弃已认证context，整轮在读取任何成本页前失败。离线严格模拟首次成功/第二次失败，原collect稳定复现RuntimeError且未读任何成本页；候选仅取一次后原两页/三平台校验成功。这是已证实的重复依赖缺陷，不是对原历史底层错误的补造。

## 两文件修复与边界

仅collect_p2pah_cost.py删除第二次取会话及其无用绑定；首次通过共享broker认证保持，成本真实页面的登录/平台/类型/分页/最新记录/八日时效等判据完整保持，不用旧成本。启动失败仍阻断，原180秒/2GiB/init/tmpfs及只读挂载不变，不改broker或其他业务消费者。

读取器将共享会话RuntimeError中已验证格式的global_order_unavailable原因码及traceback阶段保留，不输出任意异常文本、URL或Cookie；原ValueError及Playwright/成本页诊断保持。原shell按安全字段传递stage/exception_type/api_method，沿原evidence_file接续；不新增通知链或业务重试。

原publisher仅对两个冷加载成本文件执行备份/锁/CAS/原子替换，无服务重启；保留原FC队列/重试/成本锁、未决执行及源保护。直接相关离线检查与Linux/正式CI/真实原自然验收分开。Windows无IANA tzdata，单测日期使用显式UTC+8 fixture；Linux使用真实IANA数据库，Windows初次环境错误保留。

当前7项本地检查通过，正式CI/发布与下一原自然轮均未完成。只有自然轮三平台有效新成本、有效审核及原结果可以证明业务恢复；首轮恢复不等于历史底层错误已还原或长期稳定性已通过。
