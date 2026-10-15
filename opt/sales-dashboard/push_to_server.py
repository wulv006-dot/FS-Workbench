# -*- coding: utf-8 -*-
"""一键更新服务器上的销售看板。

流程：重新抓取双后台数据（可加 --no-fetch 跳过）→ 聚合 → 打包离线单文件 → scp 推到新服务器。

用法：
  python push_to_server.py             # 抓新数据 + 打包 + 推送（约2-3分钟）
  python push_to_server.py --no-fetch  # 用现有数据打包 + 推送（几秒钟）

线上地址：https://47.85.224.112/sales/ （统一登录门户鉴权）
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PY = sys.executable
SERVER = "root@47.85.224.112"
REMOTE_PATH = "/var/www/sales/index.html"
KEY_CANDIDATES = [
    Path(r"D:/共享资源/服务器/No1.pem"),
    Path(r"C:/Users/yi/.ssh_wk/No1.pem"),
]


def find_key() -> Path:
    for k in KEY_CANDIDATES:
        if k.exists():
            return k
    raise SystemExit("找不到 SSH 私钥 No1.pem，请把路径加入 KEY_CANDIDATES")


def run(step: str, *args: str) -> None:
    print(f"=== {step} ===", flush=True)
    p = subprocess.run([PY, *args], cwd=str(ROOT))
    if p.returncode != 0:
        raise SystemExit(f"{step} 失败（退出码 {p.returncode}），已中止推送。")


def main() -> None:
    if "--no-fetch" not in sys.argv:
        run("1/4 抓取双后台数据", str(ROOT / "collector" / "fetch_all.py"))
        run("2/4 聚合", str(ROOT / "collector" / "aggregate.py"))
    else:
        print("=== 跳过抓取，用现有 data/dashboard.json ===")
    run("3/4 打包离线单文件", str(ROOT / "build_offline.py"))

    key = find_key()
    out = ROOT / "销售数据看板_AION2_离线版.html"
    print("=== 4/4 推送到服务器 ===", flush=True)
    p = subprocess.run([
        "scp", "-i", str(key), "-o", "StrictHostKeyChecking=no",
        str(out), f"{SERVER}:{REMOTE_PATH}",
    ])
    if p.returncode != 0:
        raise SystemExit("scp 推送失败。")
    print("\n完成 ✔  线上看板：https://47.85.224.112/sales/")


if __name__ == "__main__":
    main()
