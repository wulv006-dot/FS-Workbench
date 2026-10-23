# FC 浏览器显示服务启动恢复（2026-10-23）

后续实际交付：主任务已于14:29:09在原空闲/写锁及Order隔离证明下发布并重启同一容器一次。宿主与容器启动SHA均为d646762e…fc28f98，DISPLAY=:0，实际CDP正常、原13 cookie名称/域指纹保持、登录判据通过；受控idle页全局Worker0，noVNC HTTP200，Order ready/login0。14:30:24原事件只读对账完成，初始因关闭后立即断言Worker数导致的unknown另存保留，没有重复重启；当前显示服务已恢复，长期及下一自然FC周期另验。以下候选阶段记录保留当时时点。

状态：根 Agent 已于 14:29:09 发布并执行一次原容器重启，14:30:24 原事件只读对账完成，未重放；本子任务仅独立读回复核。活动维护源为 `fc_browser_start_recovery_20261023/source/start.sh`，SHA `d646762e232c3dd161e4270967956368c4850bdb646bbf631924ddb86fc28f98`。原活动基线 SHA `aaf1bd6e6103c000242e8986402808915d743655724dbe822b458cbc07f831fa`，原容器脚本 mtime 为 9 月 27 日，未见此前 13:44 已修改脚本的证据。

## 故障证据

- 唯一恢复事件 `0b731584-bb72-4b8d-9134-4cf36653f62f` 于北京时间 13:15:26 开始；before_container 的 restart_count=0，StartedAt=11:33:29。
- 13:15:33 起容器日志连续报 `Missing X server or $DISPLAY`、`The platform failed to initialize. Exiting.`，Docker `unless-stopped` 策略自动拉起；后期约 62 秒一次，最后一轮失败为 13:43:35。Docker journal 同时有容器 restarting 导致 exec 失败。
- 13:44:35 容器成功启动，13:44:37 出现 DevTools listening。14:11 与 14:13 两次只读 inspect 均 RestartCount=36、StartedAt 不再变化、running=true/restarting=false/OOMKilled=false。14:13 Xvfb PID8 与 X99 lock PID8、socket 都有效。
- 只发现这一个 lifecycle 恢复事件，不是 36 次业务重放或 36 次 lifecycle 主动恢复。所查 13:10–13:47 内核日志无 OOM 选中记录；当前 OOMKilled=false 单独不能排除历史 OOM。
- Docker events 查询没有返回该区间事件，其保留范围不足以用于否定历史事件。错误日志足以证明显示服务失败，但原脚本将 Xvfb stderr 丢弃，无法追认其更细原因是陈旧锁、PID复用或启动竞态。13:44 恢复的具体动作来源尚未证明，不能编造为本任务清锁或改脚本的结果。
- `/var/lib/fc27-cloud/state/browser-lifecycle.json` 的 `verified_after_unknown` 与 reconciled_container 指向后来 13:44 的实例，原 `at/last_restart_at` 仍为 13:15 的事件时间，不能把它读成 13:15 已恢复或当前健康时间。

在 14:13 的冻结前检查时循环已停止，但固定 sleep2/固定 :99 的缺口仍在；随后 14:29 的补丁和验收单独记录如下，不能把此前 running 当作补丁完成证据。

## 最小改动

复用当前容器 Xvfb 已支持的 `-displayfd`：Xvfb 自动选择空闲显示号，并在真实可连接后向专用 FD 写编号。用容器已有 Python 标准库最多等 10 秒，收到完整合法编号且子进程仍在时 export DISPLAY，x11vnc 使用同一 DISPLAY。未就绪时保留 Xvfb stderr 到 Docker 日志，停止此次启动且不启动 Chrome；仅结束本次启动的 Xvfb 子进程。

不删除任何 X lock/socket，不检查或清理登录 profile；只删除自己 mktemp 创建的编号文件。原 Chrome 全部参数、profile、产品 URL、VNC/noVNC/CDP 端口与可视入口保持。Dockerfile 的默认 DISPLAY=:99 会被启动时 export 覆盖；只读核对 `/opt/fc27-cloud-browser` 及相关 systemd 文件，固定显示号消费者仅原 start.sh 的 Xvfb/x11vnc 及 Dockerfile 默认值，已无遗漏已知消费者。

上游依据：[Xserver 官方手册](https://xorg.freedesktop.org/releases/X11R7.5/doc/man/man1/Xserver.1.html)。本次另在实际容器执行 Xvfb -help，确认 `-displayfd fd` 说明为 “file descriptor to write display number to when ready to connect”。未在生产试启第二个 Xvfb。

## 验证与发布边界

本地 `python -m unittest discover -s fc_browser_start_recovery_20261023/tests -v` 15 项通过：就绪编号、非 99 显示、部分写入、10 秒硬限、进程退出/zombie/权限未知、非法编号、原 Chrome/profile/端口合同、无 X 锁清理。测试在 namespace 内执行真实嵌入 Python，无 subprocess/Popen，不启动业务或显示服务。根 Agent 原执行输出 chunk c08185 另记录 15 项 Linux 测试及 sh -n 通过；同条命令后续 history 数量断言曾阻断，因此不声称该整条命令全绿，后续正式发布/真实重启以独立回执为准。

根 Agent 发布时同时 CAS 宿主 start.sh 和当前容器入口，保留原字节与回执；当前 Dockerfile 的 COPY start.sh 使日后从该目录构建时使用同源。只替换运行容器内文件而不更新宿主会在重建后退回旧版，须避免。发布不等于恢复验收。

真实重启须在原 lifecycle 锁/队列/写锁空闲、Order 独立且耐久证明有效、无未对账写入时进行一次；保留原事件和 container ID，不重复未知重启。读回动态 DISPLAY、Xvfb PID/真实连接、CDP/DOM/全局 Worker、同 profile 登录、noVNC入口、Order ready，核 RestartCount/StartedAt 后续不再递增，再观察原自然采集周期。不得因此降低有效报价、身份、来源、利润或 UNKNOWN 合同。

## 14:29 发布与独立读回

根 Agent 的原事件 `f40a5ef3-c5a9-41d9-b41b-d24777e5bd25` 一次重启后，初次因异步关闭标签后立即断言 Worker=0 而记 UNKNOWN；原失败保留，没有重复重启。14:30:24 在同事件只读对账，回执 `/var/lib/fc27-cloud/recovery-receipts/browser-startup-release-20261023.json` 为 `verified_after_readonly_reconciliation`、restart_replayed=false。根 Agent 真实读回 DISPLAY=:0、CDP可用、原登录 cookie 数13、全局Worker0、noVNC200、Order ready；未向本子任务展示 cookie 内容。

本子任务 14:38:25 与 14:40:02 两次独立 inspect 均为同一原容器 b506f447…、RestartCount=0、StartedAt=14:29:09.272、Running=true/Restarting=false/OOMKilled=false。14:38 同时核宿主和容器入口均为活动 SHA d646762e…28f98，collector4d19与IGGM790c保持。计数在主动 docker restart 后重置为0，不改写此前36次历史。两个点证明所观察区间无继续重启，不代表长期自然周期或所有未来故障已验；精确时点、回执哈希与检查来源见 SOURCE-MAP。
