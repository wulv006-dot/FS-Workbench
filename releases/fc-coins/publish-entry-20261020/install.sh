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

# 安装会建立“长期以 root 替换指定文件并重启三个单元”的权限，必须显式声明已获授权。
if [ "${FC27_INSTALL_AUTHORIZED:-}" != "1" ]; then
  cat >&2 <<'EOM'
REFUSED: 这是持久发布权限的安装，需要单独授权，CI 通过不构成授权。

确认以下三项都已明确后再运行：
  1) 谁授权（人）、授权到哪一版入口（本目录 source/fc27_publish_entry.py 的 sha256）；
  2) 范围（模块 fc-coins + 策略里的目标清单 + 三个单元）；
  3) 时间窗与回滚方式（README §7.5 的卸载命令）。

确认后： FC27_INSTALL_AUTHORIZED=1 sudo -E bash install.sh
EOM
  exit 3
fi
[ -f "$SRC_ENTRY" ] || die "missing $SRC_ENTRY"
[ -f "$SRC_POLICY" ] || die "missing $SRC_POLICY"
command -v systemctl >/dev/null 2>&1 || die "systemctl not found: not the host?"

say "== 1/6 校验源码 =="
python3 -c 'import ast,sys;ast.parse(open(sys.argv[1],encoding="utf-8").read())' "$SRC_ENTRY" \
  || die "entry source does not parse"
sha256sum "$SRC_ENTRY"

say "== 2/6 宿主检出 /opt/fc27-workbench =="
CHECKOUT=/opt/fc27-workbench
if [ -d "$CHECKOUT/.git" ]; then
  if git -C "$CHECKOUT" rev-parse --verify -q refs/remotes/origin/main >/dev/null; then
    say "检出存在：$(git -C "$CHECKOUT" rev-parse --short refs/remotes/origin/main)"
  else
    say "警告：$CHECKOUT 没有 refs/remotes/origin/main；先以 root 执行 git -C $CHECKOUT fetch --prune"
    say "否则发布入口会以 release_not_on_main 失败（fail-closed，不会误发）。"
  fi
else
  say "缺失：发布入口只读 $CHECKOUT 的 git 对象，不读工作区。私有仓库需 root 侧凭据："
  say "  git clone <repo-url> $CHECKOUT && chown -R root:root $CHECKOUT && chmod -R go-w $CHECKOUT"
  say "  git -C $CHECKOUT fetch --prune     # 该 fetch 会联网，是 root 单独执行的运维动作，不属于发布入口"
  say "未建检出时所有发布都会 fail-closed。"
fi

say "== 3/6 安装入口 $ENTRY =="
# Preserve existing directory permissions; never follow an installation symlink.
ensure_directory() {
  local directory="$1" mode="$2"
  [ ! -L "$directory" ] || die "symlink directory: $directory"
  if [ -e "$directory" ]; then
    [ -d "$directory" ] || die "not a directory: $directory"
    say "preserved: $(stat -c '%n %U:%G %a' "$directory")"
  else
    install -d -o root -g root -m "$mode" "$directory"
  fi
}
ensure_directory /usr/local/sbin 0755
ensure_directory "$POLICY_DIR" 0755
ensure_directory "$POLICY_DIR/authorizations" 0700
ensure_directory "$POLICY_DIR/authorizations/fc-coins" 0700
[ ! -L "$ENTRY" ] || die "symlink entry: $ENTRY"
[ ! -L "$POLICY" ] || die "symlink policy: $POLICY"
install -o root -g root -m 0755 "$SRC_ENTRY" "$ENTRY"
say "installed: $(sha256sum "$ENTRY")"

say "== 4/6 策略 $POLICY =="
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

say "== 5/6 monitor 身份文件 $MONITOR_USER =="
if [ -s "$MONITOR_USER" ]; then
  say "已存在（$(( $(wc -c < "$MONITOR_USER") )) 字节），不打印内容"
else
  say "缺失：写入既有 monitor 接口所需身份（例如 wulv），由有权限的人填写："
  say "  printf '%s' '<monitor-user>' > $MONITOR_USER && chmod 0600 $MONITOR_USER"
  say "该文件缺失时，发布入口会在写回读阶段失败并回退，不会静默成功。"
fi

say "== 6/6 sudoers（不自动写入，请人工确认）=="
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

