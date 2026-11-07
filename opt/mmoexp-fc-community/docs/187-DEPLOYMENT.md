# 187 独立部署候选

**2026-11-06已实施更新：**本服务已独立部署并确认Discord测试群就绪。目标187默认Python缺SSL，因此实际使用 `/opt/python39/bin/python3.9` 新建 `/opt/mmoexp-fc-community/.venv-ssl`；所有下方安装命令中的系统python3和`.venv`应按此替换。服务模板已适配旧systemd（ProtectSystem=full、ReadWriteDirectories、MemoryLimit）。新服务资源限制已验证；其他服务未修改。应用和就绪状态见README。下方步骤保留为初版说明，重新部署应使用更新的install-staged.sh并先核对现有目录，不能再次直接运行首装步骤覆盖当前服务。

此文件和 systemd 单元只是部署候选：尚未连接 187、创建目录或启动服务。仅用于测试群 `1565922092518613064`；运营白名单为 `1237241595674361962`，本人可以审核自己的草稿。不要覆盖或修改现有机器人、服务和数据。实际执行前应先确认应用已安装到测试群，且已获本次部署授权。

## 目录与权限

- `/opt/mmoexp-fc-community`：独立程序工作目录，代码、配置和虚拟环境由 root 管理。
- `/opt/mmoexp-fc-community/var`：SQLite 持久目录，由专用非 root 用户 `mmoexp-fc-community` 拥有；配置中的相对路径 `var/community.sqlite3` 基于服务工作目录。
- `/etc/mmoexp-fc-community.env`：root 拥有、权限 `0600` 的运行环境文件。仓库示例不包含 Token；不要将实际文件或 Token 提交、上传到聊天或记录在命令历史中。

## 安装步骤（待授权后由操作人员执行）

先确认以上用户、目录、环境文件和 `mmoexp-fc-community.service` 名称尚未被其他用途占用；若已存在，停止并核对，不覆盖。以下命令在已核对的项目目录中执行，仅使用本项目文件：

```sh
sudo useradd --system --user-group --no-create-home --shell /usr/sbin/nologin mmoexp-fc-community
sudo install -d -o root -g root -m 0755 /opt/mmoexp-fc-community
sudo install -d -o mmoexp-fc-community -g mmoexp-fc-community -m 0700 /opt/mmoexp-fc-community/var
sudo install -o root -g root -m 0644 content_bot.py community.py requirements.txt /opt/mmoexp-fc-community/
sudo install -o root -g root -m 0644 content.config.example.json /opt/mmoexp-fc-community/content.config.json
sudo python3 -m venv /opt/mmoexp-fc-community/.venv
sudo /opt/mmoexp-fc-community/.venv/bin/python -m pip install -r /opt/mmoexp-fc-community/requirements.txt
sudo install -o root -g root -m 0600 deploy/mmoexp-fc-community.env.example /etc/mmoexp-fc-community.env
sudo install -o root -g root -m 0644 deploy/mmoexp-fc-community.service /etc/systemd/system/mmoexp-fc-community.service
```

使用受控的 root 编辑器将新应用的 Bot Token 填入 `/etc/mmoexp-fc-community.env` 的 `DISCORD_BOT_TOKEN=`，不要粘贴到命令行或聊天。确认配置中群 ID、运营 ID 和数据库路径与上述一致。之后先以服务身份执行离线检查，不会连接 Discord：

```sh
cd /opt/mmoexp-fc-community
sudo -u mmoexp-fc-community .venv/bin/python content_bot.py --config content.config.json --check
sudo .venv/bin/python -m pip check
```

确认离线检查通过、应用及测试群安装就绪后，启动服务并查看状态：

```sh
sudo systemctl daemon-reload
sudo systemctl enable --now mmoexp-fc-community.service
sudo systemctl status mmoexp-fc-community.service
sudo journalctl -u mmoexp-fc-community.service -n 50 --no-pager
```

启动会连接 Discord 并同步测试群命令。按 [试用说明](CONTENT-BOT-RUNBOOK.md) 完成测试群端到端验收；服务启动或离线检查通过不等于验收通过。

## 备份与恢复

SQLite 包含报名用户 ID，备份应受限访问。最小手动备份：停止服务，确认进程已停止后，将 `var/community.sqlite3` 复制到仅受信操作人员可访问的备份位置，再按需启动服务。没有数据库时无需备份；若发现 SQLite 的 `-journal`、`-wal` 或 `-shm` 文件，先调查并确保数据库完整，勿单独复制或删除这些文件。

恢复时先停止服务并确认已停止；保留当前数据库供排查，再将确认有效的备份恢复为 `/opt/mmoexp-fc-community/var/community.sqlite3`，属主和属组设为 `mmoexp-fc-community`、权限设为 `0600`。确认无遗留 SQLite sidecar 文件后启动服务，查看状态并在测试群核对内容与报名数据。此流程未设置自动备份或保留策略。
