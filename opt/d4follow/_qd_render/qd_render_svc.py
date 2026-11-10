# -*- coding: utf-8 -*-
"""千岛抓取「容器渲染后端」——跑在 Docker 里的 Playwright 容器内。

【为什么要它】
生产机是 CentOS 7.9（glibc 2.17 / GCC 4.8.5）。Playwright 自带的 Node driver
与它下载的 Chromium 都要求 glibc >= 2.27，在宿主机上怎么装都起不来（1.35 到最新
版全试过）。于是把「浏览器」这一段整体搬进 mcr.microsoft.com/playwright/python
容器：宿主机侧只用 127.0.0.1 的 HTTP 调它，不再依赖本机任何浏览器能力。

【口径保证】
容器**只读**挂载宿主机 /opt/d4follow → /app，直接 import 线上那一份 core_qd.py，
读同一份 config.json。也就是说抓取逻辑、区服改写（specIds/filters）、订单簿
DWC 算法与「本机直抓」跑的是同一份代码，只是换了执行环境。

【副作用】
零。只调 core_qd.scrape() / core_qd.scrape_books()，绝不触碰缓存层
（load_cache / save_cache / fetch），容器是只读挂载，写不进去任何东西。

【★ 为什么抓取要 fork 子进程（2026-09-27 实测坑）】
`core_qd.scrape_books()` 在 page.route 的 handler 里调 `route.fetch()` 重放请求。
Playwright 的同步 API 靠 greenlet 切换驱动，**在 HTTP handler 子线程里跑 handler
内的 fetch 会直接挂死**：抓取函数超时返回、state["ms"]==0、订单簿 0 条，
而同样的代码在**主线程**里跑 15 个订单簿只要 22 秒。
所以 HTTP 层只负责转派：每个抓取任务 fork 一个 worker 进程，在**进程主线程**里
执行，结果用 stdout 里的一行哨兵回传。`/scrape` 同样走 worker，行为统一。

【日志】
core_qd 的 log 回调写 stderr（进 docker logs）并随结果回传宿主机逐行重放 ——
d4follow 的 service.log 里看到的行与「本机直抓」一模一样。

【接口】
  GET  /health        探活（宿主机侧据此决定走容器还是回退本机 Playwright）
  POST /scrape        {}                              → {rows, missed, counts, log, ms}
  POST /scrape_books  {targets:[[spu,name]],specs:[]} → {books, meta, log, ms}
  内部：python qd_render_svc.py --worker（stdin 收任务，stdout 回结果）

【并发】
千岛对高频访问会返回 405「您的手速也太快了」。所有抓取串行执行（全局锁），
同一时刻只允许一个浏览器在跑。
"""
import datetime
import json
import os
import subprocess
import sys
import threading
import time
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

APP = os.environ.get("QD_APP_DIR", "/app")
CFG = os.environ.get("QD_CFG", os.path.join(APP, "config.json"))
PORT = int(os.environ.get("QD_PORT", "9223"))
LOG_TAIL = 500                                          # 回传宿主机的最多日志行数
WORKER_TIMEOUT = 900                                    # 单次抓取上限（秒）
WORKER_MARK = "@@QD_RESULT@@"

sys.path.insert(0, APP)

_lock = threading.Lock()
_t0 = time.time()

core_qd = None
CORE_ERR = None
try:
    import core_qd                                     # 线上同一份
except Exception as _e:
    CORE_ERR = repr(_e)

try:
    from importlib.metadata import version as _pkgver  # playwright 顶层无 __version__
    PW_VER = _pkgver("playwright")
except Exception as _e:
    PW_VER = "ERR:" + repr(_e)


# 容器基础镜像不带 tzdata：挂 /etc/localtime 与 -e TZ 都改不动 date 的时区（实测还是
# UTC，与宿主机差 8h，排障时对照日志很别扭）。所以自己按固定偏移算本地时间。
TZ_OFFSET = float(os.environ.get("QD_TZ_OFFSET", "8"))
_TZ = datetime.timezone(datetime.timedelta(hours=TZ_OFFSET))


def _ts():
    return datetime.datetime.now(_TZ).strftime("%Y-%m-%d %H:%M:%S")


def log(*a):
    """一律写 stderr：worker 的 stdout 要留给结果 JSON。"""
    print("[%s]" % _ts(), *a, file=sys.stderr, flush=True)


def _mklog(buf):
    """core_qd 的 log 回调：同时进容器 stderr 与回传缓冲。"""
    def _l(*a):
        s = " ".join(str(x) for x in a)
        buf.append(s)
        log(s)
    return _l


def read_cfg():
    """每次现读：config.json 是活配置（改价/开关随时变），不缓存。"""
    with open(CFG, encoding="utf-8") as f:
        return json.load(f)


# ============================================================ worker：主线程里抓
def worker_main():
    """--worker 模式：stdin 收任务 → 在进程主线程抓 → stdout 回一行哨兵 JSON。"""
    try:
        task = json.loads(sys.stdin.read() or "{}")
    except Exception as e:
        sys.stdout.write(WORKER_MARK + json.dumps(
            {"ok": False, "err": "任务解析失败: %r" % e}, ensure_ascii=False))
        return 0
    kind = task.get("kind")
    buf, out = [], {"ok": False}
    t0 = time.time()
    try:
        if kind == "fc27_lootbar":
            from fc27_lootbar import collect
            out = {"ok": True, "result": collect(task["payload"])}
        elif kind == "scrape":
            cfg = read_cfg()
            info = {}
            rows = core_qd.scrape(cfg, log=_mklog(buf), info=info)
            out = {"ok": True, "rows": rows,
                   "missed": info.get("missed") or [],
                   "counts": info.get("counts") or {}}
        elif kind == "scrape_books":
            cfg = read_cfg()
            targets = [(str(s), n) for s, n in (task.get("targets") or []) if s]
            specs = task.get("specs") or None
            books, meta = core_qd.scrape_books(cfg, targets, log=_mklog(buf),
                                               specs=specs)
            out = {"ok": bool(books), "books": books, "meta": meta}
        else:
            out = {"ok": False, "err": "未知任务 %r" % (kind,)}
    except Exception as e:
        traceback.print_exc()
        out = {"ok": False, "err": repr(e)[:400]}
    out["log"] = buf[-LOG_TAIL:]
    out["ms"] = int((time.time() - t0) * 1000)
    sys.stdout.write(WORKER_MARK + json.dumps(out, ensure_ascii=False))
    sys.stdout.flush()
    return 0


def run_worker(task):
    """fork 一个 worker 进程跑抓取（必须独立进程：见文件头「为什么要 fork」）。"""
    p = subprocess.run([sys.executable, os.path.abspath(__file__), "--worker"],
                       input=json.dumps(task, ensure_ascii=False).encode("utf-8"),
                       stdout=subprocess.PIPE, timeout=90 if task.get('kind') == 'fc27_lootbar' else WORKER_TIMEOUT)
    raw = p.stdout.decode("utf-8", "replace")
    i = raw.rfind(WORKER_MARK)
    if i < 0:
        raise RuntimeError("worker 无结果输出（exit=%s）: %s" % (p.returncode, raw[-400:]))
    return json.loads(raw[i + len(WORKER_MARK):])


# ============================================================ HTTP 服务
class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):                          # 静默默认访问日志
        pass

    def _send(self, code, obj):
        b = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)
        except (BrokenPipeError, ConnectionResetError):
            pass                                        # 客户端先走了（抓取耗时长）

    def do_GET(self):
        if self.path.split("?")[0] == "/health":
            self._send(200, {
                "ok": core_qd is not None, "svc": "qd-render",
                "python": sys.version.split()[0], "playwright": PW_VER,
                "app": APP, "cfg": CFG, "core_qd_err": CORE_ERR,
                "uptime_s": int(time.time() - _t0),
            })
        else:
            self._send(404, {"ok": False, "err": "not found"})

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == '/fc27_lootbar':
            try:
                length = self.headers.get('Content-Length', '')
                if not length.isdecimal() or not 0 < int(length) <= 2048 or self.path != p:
                    raise ValueError('invalid_fc_body_length')
            except (ValueError, TypeError):
                self.close_connection = True
                self._send(400, {'ok':False, 'reason':'lootbar_render_task_invalid'})
                return
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        try:
            body = json.loads(raw.decode("utf-8") or "{}")
        except Exception:
            body = {}
        if p == '/fc27_lootbar':
            try:
                from fc27_lootbar import validate_task
                validate_task(body)
            except (ValueError, TypeError):
                self._send(400, {'ok':False, 'reason':'lootbar_render_task_invalid'})
                return
            if not _lock.acquire(blocking=False):
                self._send(503, {'ok':False, 'reason':'renderer_busy'})
                return
            try:
                self._send(200, run_worker({'kind':'fc27_lootbar', 'payload':body}))
            except Exception:
                self._send(500, {'ok':False, 'reason':'renderer_unavailable'})
            finally:
                _lock.release()
            return
        if core_qd is None:
            self._send(500, {"ok": False,
                             "err": "core_qd import 失败: %s" % CORE_ERR})
            return
        if p == "/scrape":
            self._dispatch("scrape", {}, "抓取聚合价")
        elif p == "/scrape_books":
            self._dispatch("scrape_books",
                           {"targets": body.get("targets") or [],
                            "specs": body.get("specs") or None},
                           "抓取订单簿")
        else:
            self._send(404, {"ok": False, "err": "not found"})

    def _dispatch(self, kind, extra, title):
        task = {"kind": kind}
        task.update(extra)
        log("→ %s 开始" % title)
        with _lock:
            try:
                r = run_worker(task)
                log("← %s 完成 ok=%s ms=%s" % (title, r.get("ok"), r.get("ms")))
                code = 200 if r.get("ok") or kind == "scrape" else 200
                self._send(code, r)
            except Exception as e:
                traceback.print_exc()
                self._send(500, {"ok": False, "err": repr(e)[:400]})


if __name__ == "__main__":
    if "--worker" in sys.argv:                          # worker 模式：主线程抓取
        sys.exit(worker_main())
    log("qd-render 启动 | python=%s playwright=%s | app=%s cfg=%s port=%d"
        % (sys.version.split()[0], PW_VER, APP, CFG, PORT))
    log("core_qd 导入: %s" % ("成功" if core_qd is not None else "失败 " + str(CORE_ERR)))
    srv = ThreadingHTTPServer(("0.0.0.0", PORT), H)
    srv.daemon_threads = True
    log("listening on 0.0.0.0:%d（抓取任务 fork worker 进程执行）" % PORT)
    srv.serve_forever()
