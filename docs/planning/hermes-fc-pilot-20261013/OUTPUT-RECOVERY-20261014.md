# Hermes思考输出恢复

第十新整周调查a682327dec729ede5a5561b47c38bfd0已FAILED/unverified_provider_result；前5次成功，第6次百炼明确completion_tokens16384/finish_reason=length、7工具调用。输出上限16384是本地试点代码设置，不是Hermes或百炼限制；本地未保存原响应工具参数，不能声称确认哪一条被截断。原请求保留、不重放。

用户已读回百炼最大输出（含思考）384K。本轮将Hermes high/max的本地输出上限统一放宽至65536（包括思考与工具参数）；gateway/原provider的opt-in工具分支/worker三处闭合。原none/旧顾问分支6000保持至成品后退役；不改变high/max强度或新设累计费用闸门。仍不补造被截断JSON，也不把错误回执当成功；安全诊断仅记录tool_arguments_json_invalid，不保存私有推理。

固定官方AIAgent烟测读取实际max_tokens65536，并使合成回执输出20000tokens、其中reasoning17000，覆盖原16384天花板。原600上游/660Hermes读超时沿用，原8工具结果完整保留、二次用户轮/取消/幂等继续验收。

原WIRE8受控publisher覆盖3实际改源（proxy/worker/shared provider）与339其它保护；不修改publisher、网络、模型/密钥、权限、价格、订单、消息、采集频率或关闭状态。先最终CI/独立复核/合并，后备份/CAS发布/独立读回，再新任务。已有费用回执保留，缺失无需逐指纹确认。

暂无Hermes完整可读报告，不把技术通过当业务完成。Library物化独立阻塞及旧顾问/桌面后置不停止修复。
