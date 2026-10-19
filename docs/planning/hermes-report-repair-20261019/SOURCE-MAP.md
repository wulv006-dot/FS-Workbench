# 报告修复源码与现场映射

冻结源 commit：`3926f4500573f610b0b7438a2071bf7f6e710924`。最终文档提交可能在其后；交付前逐文件确认活动代码字节与冻结源一致。

候选清单 SHA256：`dd88f7b435f4b23d852317762f270bf0c7c6d8db39ec7e15dde89aaf4a2eeaf0`。发布及读回状态见 ACCEPTANCE.md 与项目 HANDOFF.md。

固定14个替换文件、358个保护文件，合计372路径。原发布器仍有锁、CAS、备份、在途任务检查及只读业务边界。历史清单不改写，后续变更重新读取基线。

| 本任务 source/ | 活动运行路径 | SHA256 |
|---|---|---|
| source/controller.py | /opt/fs-hermes-fc/controller.py | `01e2687ea0a6a2786808bdac158340de6f51cc00e7cbf77cdef753bd4da7e774` |
| source/es_order_structure.py | /opt/fs-hermes-fc/es_order_structure.py | `b0d90693420c85d7099a80cffdec1dbd0031d7ef36e78fc241576e8c9bd0e68e` |
| source/evidence_access.py | /opt/fs-hermes-fc/evidence_access.py | `27c85f4f21cd293e23f07cc7f5becd3117c4c1ba0d22a9ca6d01ea988f84b27d` |
| source/fs_evidence.py | /opt/fs-hermes-fc/fs_evidence.py | `18de6ffe03bf10edbabf5654e01d8d030a3bfffaede372e1b5a46a330406025d` |
| source/html_check.py | /opt/fs-hermes-fc/html_check.py | `35d26533e498126a72584dcc8478d0b3e5f5f5c64fa3d537b0a6bb0c01c82fb2` |
| source/management_context.py | /opt/fs-hermes-fc/management_context.py | `c0dafc3e10847eb82c90d4fd9e37b96cffbe4d0b09bfe11bb55bb76c7d7a4d06` |
| source/marketing_snapshot.py | /opt/fs-hermes-fc/marketing_snapshot.py | `2c4fcd655501358f126f535e7dc24d9afb1a104416c8ea54f65e2c9f7271e9c7` |
| source/research.py | /opt/fs-hermes-fc/research.py | `9bbb3ba2756c66cba5475b55dc541fcc3dd6a7b31ffe15004565081805b53c27` |
| source/source_snapshots.py | /opt/fs-hermes-fc/source_snapshots.py | `c8b3c5977838a36641813dccf8df3e0c0013447989d757505fe59ebc51d516e7` |
| source/brain-index.html | /var/www/dashboard/fs-home/brain/index.html | `6dc682983ea06f479c8032fe85efc451e70ebc9ad78169770525d1196606deb4` |
| source/brain.js | /var/www/dashboard/fs-home/brain/brain.js | `94497730990e143d8ada2143691c97788af0fa0de84db2bbcf3dbc74b654beea` |
| source/continuation.py | /opt/fs-hermes-fc/continuation.py | `8af613072e82c08d13cc2c07d391fcf3f591a96066f139e5b853e1f889b84169` |
| source/nightly.py | /opt/fs-hermes-fc/nightly.py | `c290311ae1eee043b8e1c11a00a1cc676300ab8ea38f88ddffa1f903f9f03130` |
| source/management-live.js | /var/lib/fs-navigation-formal-static/workspace-native-20261006-5a791c9d741a/management/management-live.js | `d05fd6e91642e4a8f8c5fec2ab6da89b7e5958ae96804214723d1af28ddb16d8` |

交付 deploy/baseline-paths.json 是本轮发布及单独授权的学习更新完成后的精确盘点，不是永久有效线上状态，也不是历史发布清单。历史替换前基线、候选、清单及备份原样保留；未来修订须重新盘点，不能修改旧清单哈希绕过。

回滚仅使用本轮实际备份，先确认无在途模型、会话、客单追踪及来源读取任务，再走原发布器 rollback；不得直接复制旧包覆盖。业务数据、订单、价格、权限和系统定时器不在此回滚范围。

原始报告、完整证据、客户资料、知识正文、运行数据库及凭据未进入私库。
