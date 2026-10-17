import sys, re
sys.path.insert(0, "/opt/d4follow")
import core_dd373_cost as C
try:
    tr = C._tree_disk_load()
    h = C._get(C._short_url(tr["NA East|zikel"]["url_seg"]), tries=1)
    if C._blocked(h):
        print("BLOCKED len=%d" % len(h))
    else:
        print("OK len=%d num=%d" % (len(h), len(re.findall(r'class="goods-num"', h))))
except Exception as e:
    print("ERR %r" % (e,))
