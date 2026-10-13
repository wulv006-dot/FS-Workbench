# Hermes FC 只读试点：第一阶段候选

状态：独立合同和离线测试已完成；尚未接通 Hermes 运行时、真实数据或模型，也未部署。2026-10-13 恢复原会话继续施工，没有新建任务或触发日报。

## 范围与来源

本地代码 `hermes_fc_pilot_20261013/`；私库候选路径 `releases/fs-dashboard/hermes-fc-pilot-20261013/`。纯文档归档于本目录。原 E 工程不 stage/commit/push。共享业务源码未改；私库仅给既有 `tools/pr_fast.py` 增加独立受影响测试组，保留捆绑包等已有分组。

施工主文件 Library `libfile_b12d6f8e7df88191a0f23719996973f6` 正文492行已读取。当前 Windows 官方物化过程在身份写回阶段失败，原 Markdown 和 Word 未归档成功，不能把本目录说明当原件。详情见 `library-materialization.json`。顾问交接中所列原件相对路径在本地检查不存在；未假定其云端路径可访问。

## 最新依赖

顾问 PR107 merge `7359c004ea15e343439ff9a26f96daca0b1aa4e4`，revision10正式页面和报告已由原 owner 验收，Git/生产/模型窗口已释放。原 owner 最终交接为 `docs/planning/fc-deep-advisor-20261013/DELIVERY.md`；其148分析+9发布测试属于顾问验收，不算 Hermes 测试。

本任务于2026-10-13T14:12:38Z只读复核：fc_deep_model=`15965d1d331444635dd8ef677cacb2f05d2e21fa6c33ff6ae7bf53315b76b067`；range=`d4a702c54319ba464271587822d6b5e0b5671bfb141af4dc4aefc34024f1a70a`；boss=`ab8e249864fdee350d3d35cdf83995e473112b17f86281a331f14581a65d189c`，均符合最终交接。顾问09:15首次自然周期仍待原任务后续观察，未补跑。

私库 main 已进一步合入捆绑包：`31708cf8fe22d02a7fa968769c7c6c88e60b31ef` / tree `2a7d8766b057e9be62ff6ee5def9c6572bcaaf5b`。不能用 PR107 的旧 CI 文件覆盖新分组。`source-runtime-mapping.json` 保留13:11的历史精确映射，PR106模型SHA已被上述现场替代。

## 已证实可复用的能力

`capability-catalog.json` 区分历史、代码存在与现场读回。现有准确区间、FCDetails同次采集、报告历史、模型调用账本和 provider_slot 可复用；没有把顾问内部 request_model 宣称为现成 Hermes 网关。原接口只做单次、非流式报告生成，没有 tools/tool_choice 代理。数据采集最长等待920秒，必须先异步准备分析快照，再让模型快速查询，不应延长普通工具超时或恢复两小时全页缓存。

## 固定版本与实现

官方 Hermes v0.21.7，commit `71d34bad1045610252eda02ee79549436896e784`。仅根据官方仓库固定源码核验 Runs API、持久幂等、停止和 MCP 名称；详情 `hermes-source-pin.json`。生产 Python3.9不满足候选包要求，隔离 Python3.14运行时尚待验证，原Python不升级。

代码已提供任务持久化、owner隔离、同输入幂等、未知派发阻断、单并发、lease/CAS、中断状态、取消确认与真正停止分离、聚合证据投影、五工具白名单、估算和缺口、报告引用/数字核验，以及固定版本 Runs 协议检查。它是可执行的离线基础，不是完整网关、MCP服务或生产监督器。

## 验证及局限

运行 `python -B -m unittest discover -s hermes_fc_pilot_20261013 -v`：29项不同测试通过，0失败/错误/跳过，Windows Python3.14.7。初次数据库未关闭导致的Windows清理失败已修复；中间重复加载导致53次执行不作为53项用例。私库 CI 另留精确提交回执。

未验证：Linux隔离运行时、Hermes实际工具发现、真实模型tool-call/usage、FS身份与界面、停止后的实际线程/进程释放、真实周业务质量。当前token计数属于事后合同检查，不能宣称硬预算已实施。自由文本因果质量仍须人工评估。

## 后续施工与授权

具体接口和验收见 `CONTRACT.md`、`EVALUATION.md`；需要主对话确认的身份/网络动作与撤销见 `ACCESS-AND-RELEASE.md`。先独立草稿PR/CI，再补模型代理、运行监督和真实只读适配；最终CI/合并后经唯一发布者受控上线、备份和独立读回。初期结果只进入专用区域。Portal授权是用户本人研究，本任务未触发登录、未使用其额度或撤销授权。
