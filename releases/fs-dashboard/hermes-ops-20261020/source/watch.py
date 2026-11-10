"""Hermes native no-agent cron: bounded checks, change-only Feishu alerts."""
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile
import fcntl
import urllib.request
from datetime import datetime, timezone, timedelta
from common import age, sha

HOME = Path(os.environ.get('FS_WATCH_HOME', '/profile/ops-watchdog'))
HOURLY_SNAPSHOT_MAX_AGE_S = 75 * 60
PRICING_PREFIXES = ('fc_pricing_', 'rpg_pricing_', 'pricing_monitor_')
# A controlled restart can leave the unit non-active for tens of seconds
# (Stopping -> wait for the running job -> Stopped -> Started). A probe sample
# taken inside that window is not an outage, so a never-seen pricing code has to
# survive this window before it may open an incident.
PRICING_DEBOUNCE_S = int(os.environ.get('FS_WATCH_PRICING_DEBOUNCE_S', '120'))
# 用户 2026-10-25 明确：不影响自动改价按时启动的短暂小问题不报警。
# 仅当"下一轮仍按计划启动"（coin.next_at 在未来）时才允许抑制这些瞬时代码；
# 写入未确认类（business_write_unresolved / *_needs_reconcile / unresolved:<id>）与
# 调度未排（next_at 缺失或已过）始终照报。
TRANSIENT_PRICING_CODES = (
    'fc_pricing_latest_coin_job_failed',
    'fc_pricing_collection_stale_or_clock_invalid',
    'fc_pricing_source_coverage_unverified',
)
# 用户 2026-10-27 明确：只要固定时段的自动改价能跑起来就行，卡点与小细节不报警；
# 只有「改价程序跑不起来 / 写入状态未知 / 看不见改价链路」才允许发飞书。
# 未列入本表的码（采集、覆盖率、浏览器会话、三平台发布确认、日报与夜间数据、
# brain/monitor 自修等）一律静默归档到 silenced-<日期>.json，不进群、不算恢复。
BLOCKING_PREFIXES = (
    'fc_pricing_coin_schedule_paused_after_failure',
    'fc_pricing_latest_coin_job_failed',
    'fc_pricing_service_unavailable:fc-pricing',
    'fc_pricing_automation_timer_inactive_or_unknown',
    'fc_pricing_business_write_unresolved',
    'fc_pricing_coin_execution_needs_reconcile',
    'pricing_monitor_snapshot_',
    'pricing_monitor_read_failed',
    'watchdog_export_',
    'rpg_pricing_write_failed',
    'rpg_pricing_unknown',
    'rpg_pricing_rpg_dependency_unavailable',
    'rpg_pricing_rpg_health_unreachable',
)

# WorkBuddy 终结回执 2026-11-02（事件 bec4bcb2e2a486ed / 7b098c774e4504a3）：
# RPG 执行器已由 187 迁到 183。187 上 d4follow / p2pah-srv-exec 带 drop-in
# 90-rpg-migrated.conf（反条件 cutover.active），是「按设计停在 inactive」，
# 用 systemctl is-active 判死活会每轮误报。判据改成 HTTP：187:8900/api/health
# （ssh 本地转发到 183）返回 200 且 ok=true 视为可用 —— 此时这两条 unit 码退役；
# 探测失败则保留这两条码，并加报 rpg_pricing_rpg_health_unreachable（同样去抖）。
RPG_HEALTH_URL = os.environ.get('FS_RPG_HEALTH_URL', 'http://127.0.0.1:8900/api/health')
RPG_RETIRED_UNIT_CODES = (
    'rpg_pricing_rpg_dependency_unavailable:d4follow.service',
    'rpg_pricing_rpg_dependency_unavailable:p2pah-srv-exec.service',
)
RPG_HEALTH_UNREACHABLE = 'rpg_pricing_rpg_health_unreachable'


def rpg_health(url=None, timeout=4):
    """Read RPG availability from the executor's HTTP health endpoint."""
    target = url or RPG_HEALTH_URL
    try:
        with urllib.request.urlopen(target, timeout=timeout) as response:
            status = response.status
            body = json.loads(response.read(2048).decode('utf-8'))
        ok = status == 200 and isinstance(body, dict) and body.get('ok') is True
        detail = json.dumps({'status': status, 'ok': body.get('ok') if isinstance(body, dict) else None,
                             'version': body.get('version') if isinstance(body, dict) else None}, ensure_ascii=False)
        return ok, detail
    except Exception as error:  # network, timeout, non-JSON body: treat as unavailable
        return False, type(error).__name__ + ': ' + str(error)[:120]



def blocking(code, on_time=False):
    """True only for codes that mean the scheduled repricing cannot run."""
    if not isinstance(code, str):
        return False
    if not any(code.startswith(prefix) for prefix in BLOCKING_PREFIXES):
        return False
    # 下一轮仍按计划启动时，上一轮失败/采集抖动不阻断改价，照旧静默。
    if on_time and code in TRANSIENT_PRICING_CODES:
        return False
    return True


def record_silenced(home, codes, now):
    """Keep a bounded, day-scoped local record of everything deliberately not sent."""
    path = home/('silenced-%s.json' % now.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d'))
    current = read(path, {}) or {}
    for code in codes:
        entry = current.get(code) or {'count': 0, 'first': now.isoformat()}
        entry['count'] = int(entry.get('count', 0)) + 1
        entry['last'] = now.isoformat()
        current[code] = entry
    if len(current) > 500:
        keep = sorted(current.items(), key=lambda item: item[1].get('last', ''))[-500:]
        current = dict(keep)
    write(path, current)



def cycle_on_time(home, now):
    """True only when the repricing cycle still has a future scheduled start."""
    coin = (read(home/'snapshot.json', {}) or {}).get('coin') or {}
    if coin.get('enabled') is not True:
        return False
    raw = coin.get('next_at')
    if not raw:
        return False
    try:
        due = datetime.fromisoformat(str(raw).replace('Z', '+00:00'))
    except (TypeError, ValueError):
        return False
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    return due > now


def muted_prefixes(home, now):
    """Code prefixes the user asked to silence temporarily (file-based, reversible)."""
    cfg = read(home/'mute.json', {}) or {}
    until = cfg.get('until')
    if until:
        try:
            due = datetime.fromisoformat(str(until).replace('Z', '+00:00'))
        except (TypeError, ValueError):
            due = None
        if due is not None:
            if due.tzinfo is None:
                due = due.replace(tzinfo=timezone.utc)
            if now >= due:
                return []
    return [p for p in (cfg.get('pricing_prefixes') or []) if isinstance(p, str) and p]

def mute_includes_blocking(home, muting=()):
    """前缀静默只能盖住非阻断码，除非配置里明确 include_blocking=true。"""
    if not muting:
        return False
    cfg = read(home/'mute.json', {}) or {}
    return cfg.get('include_blocking') is True


def pricing_owned(code):
    return isinstance(code, str) and code.startswith(PRICING_PREFIXES)

def debounce(codes, alerted, previous_pending, now):
    """Split pricing codes into (confirmed, still_pending) with a hold window."""
    confirmed, pending = [], {}
    for code in codes:
        if code in alerted:
            confirmed.append(code)
            continue
        first = previous_pending.get(code)
        if not first:
            pending[code] = now.isoformat()
            continue
        try:
            elapsed = (now - datetime.fromisoformat(first)).total_seconds()
        except (TypeError, ValueError):
            pending[code] = now.isoformat()
            continue
        if elapsed >= PRICING_DEBOUNCE_S:
            confirmed.append(code)
        else:
            pending[code] = first
    return confirmed, pending

def pricing_issues(home, previous, now, pricing_only):
    path = home/'pricing-snapshot.json'
    installed = previous.get('pricing_installed', False) or path.exists() or pricing_only
    retained = [code for code in previous.get('issues', []) if isinstance(code, str) and code.startswith(('fc_pricing_', 'rpg_pricing_'))]
    if not installed:
        return None, False, None, []
    try:
        supplement = read(path)
        if supplement is None:
            return sorted(set(retained + ['pricing_monitor_snapshot_missing'])), True, previous.get('pricing_exported_at'), []
        stamp = supplement['exported_at']
        if not -60 <= age(stamp, now) <= HOURLY_SNAPSHOT_MAX_AGE_S:
            return sorted(set(retained + ['pricing_monitor_snapshot_stale'])), True, previous.get('pricing_exported_at'), []
        codes = supplement['issues']
        if not isinstance(codes, list) or not all(pricing_owned(code) for code in codes):
            raise ValueError('owned_codes_required')
        legacy = supplement.get('legacy_issue_codes', [])
        if not isinstance(legacy, list) or len(legacy) > 1000 or not all(isinstance(code, str) and 0 < len(code) <= 512 for code in legacy):
            raise ValueError('bounded_legacy_codes_required')
        old_stamp = previous.get('pricing_exported_at')
        if old_stamp and age(stamp, now) > age(old_stamp, now):
            return sorted(set(retained + ['pricing_monitor_snapshot_regressed'])), True, old_stamp, []
        return sorted(set(codes)), True, stamp, sorted(set(legacy))
    except (KeyError, TypeError, ValueError, AttributeError, OSError):
        return sorted(set(retained + ['pricing_monitor_snapshot_invalid'])), True, previous.get('pricing_exported_at'), []

def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.ops-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)

def read(path, default=None):
    try: return json.loads(path.read_text('utf-8'))
    except FileNotFoundError: return default

def send(message, target):
    sys.path.insert(0, '/opt/hermes')
    from hermes_cli.env_loader import load_hermes_dotenv
    load_hermes_dotenv(hermes_home='/profile')
    from tools.send_message_tool import send_message_tool
    response = send_message_tool({'target': target, 'message': message})
    result = json.loads(response) if isinstance(response, str) else response
    return result

def message_id(result):
    # An accepted send without an actual ID is retained as unknown, never retried.
    if result.get('success') is False or result.get('error'):
        return None
    return result.get('message_id') or (result.get('raw_response') or {}).get('message_id')

def task_text(issues, config, incident):
    sections = []
    rpg = [code for code in issues if code.startswith(('rpg_', 'd4_', 'poe2_', 'aion2_'))]
    fc = [code for code in issues if code not in rpg]
    for label, codes, owner in (('FC / FS', fc, 'codex'), ('RPG', rpg, 'workbuddy')):
        if not codes: continue
        identity = config.get('owners', {}).get(owner)
        mention = '<at user_id="' + identity + '"></at> ' if identity else ''
        sections.append(mention + label + ' 故障任务\n' + '\n'.join('• ' + code for code in codes))
    return '\n\n'.join(sections) + '\n事件：' + incident

def run(home=HOME, transport=send, now=None, pricing_only=False):
    home.mkdir(parents=True, exist_ok=True)
    with (home/'.watch.lock').open('a+b') as guard:
        try:
            fcntl.flock(guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return {'state': 'concurrent_check_skipped'}
        now = now or datetime.now(timezone.utc)
        result = _run_locked(home, transport, now, pricing_only)
        conclude(home, now, pricing_only, result)
        return result

def conclude(home, now, pricing_only, result):
    """Tag each persisted conclusion so escalation counts only entry 1/2 rounds."""
    state = read(home/'watch-state.json', {}) or {}
    record = {'checked_at': now.isoformat(), 'issues': sorted(set(state.get('issues', []))),
              'state': result.get('state'), 'mode': 'pricing' if pricing_only else 'general',
              'entry': 'pricing-check' if pricing_only else 'entry1-general',
              'evidence_stamp': {'business': (read(home/'snapshot.json', {}) or {}).get('exported_at'),
                                 'pricing': state.get('pricing_exported_at')}}
    write(home/'last-check.json', record)
    if not pricing_only:
        # A 3h pricing run overwrites last-check.json; entry 1 keeps its own file.
        write(home/'last-general-check.json', record)

def _run_locked(home, transport, now, pricing_only):
    now = now or datetime.now(timezone.utc)
    previous = read(home/'watch-state.json', {})
    # Keep the original event across both modes, including a crash before state commit.
    event_id = previous.get('pending_event')
    pending_path = home/'outbox'/(event_id + '.json') if event_id else None
    old_pending = read(pending_path, {}) if pending_path else {}
    if pending_path and old_pending.get('state') == 'sent' and old_pending.get('message_id') and old_pending.get('target_state'):
        write(home/'watch-state.json', old_pending['target_state'])
        if old_pending.get('repair_action'):
            write(home/'request.json', {'incident': old_pending['target_state']['incident'], 'action': old_pending['repair_action'], 'created_at': old_pending['created_at']})
        return {'state': 'reconciled_sent'}
    unresolved = [(p.stem, read(p, {})) for p in sorted((home/'outbox').glob('*.json'))]
    unresolved = [(event, value) for event, value in unresolved if value.get('state') in {'sending', 'unknown'}]
    unknown_codes, unknown_recoveries = set(), set()
    for _, value in unresolved:
        scope = value.get('notification_scope')
        unknown_codes.update(scope.get('new', []) if scope else value.get('target_state', {}).get('issues', []))
        if scope: unknown_recoveries.update(scope.get('recovered', []))
    snapshot = read(home/'snapshot.json', {})
    if pricing_only:
        issues = [code for code in previous.get('issues', []) if not pricing_owned(code)]
        repair = previous.get('repair_summary')
        if repair is None:
            legacy = snapshot.get('repair') or {}
            legacy_signature = sha(json.dumps({'issues': sorted(set(previous.get('issues', []))), 'repair': {k: legacy.get(k) for k in ('incident', 'status', 'error')}}, sort_keys=True).encode())
            repair = legacy if legacy_signature == previous.get('signature') else {}
    else:
        issues = list(snapshot.get('issues', []))
        try:
            if not -60 <= age(snapshot['exported_at'], now) <= HOURLY_SNAPSHOT_MAX_AGE_S:
                issues.append('watchdog_export_stale')
        except (KeyError, TypeError, ValueError): issues.append('watchdog_export_missing')
        repair = snapshot.get('repair') or {}
    supplement, installed, pricing_stamp, legacy_codes = pricing_issues(home, previous, now, pricing_only)
    pricing_pending = {}
    prior_pending = previous.get('pricing_pending') or {}
    transient_suppressed = []
    rpg_health_state = previous.get('rpg_health')
    if supplement is not None and any(code in RPG_RETIRED_UNIT_CODES for code in supplement):
        # 迁移后 187 的两个 unit 常驻 inactive：用 HTTP 健康判定可用性，而不是 unit 状态。
        healthy, detail = rpg_health()
        rpg_health_state = {'ok': healthy, 'detail': detail, 'url': RPG_HEALTH_URL, 'at': now.isoformat()}
        if healthy:
            supplement = [code for code in supplement if code not in RPG_RETIRED_UNIT_CODES]
        elif RPG_HEALTH_UNREACHABLE not in supplement:
            supplement = list(supplement) + [RPG_HEALTH_UNREACHABLE]
    if supplement is not None:
        confirmed, pricing_pending = debounce(supplement, set(previous.get('issues', [])), previous.get('pricing_pending') or {}, now)
        if pricing_only and cycle_on_time(home, now):
            transient_suppressed = sorted(code for code in confirmed if code in TRANSIENT_PRICING_CODES)
            confirmed = [code for code in confirmed if code not in TRANSIENT_PRICING_CODES]
            # 被当作瞬时抑制的码保留首次观测时间：调度一旦过期/停排，
            # 下一轮立刻按阻断码报，不必再等一个去抖窗口。
            for code in transient_suppressed:
                pricing_pending.setdefault(code, prior_pending.get(code) or now.isoformat())
        issues = [code for code in issues if not pricing_owned(code) and code not in legacy_codes] + confirmed
    repair_summary = {key: repair.get(key) for key in ('incident', 'status', 'error', 'url')} if repair else {}
    issues = sorted(set(issues))
    on_time = cycle_on_time(home, now)
    muting = muted_prefixes(home, now)
    mute_blocking = mute_includes_blocking(home, muting)
    # 用户 2026-10-27：静默只收窄到非阻断码——前缀静默默认不能掩盖「改价跑不起来」。
    muted_issues = sorted(code for code in issues
                          if any(code.startswith(pfx) for pfx in muting)
                          and (mute_blocking or not blocking(code, on_time)))
    if muted_issues:
        issues = [code for code in issues if code not in muted_issues]
    # 用户 2026-10-27：只有阻断改价的码进群；其余静默归档，不进群、不算恢复。
    # 自修动作判据用完整 issue 集：静默只影响"发不发群"，不关闭已安装的白名单自修。
    issues_all = list(issues)
    silenced_issues = sorted(code for code in issues if not blocking(code, on_time))
    if silenced_issues:
        record_silenced(home, silenced_issues, now)
        issues = [code for code in issues if blocking(code, on_time)]
        # 因「下一轮仍按计划启动」而静默的改价码保留首次观测时间：
        # 调度一旦过期，下一轮直接按阻断码报，不再等一个去抖窗口。
        for code in silenced_issues:
            if pricing_owned(code) and code in TRANSIENT_PRICING_CODES:
                pricing_pending.setdefault(code, prior_pending.get(code) or now.isoformat())
    signature = sha(json.dumps({'issues': issues, 'repair': {k: repair.get(k) for k in ('incident', 'status', 'error')}}, sort_keys=True).encode())
    def state(incident=None):
        value = {'signature': signature, 'issues': issues, 'checked_at': now.isoformat(), 'repair_summary': repair_summary, 'pricing_installed': installed, 'pricing_exported_at': pricing_stamp, 'pricing_pending': pricing_pending, 'unknown_notification_events': [event for event, _ in unresolved], 'transient_suppressed': transient_suppressed, 'muted_issues': muted_issues, 'silenced_issues': silenced_issues, 'rpg_health': rpg_health_state}
        if incident: value['incident'] = incident
        return value
    if signature == previous.get('signature') and not ((unknown_codes-set(issues))-unknown_recoveries):
        # Freshness metadata is not an alert change, but must advance monotonically.
        write(home/'watch-state.json', state(previous.get('incident')))
        return {'state': 'unchanged_quiet'}
    if not issues and not previous.get('issues') and not repair and not unknown_codes:
        write(home/'watch-state.json', state())
        return {'state': 'healthy_quiet'}
    incident = previous.get('incident') if issues == previous.get('issues') else None
    if not incident:
        incident = sha((str(previous.get('signature')) + str(previous.get('checked_at')) + json.dumps(issues)).encode())[:16]
    config = read(home/'private-target.json')
    action = None if pricing_only else 'brain-theme' if snapshot.get('brain', {}).get('repairable') and 'brain_ui_dependencies_missing' in issues_all else 'monitor-health' if snapshot.get('monitor_repairable') and 'monitor_known_health_schema_regression' in issues_all else None
    def request_repair():
        if action:
            write(home/'request.json', {'incident': incident, 'action': action, 'created_at': now.isoformat()})
    eligible = lambda code: pricing_owned(code) if pricing_only else True
    before_codes = set(code for code in previous.get('issues', []) if blocking(code, on_time))
    if transient_suppressed:
        # A suppressed transient must also not be reported later as "recovered".
        before_codes -= set(TRANSIENT_PRICING_CODES)
    shown_issues = sorted(code for code in set(issues)-before_codes-unknown_codes if eligible(code))
    recovered = sorted(code for code in (before_codes | unknown_codes)-set(issues)-unknown_recoveries if eligible(code) and blocking(code, on_time))
    if muting:
        # 暂停的码既不该新增告警，也不该在暂停期间被当成"已恢复"发回执：
        # 暂停本身不是修复证据，恢复播报要等 mute 到期后由真实清除触发。
        recovered = [code for code in recovered if not any(str(code).startswith(pfx) for pfx in muting)]
    # 自修/PR 状态变化只在确实有阻断改价的故障时才播报，避免同类"状态更新"噪声。
    changed_repair = not pricing_only and bool(issues) and repair_summary != previous.get('repair_summary', {})
    scope = {'new': shown_issues, 'recovered': recovered, 'repair': repair_summary if changed_repair else {}}
    same_unknown = next((event for event, value in unresolved if value.get('notification_scope') == scope), None)
    if same_unknown or (not shown_issues and not recovered and not changed_repair and unresolved):
        return {'state': 'notification_unknown_no_retry', 'event': same_unknown or event_id or unresolved[0][0]}
    if not shown_issues and not recovered and not changed_repair:
        # Nothing actionable to announce (e.g. only suppressed transients):
        # persist the new signature quietly instead of sending an empty update.
        write(home/'watch-state.json', state(previous.get('incident')))
        return {'state': 'transient_quiet' if transient_suppressed else 'unchanged_quiet'}
    if shown_issues:
        text = 'Hermes 业务巡检发现新增异常\n' + task_text(shown_issues, config, incident)
        if pricing_only:
            text = 'Hermes FC/RPG自动改价即时检查发现异常\n' + task_text(shown_issues, config, incident)
        text += '\n巡检时间（北京）：' + now.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
        if pricing_only:
            text += '\n请负责方排查并修复。RPG 由大超的WorkBuddy处理，接单请回“WorkBuddy接管 ' + incident + '”；FC 由 Codex 处理，接单请回“Codex接管 ' + incident + '”。未接单请 @Hermes 说明现场。'
        else:
            text += '\n接单后请 @Hermes 回复“Codex接管 ' + incident + '”或“WorkBuddy接管 ' + incident + '”。FC未接单10分钟后，仅执行已验证自修白名单；RPG由WorkBuddy处理。未覆盖故障保留现场并升级。'
    else:
        text = ('Hermes FC/RPG自动改价：异常恢复状态更新。' if pricing_only else 'Hermes 业务巡检：状态更新。') + '\n核对时间（北京）：' + now.astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M:%S')
    if recovered:
        recovered_price = [code for code in recovered if pricing_owned(code)]
        recovered_general = [code for code in recovered if not pricing_owned(code)]
        if recovered_price: text += '\nFC/RPG价格巡检已恢复项：\n' + '\n'.join('• ' + code for code in recovered_price)
        if recovered_general: text += '\n其他巡检已恢复项：\n' + '\n'.join('• ' + code for code in recovered_general)
    if unresolved:
        text += '\n此前独立通知仍待对账（本次不重发其正文）：' + ', '.join(event for event, _ in unresolved)
    if repair and not pricing_only:
        text += '\n修复状态：' + str(repair.get('status'))
        if repair.get('url'): text += '\nPR：' + repair['url']
        if repair.get('error'): text += '\n待处理：' + repair['error']
    event = sha((str(previous.get('signature')) + str(previous.get('checked_at')) + signature).encode())
    pending = home/'outbox'/ (event + '.json')
    old = read(pending, {})
    if old.get('state') in {'sending', 'unknown'}:
        return {'state': 'notification_unknown_no_retry'}
    if old.get('state') == 'sent':
        if not old.get('message_id'):
            return {'state': 'notification_unknown_no_retry', 'event': event}
        request_repair()
        write(home/'watch-state.json', state(incident))
        return {'state': 'reconciled_sent'}
    # Persist the body before sending: an accepted send without an id leaves state=unknown,
    # and without the text neither side can reconcile what was (or was not) announced.
    journal = {'state': 'sending', 'signature': signature, 'created_at': now.isoformat(), 'event': event, 'target_state': state(incident), 'repair_action': action, 'notification_scope': scope, 'text': text}
    write(pending, journal)
    write(home/'watch-state.json', dict(previous, pending_event=event, unknown_notification_events=[item for item, _ in unresolved] + [event]))
    try:
        receipt = transport(text, config['target'])
        mid = message_id(receipt)
        write(pending, dict(journal, state='sent' if mid else 'unknown', message_id=mid, checked_at=now.isoformat()))
        if not mid: return {'state': 'notification_unknown_no_retry'}
    except Exception as error:
        write(pending, dict(journal, state='unknown', error=type(error).__name__, checked_at=now.isoformat()))
        return {'state': 'notification_unknown_no_retry'}
    write(home/'watch-state.json', state(incident))
    request_repair()
    return {'state': 'sent', 'message_id': mid}

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', nargs='?', choices=['check', 'pricing-check', 'claim', 'release', 'status', 'digest', 'review'], default='check')
    parser.add_argument('incident', nargs='?')
    parser.add_argument('--owner', choices=['codex', 'workbuddy'], default='codex')
    args = parser.parse_args()
    if args.action in {'claim', 'release'}:
        import re
        if not args.incident or not re.fullmatch('[a-f0-9]{16}', args.incident): raise SystemExit('valid_incident_required')
        # One lease per (owner, incident): a new event must not overwrite another
        # event's lease. The legacy single-slot claim-<owner>.json is still read
        # (escalate.claim_files) but never written again.
        path = HOME/('claim-%s-%s.json' % (args.owner, args.incident))
        previous = read(path, {}) or {}
        now = datetime.now(timezone.utc).isoformat()
        write(path, {'incident': args.incident, 'owner': args.owner, 'active': args.action == 'claim',
                     'claimed_at': now, 'first_claimed_at': previous.get('first_claimed_at') or now})
        print(json.dumps({'state': 'claimed' if args.action == 'claim' else 'released', 'lease_minutes': 60, 'claim_file': path.name}))
    elif args.action == 'status': print(json.dumps(read(HOME/'snapshot.json', {}), ensure_ascii=False))
    elif args.action == 'review':
        now = datetime.now(timezone.utc)
        state = read(HOME/'watch-state.json', {}) or {}
        general = read(HOME/'snapshot.json', {}) or {}
        pricing = read(HOME/'pricing-snapshot.json', {}) or {}
        receipts = pricing.get('rpg_receipt_details') or {}
        active_ids = [code.rsplit(':', 1)[-1] for code in (state.get('issues') or [])
                      if code.startswith('rpg_pricing_') and ':' in code]
        print(json.dumps({'checked_at': now.isoformat(), 'alerting_issues': state.get('issues') or [],
                          'general_exported_at': general.get('exported_at'),
                          'pricing_exported_at': pricing.get('exported_at'),
                          'pricing_issues': (pricing.get('issues') or [])[:40],
                          'rpg_receipt_details': {jid: receipts[jid] for jid in active_ids[:20] if jid in receipts},
                          'rpg_health': state.get('rpg_health'),
                          'notification_unknown_events': state.get('unknown_notification_events') or [],
                          'muted_issues': (state.get('muted_issues') or [])[:40],
                          'silenced_issues': (state.get('silenced_issues') or [])[:40]}, ensure_ascii=False))
    elif args.action == 'digest':
        # 静默归档查询：这些码按用户 2026-10-27 的口径不发群，只在本机留痕。
        now = datetime.now(timezone.utc)
        state = read(HOME/'watch-state.json', {}) or {}
        today = read(HOME/('silenced-%s.json' % now.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d')), {}) or {}
        print(json.dumps({'checked_at': now.isoformat(),
                          'alerting_blocking_issues': state.get('issues', []),
                          'silenced_today': today,
                          'muted_issues': state.get('muted_issues', []),
                          'blocking_prefixes': list(BLOCKING_PREFIXES)}, ensure_ascii=False, indent=1))
    else:
        result = run(pricing_only=args.action == 'pricing-check')
        write(HOME/'last-run.json', result)
        # Native cron records failures and uses failure_deliver; successful runs stay local.
        if result['state'] == 'notification_unknown_no_retry':
            print('Feishu notification result unknown; preserve outbox, do not blindly resend.')
            raise SystemExit(1)
