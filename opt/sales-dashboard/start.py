# -*- coding: utf-8 -*-
"""销售数据看板 · 本地服务（只在 127.0.0.1 监听，不对外）。

  python start.py            # 起服务 + 开浏览器（无数据时自动抓一次）
  python start.py --refresh  # 先重新抓取再起服务
  python start.py --no-open  # 不起浏览器
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
# 默认只监听本机回环，最安全。需要同局域网其它设备访问时：
#   set DASH_HOST=0.0.0.0 && start.bat
import os
HOST = os.environ.get("DASH_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASH_PORT", "8899"))


def lan_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return None

try:
    from flask import Flask, jsonify, request, send_from_directory
except ImportError:
    print("缺少 flask，请先安装：pip install flask")
    raise

app = Flask(__name__, static_folder=None)


def _run(script, *args):
    """跑采集/聚合子进程，返回 (ok, 输出)。"""
    cmd = [sys.executable, str(ROOT / "collector" / script), *args]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace", cwd=str(ROOT))
    out = (p.stdout or "") + (("\n" + p.stderr) if p.stderr else "")
    return p.returncode == 0, out.strip()


@app.route("/")
def index():
    return send_from_directory(ROOT / "web", "index.html")


@app.route("/data/<path:fn>")
def data_file(fn):
    return send_from_directory(DATA, fn)


@app.route("/api/meta")
def api_meta():
    p = DATA / "_meta.json"
    return jsonify(json.loads(p.read_text(encoding="utf-8")) if p.exists() else {})


@app.route("/api/refresh", methods=["POST"])
def api_refresh():
    body = request.get_json(silent=True) or {}
    meta = {}
    mp = DATA / "_meta.json"
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    start = body.get("start") or meta.get("start") or "2026-09-17"
    end = body.get("end") or time.strftime("%Y-%m-%d")
    logs = []
    try:
        ok, out = _run("fetch_all.py", start, end)
        logs.append(out[-4000:])
        if not ok:
            return jsonify(ok=False, error="采集失败", log="\n".join(logs)), 200
        ok2, out2 = _run("aggregate.py")
        logs.append(out2[-4000:])
        if not ok2:
            return jsonify(ok=False, error="聚合失败", log="\n".join(logs)), 200
        return jsonify(ok=True, start=start, end=end, log="\n".join(logs))
    except Exception as e:
        return jsonify(ok=False, error=repr(e), log="\n".join(logs)), 200


def open_later():
    time.sleep(1.5)
    webbrowser.open("http://127.0.0.1:%d/" % PORT)


def main():
    args = sys.argv[1:]
    if "--refresh" in args or not (DATA / "dashboard.json").exists():
        print("=== 首次/强制抓取数据 ===")
        meta = {}
        mp = DATA / "_meta.json"
        if mp.exists():
            try:
                meta = json.loads(mp.read_text(encoding="utf-8"))
            except Exception:
                pass
        if not _refresh_cli(meta):
            print("抓取失败，仍然尝试用已有数据启动。")
    if "--no-open" not in args:
        threading.Thread(target=open_later, daemon=True).start()
    print("\n看板地址（在你自己电脑的浏览器里打开）：")
    print("   http://127.0.0.1:%d/" % PORT)
    if HOST == "0.0.0.0":
        ip = lan_ip()
        if ip:
            print("   http://%s:%d/   （同局域网其它设备用这个）" % (ip, PORT))
    print("   离线单文件：双击 销售数据看板_AION2_离线版.html（无需服务）")
    print("   打不开时排查：浏览器是否配了代理 → 在代理例外里加上 127.0.0.1")
    print("   Ctrl+C 结束\n")
    app.run(host=HOST, port=PORT, debug=False, threaded=True)


def _refresh_cli(meta):
    start = meta.get("start") or "2026-09-17"
    end = time.strftime("%Y-%m-%d")
    ok, out = _run("fetch_all.py", start, end)
    print(out[-3000:])
    if not ok:
        return False
    ok2, out2 = _run("aggregate.py")
    print(out2[-3000:])
    return ok2


if __name__ == "__main__":
    main()
