# 发布与回退范围

仅本轮七游戏及 All 经营摘要候选。合并及生产发布须核本轮明确授权，前一轮登录/流量界面的上线授权不自动扩展到这些新游戏与全部网站口径。

1. 核当前 main/head/required pr-fast 与活动来源 SHA。保留原 E 工作区未提交内容；私库 candidate release 独立，不能旧整包重放。
2. 后端复用 `deploy/release_navigation.py` 的锁/CAS/备份和自动回退；仅 scope `fs-game-dashboards-20261012`，恰好两目标。collector 写 `/opt/fs-transaction-snapshot/collector.py`，Admin 白名单写 `/opt/fc27-cloud/marketing-session-20261009/admin_summary.py`。清单不得把目标同时列为必须不变。
3. 保留已验证 current/base Session 镜像与 Dockerfile/另两 Session 源 SHA。用已有 Dockerfile 离线、禁拉取构建既有业务 Session 镜像，读回三份镜像源码 SHA；只重启 `fc27-p2pah-session.service` 与 `fs-business-range.service`，使 Admin 白名单与 collector 导入清单生效。这可能短暂影响 Admin/Order 统计读取及共用 Session；不重启 FC Worker/API、认证、任务台，不改计时器或业务写入护栏。
4. 再用 `frontend/release_workspace.py` 发布 All 前端版本。保持原登录及流量 UI；14 不可变资产/3 入口文件范围未扩展。该清单的 backend 源保护 SHA 指向本轮已经安装的两份新源码，所以不能先发前端后端。
5. 两清单候选均 ready=false。获本轮批准并核现场 CAS 后生成独立 ready 清单；原候选字节留存。先 `inspect`，再以确切清单 SHA `apply`；不能重用已成功或未知结果 ID、不清 pending。失败先查原发布 journal。
6. 真实入口验证 All 销售额/订单数和预估利润、七款选择和自定义日期，以及匿名拒绝。新游戏完整历史/快照需原下一自然采集发布后验收；不得把模拟快照或人工测试称为自然成功。原采集预算及 120 分钟计划保持。

必要回退顺序：先工作台 All 前端，再后端两源码，通过各原 publisher 和原 manifest SHA 锁内 CAS；后端恢复后重建镜像并仅恢复两统计消费者。不可删除新不可变版本、回滚数据库/订单/账本/缓存历史或恢复旧 publisher。新游戏快照历史保留；回退时若当前快照仍含新清单，不把七游戏查询视为旧版支持，等原自然快照重新一致或单独核定恢复动作。

本地候选：`fs_game_dashboards_20261012/deploy/approved-manifest.json`、`frontend/release-manifest.json` / `release-contract.json`。基线收据 `evidence/fresh-baseline.json` 仅有受保护路径哈希和公开入口代码，不含会话、凭据或客户订单记录。共享 publisher 保持现有恢复日志、symlink/ownership 检查与 collector 锁；Windows 模拟不是实际 Linux 锁或重启证明。
