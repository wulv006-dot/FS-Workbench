#!/usr/bin/env bash
# 从 d4follow 同步 vendor 快照（只在确认要跟随上游成本逻辑时手动跑一次）。
# 本系统运行时**不依赖** d4follow 目录；这份快照是「复制」，不是软链。
set -euo pipefail
HERE="$(cd "$(dirname "$0")/.." && pwd)"
SRC="${1:-$HERE/../d4follow}"
cp -v "$SRC/core_dd373_cost.py" "$HERE/vendor/core_dd373_cost.py"
echo ">>> 已同步。改动处请用 '# [g2gfollow]' 标注，便于下次 diff。"
