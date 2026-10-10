# 本次发布与回滚

已在用户授权下发布。以下回滚方案准备完成，尚未执行成功回滚。每步先检查当前 SHA、保护路径、活动来源及本次 journal；使用现有发布器与准确清单，不覆盖私有 DB、报表或队列，不修改所有权保护。

完整恢复原版本需按依赖逆序执行；不能先回滚初始前端，因为当前 range 修复改变了它的受保护路径。

1. `python3 /opt/fs-business-live-entries-20261010-850d6ef3/release_workspace.py rollback --backup /var/backups/fs-navigation-native-20261006/workspace-native-20261006-f799b2a81b51 --approved-manifest-sha 10a98261918eb2e7bdf2ab2016c1625b86d0f4c9820dfb214ffc354d0a2c32be`
2. `python3 /opt/fs-business-live-stale-20261010-d90b6b65/release_navigation.py rollback --backup /var/backups/fs-navigation-20261006/nav-20261010T070300Z --approved-manifest-sha f54579bd0e53fd789096c3e065d861b3701ba5ddbc916e60b688454b1f350ca1`。仅 range 重启。
3. `python3 /opt/fs-business-live-release-20261010-888eb95e/frontend/release_workspace.py rollback --backup /var/backups/fs-navigation-native-20261006/workspace-native-20261006-cd6876c8a22a --approved-manifest-sha ecbb8c141d793a1ba7d643a0eb0827eb577a6c448603fa18d5244a4671f42ae9`
4. `python3 /opt/fs-business-live-release-20261010-888eb95e/backend/release_navigation.py rollback --backup /var/backups/fs-navigation-20261006/nav-20261010T065200Z --approved-manifest-sha 4b187d3664f8f472423bb083add6b9a028d794376698f5fc69431b981d8ec472`。恢复旧 session 镜像与 range；session 现有 Requires 关系可能间接重启 worker，执行前确保业务空闲。

每步完成后核对文件、镜像、受保护路径及真实页面。遇 peer drift、pending、CAS 失败立即停止。第一步恢复的 CD 入口本身有已知旧版本引用缺陷，因此完整回滚必须连续推进至原 F6 前端，不将中间状态当作完成。

此前直接尝试第三步被 range 保护路径漂移检查拒绝，没有写入；记录保留，不修改旧清单绕过检查。若只回滚某一修复，先核实其受保护路径仍吻合，不能跳过依赖。
