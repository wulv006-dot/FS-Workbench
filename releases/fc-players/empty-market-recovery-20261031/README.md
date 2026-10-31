# 原8人缺价上新恢复 · 2026-10-31

原4eb2f5ce34bb4951bd81a357a2d737d8中8次模型新增均HTTP500，恰好全部带PC市场价null，一人PS也null；其余26人原值均完整且成功。cloud19把缺市场价统一提交原生文本空串，保留unknown语义和fallback_9999；不把市场币伪造为0/9999，不改有价平台或既有价格/自动化规则。

仅两个运行目标：direct_model_payload.py和VERSION。原34人计划、源文件、摘要、add未知事件均不修改。recovery脚本显式限定原execution/plan/8IDs，要求原HTTP500/原载荷摘要/当前完整模型对账，逐人记录独立add_empty_market_recovery阶段和修正体摘要；同阶段中断只GET补验，不重发。随后沿原execute_direct_plan完成原标签、同步、缺价平台兜底、六商品启售和写后回读，已验证26人不重做。普通resume仍不自动重发unknown。

脚本默认仅检查。--apply仅能在原API进程停止、取得同一api-instance.lock且无其它执行时运行；先SQLite原子备份和原对账快照。借既有容器身份/挂载/ENV，完成后恢复原按需入口。用户已明确要求修复并完成8人，未新增业务范围。原未知记录不删除；修正再次失败就留原ID停止。

发布仍使用原10/29 publisher和锁/CAS/备份；清单固定cloud18现役51源，仅2文件，ENV/人工权限/600秒按需退出保持。tar成员mtime固定1793390400，避免旧BuildKit同大小/同mtime版本内容缓存；内容仍逐文件SHA验证。具体manifest/source映射见同目录JSON。无Notion或知识层变更。

本地与正式CI检查：空值语义、有效价不变、0不冒充未知、原回读与兜底；原HTTP500绑定、只读检查、一次修正新增、恢复丢响应仅GET、重复调用不重发、原计划/UNKNOWN历史保留。部署与实际8人结果另留最终回执，不以测试通过代替业务完成。
