#!/bin/sh
# ============================================================
# 钉钉密钥一键配置 · 用法（在服务器上执行）：
#     sh /opt/d4follow/set_dingtalk_secret.sh
# 然后粘贴从钉钉后台复制的密钥，回车即可。
# 脚本会：写文件 → 设权限 → 自动跑签名自检
# ============================================================

echo "=============================================="
echo " 钉钉密钥配置（AION2 金币监控）"
echo "=============================================="
echo ""
echo "请粘贴从钉钉群机器人设置里复制的密钥："
echo "  · 形如 SECabc123... 的整串，或只有后面的十六进制也行"
echo "  · 粘贴后直接回车（Ctrl+V 通常也能用）"
echo ""
printf "密钥："
read SECRET

if [ -z "$SECRET" ]; then
  echo "❌ 没读到内容，已退出。密钥没改动。"
  exit 1
fi

# 去掉首尾空白与可能混入的引号
SECRET=$(printf '%s' "$SECRET" | tr -d ' \t\r\n"\047')

if [ -z "$SECRET" ]; then
  echo "❌ 去掉空白后为空，已退出。密钥没改动。"
  exit 1
fi

echo ""
echo "已读入密钥，长度 ${#SECRET}（正常是 64或 67 位：67 = 含 SEC 前缀）"
echo ""

cd /opt/d4follow || exit 1

# 写入 dingtalk.env：只替换 DINGTALK_SECRET 行，webhook 行原样保留
/opt/d4follow/venv/bin/python - "$SECRET" <<'PYEOF'
import io, re, sys, os
secret = sys.argv[1]
path = "/opt/d4follow/dingtalk.env"
lines = open(path, encoding="utf-8").read().splitlines() if os.path.exists(path) else []
out, done = [], False
for ln in lines:
    if ln.strip().startswith("DINGTALK_SECRET"):
        out.append("DINGTALK_SECRET=" + secret)
        done = True
    elif ln.strip().startswith("DINGTALK_WEBHOOK"):
        out.append(ln)
    else:
        out.append(ln)
if not done:
    out.append("DINGTALK_SECRET=" + secret)
    # 凭据不入库：webhook 从环境变量注入（部署时由运维在服务器上填写）
    out.append("DINGTALK_WEBHOOK=" + os.environ.get("DINGTALK_WEBHOOK", ""))
open(path, "w", encoding="utf-8").write("\n".join(out) + "\n")
print("[写入完成] /opt/d4follow/dingtalk.env")
PYEOF

if [ $? -ne 0 ]; then
  echo "❌ 写入失败，密钥未生效。"
  exit 1
fi

chmod 600 /opt/d4follow/dingtalk.env
echo "[权限已设] 600"
echo ""
echo "----------------------------------------------"
echo " 自动签名自检（会试 4 种签名口径，各发一次）"
echo "==============================================="
rm -rf /opt/d4follow/__pycache__
/opt/d4follow/venv/bin/python /opt/d4follow/dingtalk_selftest.py
RC=$?

echo ""
if [ $RC -eq 0 ]; then
  echo "=============================================="
  echo " ✅ 通了！钉钉群里应该已经收到一条自检消息。"
  echo " 15 分钟采集 / 每 4 轮推送会自动开始工作。"
  echo " 想立刻推一条完整报告："
  echo "   cd /opt/d4follow && venv/bin/python aion2_watch.py --force-push"
  echo "=============================================="
else
  echo "=============================================="
  echo " ❌ 仍不通。两种可能："
  echo " 1) 密钥还是复制错了 → 回到群里再复制一次，"
  echo "    注意必须是**这个**机器人的密钥。"
  echo " 2) 机器人后台的安全设置不是「加签」而是「关键词」"
  echo "    → 那 SECRET 留空即可，改为在群里发消息告诉我。"
  echo "=============================================="
fi
exit $RC
