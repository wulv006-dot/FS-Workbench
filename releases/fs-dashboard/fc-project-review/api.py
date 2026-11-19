"""Dedicated FC review on the existing authenticated FS range service."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from hashlib import sha256
import json
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time

from .review import TZ, interval, packet, save

ROOT = Path("/var/lib/fs-fc-project-review")
HERE = Path(__file__).resolve().parent
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="fc-project-review")
LOCK = threading.Lock()
JOBS = {}
LOG = logging.getLogger(__name__)


def read_range(get_range, game, start, end, mode, actor):
    params = {k:[v] for k,v in dict(profile=game,start=start,end=end,mode=mode,profit_site="all",profit_basis="shipping").items()}
    for _ in range(40):
        code, data = get_range(params, **({"summary_actor":actor} if mode=="summary" else {}))
        if code not in (200,202):
            raise RuntimeError(f"{mode} HTTP {code}")
        if code == 200 and data.get("status") != "pending" and data.get("archive",{}).get("nativeStatus") != "pending":
            return data
        time.sleep(3)
    raise TimeoutError(mode)


def read_program(python, script, *args):
    result = subprocess.run([python,"-B",str(HERE/script),*args],capture_output=True,timeout=270)
    if result.returncode:
        raise RuntimeError(f"{script} exit {result.returncode}")
    return json.loads(result.stdout.decode("utf-8"))


def read_order_attribution(order_facts, actor, periods):
    from .traffic import channel_packet, channel_windows

    replies = {}
    available_start = datetime.now(TZ).date() - timedelta(days=365)
    for side, period in periods.items():
        pages = replies[side] = []
        for segment in channel_windows(period, available_start):
            if segment["end"] < available_start.isoformat():
                pages.append({"error": "outside_order_facts_retention"})
                continue
            params = {k: [v] for k, v in dict(segment, mode="order-facts", site_id="all", gid="1327", status="all").items()}
            try:
                for attempt in range(20):
                    code, body = order_facts.get(params, actor)
                    if code != 202:
                        break
                    if attempt < 19:
                        time.sleep(2)
                if code == 200 and isinstance(body, dict) and isinstance(body.get("channels"), list):
                    pages.append({"status_code": 200, "data": body["channels"], "data_context": {"": body},
                                  "response_view": {"value_complete": True}})
                else:
                    pages.append({"status_code": code, "error": "invalid_channel_payload" if code == 200
                                  else f"order_facts_http_{code}"})
            except (OSError, RuntimeError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
                LOG.warning("FC order attribution %s–%s: %s", segment["start"], segment["end"], type(exc).__name__)
                pages.append({"error": type(exc).__name__})
    return channel_packet(periods, "all", replies, available_start)


def capture(game, start, end, actor, get_range, order_facts, authorizer):
    if not authorizer(actor):
        raise PermissionError("authorization_changed")
    summary = read_range(get_range,game,start,end,"summary",actor)
    admin = summary["profile"]["supplement"]
    if admin.get("status") != "available" or admin.get("normalisedScope") != "all-websites":
        raise ValueError("Admin 全站汇总尚未就绪")
    history = read_range(get_range,game,start,end,"profit-history",actor)
    core = dict(game=game,start=start,end=end,scope="all",admin={**admin,"scope":admin.get("effective_scope",{})},
                shipping=history["history"]["daily"])
    result = packet(core)
    lo,hi = map(date.fromisoformat,(start,end))
    # Compare partial weeks with the same weekdays. Longer custom windows use the preceding equal-length interval.
    length=(hi-lo).days+1
    shift=timedelta(days=7 if length<=7 else length)
    previous={"start":str(lo-shift),"end":str(hi-shift)}
    try:
        orders=read_program(sys.executable,"orders.py",start,end,"--game",game)
        result["ordersData"]=orders
        if game=="FC27" and length<=7 and hi<datetime.now(TZ).date() and not orders.get("products"):
            # Native product membership is expensive. Prioritize the most recent closed date missing product proof.
            try:
                orders=read_program(sys.executable,"orders.py",start,end,"--game",game,"--native-day",end)
                result["ordersData"]=orders
            except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
                LOG.warning("FC native products: %s",type(exc).__name__)
                result["coverage"].append("商品目录补查未完成，保留共享归档分类及未知项")
        disc=orders["discount"]
        result["kpi"]["discountPct"]=disc.get("discountPct")
        if disc.get("status")!="complete":
            result["coverage"].append(f"优惠率按已核 {disc.get('coveredOrders')}/{disc.get('totalOrders')} 单计算")
    except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
        LOG.warning("FC orders: %s",type(exc).__name__)
        result["coverage"].append("订单专项归档暂缺，主盘保留")
    if game=="FC27" and hi < datetime.now(TZ).date():
        try:
            result["prices"]=read_program(sys.executable,"prices.py",start,end)
        except (OSError,RuntimeError,ValueError,subprocess.TimeoutExpired) as exc:
            LOG.warning("FC price history: %s",type(exc).__name__)
            result["coverage"].append("定价窗口未取得")
        try:
            traffic=read_program("/opt/mmoexp-marketing/venv-ssl/bin/python","traffic.py",
                                 "--start",start,"--end",end,"--previous-start",previous["start"],"--previous-end",previous["end"])
            result["traffic"]=traffic
            if order_facts:
                traffic["orders"]=read_order_attribution(order_facts,actor,traffic["periods"])
        except (OSError,RuntimeError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
            LOG.warning("FC traffic: %s",type(exc).__name__)
            result["coverage"].append("流量或归因源本次未完整返回")
        try:
            sampled=read_program(sys.executable,"fulfillment_completion_bridge.py","--start",start,"--end",end)
            if (sampled["start"],sampled["end"])!=(start,end):
                raise ValueError("delivery window mismatch")
            result.setdefault("ordersData",{})["delivery"]=sampled
        except (OSError,RuntimeError,ValueError,KeyError,subprocess.TimeoutExpired) as exc:
            LOG.warning("FC delivery: %s",type(exc).__name__)
            result["coverage"].append("Order 交付事件抽样本次未取得，无法核验全程时长")
    if not authorizer(actor):
        raise PermissionError("authorization_changed")
    return result


def publish(result, root=ROOT):
    if result.get("game") not in ("FC26","FC27") or result.get("scope")!="all":
        raise ValueError("invalid archive scope")
    interval(result["game"],result["start"],result["end"])
    if any(str(date.fromisoformat(result[k]))!=result[k] for k in ("start","end")):
        raise ValueError("invalid archive dates")
    root.mkdir(mode=0o700,parents=True,exist_ok=True)
    daydir=root/result["game"]
    daydir.mkdir(mode=0o700,parents=True,exist_ok=True)
    base=result["start"]+"_"+result["end"]
    raw=json.dumps(result,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()
    revision=sha256(raw).hexdigest()
    doc={"schema":1,"archivedAt":datetime.now(TZ).isoformat(),"revision":revision,"packets":[result]}
    save(daydir/"versions"/(base+"_"+revision+".json"),doc)
    save(daydir/(base+".json"),doc)
    return doc


def get(params, actor, get_range, order_facts, authorizer, root=ROOT):
    if not actor or not authorizer(actor):
        return 403,{"error":"admin_required"}
    if set(params)-{"mode","profile","start","end","refresh"} or not {"mode","profile","start","end"}<=set(params) or any(not isinstance(v,list) or len(v)!=1 for v in params.values()):
        return 422,{"error":"invalid_review_query"}
    if "refresh" in params and params["refresh"]!=["true"]:
        return 422,{"error":"invalid_refresh"}
    game,start,end=(params[k][0] for k in ("profile","start","end"))
    try:
        if game not in ("FC26","FC27"):raise ValueError()
        interval(game,start,end)
        if str(date.fromisoformat(start))!=start or str(date.fromisoformat(end))!=end:raise ValueError()
    except (TypeError,ValueError):
        return 422,{"error":"invalid_review_interval"}
    target=root/game/(start+"_"+end+".json")
    if target.is_file() and "refresh" not in params:
        doc=json.loads(target.read_text(encoding="utf-8"))
        if len(doc["packets"])!=1 or any(doc["packets"][0].get(k)!=v for k,v in
                (("game",game),("scope","all"),("start",start),("end",end))):
            raise ValueError("archive identity mismatch")
        if end<str(datetime.now(TZ).date()) or time.time()-target.stat().st_mtime<300:
            return 200,doc
    key=(game,start,end,actor)
    with LOCK:
        previous=JOBS.get(key)
        if previous and previous[0].done():
            try:
                completed=previous[0].result()
                if time.time()-target.stat().st_mtime<60:
                    return 200,completed
            except Exception:
                del JOBS[key]
                return 503,{"error":"review_sources_unavailable","retryAfter":60}
            del JOBS[key]
        if key not in JOBS:
            if sum(not f.done() for f,_ in JOBS.values())>=3:return 429,{"error":"review_busy","retryAfter":10}
            for old,(f,since) in list(JOBS.items()):
                if f.done() and time.monotonic()-since>=60:del JOBS[old]
            def collect():
                try:
                    return publish(capture(game,start,end,actor,get_range,order_facts,authorizer),root)
                except Exception:
                    LOG.exception("FC project review capture failed for %s %s %s",game,start,end)
                    raise
            JOBS[key]=(POOL.submit(collect),time.monotonic())
    return 202,{"status":"pending","retryAfter":3}
