"""Run one FC27 Players repricing job with the server-owned chenchao identity.

This module runs in an isolated fc27-cloud-session container. A dispatch intent is
durably recorded before every POST; an interrupted or uncertain request is never
replayed automatically.
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
from random import SystemRandom
import subprocess
import sys
import tempfile
import time
import uuid
import urllib.error
import urllib.request
from urllib.parse import urlencode

sys.path.insert(0, "/usr/local/bin")
from p2pah_session_service import allowed_admin_usernames, HEADERS, SessionManager, read_private_config


ROOT = Path("/run/player-sync")
REQUEST = Path("/run/request.json")
EXECUTION = Path("/run/coin-execution.json")
POLICY = Path("/run/config/player-sync.json")
GID, CID, MMOEXP_SITE = 1327, 9627, 266
TOLERANCE = Decimal("0.001")
PUBLIC_PAGE = "https://www.mmoexp.com/Fc-27/Players.html"
PUBLIC_API = "https://www.mmoexp.com/ajax/goods"
PUBLIC_AREAS = {"PS": 21587, "XBOX": 21585, "PC": 21589}


def now():
    return datetime.now(timezone.utc).isoformat()


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def decimal(value, label, *, positive=True):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(label + "_invalid") from None
    if not result.is_finite() or (positive and result <= 0):
        raise ValueError(label + "_invalid")
    return result


def atomic(path, value):
    fd, temporary = tempfile.mkstemp(prefix=".player-sync-", suffix=".json", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def query_pairs(filters, **simple):
    value = dict(simple)
    for index, (field, expected) in enumerate(filters):
        prefix = f"search[{index}]"
        value[prefix + "[field]"] = field
        value[prefix + "[operator]"] = "="
        value[prefix + "[val]"] = str(expected)
    return urlencode(value)


def api(manager, path, *, payload=None):
    for attempt in range(3 if payload is None else 1):
        try:
            status, raw = manager.request(path, data=payload, token=manager.token)
            break
        except OSError:
            if payload is not None or attempt == 2:
                raise
            time.sleep(attempt + 1)
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("backend_response_invalid") from None
    if status != 200 or result.get("code") != 1:
        raise ValueError("backend_request_rejected")
    return result.get("data")


def recalculate_category(manager, *, observer=None):
    """Submit the admin page's category action once with a bulk sized timeout."""
    headers = {**HEADERS, "Content-Type": "application/json", "batoken": manager.token}
    body = json.dumps({"gid": GID, "cid": CID, "id": []}).encode("utf-8")
    request = urllib.request.Request(
        manager.config["P2PAH_API_BASE"] + "/admin/goods.GoodsMould/recalcFc27Price",
        data=body, headers=headers, method="POST")
    receipt = {"path": "/admin/goods.GoodsMould/recalcFc27Price", "started_at": now()}
    try:
        try:
            with urllib.request.urlopen(request, timeout=300) as response:
                receipt["http_status"] = response.status
                status, raw = response.status, response.read()
        except urllib.error.HTTPError as exc:
            receipt["http_status"] = exc.code
            status, raw = exc.code, exc.read()
    except Exception as exc:
        receipt.update(received_at=now(), transport_error=type(exc).__name__)
        if observer:
            observer(receipt)
        raise
    receipt.update(received_at=now(), response_code=None,
                   response_sha256=hashlib.sha256(raw).hexdigest())
    try:
        result = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        if observer:
            observer(receipt)
        raise ValueError("backend_response_invalid") from None
    code = result.get("code") if isinstance(result, dict) else None
    if type(code) is int:
        receipt["response_code"] = code
    if observer:
        observer(receipt)
    if status != 200 or result.get("code") != 1:
        raise ValueError("backend_request_rejected")
    return result.get("data")


def list_models(manager):
    rows, expected_total = [], None
    for page in range(1, 101):
        data = api(manager, "/admin/goods.GoodsMould/index?" + query_pairs(
            [("gid", GID), ("cid", CID)], page=page, limit=200, order="sort,desc"))
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise ValueError("model_list_invalid")
        total = int(data.get("total", -1))
        if total < 1 or total > 10000 or (expected_total is not None and total != expected_total):
            raise ValueError("model_list_total_changed")
        expected_total = total
        page_rows = data["list"]
        if not page_rows or len(page_rows) > 200:
            raise ValueError("model_list_incomplete")
        rows.extend(page_rows)
        if len(rows) >= total:
            break
    if len(rows) != expected_total:
        raise ValueError("model_list_incomplete")
    ids = [int(row["id"]) for row in rows]
    if len(set(ids)) != len(ids) or any(str(row.get("gid")) != str(GID)
                                    or str(row.get("cid")) != str(CID) for row in rows):
        raise ValueError("model_list_scope_invalid")
    return rows


def products(manager, model_id):
    rows, expected_total = [], None
    for page in range(1, 21):
        data = api(manager, "/admin/goods.Goods/index?" + query_pairs(
            [("gid", GID), ("cid", CID), ("mid", model_id)], page=page, limit=200))
        if not isinstance(data, dict) or not isinstance(data.get("list"), list):
            raise ValueError("product_list_invalid")
        total = int(data.get("total", -1))
        if total < 0 or total > 4000 or (expected_total is not None and total != expected_total):
            raise ValueError("product_list_total_changed")
        expected_total = total
        rows.extend(data["list"])
        if len(rows) >= total:
            break
        if not data["list"]:
            raise ValueError("product_list_incomplete")
    if len(rows) != expected_total:
        raise ValueError("product_list_incomplete")
    ids = [int(row["id"]) for row in rows]
    if len(set(ids)) != len(ids) or any(str(row.get("gid")) != str(GID)
                                    or str(row.get("cid")) != str(CID)
                                    or int(row.get("mid") or 0) != model_id for row in rows):
        raise ValueError("product_list_scope_invalid")
    if any(str(row.get("site_id")) not in {"0", str(MMOEXP_SITE)} for row in rows):
        raise ValueError("product_site_scope_unknown")
    return rows


def area(row):
    item = row.get("gameArea")
    name = str(item.get("title") if isinstance(item, dict) else "").lower()
    if "xbox" in name:
        return "XBOX"
    if "playstation" in name or name.startswith("ps"):
        return "PS"
    if "pc" in name:
        return "PC"
    raise ValueError("player_product_platform_unknown")


def model_inputs(row):
    more = row.get("more")
    if not isinstance(more, dict) or not isinstance(more.get("extend"), list):
        raise ValueError("model_price_inputs_missing")
    values = {str(item.get("key")): item.get("value") for item in more["extend"]
              if isinstance(item, dict)}
    return {"PS": decimal(values.get("ps_price"), "player_ps_coins"),
            "XBOX": decimal(values.get("ps_price"), "player_xbox_coins"),
            "PC": decimal(values.get("pc_price"), "player_pc_coins"),
            "coefficient": decimal(values.get("coefficient") or "1.1", "player_coefficient")}


def formula_ok(rows, inputs, rates):
    selling = [row for row in rows if active(row)]
    if not selling:
        return False
    for row in selling:
        platform = area(row)
        expected = inputs[platform] / Decimal(1000) * rates[platform] * inputs["coefficient"]
        actual = decimal(row.get("unit_price"), "player_unit_price")
        if abs(actual - expected) > TOLERANCE:
            return False
    return True


def active(row):
    return (str(row.get("site_id")) == str(MMOEXP_SITE)
            and str(row.get("status")) == "1"
            and int(row.get("total") or 0) > 0)


def recovery_start(ledger, *, job_id, coin_id, count, digest):
    """Only continue the same immutable plan after an operator reconciles its stop."""
    if (ledger.get("job_id") != job_id or ledger.get("coin_execution_id") != coin_id
            or ledger.get("status") != "needs_reconcile"
            or ledger.get("model_count") != count or ledger.get("model_ids_sha256") != digest
            or type(ledger.get("verified_count")) is not int
            or type(ledger.get("next_index")) is not int
            or ledger["verified_count"] != ledger["next_index"]
            or not 0 <= ledger["verified_count"] < count):
        raise ValueError("player_sync_recovery_state_invalid")
    return ledger["verified_count"]


def category_samples(manager, models, size=5):
    """Choose a uniform random sample from active models with MMOEXP stock."""
    candidates = [row for row in models if str(row.get("status")) == "1"]
    SystemRandom().shuffle(candidates)
    selected = []
    for row in candidates:
        model_id = int(row["id"])
        linked = products(manager, model_id)
        selling = [item for item in linked if active(item)]
        if len(selling) != 3 or {area(item) for item in selling} != set(PUBLIC_AREAS):
            continue
        for item in linked:
            area(item)
        selected.append({"id": model_id,
                         "product_ids": sorted(int(item["id"]) for item in linked),
                         "title": str(row.get("title") or "").split("/", 1)[0].strip()})
        if len(selected) == size:
            if any(not item["title"] for item in selected):
                raise ValueError("player_sample_title_missing")
            return selected
    raise ValueError("player_sample_incomplete")


def public_offer(product_id, model_id, platform, player_name):
    """Read the public card feed that renders Our Price; match by exact product ID."""
    if platform not in PUBLIC_AREAS or not player_name or not 0 < len(player_name) < 150:
        raise ValueError("public_player_query_invalid")
    form = {"orderBy": "", "prop_ids": "", "site_id": MMOEXP_SITE,
            "Game_id": GID, "page": 1, "top_cid": 2, "category_id": "",
            "cid": CID, "aid": PUBLIC_AREAS[platform], "keyword": player_name,
            "tid": "", "perpage": 12, "is_search_category": 1}
    expected_total = None
    for page in range(1, 51):
        form["page"] = page
        command = ["curl", "--fail", "--silent", "--show-error", "--location",
                   "--max-time", "18", "--max-filesize", "4000000",
                   "--proto", "=https", "--proto-redir", "=https",
                   "--user-agent", "Mozilla/5.0 (compatible; FC27-player-monitor/1.0)",
                   "--referer", PUBLIC_PAGE, "--header", "Accept: application/json",
                   "--header", "Content-Type: application/x-www-form-urlencoded",
                   "--header", "Cache-Control: no-cache", "--header", "Pragma: no-cache",
                   "--data", urlencode(form), PUBLIC_API]
        try:
            response = subprocess.run(command, capture_output=True, timeout=22)
            if response.returncode or not response.stdout or len(response.stdout) > 4000000:
                raise ValueError("public_player_source_unavailable")
            payload = json.loads(response.stdout)
            listing = payload["goods"]["index"]
            rows = listing["list"]
            total = int(listing["total"])
            if (not isinstance(rows, list) or total < 1 or total > 600
                    or expected_total is not None and total != expected_total
                    or not 0 < len(rows) <= 12):
                raise ValueError("public_player_listing_invalid")
        except (OSError, subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
            raise ValueError("public_player_source_unavailable") from None
        expected_total = total
        matches = [row for row in rows if int(row.get("id") or 0) == product_id]
        if len(matches) > 1:
            raise ValueError("public_player_product_ambiguous")
        if matches:
            row = matches[0]
            if (int(row.get("mid") or 0) != model_id
                    or int(row.get("gid") or 0) != GID
                    or int(row.get("cid") or 0) != CID
                    or int(row.get("site_id") or 0) != MMOEXP_SITE
                    or int(row.get("aid") or 0) != PUBLIC_AREAS[platform]
                    or str(row.get("status")) != "1"
                    or int(row.get("total") or 0) <= 0):
                raise ValueError("public_player_product_mismatch")
            meta = row.get("more_extend_fromat")
            if not isinstance(meta, dict):
                raise ValueError("public_player_coins_missing")
            coin_field = "pc_price" if platform == "PC" else "ps_price"
            return {"product_id": product_id, "model_id": model_id,
                    "platform": platform, "our_price_coins": decimal(meta.get(coin_field),
                                                                         "public_player_coins"),
                    "coefficient": decimal(meta.get("coefficient") or "1.1",
                                           "public_player_coefficient"),
                    "usd": decimal(row.get("unit_price"), "public_player_usd"),
                    "checked_at": now()}
        if page * 12 >= total:
            break
    raise ValueError("public_player_product_missing")


def public_formula_status(sample, linked, rates):
    """Check both backend and public dollars against the public Our Price coins."""
    details = []
    for product in linked:
        if not active(product):
            continue
        platform = area(product)
        offer = public_offer(int(product["id"]), sample["id"], platform, sample["title"])
        expected = offer["our_price_coins"] / Decimal(1000) * rates[platform] * offer["coefficient"]
        backend = decimal(product.get("unit_price"), "player_unit_price")
        details.append({"platform": platform, "product_id": offer["product_id"],
                        "our_price_coins": str(offer["our_price_coins"]),
                        "coefficient": str(offer["coefficient"]),
                        "target_usd": str(expected), "backend_usd": str(backend),
                        "public_usd": str(offer["usd"]), "checked_at": offer["checked_at"],
                        "backend_match": abs(backend - expected) <= TOLERANCE,
                        "public_match": abs(offer["usd"] - expected) <= TOLERANCE})
    if len(details) != 3 or {row["platform"] for row in details} != set(PUBLIC_AREAS):
        raise ValueError("player_sample_platforms_incomplete")
    return details


def basis_parent_hash(parent):
    fields={k:parent.get(k) for k in ['job_id','kind','actor','status','request','run_id','result','completed_at','player_sync_basis','player_sync_intent']}
    return hashlib.sha256(json.dumps(fields,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()


def basis_owner_allowed(path, uid, operational=False):
    # Normal writer containers own these two immutable, readonly-mounted ledgers.
    # Root-only parent/supersession records retain their original requirement.
    return uid == 0 or (operational and uid == 11027 and str(path) in {
        '/run/coin-execution.json', '/run/coin-all-ledger.json'})


def trusted_basis_bytes(path, operational=False):
    import stat
    descriptor=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        before=os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or not basis_owner_allowed(path,before.st_uid,operational) or before.st_gid not in {0,11028} or stat.S_IMODE(before.st_mode)!=0o640 or before.st_nlink!=1:raise ValueError('player_automatic_basis_file_untrusted')
        with os.fdopen(descriptor,'rb',closefd=False) as stream:raw=stream.read(32000001)
        after=os.fstat(descriptor);current=os.stat(path,follow_symlinks=False)
        if len(raw)>32000000 or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or (current.st_dev,current.st_ino)!=(before.st_dev,before.st_ino):raise ValueError('player_automatic_basis_file_changed')
        return raw
    finally:os.close(descriptor)


def validate_automatic_basis(request,execution,policy,parent,coin_policy,execution_raw,ledger_raw,at=None):
    import uuid
    receipt=request.get('automatic_basis') or {};basis=receipt.get('basis') or {};cid=request['coin_execution_id'];jid=request['job_id']
    if set(receipt)!={'parent_id','parent_fields_sha256','basis'} or str(uuid.UUID(receipt['parent_id']))!=receipt['parent_id'] or parent.get('job_id')!=receipt['parent_id'] or parent.get('run_id')!=parent['job_id'] or parent.get('kind')!='auto_cycle' or parent.get('actor')!='system-automation' or parent.get('status')!='ready' or (parent.get('result') or {}).get('status')!='no_price_change' or parent.get('error') or parent.get('error_detail'):raise ValueError('player_automatic_basis_parent_invalid')
    if parent.get('player_sync_basis')!=basis or basis_parent_hash(parent)!=receipt['parent_fields_sha256'] or parent.get('player_sync_intent')!={'enabled':True,'revision':policy['revision']}:raise ValueError('player_automatic_basis_parent_changed')
    end=datetime.fromisoformat(parent['completed_at'].replace('Z','+00:00'));at=at or datetime.now(timezone.utc)
    if end.tzinfo is None or not 0<=(at-end).total_seconds()<=300:raise ValueError('player_automatic_basis_expired')
    if not coin_policy.get('system_enabled') or coin_policy.get('mode')!='auto' or coin_policy.get('revision')!=basis.get('coin_revision') or (parent.get('request') or {}).get('policy_revision')!=coin_policy['revision'] or not policy.get('enabled') or policy.get('revision')!=basis.get('player_revision') or request.get('config_revision')!=policy['revision']:raise ValueError('player_automatic_basis_policy_changed')
    if execution.get('execution_id')!=cid or execution.get('status')!='CONFIRMED' or execution.get('sync_confirmed') is not True or execution.get('all_baseline',{}).get('status')!='confirmed' or basis.get('coin_execution_id')!=cid or hashlib.sha256(execution_raw).hexdigest()!=basis.get('coin_execution_sha256') or hashlib.sha256(ledger_raw).hexdigest()!=basis.get('all_ledger_sha256') or str(uuid.uuid5(uuid.NAMESPACE_URL,('fc27-player-recovery:'+parent['job_id']) if basis.get('kind')=='prewrite_auth_recovery' else ('fc27-player-sync:'+cid)))!=jid:raise ValueError('player_automatic_basis_coin_changed')
    return json.loads(ledger_raw)


def validate_basis_prices(manager,execution,ledger,backend_only=False):
    """Independent typed GETs: both sites and all 45 public quantities, before POST."""
    import coin_all_sync_job as coins
    rates={r['platform']:decimal(r['b2c'],'coin_sale_price') for r in execution['after']['rows']}
    steps=ledger.get('steps',[])
    if ledger.get('status')!='confirmed' or len(steps)!=3 or {x.get('platform') for x in steps}!=set(rates) or any(x.get('status')!='confirmed' for x in steps):raise ValueError('player_automatic_basis_all_incomplete')
    backend={}
    for step in steps:
        platform=step['platform'];source=step['source'];target=step['payload']
        if decimal(source['unit_price'],'coin_sale_price')!=rates[platform] or decimal(target['unit_price'],'coin_sale_price')!=rates[platform]:raise ValueError('player_automatic_basis_all_rate_changed')
        for key in ['gold','give','discount','price']:
            if len(source['more'][key])!=15 or [Decimal(str(x)) for x in source['more'][key]]!=[Decimal(str(x)) for x in target['more'][key]]:raise ValueError('player_automatic_basis_all_vector_changed')
        for site in (0,266):
            row=coins.read_row(manager,platform,site)
            if decimal(row['unit_price'],'coin_sale_price')!=rates[platform]:raise ValueError('player_automatic_basis_backend_changed')
            for key in ['gold','give','discount','price']:
                if [Decimal(str(x)) for x in row['more'][key]]!=[Decimal(str(x)) for x in source['more'][key]]:raise ValueError('player_automatic_basis_backend_tiers_changed')
            if site==266:backend[platform]=row
    if backend_only:return
    import storefront_monitor as sf
    with tempfile.TemporaryDirectory(prefix='fc27-player-basis-public-') as folder:
        jar=Path(folder)/'public-cookie.txt';mapping=sf.page_mapping(sf.fetch(sf.PAGE_URL,cookie_jar=jar))
        for key,platform in sf.PLATFORMS.items():
            payload=json.loads(sf.fetch(sf.GOODS_URL,{'Game_id':'1327','top_cid':'1','aid':mapping['servers'][key],'cid':mapping['cid'],'site_id':mapping['site_id']},100000,jar))
            rows=payload['goods']['index']['list'];row=backend[platform]
            if len(rows)!=1 or rows[0]['unit']!='K' or int(rows[0]['id'])!=int(row['id']) or len(rows[0]['goods_list'])!=15:raise ValueError('player_automatic_basis_public_scope_changed')
            for i,tier in enumerate(rows[0]['goods_list'].values()):
                for public_key,backend_key in [('num','gold'),('give','give'),('discount','discount'),('price','price'),('price_discount','price')]:
                    if Decimal(str(tier[public_key]))!=Decimal(str(row['more'][backend_key][i])):raise ValueError('player_automatic_basis_public_tier_changed')


def current_automatic_basis(request,execution,policy,manager=None):
    operational=((request.get('automatic_basis') or {}).get('basis') or {}).get('kind')=='prewrite_auth_recovery'
    eraw=trusted_basis_bytes(EXECUTION,operational);lraw=trusted_basis_bytes(Path('/run/coin-all-ledger.json'),operational)
    parent=json.loads(trusted_basis_bytes(Path('/run/automatic-parent.json')))
    current=json.loads(eraw)
    if current!=execution:raise ValueError('player_automatic_basis_execution_changed')
    ledger=validate_automatic_basis(request,current,policy,parent,read(Path('/run/config/automation.json')),eraw,lraw)
    if manager is not None:validate_basis_prices(manager,current,ledger,backend_only=operational)


def receipt_platform_prices(receipt, prices):
    """Only explicit native receipts use independent keys; old receipts retain their meaning."""
    scope = receipt.get('price_scope_contract')
    if scope == 'fc27_three_platform_v1':
        if (receipt.get('financial_contract_version') != 'fc27_dual20_d9_d2_platform_100k_v4'
                or set(prices) != set(PUBLIC_AREAS)):
            raise ValueError('player_three_platform_receipt_invalid')
        return {p: decimal(prices[p], 'coin_sale_price') for p in PUBLIC_AREAS}
    if scope is not None or receipt.get('financial_contract_version') != 'fc27_dual20_v1':
        raise ValueError('player_receipt_contract_invalid')
    return {p: decimal(prices['pc' if p == 'PC' else 'console'], 'coin_sale_price')
            for p in PUBLIC_AREAS}


def verified_closed_coin(execution,completion):
    """Accept the same bound Order/Admin proof and terminal ledger snapshot supplied by the worker."""
    try:
        original=execution['pricing_decision_receipt'];close=execution['close_receipt'];proof=completion or {};readback=proof['readback'];ident=execution['execution_id']
        if (execution.get('status') not in ('ORDER_ADMIN_CONFIRMED','PUBLIC_CONFIRMED') or execution.get('ledger_status')!='COMPLETED' or
                execution.get('operation_id')!=ident or execution.get('confirmation_scope')!='Order_Admin' or
                proof.get('operation_id')!=ident or proof.get('status')!='COMPLETED' or
                not original.get('sha256') or proof.get('bundle_sha256')!=original['sha256'] or
                not original.get('snapshot_id') or proof.get('snapshot_id')!=original['snapshot_id'] or
                readback.get('operation_id')!=ident or readback.get('confirmation_scope')!='Order_Admin' or
                readback.get('status')!=execution['status'] or close.get('status')!=execution['status'] or
                not isinstance(execution.get('sync_message'),str) or not execution['sync_message'].strip() or
                (readback.get('order_feedback') or {}).get('sync_message')!=execution['sync_message']):return False
        prices=readback['admin_unit_prices'];saved=close['admin_unit_prices'];targets={r['platform']:r['quote'] for r in readback['targets']}
        rates={r['platform']:decimal(r['b2c'],'coin_sale_price') for r in execution['after']['rows']}
        if set(rates)!=set(prices) or set(rates)!=set(saved) or set(rates)!=set(targets) or set(rates)!={'PS','XBOX','PC'}:return False
        quoted = receipt_platform_prices(original, proof['base_prices'])
        return all(decimal(prices[p],'admin_price')==decimal(saved[p],'admin_price')==rates[p] and
                   decimal(targets[p],'target')==rates[p]*100==quoted[p] for p in rates)
    except (KeyError,ValueError,TypeError,OverflowError):return False


def verified_v3_coin_execution(execution,completion=None):
    """An operator-triggered program cycle retains the same proven V3 authority."""
    receipt=execution.get('pricing_decision_receipt') or {};proof=receipt.get('financial_proof') or {}
    if not ((execution.get('status')=='CONFIRMED' or verified_closed_coin(execution,completion)) and receipt.get('schema_version')=='fc-pricing-v3-20261026' and
            receipt.get('decision_bundle_id')==execution.get('execution_id') and
            receipt.get('review_contract')=='program_pricing_with_daily_hermes_review_v3' and
            receipt.get('decision_source')=='program_current_strategy' and receipt.get('execution_authorized') is True and
            proof.get('pass_all') is True and
            proof.get('execution_eligible') is True and execution.get('sync_confirmed') is True):return False
    try:
        rows=execution['after']['rows'];prices=receipt_platform_prices(receipt, receipt['action']['base_prices'])
        return len(rows)==3 and {r['platform'] for r in rows}=={'PS','XBOX','PC'} and all(
            decimal(r['b2c'],'coin_sale_price')*100==prices[r['platform']] for r in rows)
    except (KeyError,ValueError,TypeError):return False


def bulk_main():
    """Submit the category action once; do not verify wiki/player selling prices."""
    request, execution, policy = read(REQUEST), read(EXECUTION), read(POLICY)
    job_id, coin_id = request["job_id"], request["coin_execution_id"]
    dry_run = request.get("dry_run") is True
    verified_v3=verified_v3_coin_execution(execution,request.get('v3_completion'))
    if execution.get('status') in ('ORDER_ADMIN_CONFIRMED','PUBLIC_CONFIRMED') and not request.get('automatic_basis') and job_id!=str(uuid.uuid5(uuid.NAMESPACE_URL,'fc27-player-sync:'+coin_id)):
        raise ValueError('player_sync_original_job_mismatch')
    if ((not policy.get("enabled") and not dry_run)
            or policy.get("revision") != request.get("config_revision")
            or execution.get("execution_id") != coin_id
            or (execution.get("status") != "CONFIRMED" and not verified_v3)
            or (execution.get("automatic") is not True and not request.get("automatic_basis") and not verified_v3)):
        raise ValueError("player_sync_preflight_changed")
    if request.get('automatic_basis'):current_automatic_basis(request,execution,policy)
    rate_rows = execution.get("after", {}).get("rows") or []
    rates = {row["platform"]: decimal(row.get("b2c"), "coin_sale_price") for row in rate_rows}
    if set(rates) != {"PS", "XBOX", "PC"} or len(rate_rows) != 3:
        raise ValueError("coin_sale_prices_incomplete")
    manager = SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError("chenchao_auth_unavailable")
    identity = api(manager, "/admin/index/index")
    if not isinstance(identity, dict) or identity.get("adminInfo", {}).get("username") not in allowed_admin_usernames():
        raise ValueError("chenchao_identity_invalid")
    if request.get('automatic_basis'):current_automatic_basis(request,execution,policy,manager)
    if request.get('recovery_preflight'):
        if not dry_run:raise ValueError('recovery_probe_must_be_readonly')
        validate_basis_prices(manager,execution,json.loads(trusted_basis_bytes(Path('/run/coin-all-ledger.json'),operational=True)),backend_only=True)
    models = list_models(manager)
    samples, sample_before = [], {}  # User retired player price verification, including wiki cards.
    scope_digest = hashlib.sha256(json.dumps([int(row["id"]) for row in models],
                                             separators=(",", ":")).encode()).hexdigest()
    if dry_run:
        print(json.dumps({"status": "preflight_ready", "mode": "category_all",
                          "model_count": len(models), "sample_count": len(samples),
                          "sample_model_ids": [row["id"] for row in samples],
                          "model_ids_sha256": scope_digest, "coin_execution_id": coin_id}))
        return
    ledger_path = ROOT / (job_id + ".json")
    if ledger_path.exists():
        raise ValueError("player_sync_job_already_started")
    ledger = {"job_id": job_id, "coin_execution_id": coin_id,
              "created_at": now(), "status": "running", "mode": "category_all",
              "stage": "sample_selected", "model_count": len(models),
              "model_ids_sha256": scope_digest, "sample_count": len(samples),
              "sample_model_ids": [row["id"] for row in samples],
              "price_verification": "disabled", "sample_source": None,
              "sample_before": sample_before, "sample_readback": {},
              "sample_verified_count": 0, "sample_verified_model_ids": [],
              "verified_count": 0,
              "active_model_id": None}
    atomic(ledger_path, ledger)
    def observed(response):
        ledger["post_response"] = response
        atomic(ledger_path, ledger)
    try:
        current_policy = read(POLICY)
        if not current_policy.get("enabled") or current_policy.get("revision") != request["config_revision"]:
            raise ValueError("player_sync_switch_changed")
        if request.get('automatic_basis'):current_automatic_basis(request,execution,current_policy,manager)
        ledger.update({"stage": "category_dispatch_intent", "updated_at": now()})
        atomic(ledger_path, ledger)
        # The live admin button submits an empty selection to recalculate gid/cid in one call.
        recalculate_category(manager, observer=observed)
        verified = set()
        ledger["category_response"] = "accepted"
        ledger.update({"status": "confirmed", "stage": "complete", "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "confirmed", "mode": "category_all",
                          "model_count": len(models), "sample_count": len(samples),
                          "price_verification": "disabled", "category_response": "accepted",
                          "sample_verified_count": len(verified),
                          "coin_execution_id": coin_id, "post_response": ledger.get("post_response")}))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        ledger.update({"status": "needs_reconcile", "stage": "stopped",
                       "error": reason[:90], "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "needs_reconcile", "reason": reason[:90],
                          "mode": "category_all", "sample_verified_count": len(verified)
                          if "verified" in locals() else 0,
                          "active_model_id": ledger["active_model_id"],
                          "post_response": ledger.get("post_response")}))
        raise SystemExit(2)


def main():
    request, execution, policy = read(REQUEST), read(EXECUTION), read(POLICY)
    job_id, coin_id = request["job_id"], request["coin_execution_id"]
    dry_run = request.get("dry_run") is True
    if ((not policy.get("enabled") and not dry_run)
            or policy.get("revision") != request.get("config_revision")
            or execution.get("execution_id") != coin_id
            or execution.get("status") != "CONFIRMED" or execution.get("automatic") is not True):
        raise ValueError("player_sync_preflight_changed")
    rate_rows = execution.get("after", {}).get("rows") or []
    rates = {row["platform"]: decimal(row.get("b2c"), "coin_sale_price") for row in rate_rows}
    if set(rates) != {"PS", "XBOX", "PC"} or len(rate_rows) != 3:
        raise ValueError("coin_sale_prices_incomplete")
    manager = SessionManager(read_private_config())
    if not manager.ensure():
        raise ValueError("chenchao_auth_unavailable")
    identity = api(manager, "/admin/index/index")
    if not isinstance(identity, dict) or identity.get("adminInfo", {}).get("username") not in allowed_admin_usernames():
        raise ValueError("chenchao_identity_invalid")
    models = list_models(manager)
    planned = []
    for row in models:
        if str(row.get("status")) != "1":
            continue
        model_id = int(row["id"])
        linked = products(manager, model_id)
        if not any(active(item) for item in linked):
            continue
        inputs = model_inputs(row)
        for item in linked:
            area(item)
        planned.append({"id": model_id, "product_ids": sorted(int(item["id"]) for item in linked),
                        "inputs": {key: str(value) for key, value in inputs.items()}})
    if not planned:
        raise ValueError("no_active_player_models")
    ids = [item["id"] for item in planned]
    digest = hashlib.sha256(json.dumps(ids, separators=(",", ":")).encode()).hexdigest()
    if dry_run:
        print(json.dumps({"status": "preflight_ready", "model_count": len(planned),
                          "model_ids_sha256": digest, "coin_execution_id": coin_id}))
        return
    ledger_path = ROOT / (job_id + ".json")
    resume = request.get("resume") is True
    if ledger_path.exists():
        if not resume:
            raise ValueError("player_sync_job_already_started")
        ledger = read(ledger_path)
        start_index = recovery_start(ledger, job_id=job_id, coin_id=coin_id,
                                     count=len(planned), digest=digest)
        uncertain_model = ledger.get("active_model_id")
        if uncertain_model is not None and uncertain_model != planned[start_index]["id"]:
            raise ValueError("player_sync_recovery_model_changed")
        ledger.setdefault("recoveries", []).append({
            "at": now(), "previous_error": ledger.get("error"),
            "verified_count": start_index, "uncertain_model_id": uncertain_model})
        ledger.update({"status": "running", "stage": "rechecking_uncertain_model",
                       "error": None, "completed_at": None, "updated_at": now()})
    else:
        if resume:
            raise ValueError("player_sync_recovery_ledger_missing")
        start_index, uncertain_model = 0, None
        ledger = {"job_id": job_id, "coin_execution_id": coin_id,
                  "created_at": now(), "status": "running", "model_count": len(planned),
                  "model_ids_sha256": digest, "verified_count": 0, "next_index": 0,
                  "active_model_id": None, "last_verified_model_id": None}
    atomic(ledger_path, ledger)
    last_auth_check = time.monotonic()
    try:
        for index in range(start_index, len(planned)):
            item = planned[index]
            if time.monotonic() - last_auth_check > 300:
                if not manager.ensure():
                    raise ValueError("chenchao_auth_expired")
                last_auth_check = time.monotonic()
            current_policy = read(POLICY)
            if not current_policy.get("enabled") or current_policy.get("revision") != request["config_revision"]:
                raise ValueError("player_sync_switch_changed")
            model_id = item["id"]
            detail = api(manager, "/admin/goods.GoodsMould/edit?id=" + str(model_id))
            row = detail.get("row") if isinstance(detail, dict) else None
            if (not isinstance(row, dict) or int(row.get("id") or 0) != model_id
                    or str(row.get("gid")) != str(GID) or str(row.get("cid")) != str(CID)
                    or str(row.get("status")) != "1"):
                raise ValueError("player_model_changed")
            inputs = {key: decimal(value, key) for key, value in item["inputs"].items()}
            if model_inputs(row) != inputs:
                raise ValueError("player_formula_inputs_changed")
            before = products(manager, model_id)
            if sorted(int(row["id"]) for row in before) != item["product_ids"] or not any(active(row) for row in before):
                raise ValueError("player_products_changed")
            if resume and index == start_index and uncertain_model == model_id:
                matched = formula_ok(before, inputs, rates)
                ledger["recoveries"][-1]["readback_before_retry_matches"] = matched
                atomic(ledger_path, ledger)
                if matched:
                    ledger.update({"verified_count": index + 1, "next_index": index + 1,
                                   "active_model_id": None, "last_verified_model_id": model_id,
                                   "stage": "verified_after_uncertain_write", "updated_at": now()})
                    atomic(ledger_path, ledger)
                    continue
            ledger.update({"next_index": index, "active_model_id": model_id,
                           "stage": "dispatch_intent", "updated_at": now()})
            atomic(ledger_path, ledger)
            try:
                api(manager, "/admin/goods.GoodsMould/recalcFc27Price",
                    payload={"gid": GID, "cid": CID, "id": [model_id]})
            except OSError:
                ledger.update({"stage": "write_response_unknown_readback", "updated_at": now()})
                atomic(ledger_path, ledger)
            deadline = time.monotonic() + 75
            while True:
                after = products(manager, model_id)
                if (sorted(int(row["id"]) for row in after) != item["product_ids"]
                        or not any(active(row) for row in after)):
                    raise ValueError("player_product_readback_scope_changed")
                if formula_ok(after, inputs, rates):
                    break
                if time.monotonic() >= deadline:
                    raise ValueError("player_formula_readback_timeout")
                time.sleep(2)
            ledger.update({"verified_count": index + 1, "next_index": index + 1,
                           "active_model_id": None, "last_verified_model_id": model_id,
                           "stage": "verified", "updated_at": now()})
            atomic(ledger_path, ledger)
        ledger.update({"status": "confirmed", "stage": "complete", "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "confirmed", "model_count": len(planned),
                          "verified_count": len(planned), "coin_execution_id": coin_id}))
    except Exception as exc:
        reason = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
        ledger.update({"status": "needs_reconcile", "stage": "stopped",
                       "error": reason[:90], "completed_at": now()})
        atomic(ledger_path, ledger)
        print(json.dumps({"status": "needs_reconcile", "reason": reason[:90],
                          "verified_count": ledger["verified_count"],
                          "active_model_id": ledger["active_model_id"]}))
        raise SystemExit(2)


def run_selected():
    if read(REQUEST).get("resume") is True:
        raise ValueError("legacy_player_sync_resume_requires_manual_reconciliation")
    bulk_main()


if __name__ == "__main__":
    try:
        run_selected()
    except Exception as exc:
        print(json.dumps({"status": "blocked_before_write", "reason": str(exc)[:90]
                          if isinstance(exc, ValueError) else type(exc).__name__}))
        raise SystemExit(1)
