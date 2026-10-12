# -*- coding: utf-8 -*-
"""把本批改动同步到 play187（47.85.224.112）。

本批只改前端文案，所以**只有 `index.html` 需要上线**（静态文件，nginx 直接读，
无需重启 mlb-online）。其余三个文件（DEPLOY_NOTES / 两个测试）只入库不上线。

流程（与 _server_deploy_gate.py 同一套姿势）
--------------------------------------------
① 备份线上现有文件到 /opt/_bak_mlb_<date>_copy/
② base64 分块上传（本地含中文路径，scp/ssh -o 上传会 255）
③ 远端 base64 -d 落盘 → chmod → **md5 双向回验**
④ 通过 nginx 与直连两种方式抓线上字节，确认新文案真的生效

用法: _server_deploy_copy.py [plan|go]
"""
from __future__ import annotations

import base64
import hashlib
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent          # 仓库根
KEY = ROOT / "共享资源" / "新服务器密钥" / "云服务器187_运营在线数据平台.pem"
HOST = "root@47.85.224.112"
STAMP = "20261012_copy"
BAK = "/opt/_bak_mlb_%s" % STAMP
CHUNK = 3400

# (本地相对路径, 远端绝对路径, 权限)
FILES = [
    ("共享资源/MLB新卡上架/web/index.html",
     "/var/www/mlb-online/index.html", "644"),
]


def ssh(cmd: str, timeout: int = 180) -> str:
    r = subprocess.run(
        ["ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=20", HOST, cmd],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
    return (r.stdout or b"").decode("utf-8", "replace")


def sha(path: Path) -> str:
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def upload(local: bytes, remote: str, mode: str):
    b64 = base64.b64encode(local).decode("ascii")
    tmp = remote + ".b64"
    # ⚠️ 父目录一律**字符串切分**求：Windows 的 Path(...).parent 会给
    #    '\opt\a\b'（反斜杠），丢给 bash 被当转义符吃掉 → 在当前目录建垃圾目录。
    parent = remote.rsplit("/", 1)[0] if "/" in remote else "."
    ssh("mkdir -p %s && rm -f %s" % (parent, tmp))
    for i in range(0, len(b64), CHUNK):
        ssh("printf '%%s' '%s' >> %s" % (b64[i:i + CHUNK], tmp))
    ssh("base64 -d %s > %s && rm -f %s" % (tmp, remote, tmp))
    ssh("chmod %s %s" % (mode, remote))


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    print("=" * 70)
    print("本批上线（只前端文案）  目标 = %s" % HOST)
    print("=" * 70)

    print("\n① 本地文件")
    locals_ = {}
    for rel, remote, perm in FILES:
        p = ROOT / rel
        if not p.is_file():
            print("  ✗ 本地缺:", rel)
            return 1
        locals_[rel] = sha(p)
        print("  %-46s %8d B  md5 %s" % (rel, p.stat().st_size, locals_[rel]))

    print("\n② 远端现状")
    for rel, remote, perm in FILES:
        print("  " + ssh("md5sum %s 2>&1; ls -la %s 2>&1" % (remote, remote)).rstrip())

    if mode != "go":
        print("\n[plan] 只预演，未做任何写入。执行请加 go")
        return 0

    print("\n③ 备份")
    ssh("mkdir -p %s" % BAK)
    for rel, remote, perm in FILES:
        ssh("cp -p %s %s/ 2>&1" % (remote, BAK))
    print("  " + ssh("ls -la %s" % BAK).rstrip())

    print("\n④ 上传 + 回验")
    ok = True
    for rel, remote, perm in FILES:
        upload((ROOT / rel).read_bytes(), remote, perm)
        rem = ssh("md5sum %s" % remote).split()[0] if ssh("md5sum %s" % remote) else ""
        same = (rem == locals_[rel])
        ok = ok and same
        print("  %s  remote md5 = %s  → %s" % (remote, rem, "一致" if same else "❌ 不一致"))

    print("\n⑤ 线上实抓（确认新文案真的生效）")
    # ⚠️ 必须走**直连端口**抓内容：nginx :80 上有统一鉴权（auth_request），
    #    未登录一律 302 → /__auth/login，抓回来的是登录跳转，grep 文案永远是 0，
    #    看起来像"部署失败"，其实只是没带 Cookie。
    probe = (
        'echo "  直连 :8897（应用本体，绕过 nginx）";'
        ' curl -s -o /tmp/_new.html -w "    HTTP %{http_code}  %{size_download} B\\n"'
        '   http://127.0.0.1:8897/;'
        ' echo -n "    新文案「一张新卡 = 一个模型」命中 = ";'
        ' grep -c "一张新卡 = 一个模型" /tmp/_new.html;'
        ' echo -n "    新表头「渠道产品」命中 = ";'
        ' grep -c "渠道产品" /tmp/_new.html;'
        ' echo -n "    旧文案「48 个产品」命中（应为 0）= ";'
        ' grep -c "48 个产品" /tmp/_new.html;'
        ' echo "  nginx :80（鉴权门禁应完好）";'
        ' curl -s -o /dev/null -w "    /mlb/ -> %{http_code} %{redirect_url}\\n"'
        '   http://127.0.0.1/mlb/;'
        ' curl -s -o /dev/null -w "    /mlb/api/health -> %{http_code} %{redirect_url}\\n"'
        '   http://127.0.0.1/mlb/api/health;'
        ' echo "  服务";'
        ' systemctl is-active mlb-online'
    )
    print(ssh(probe))

    print("\n⑥ 结果:", "全部一致 ✅" if ok else "有文件不一致 ❌")
    print("回滚: ssh -i <pem> %s 'cp -p %s/index.html /var/www/mlb-online/index.html'"
          % (HOST, BAK))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
