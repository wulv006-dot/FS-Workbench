#!/usr/bin/env bash
# FC27 受控发布入口 · 宿主安装（root，一次性，可重复执行且幂等）
#
# 只做四件事：装入口、放策略（已存在则不覆盖）、确认 monitor 身份文件、打印 sudoers 片段。
# 不启停任何单元、不碰 /opt 源码、不写 /var/lib/fc27-cloud。
#
#   sudo bash releases/fc-coins/publish-entry-20261020/install.sh
#
# 需要显式声明将要放行的调用组：FC27_PUBLISH_GROUP（默认 fc27ops）。
set -euo pipefail

ENTRY=/usr/local/sbin/fc27-publish
POLICY_DIR=/etc/fc27-cloud
POLICY=$POLICY_DIR/release-policy.json
MONITOR_USER=$POLICY_DIR/monitor-user
GROUP="${FC27_PUBLISH_GROUP:-fc27ops}"

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_ENTRY="$HERE/source/fc27_publish_entry.py"
SRC_POLICY="$HERE/source/release-policy.example.json"

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "must run as root"
[ -f "$SRC_ENTRY" ] || die "missing $SRC_ENTRY"
[ -f "$SRC_POLICY" ] || die "missing $SRC_POLICY"
command -v systemctl >/dev/null 2>&1 || die "systemctl not found: not the host?"

say "== 1/5 校验源码 =="
python3 -c 'import ast,sys;ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$SRC_ENTRY" \
  || die "entry source does not parse"
sha256sum "$SRC_ENTRY"

say "== 2/5 安装入口 $ENTRY =="
install -d -o root -g root -m 0755 /usr/local/sbin "$POLICY_DIR"
install -o root -g root -m 0755 "$SRC_ENTRY" "$ENTRY"
say "installed: $(sha256sum "$ENTRY")"

say "== 3/5 策略 $POLICY =="
if [ -e "$POLICY" ]; then
  say "已存在，不覆盖：$POLICY"
  say "如需按示例重建，先人工比对：diff -u $POLICY $SRC_POLICY"
else
  install -o root -g root -m 0644 "$SRC_POLICY" "$POLICY"
  say "已放置示例策略：$POLICY"
  say "注意：示例里的 37 个目标需先用 source/calibrate.py 在宿主核对现场哈希后再启用。"
fi
python3 -c 'import json,sys;json.load(open(sys.argv[1],encoding="utf-8"))' "$POLICY" \
  || die "policy is not valid json"

say "== 4/5 monitor 身份文件 $MONITOR_USER =="
if [ -s "$MONITOR_USER" ]; then
  say "已存在（$(( $(wc -c < "$MONITOR_USER") )) 字节），不打印内容"
else
  say "缺失：写入既有 monitor 接口所需身份（例如 wulv），由有权限的人填写："
  say "  printf '%s' '<monitor-user>' > $MONITOR_USER && chmod 0600 $MONITOR_USER"
  say "该文件缺失时，发布入口会在写回读阶段失败并回退，不会静默成功。"
fi

say "== 5/5 sudoers（不自动写入，请人工确认）=="
cat <<EOF

把下面内容交给 visudo -f /etc/sudoers.d/fc27-publish（只放行这一条命令，不给 shell）：

    Cmnd_Alias FC27_PUBLISH = $ENTRY
    %$GROUP ALL=(root) NOPASSWD: FC27_PUBLISH

保存后校验：
    visudo -c -f /etc/sudoers.d/fc27-publish

用法（调用端只用这三个参数）：
    sudo $ENTRY <module> <release> <pr-number>          # 只校验
    sudo $ENTRY <module> <release> <pr-number> --apply  # 执行

EOF

say "== 自检：无参数应返回 2（usage） =="
set +e
"$ENTRY" >/dev/null 2>&1
code=$?
set -e
say "exit=$code"
[ "$code" -eq 2 ] || die "self-check failed: expected usage exit 2"
say "OK：入口已安装。本脚本没有启动/停止任何服务，也没有改任何源码。"
