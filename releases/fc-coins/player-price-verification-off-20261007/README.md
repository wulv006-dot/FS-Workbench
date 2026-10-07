# FC 球员价格复验退役：生产源码回补

2026-10-07 用户明确要求取消球员售价同步的主动核查，并部署到服务器，解除 wiki 展示卡导致的自动金币改价阻塞。本目录保存已经部署的六份精确源码；2026-10-08 只读服务器 SHA-256 再次与全部六文件一致。本 PR 不重新部署、不触发真实改价。

业务负责人：吴律。Git 基线：`364f7cc66ee07aa61f6e3a4a4cef0fe97923cda8`。实际映射、完整字节数及 SHA-256 见 [SOURCE-MANIFEST.json](SOURCE-MANIFEST.json)，仓库索引见 `docs/collaboration/SOURCE-MAP.json` 的 `fcPlayerPriceVerificationOff20261007`。

- category 算价保留一次后台请求及原身份、配置、已确认金币输入保护，移除请求前后球员抽样、售价与价格公式复验。wiki 展示卡没有有效售价不再因此拦截。
- 仅 job/ledger 双记录精确关联、已成功返回请求后的历史 `player_sample_readback_timeout` 豁免阻塞。未知/拒绝请求、缺账本、错关联、遗漏联动及排队/运行仍阻塞；不改写历史失败，不重放旧任务。
- API/页面明确 `price_verification=disabled`；`confirmed` 只表示请求成功返回，不表示球员售价已验证生效。金币核验、上新/图片校验及既有角色、定价、赠送、平台护栏和调度继续按各自合同执行。

本目录是六文件维护真源的精确回补，**不是完整部署包**。其余依赖仍为既有现场版本；整个 FC 模块维持 `legacy-unreconciled`。不要将旧 `fc27_cloud_browser/`、历史 v3/v4 候选或此目录整包覆盖服务器。后续修改这些六文件应基于本目录，并重新核当前现场和依赖，仅按实际改动发布；不得因 Git 合并自动再部署。旧清单和冻结 checker 保持原对象，旧历史源码及 PR #12 不在本 PR 修改范围。

2026-10-07 实际部署后原 timer 自然恢复，北京时间 21:59:19 创建自动周期，22:01:20 以 `no_price_change` 完成；没有新价格写入或新球员 POST。此为当日已验现场结果，不冒充本 PR 的新增线上执行。

复用原 9 项业务回归并增加六文件清单一致性检查，共 10 项。测试在临时目录和假后台中运行，禁止外部网络和子进程的隔离由既有 `pr-fast` 提供；没有读取真实球员售价。导入使用本目录三份 Python 真源与仓库已有依赖，新增路径仅映射到这组相关检查，复用原工作流。

从仓库根执行：

```text
python releases/fc-coins/player-price-verification-off-20261007/test_rule.py
```

原上线证据保存在受控本地工程 `docs/fc27-coins/player-price-verification-off-20261007/`；Git 中只包含源码、合成测试和脱敏映射，不包含真实配置、会话、运行账本、队列、数据库或生产发布脚本。合并状态、最终 commit/tree、实际 CI 结果以 PR 当前读回为准。
