# 注册权限：源码、发布材料与验收索引

本模块ID：`registration-runtime-v3`。机器可读映射：[registration-runtime-v3-index.json](registration-runtime-v3-index.json)；全仓来源入口：[SOURCE-MAP.json](SOURCE-MAP.json)。负责人沿用 [OWNERS.json](OWNERS.json) 的 portal 合同，未调整业务归属或权限。

## 当前有据版本

| 层级 | 版本 / 证据 | 使用范围 |
| --- | --- | --- |
| 索引观察的 main | `56021e9d2b7c7214a1edca185d09d02182680c60` | 集成快照；不替代生产版本 |
| 发布源码 | [2152c8c9ea2fd68be3876349299d490d38903404](https://github.com/wulv006-dot/FS-Workbench/commit/2152c8c9ea2fd68be3876349299d490d38903404) | 18发布源码及1恢复文件逐blob匹配本地材料 |
| QA checkout/合并版本 | [364f7cc66ee07aa61f6e3a4a4cef0fe97923cda8](https://github.com/wulv006-dot/FS-Workbench/commit/364f7cc66ee07aa61f6e3a4a4cef0fe97923cda8) | [run 37645305282](https://github.com/wulv006-dot/FS-Workbench/actions/runs/37645305282) completed/success；311/311数量引用已有用户/交接证据，本次未取完整日志或重跑 |
| 发布材料 | `registration-20261007163102Z` | manifest SHA `d17e695860b2300aa65470f77e89e7aa6c6e1e52bff3399a3ea3edd7365d9cb8`；tar SHA `62154dec318d7c4a80b5df7ddc0043ff85ff8b2f1a1bf2431ee4bc61aab5791f`，文件保留本地 |
| 生产证据 | 2026-10-07T16:51:09.960703+00:00 独立读回 | 21目标/25保护文件、3服务、11入口及只读存储基础检查通过；本索引任务未新读生产 |

## 从 GitHub 找到本地文件

本地统一入口为项目 `docs/LOCAL-DIRECTORY-INDEX.md`，机器绑定文件为 `docs/planning/registration-production-release-20261008/github-index/local-bindings.json`。它们保留实际盘符并通过模块ID关联本文；不在GitHub保存机器绝对路径或原始现场收据。

在本地绑定文件找到本模块的 `artifactRoot` 后，拼接映射JSON每项 `artifactRelativePath` 即为实际发布归档文件；`sha256` 校验该文件，`source.commit/path/blob` 找到确切GitHub源码。配置项 `source=null` 表示以本地批准配置和SHA为据，不把example冒充实际配置。

- 15个runtime发布文件在观察main中同路径同blob；tests/fixtures未进入生产载荷。
- 3个caller与1个recovery的候选路径及相同blob不在观察main中。映射链接固定批准commit，状态明确保留；没有恢复文件到main或认定main其他同名文件已接管。
- 原始runtime v3 ZIP与本地原源码目录属于历史冻结对象，不能因GitHub目录同名认定其等于后续main。

## 仍缺的真实验收

已部署且基础读回通过，不等于全部角色与真实账户生命周期已验收。合法readonly/editor、其他管理员逐账号登录、真实注册审批/撤销，以及生产页面“本地候选/合成演示”文案修订仍待。原始失败与旧状态快照保留；本增量只记录新索引，不关闭这些事项、不授生产操作或新账户权限。

原始配置、数据库、凭据、用户数据、日志、完整生产源码及部署包不随本索引上传。历史被拒绝/取消的原服务器QA上传不重试。
