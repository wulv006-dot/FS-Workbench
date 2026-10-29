# cloud15 原发布器窄适配候选

来源：`fc27_players_cloud/deploy/upgrade_cloud9.py` 原发布器；只适用于当前cloud14→cloud15。尚未真实部署。

- `upgrade_direct_json.py`：保deployment.lock、原SQLite在线备份、env/unit备份、两次CAS、原子current切换与失败回滚。env不变；回滚从不恢复旧DB。仅更换Players镜像及两个实际bind的src；原readonly、user992:987、2g、Coins共用锁、旧/run目录挂载保持，不启动8767。
- `Dockerfile`：只FROM当前cloud14，并COPY player_web、球员维护工具、VERSION；无依赖安装/网络升级。
- `manifest.fixture.json`：现场49文件、镜像和配置基线模板。含明确占位SHA，验证器会拒绝原样执行。打包时移除_fixture_only、补齐最终files/archive/dockerfile SHA，仍须保所有原49 baseline映射。
- `test_upgrade_direct_json.py`：离线validator/unit/DB语义检查和完整部署成功/回滚仿真。所有systemctl/docker均替身；未运行真实命令或HTTP业务请求。仅完整main仿真用临时基线替身，独立validator用现场真实基线模板检查。

最终delta必须含VERSION、基于当前有效5d90a37f...改为主线8912的`player_web/shared_session.py`、基于当前6ec742...修订的`球员维护工具/admin_client.py`，以及本次逐人JSON实现需要的精确文件。before仍固定原5d90/6ec742；候选shared_session的SHA由最终manifest按字节检查，AST合同要求主线8912、保retired异常和原client构造/身份核对，不允许AF_UNIX或启动旧会话。两个old patch源不覆盖；在主unit和on-demand.conf把原src精确指向新release下相同相对文件，dst及readonly不变。

manifest新增字段：`base_on_demand_sha256`、`base_source_manifest_sha256`，取模板；其余沿原publisher。实际部署入口仍是该脚本接受**一个**位于`/opt/fc27-player-tool/staging/`下stage目录参数，不自动安装或启动其他服务。必须由root完成真实包、正式CI/合并及当前授权下的真实apply；本目录离线证据不能作为真实上线或新增验收。
