# -*- coding: utf-8 -*-
"""
IGGM 全站价格抓取 · Web 版入口（Flask）
======================================
无账号体系：打开即用，所有人共享一条全局队列。
可选：设置环境变量 IGGM_ACCESS_CODE 开启「一次性访问口令」（记住 30 天），
      不设置则完全开放（建议配合阿里云安全组只放行团队 IP）。
"""
import os
import re

from flask import (Flask, abort, jsonify, make_response, redirect,
                   render_template, request, send_file)

import db
import runner
import sites
from core import IGGMCrawler

app = Flask(__name__)
app.secret_key = os.environ.get("IGGM_SECRET") or ("dev-" + os.urandom(24).hex())
try:
    app.json.ensure_ascii = False      # Flask >= 2.3
except AttributeError:
    app.config["JSON_AS_ASCII"] = False

ACCESS_CODE = (os.environ.get("IGGM_ACCESS_CODE") or "").strip()

db.init_db()
_runner_recovered = runner.recover_pending()


# ---------------- 可选访问口令 ----------------
@app.before_request
def _gate():
    if not ACCESS_CODE:
        return None
    if request.path.startswith("/static/") or request.path == "/healthz":
        return None
    if request.cookies.get("iggm_access") == ACCESS_CODE:
        return None
    if request.path == "/gate" and request.method == "POST":
        return None
    if request.path.startswith("/api/"):
        return jsonify({"ok": False, "error": "需要访问口令"}), 401
    return render_template("gate.html", bad=False)


@app.post("/gate")
def gate_post():
    code = (request.form.get("code") or "").strip()
    if code != ACCESS_CODE:
        return render_template("gate.html", bad=True)
    resp = make_response(redirect("/"))
    resp.set_cookie("iggm_access", code, max_age=30 * 86400,
                    httponly=True, samesite="Lax")
    return resp


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "queue": runner.snapshot()["queue_len"]})


# ---------------- 页面 ----------------
@app.get("/")
def index():
    return render_template("index.html", gate=bool(ACCESS_CODE))


# ---------------- 游戏名解析 ----------------
_TAIL = re.compile(
    r"\s*((cheap\s+|best\s+)?(buy|sell|selling)\s+)?"
    r"(items?|gold|coins?|golds?|boosting|boost|carry[-\s]?runs?|accounts?|"
    r"power[-\s]?leveling|cd[\s-]?keys?|currency|services?|shop|store)\s*"
    r"(for\s+(sale|cheap)(\s+online)?|online|at\s+iggm\w*)?\s*$", re.I)
_SMALL = {"of", "the", "and", "for", "a", "an", "to", "in", "on", "with"}


def _clean_title(t):
    t = re.sub(r"\s+", " ", t or "").strip()
    t = re.split(r"\s*[|\-–—]\s*", t)[0].strip()          # "Arc Raiders | IGGM.COM"
    t = re.sub(r"^\s*(cheap|best|buy|sell)\s+", "", t, flags=re.I)
    t = _TAIL.sub("", t).strip(" -–—|")
    return t


def pretty_slug(slug):
    s = re.sub(r"[-_]+", " ", slug or "").strip()
    if not s:
        return ""
    out = []
    for i, w in enumerate(s.split()):
        if w.isupper() or any(c.isdigit() for c in w):
            out.append(w)
        elif i > 0 and w.lower() in _SMALL:
            out.append(w.lower())
        else:
            out.append(w[:1].upper() + w[1:])
    return " ".join(out)


def game_name_from_page(page):
    m = re.search(
        r'<meta[^>]+(?:property|name)=["\']og:title["\'][^>]*content=["\']([^"\']+)',
        page, re.I)
    if not m:
        m = re.search(r"<title[^>]*>(.*?)</title>", page, re.S | re.I)
    raw = m.group(1) if m else ""
    raw = re.sub(r"<[^>]+>", " ", raw)
    raw = (raw.replace("&amp;", "&").replace("&#39;", "'")
              .replace("&quot;", '"').replace("&nbsp;", " "))
    return _clean_title(raw)


def split_url(url):
    """返回 (game_slug, is_single)"""
    parts = url.rstrip("/").split("/")
    if len(parts) >= 5:
        return parts[3], True        # https://x.com/slug/coins
    if len(parts) >= 4:
        return parts[3], False       # https://x.com/slug
    return "", False


# ---------------- API ----------------
@app.post("/api/discover")
def api_discover():
    url = (request.json or {}).get("url", "").strip()
    if not url:
        return jsonify({"ok": False, "error": "URL 不能为空"}), 400
    if not url.startswith("http"):
        url = "https://" + url
    site = sites.detect_site(url)
    if not site:
        return jsonify({"ok": False,
                        "error": "仅支持 iggm.com / aoeah.com / u4gm.com"}), 400
    try:
        if site == "iggm":
            slug, single = split_url(url)
            if not slug:
                return jsonify({"ok": False,
                                "error": "无法识别游戏，请填 https://www.iggm.com/<游戏>"}), 400
            crawler = IGGMCrawler(log=lambda m: None)
            if single:
                links = [url.rstrip("/")]
            else:
                links = crawler.discover_game(url)
            try:
                name = game_name_from_page(crawler.get(url)) or pretty_slug(slug)
            except Exception:
                name = pretty_slug(slug)
            if len(name) > 40 or not name:
                name = pretty_slug(slug)
            return jsonify({"ok": True, "site": site,
                            "mode": "single" if single else "game",
                            "url": url, "game": name, "categories": links})
        d = sites.discover(url)
        return jsonify({"ok": True, "site": site,
                        "mode": "game" if len(d["categories"]) > 1 else "single",
                        "url": url, "game": d["game"],
                        "categories": d["categories"]})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/scrape")
def api_scrape():
    body = request.json or {}
    url = (body.get("url") or "").strip()
    cats = body.get("categories") or []
    game = (body.get("game") or "").strip()[:80]
    who = (body.get("submitter") or "").strip()[:40]
    site = (body.get("site") or "").strip()[:20]
    if not url or not cats:
        return jsonify({"ok": False, "error": "URL 和品类不能为空"}), 400
    if not game:
        game = pretty_slug(split_url(url)[0])
    tid = runner.submit(url, cats, game=game, submitter=who, site=site)
    return jsonify({"ok": True, "task_id": tid})


@app.get("/api/state")
def api_state():
    return jsonify({"ok": True, **runner.snapshot()})


@app.post("/api/cancel")
def api_cancel():
    tid = (request.json or {}).get("task_id", "")
    ok, msg = runner.cancel(tid)
    return jsonify({"ok": ok, "error": None if ok else msg, "message": msg})


@app.get("/api/logs")
def api_logs():
    task = runner.get(request.args.get("task_id", ""))
    if not task:
        return jsonify({"ok": False, "error": "任务不存在"}), 404
    return jsonify({"ok": True, "logs": task.get("logs", [])})


@app.get("/api/preview/<task_id>")
def api_preview(task_id):
    import csv as _csv
    task = runner.get(task_id)
    if not task or not task["file"]:
        return jsonify({"ok": False, "error": "没有可预览的数据"}), 404
    path = os.path.join(db.EXPORT_DIR, task["file"])
    if not os.path.exists(path):
        return jsonify({"ok": False, "error": "文件已不存在"}), 404
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        rd = _csv.reader(f)
        head = next(rd, [])
        rows = []
        for i, row in enumerate(rd):
            if i >= 50:
                break
            rows.append(row)
    return jsonify({"ok": True, "head": head, "rows": rows,
                    "total": task["rows"]})


@app.get("/download/<task_id>")
def download(task_id):
    task = runner.get(task_id)
    if not task or not task["file"]:
        abort(404)
    path = os.path.join(db.EXPORT_DIR, task["file"])
    if not os.path.exists(path):
        abort(404)
    return send_file(path, as_attachment=True, download_name=task["file"],
                     mimetype="text/csv")


if __name__ == "__main__":
    port = int(os.environ.get("IGGM_PORT", "8787"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
