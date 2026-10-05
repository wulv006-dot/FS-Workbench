# FS-Workbench 首批协作源码基线

MMOEXP 游戏运营Agent。首批准备于2026-10-06标签任务，来源是冻结revision3准确311文件，保留原源码相对路径；只更新治理文档并加入最新决定与操作材料。未纳入正在开发的新UI或NBA revision4。

**可协作源码基线，不是可部署全平台包。** 用户条件批准符合标准的白名单源码/测试/文档入私库，后续今晚允许根协调自主推进普通实现。本目录待根核对最终清单与写入口，尚未commit/push。releaseReady=false，未验模块不得上线。

- 两位用户先读 [人类操作手册和AI模板](docs/collaboration/OPERATION-GUIDE.md)。
- AI每次先读 [AGENTS.md](AGENTS.md)、[OWNERS](docs/collaboration/OWNERS.json)、[当前状态](docs/collaboration/CURRENT-STATUS.md)、[SOURCE-MAP](docs/collaboration/SOURCE-MAP.json) 和现有模块合同。
- 首次上传准备与排除范围：[FIRST-UPLOAD-PLAN](docs/collaboration/FIRST-UPLOAD-PLAN.md)。后续完成情况以入库清单和根协调读回记录为准，历史准备计划中的“尚待生成”已由本目录的清单补齐。
- 最新有限复审：[FINAL-INTEGRATION-STATUS](docs/collaboration/FINAL-INTEGRATION-STATUS.md)。旧docs记录保留历史，开头更正指向当前状态；不能按旧日期宣称仍未选owner或把合成检查当生产通过。
- 完整实际上传树清单由交付方保存在ZIP外 `final-target-inventory.json`，包含所有文件和自身文档manifest的SHA。仓内两个UPLOAD-ALLOWLIST只列除这两个生成manifest外的内容集合，避免自引用哈希。

没有自动部署workflow、运行凭据、订单/实报表/私有PROFIT JSON、数据库、会话、旧Git历史。代码/配置schema/运行状态/业务授权分别管理。Git合并不自动上线；确切模块、commit与产物、现场基线、安全运行门槛和受控发布合同必须齐全。
