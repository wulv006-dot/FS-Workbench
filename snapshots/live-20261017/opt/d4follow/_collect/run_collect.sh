#!/bin/sh
# D4 采集一轮触发器（与页面上手动点「采集一轮」完全同一条代码路径）
# 说明：
#   - 打本机 127.0.0.1:8900，不依赖任何公网 IP，迁移/换机后无需改地址
#   - spawn() 自带并发锁：已有任务在跑时接口返回 409，本轮自动跳过，不会叠跑
#   - stdout/stderr 由 systemd 单元重定向到 /opt/d4follow/logs/auto_collect.log
#     （CentOS 7 的 systemd 219 不支持 StandardOutput=append:，只能这样落盘）
exec /usr/bin/curl -sS --max-time 900 -X POST http://127.0.0.1:8900/api/task \
  -H "Content-Type: application/json" \
  -d '{"kind":"collect"}'
