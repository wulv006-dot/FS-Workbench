#!/bin/sh
# ─────────────────────────────────────────────────────────────────────
# D4 清单一键刷新（按登记类目抓）· 2026-10-08
#
# 背景：D4 赛季普通（gid=456 / aid=15711）后台有 334 页 ≈6.7 万件，
#       登记在自动改价系统里的 359 个档位散落在第 31~334 页。
#       全量翻页（本机 fetch_backend_items_pw3.py --pages 30）翻不完 ⇒ 截断 ⇒
#       闸一全量判 id_gone ⇒ D4 全线停手（2026-10-05~08 整整 3 天）。
#       本脚本只抓「登记键所在的类目」⇒ 11 个类目 / 17 页 / 1 分钟 / 命中 100%。
#
# 用法：
#   sh /opt/d4follow/_p2pah_srv/refresh_d4_items.sh              # 抓 + 合并到临时文件
#   sh /opt/d4follow/_p2pah_srv/refresh_d4_items.sh 5221,8888    # 额外再抓几个类目
#   sh /opt/d4follow/_p2pah_srv/refresh_d4_items.sh --apply      # 合并后直接覆盖线上清单
#
# ⚠ 默认**不**覆盖线上清单：只产出 /tmp/backend_items.new.json 并打印
#   「登记键命中率 + 闸一预演」。确认无误后再上线（见脚本末尾提示）。
# ─────────────────────────────────────────────────────────────────────
cd /opt/d4follow || exit 1
APPLY=""
for a in "$@"; do
  case "$a" in
    --apply) APPLY="--apply" ;;
    *) EXTRA="$a" ;;
  esac
done

# ── 1) 登记类目集合：优先 item_cid.json，缺失则用内置已知集合 ──────────
# item_cid.json 结构：{"saved_at":..,"source":..,"games":{"456":{"aid":"15711","id2cid":{后台ID:cid}}}}
CIDS=$(python3 - <<'PY'
import io, json, os
p = '/opt/d4follow/_p2pah_srv/item_cid.json'
DEFAULT = ('2371,3845,3955,3957,3959,442,8793,8799,8821,10215,1591,'
           '8769,8771,8773,8787,10221,4881,1723,3675,3677')
try:
    d = json.load(io.open(p, encoding='utf-8'))
    gm = (d.get('games') or {}).get('456') or {}
    m = gm.get('id2cid') or {}
    vals = sorted(set(str(v) for v in m.values() if str(v).isdigit()), key=int)
    print(','.join(vals) if vals else DEFAULT)
except Exception as e:
    print(DEFAULT)
PY
)
[ -n "$EXTRA" ] && CIDS="$CIDS,$EXTRA"
echo "→ 登记类目 cid：$CIDS"

# ── 2) 容器内按类目抓（用容器里的登录态，免验证码）────────────────────
# 输出落盘 —— 万一 SSH 掉线，日志还在（之前那次就是丢了日志只能靠 docker logs 猜）
DUMP_LOG=/opt/d4follow/_p2pah_srv/_refresh_dump.log
echo "→ 开始抓取（约 1 分钟），日志 $DUMP_LOG …"
docker run --rm --network host --shm-size=1g --memory=3g -e P2PAH_CHANNEL= \
  -v /opt/d4follow:/srv -w /srv p2pah-srv:1 \
  python /srv/_p2pah_srv/_dump_by_cat.py --gid 456 --aid 15711 \
  --config /srv/config.json --stop-hit --only "$CIDS" \
  --dump /srv/_p2pah_srv/_d4_sel.json > "$DUMP_LOG" 2>&1
echo "RC=$?"
tail -30 "$DUMP_LOG"

# ── 3) 合并进清单（默认写临时文件）+ 闸一预演 ────────────────────────
echo ""
echo "→ 合并 + 闸一预演"
if [ -n "$APPLY" ]; then
  cp -p data/backend_items.json "data/_bak_backend_items_$(date +%Y%m%d_%H%M%S).json"
  python3 _p2pah_srv/merge_backend_items.py --dst /tmp/backend_items.new.json --apply-gate
  cp /tmp/backend_items.new.json data/backend_items.json
  echo "✅ 已覆盖 data/backend_items.json（回滚点见 data/_bak_backend_items_*.json）"
else
  python3 _p2pah_srv/merge_backend_items.py --dst /tmp/backend_items.new.json --apply-gate
  echo ""
  echo "新清单：/tmp/backend_items.new.json"
  echo "确认命中率 100% 且闸一无 D4 漂移后，执行："
  echo "    cp -p data/backend_items.json data/_bak_backend_items_\$(date +%Y%m%d_%H%M%S).json"
  echo "    cp /tmp/backend_items.new.json data/backend_items.json"
fi
