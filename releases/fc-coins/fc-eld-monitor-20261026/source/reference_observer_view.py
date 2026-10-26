"""Public-market projection for the existing authenticated FC API; no collection."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import json
import os
from pathlib import Path
import subprocess
import tempfile

STATE = Path('/var/lib/fc27-price-observer')
VIEW = Path('/var/lib/fc27-cloud/monitor/reference-observer.json')
SOURCES = ('Lootbar', 'U7Buy', 'ItemD2R', 'IGGM', 'U4GM')
PLATFORMS = ('PS', 'XBOX', 'PC')


def load(path):
    if path.stat().st_size > 2_000_000:
        raise ValueError('observation_file_too_large')
    return json.loads(path.read_text(encoding='utf-8'))


def number(value):
    try:
        result = Decimal(str(value))
        return str(result) if result.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def offers(rows):
    output = []
    for row in rows:
        if row.get('source') not in SOURCES or row.get('platform') not in PLATFORMS:
            continue
        valid = (row.get('status') == 'valid' and row.get('currency') == 'USD'
                 and row.get('comparable', True) is True and not row.get('conditional'))
        output.append({**{k: row.get(k) for k in ('source', 'platform', 'captured_at')},
                       'status': 'valid' if valid else 'missing',
                       **{k: number(row.get(k)) if valid else None for k in
                          ('gross_usd', 'purchase_k', 'bonus_k', 'effective_usd_per_k')}})
    return output


def project(record):
    simulation = record.get('simulation', {})
    weighted = []
    for platform in PLATFORMS:
        data = simulation.get('weighted_platforms', {}).get(platform, {})
        for scenario in data.get('scenarios', [])[:3]:
            if number(scenario.get('weighted_unit')) is None:
                continue
            weighted.append({'platform': platform,
                             'storefront_comparable': data.get('storefront_problem') is None,
                             **{k: number(scenario.get(k)) for k in
                                ('anchor_weight', 'weighted_unit', 'delta_vs_lootbar_pct', 'delta_vs_storefront_pct')},
                             'unavailable_sources': [s for s in data.get('unavailable_sources', []) if s in SOURCES]})
    return {'run_id': record.get('run_id'), 'status': record.get('status'),
            'started_at': record.get('started_at'), 'completed_at': record.get('completed_at'),
            'simulation_status': simulation.get('status', 'not_evaluated'),
            'itemd2r': offers(record.get('itemd2r', [])),
            'eldorado':record.get('eldorado',{'status':'not_collected','platforms':[],'direct_pricing_weight':'0'}),
            'market': offers(record.get('original_competitors', []) + record.get('itemd2r', [])),
            'weighted': weighted}


def build_view(state=STATE):
    paths = sorted((state / 'samples').glob('*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
    samples, failures = [], 0
    # shortcut: the page covers the latest 100 samples; use the private archive for longer research.
    for path in paths[:100]:
        try:
            samples.append(project(load(path)))
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            failures += 1
    samples.sort(key=lambda r: r.get('started_at') or '', reverse=True)
    observed = [s for s in samples if s['status'] == 'observed']
    eld=next((s['eldorado'] for s in samples if s.get('eldorado',{}).get('status') not in (None,'not_collected')),None)
    if eld is None and (state/'eldorado-initial.json').is_file():
        initial=load(state/'eldorado-initial.json')
        eld={k:initial.get(k) for k in ('source','kind','status','operation_id','observed_at','platforms','direct_pricing_weight')}
    eld=eld or {'status':'not_collected','platforms':[],'direct_pricing_weight':'0'}
    return {'schema': 1, 'simulation_only': True, 'business_effect': 'none',
            'exported_at': datetime.now(timezone.utc).isoformat(),
            'archive_count': len(paths), 'window_count': len(samples), 'read_failures': failures,
            'observed_count': len(observed), 'comparable_count': sum(bool(s['weighted']) for s in observed),
            'eldorado':eld,
            'latest_attempt': samples[0] if samples else None,
            'latest_observed': observed[0] if observed else None,
            'history': [{k: s[k] for k in ('run_id', 'status', 'started_at', 'completed_at', 'simulation_status', 'itemd2r')}
                        for s in samples]}


def publish_view():
    import grp
    payload = build_view()
    fd, name = tempfile.mkstemp(prefix='.reference-observer-', dir=VIEW.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(payload, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chown(name, 0, grp.getgrnam('fc27cloud').gr_gid)
        os.chmod(name, 0o640)
        os.replace(name, VIEW)
    finally:
        if os.path.exists(name):
            os.unlink(name)
    return payload


def read_view():
    payload = load(VIEW) if VIEW.exists() else {'schema': 1, 'simulation_only': True, 'business_effect': 'none',
                                               'history': [], 'window_count': 0, 'observed_count': 0,
                                               'comparable_count': 0, 'archive_count': 0, 'read_failures': 0}
    try:
        result = subprocess.run(['systemctl', 'show', 'fc27-price-observer.service',
                                 '-p', 'ActiveState', '-p', 'SubState', '-p', 'Result'],
                                capture_output=True, text=True, timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        result = None
    if result is None or result.returncode:
        payload['service'] = {'ActiveState': 'unknown', 'Result': 'status_unavailable'}
    else:
        payload['service'] = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    return payload
