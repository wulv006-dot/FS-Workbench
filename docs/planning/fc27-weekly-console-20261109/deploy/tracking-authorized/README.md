# 单独授权的追踪部署候选

本包仅对应用户在整批发布被自动审批拒绝后再次明确“允许追踪”的新范围。它不包含其余17个页面/商品目标，不是执行原23文件apply的替代路径。只准备本地载荷，未上传、未发布。

- 四个 Git 源读取自 `c17bc4d7c06c71d7d2f9c34e2397b37bd5aacd2f` 的原始字节，各 SHA 与先前23目标中对应候选一致。
- 另两目标：server-local `analytics-config.js` 唯一 enabled false→true，以及110项 static manifest 仅更新该文件和 `seasonal/activity-analytics.js` 的两个哈希。
- 所有6目标使用 launch-baseline 部署前 SHA；其余59个文件保持原SHA守卫。
- release.py 仅替换原 launch-check adapter 的 TARGETS / ROLLBACK_BASELINES / len(files)=6。原publisher pins、locks、admission fence、备份、CAS、rollback及三服务激活保持。
- 配置字节不在本地包中。总控在服务器独立stage生成/复制，预期 before SHA `04bfcb6e2cb9c787ba59d0dbfa653ced169c99c4a6efc517b0a425267b0d0d2d`、候选 SHA `6d35f615619466fa1f67565ef4d2e594323a4d310120e4964f1e61a28af661e7`，仅该字段变化。补齐后才能沿原inspect/apply。

本地包：`.agent_runtime/weekly-console/tracking-authorized-stage.tar.gz`；计划服务器目录 `/opt/fs-release-stage/fc27-tracking-authorized-20261109`。

manifest SHA256：`1d8d686405640c290912688f7d1a21b984a6aa51f11aaf89944fcec0f7958b5c`

launcher SHA256：`094f912f1bb1c09185d8f578f9e9d21c89defb27dc574efe1780c0ce7d619fd2`

自检已确认6目标、59守卫、110静态条目仅2变化；tar为3元文件+5份载荷，没有配置源码；adapter除3处精确scope替换外与原字节等价。候选准备不代表生产已开启。总控是唯一审批与发布执行者。
