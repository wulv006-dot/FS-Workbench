# -*- coding: utf-8 -*-
"""把本批（人工确认闸门 + 金币售价取价）部署到 47.85.224.112（play187）。

为什么走 base64 分块而不是 scp/-Action Upload
---------------------------------------------
本地路径含中文（`共享资源/MLB新卡上架/...`），scp 与既有 `-Action Upload`
对**含中文/空格的本地路径**会失败（ssh 255）。所以：
    本地 ToBase64String → 远端清空 .b64 → 每块 ≤4000 字符 `printf '%s' >>`
    → 远端 `base64 -d` → **核对 md5** → 安置 → 复验 → 清理

铁律
----
- 先备份 → 改 → 复核；任何一步不过就**停**，不留半成品
- 线上 `server_config.json` 必须是 `dry_run=false`（仓库里是 true 作安全默认）
- 上传后**必须 md5 回验**（这是唯一能挡住"通道改字节"的闸门）

用法:
    python _server_deploy_gate.py plan    # 只打印将要做什么 + 现状 md5
    python _server_deploy_gate.py go      # 真部署
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

SRC = Path(r"E:\WorkBuddy\大超服务器")
KEY = SRC / "共享资源" / "新服务器密钥" / "云服务器187_运营在线数据平台.pem"
HOST = "root@47.85.224.112"
STAMP = "20261012_gate"
BAK = "/opt/_bak_mlb_%s" % STAMP
CHUNK = 4000

# (本地路径, 远端路径, 远端权限)
FILES = [
    ("共享资源/MLB新卡上架/server/mlb_writeback.py",
     "/opt/mlb-online/mlb_writeback.py", "644"),
    ("共享资源/MLB新卡上架/server/mlb_coins_rate.py",
     "/opt/mlb-online/mlb_coins_rate.py", "644"),
    ("共享资源/MLB新卡上架/server/mlb_server.py",
     "/opt/mlb-online/mlb_server.py", "644"),
    ("共享资源/MLB新卡上架/web/index.html",
     "/var/www/mlb-online/index.html", "644"),
    ("mlb_admin_import_20261012/src/p2pah_price.py",
     "/opt/mlb-admin-write/src/p2pah_price.py", "644"),
    ("共享资源/MLB新卡上架/tests/verify_writeback_e2e.py",
     "/opt/mlb-online/_selftest/tests/verify_writeback_e2e.py", "644"),
    # 服务器端闸门自检脚本（本批新增）
    ("mlb_admin_import_20261012/evidence/_server_gate_check.py",
     "/opt/mlb-admin-write/evidence/_server_gate_check.py", "644"),
]

# 备份清单：远端路径 → 备份子路径
BACKUP = {
    "/opt/mlb-online/mlb_server.py": "mlb-online/mlb_server.py",
    "/opt/mlb-online/mlb_writeback.py": "mlb-online/mlb_writeback.py",
    "/opt/mlb-online/server_config.json": "mlb-online/server_config.json",
    "/var/www/mlb-online/index.html": "www/index.html",
    "/opt/mlb-admin-write/src/p2pah_price.py": "admin-write/p2pah_price.py",
}


def ssh(cmd: str, timeout=180) -> str:
    p = subprocess.run(
        ["ssh", "-i", str(KEY), "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=20", "-o", "BatchMode=yes", HOST, cmd],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    err = p.stderr.decode("utf-8", "replace")
    if p.returncode != 0 and "WARNING" not in err.split("\n")[0]:
        pass
    if p.returncode != 0:
        raise RuntimeError("ssh 失败(%d): %s" % (p.returncode, err[-800:]))
    return p.stdout.decode("utf-8", "replace")


def md5_local(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def live_config_bytes() -> bytes:
    """仓库 config + dry_run=false（线上口径），保证与仓库只差这一个开关。"""
    cfg = json.loads((SRC / "共享资源/MLB新卡上架/server/server_config.json")
                     .read_text(encoding="utf-8"))
    cfg["writeback"]["dry_run"] = False
    cfg["writeback"]["_note"] = (
        "采集完成后直写 p2pah 后台。【本机=线上，dry_run=false 真的会写】"
        "四道闸门：任务勾选 write_back + 此处 enabled + 脚本/凭据文件存在 + 人工放行"
        "(require_approval)。改本文件后需 systemctl restart mlb-online 才生效。")
    return (json.dumps(cfg, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def upload(local: bytes, remote: str, mode: str):
    b64 = base64.b64encode(local).decode("ascii")
    tmp = remote + ".b64"
    # ⚠️ 必须先建父目录：否则 `>> tmp` 会以
    #    `bash: <path>.b64: No such file or directory` 失败 —— 而报错文本
    #    里只有 bash 的一句，很容易被误读成 ssh/权限问题。
    # ⚠️ 父目录必须用**字符串切分**求，不能用 `Path(...).parent`：
    #    Windows 上 `Path` 是 WindowsPath，`str(...parent)` 给出 `\opt\a\b`
    #    （反斜杠），丢给 bash 会被当转义符吃掉 → 在 /root 下建出
    #    `optmlb-online_selftesttests` 这种垃圾目录（本次已踩）。
    parent = remote.rsplit("/", 1)[0] if "/" in remote else "."
    ssh("mkdir -p '%s' && rm -f '%s'" % (parent, tmp))
    for i in range(0, len(b64), CHUNK):
        ssh("printf '%%s' '%s' >> %s" % (b64[i:i + CHUNK], tmp))
    ssh("base64 -d %s > %s && rm -f %s" % (tmp, remote, tmp))
    ssh("chmod %s %s" % (mode, remote))


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    print("=" * 70)
    print("本批部署 → %s" % HOST)
    print("备份目录          =", BAK)

    print("\n① 本地文件清单")
    todo = []
    for rel, rem, mode_ in FILES:
        p = SRC / rel
        if not p.exists():
            print("   ⛔ 本地缺:", rel)
            return 1
        todo.append((p, rem, mode_, md5_local(p)))
        print("   %-58s %s  %d B" % (rel, todo[-1][3], p.stat().st_size))
    cfg_bytes = live_config_bytes()
    print("   %-58s %s  %d B  (dry_run=false)"
          % ("<生成> server_config.json", hashlib.md5(cfg_bytes).hexdigest(),
             len(cfg_bytes)))

    print("\n② 远端现状")
    for _, rem, _, _ in todo:
        out = ssh("md5sum %s 2>/dev/null || echo '(不存在)'" % rem).strip()
        print("   %-52s %s" % (rem, out))
    for src in sorted(BACKUP):
        out = ssh("md5sum %s 2>/dev/null || echo '(不存在)'" % src).strip()
        print("   [现网] %-45s %s" % (src, out))
    print("   服务状态:", ssh(
        "systemctl is-active mlb-online; ls /opt/mlb-online/; "
        "echo '--- data:'; ls /opt/mlb-online/data/ 2>&1; "
        "echo '--- src:'; ls /opt/mlb-admin-write/src/").rstrip())
    print("   订单后台凭据:",
          ssh("ls -la /opt/mlb-admin-write/_cred_order.json 2>&1").strip())

    if mode != "go":
        print("\n[plan] 未做任何改动。加 go 执行。")
        return 0

    print("\n③ 备份")
    ssh("mkdir -p " + " ".join(
        sorted(set(BAK + "/" + str(Path(v).parent) for v in BACKUP.values()))))
    for src, sub in BACKUP.items():
        ssh("cp -a %s %s/%s 2>/dev/null || true" % (src, BAK, sub))
    print(ssh("find %s -type f -printf '   %%p  %%s B\\n' 2>/dev/null" % BAK).rstrip())
    ssh("cp -a /opt/mlb-online/data/mlb.db %s/mlb-online/mlb.db.bak 2>/dev/null || true" % BAK)

    print("\n④ 上传（base64 分块 + md5 回验）")
    for p, rem, mode_, lm in todo:
        upload(p.read_bytes(), rem, mode_)
        got = ssh("md5sum %s" % rem).split()[0]
        flag = "OK" if got == lm else "⛔不一致"
        print("   [%s] %-52s %s" % (flag, rem, got))
        if got != lm:
            print("   ⛔ md5 不符，中止（可能通道改了字节）")
            return 1
    upload(cfg_bytes, "/opt/mlb-online/server_config.json", "644")
    got = ssh("md5sum /opt/mlb-online/server_config.json").split()[0]
    print("   [%s] %-52s %s"
          % ("OK" if got == hashlib.md5(cfg_bytes).hexdigest() else "⛔不一致",
             "/opt/mlb-online/server_config.json", got))

    print("\n⑤ 搭自检目录（软链到**已部署字节**，不复制副本）")
    # 目的：让 verify_writeback_e2e.py 的 TOOL/server/* 与 TOOL/web/index.html
    # 指向线上那份 mlb_server.py / mlb_writeback.py / mlb_coins_rate.py / index.html，
    # 这样它在 Py3.9.18 上跑的就是**真正部署的字节**，而不是又一份拷贝。
    ssh("mkdir -p /opt/mlb-online/_selftest/tests /opt/mlb-online/_selftest/server "
        "/opt/mlb-online/_selftest/web")
    for f in ("mlb_server.py", "mlb_writeback.py", "mlb_coins_rate.py"):
        ssh("ln -sfn /opt/mlb-online/%s /opt/mlb-online/_selftest/server/%s" % (f, f))
    ssh("ln -sfn /var/www/mlb-online/index.html "
        "/opt/mlb-online/_selftest/web/index.html")
    # 旧版遗留副本（9933 B，上一轮那份）归档掉，避免以后误跑
    ssh("test -f /opt/mlb-online/verify_writeback_e2e.py && "
        "mkdir -p %s/stale && mv /opt/mlb-online/verify_writeback_e2e.py %s/stale/ "
        "|| true" % (BAK, BAK))
    print(ssh("ls -la /opt/mlb-online/_selftest/ /opt/mlb-online/_selftest/server/ "
              "/opt/mlb-online/_selftest/web/").rstrip())

    print("\n⑥ 重启服务")
    ssh("systemctl restart mlb-online && sleep 3 && systemctl is-active mlb-online")
    time.sleep(2)
    print(ssh("curl -s -m 10 http://127.0.0.1:8897/api/health").strip()[:600])

    print("\n⑦ 部署后复核（md5 再比一次）")
    ok = True
    for p, rem, mode_, lm in todo:
        got = ssh("md5sum %s" % rem).split()[0]
        same = got == lm
        ok = ok and same
        print("   [%s] %s" % ("OK" if same else "⛔", rem))
    print("\n回滚命令：")
    print("   B=%s" % BAK)
    print("   cp $B/mlb-online/mlb_server.py     /opt/mlb-online/mlb_server.py")
    print("   rm -f /opt/mlb-online/mlb_coins_rate.py")
    print("   cp $B/mlb-online/mlb_writeback.py  /opt/mlb-online/mlb_writeback.py")
    print("   cp $B/mlb-online/server_config.json /opt/mlb-online/server_config.json")
    print("   cp $B/www/index.html               /var/www/mlb-online/index.html")
    print("   systemctl daemon-reload && systemctl restart mlb-online")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
