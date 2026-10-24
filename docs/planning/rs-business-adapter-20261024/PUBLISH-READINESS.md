# 首次利润来源发布失败与有界就绪等待

PR431已通过正式CI并合并。首次发布ID `nav-20261024T093500Z` 在原publisher的约5秒范围健康检查阶段失败，回执`rolled-back`、failure=`range health failed`、rollbackFailure=null。真实读取全部11目标SHA与发布前一致，新文件已回退；原经营服务active，/health的ok=true，用户分析ready，无活动客户报告。失败时段未见Python崩溃堆栈；具体耗时来源未证实，不把“冷启动”写成已确定根因。

因此只补发布器就绪诊断适配：原CAS、锁、准入、备份、第一次重启和5秒健康检查完整保留；仅捕获该scope的精确`range health failed`，在同一次重启、同一准入fence内最多额外等待25秒，仍须真实/health ok=true，随后执行原nginx检查与reload。不会重启第二次；超时、其他错误或其他scope仍失败并由原publisher回退，不跳过或放宽健康断言。运行代码与11目标SHA保持PR431版本。

首次已明确回退且逐目标读回后，后续使用新的发布ID；原失败回执及备份保留。新增三项检查覆盖同进程/原fence、ok=false不放行、等待上限、其他错误/范围不捕获。CI和下一实际发布分别记录。
