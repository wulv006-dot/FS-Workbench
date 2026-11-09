# 连接器传输与镜像验收补充

截至 2026-11-09，发布负责人已确认线上 DCR 更新回执 `updated_anonymous_entry_verified`；此记录不等于 ChatGPT/Codex 完整授权和业务查询验收。

## 当前已部署版本

- 测试源码：`1d9ebb452772e8aa6f5dddca8fa85a9cf8382d95`；合并：`f291f5306df70b5af7dfc3c526c6e14dc33f7aa3`。
- 线上镜像：`sha256:abfab1a8a0f5abed1591a0d71c66c833dba068c62ca62644708aa14639e03b59`；原镜像：`sha256:3caead07927408c26da245d25ad3aeeef8ba795a8b0936b2e909b772b85dc152`。
- 导出包 SHA256：`8320c07f39c9098401c764a977b73258eb2d80463bb0f21878203d0811e916ff`，62298140 字节。详细构建与隔离测试见 `dcr-image-receipt.json`；依赖见 `runtime-pip-freeze.txt`。
- 183 新镜像内 auth/server/portal 57 项通过，0 失败、0 skip；实际 HTTP DCR native/web 均 201，8 个核心非法字段形态均 400。测试只创建两个隔离客户端，没有真实用户授权。
- 183 匿名入口检查通过：双 metadata、无 token MCP 401/challenge、4 资产 200、CSP、未知路由 404；测试容器已删除。
- 187 发布负责人回执：`/var/backups/fs-data-connector/dcr-1d9ebb/receipt.json`。镜像更新沿原 unit 严格 CAS，仅重启独立 connector；OAuth 目录与 nginx 保持。

## 执行与恢复

187 必须用 `/opt/python39/bin/python3 -B` 执行部署预检/更新脚本；系统 `python3` 的 `ssl` 导入失败，不可作为该主机的执行入口。历史准备阶段解包和 docker load 已成功后出现该错误，发布负责人沿原 stage 改正确解释器继续，没有重放安装。

首次安装曾在 nginx reload 后立即读到旧 worker 的 404。发布负责人没有重放安装，同 release 只读复核后通过 TLS、双 metadata、401/challenge、4 资产、CSP、404、dashboard 302 和镜像/监听核对。安装与更新现通过最长 10 秒的只读 metadata 等待吸收该竞态，不重复 reload 或服务写入。原服务状态保持；历史 timer 差异仅为自然 running/waiting 切换。

`update_connector_image_187.py` 默认保留本次 DCR 版本。下一已审核版本的小 runner 可设置 `OLD_IMAGE`、`REVISION`、`MERGED_COMMIT`、`BACKUP` 及 `base.BACKUP` 后复用同一 check/apply/rollback；不得重放首次 install。回退仍核 unit/backup SHA；容器存在时核镜像，不存在时只允许 failed/inactive unit 恢复旧镜像。

## 未完成与范围

当前用户范围为 FS 业务数据、取数方法及口径，由用户自有 AI 分析报告。Hermes 技能候选未激活，相关后续测试与发布已停止。新的业务目录及相同 resource 参数兼容修改尚待固定版本镜像，不能据本回执宣称已上线。

ChatGPT 正常 UI 曾返回 does not implement OAuth；尚未通过真实 ChatGPT 授权。只读检查确认现役 TLS 使用 Mozilla CA 校验及 IP hostname 校验通过（Let's Encrypt YE1），MCP GET 返回 401 与正确 challenge；vhost 存在先于 location 的 IP/UA 条件门，但尚未证明本次云请求被该门拒绝。现有已发布 metadata location 关闭访问日志；仅看到历史双带路径 metadata 404，未发现可证实的 root fallback 请求，不据此新增 alias 或修改访问限制。
