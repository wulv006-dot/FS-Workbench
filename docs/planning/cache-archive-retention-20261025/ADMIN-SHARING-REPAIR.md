# 原事务读取器的共享会话修复候选

生产/根因已核：/opt/fs-transaction-snapshot/supplement_reader.py 原SHA 7f5d150842d049bdeff535fa32202309464638371fc32bb6006584430f448d38，在现有Admin容器另建SessionManager并ensure；它是第二个登录方，保存自己的session_state检查点，能覆盖8767在用身份的检查点。此缺陷在归档发布前存在，原01:14自然轮未停止或重放。

最小修复：保留原request、全部筛选、解析和结果结构，每一条统计读取只从8767/session/admin-token借当前令牌，避免批量期间令牌更新。消费者不ensure、不登录、不refresh、不保存检查点；原SessionManager仅复用既有request实现。全局未ready/令牌不合格/本地读取失败，沿原逐条unavailable，不换身份兜底或补旧数。

只发布一个host读取器文件；原collector在下次自然运行读取它，不重启服务、不触发新采集，不改调度、定价、权限或原失败记录。三项本地用例通过，覆盖每行使用新鲜共享令牌、缺失/非法身份不登录及本地失败原状态。真实只读候选和正式CI另记录；代码候选不冒称原自然轮验收。
