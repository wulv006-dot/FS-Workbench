"""Import independently observed Windows browser quotes into a finished monitoring round."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import sys
from uuid import UUID

LIVE_DB = Path('/var/lib/fc27-cloud/v3/control.sqlite3')
MAX_INPUT = 8192


def import_quotes(db, batch, now, apply):
    from fc_collection.package_reader import U4GM, amount, row
    from fc_pricing_v3.competitor_offers import CURRENT_QUANTITIES, PLATFORMS, POLICY, normalize_offers
    from fc_pricing_v3.financial import fingerprint, instant

    if (not isinstance(batch, dict) or set(batch) != {'run_id', 'captured_at', 'offers'}
            or not isinstance(batch['offers'], list) or not 1 <= len(batch['offers']) <= 6):
        raise ValueError('browser_observation_batch_scope')
    run_id, captured_at = batch['run_id'], batch['captured_at']
    if str(UUID(run_id)) != run_id:
        raise ValueError('browser_observation_round_id')
    stamp = instant(captured_at)
    if not 0 <= (now - stamp).total_seconds() <= 900:
        raise ValueError('browser_observation_stale')
    urls = {'U4GM': U4GM}
    slots = set()
    raw = []
    for offer in batch['offers']:
        if not isinstance(offer, dict) or set(offer) != {'source', 'platform', 'purchase_k', 'regular_price', 'bonus_k'}:
            raise ValueError('browser_observation_offer_fields')
        source, platform, quantity = (offer[k] for k in ('source', 'platform', 'purchase_k'))
        if source not in urls or platform not in PLATFORMS or quantity not in CURRENT_QUANTITIES:
            raise ValueError('browser_observation_offer_scope')
        slot = source, platform, quantity
        price, bonus = (amount(offer[k]) for k in ('regular_price', 'bonus_k'))
        if slot in slots or price <= 0 or price.as_tuple().exponent < -2:
            raise ValueError('browser_observation_offer_value')
        slots.add(slot)
        raw.append(dict(row(source, platform, quantity, price, bonus, urls[source], captured_at,
                            'selected_native_price'), run_id=run_id, collection_node='local',
                        evidence_ref={'price_basis': 'selected_native_price', 'capture': 'windows_browser_readback'}))
    offers = normalize_offers(raw, run_id, now)
    if len(offers) != len(slots) or any(not offer['comparable'] for offer in offers):
        raise ValueError('browser_observation_incomparable')

    uri = db.resolve().as_uri() + ('?mode=rw' if apply else '?mode=ro')
    with sqlite3.connect(uri, uri=True, timeout=5) as connection:
        connection.execute('BEGIN IMMEDIATE' if apply else 'BEGIN')
        latest = connection.execute('SELECT id, body FROM market_observations ORDER BY rowid DESC LIMIT 1').fetchone()
        snapshot = connection.execute('SELECT body FROM pricing_snapshots WHERE id=?', (run_id,)).fetchone()
        if not latest or latest[0] != run_id or not snapshot:
            raise ValueError('browser_observation_latest_round_required')
        observation, snap = json.loads(latest[1]), json.loads(snapshot[0])
        evidence = snap['evidence']
        if (snap.get('origin') != 'live_collector' or evidence.get('competitor_policy') != POLICY
                or observation.get('status') != 'observed' or observation.get('run_id') != run_id
                or observation.get('source_snapshot_sha256') != fingerprint(evidence)
                or stamp < instant(evidence['checked_at'])
                or not 0 <= (now - instant(snap['created_at'])).total_seconds() <= 900):
            raise ValueError('browser_observation_original_round_required')
        existing = observation.get('package_offers', [])
        by_slot = {(o['source'], o['platform'], o['purchase_k']): o for o in existing}
        added = [o for o in offers if (o['source'], o['platform'], o['purchase_k']) not in by_slot]
        for source in urls:
            supplemental = [o for o in added if o['source'] == source]
            if not supplemental:
                continue
            status = observation['package_status'][source]
            count = len({(o['platform'], o['purchase_k']) for o in existing + supplemental if o['source'] == source})
            additions = [[o['platform'], o['purchase_k']] for o in supplemental]
            status.setdefault('browser_readbacks', []).append(dict(accepted=additions, captured_at=captured_at))
            status['status'] = 'captured' if count == len(PLATFORMS) * len(CURRENT_QUANTITIES) else 'partial'
        if apply and added:
            observation['package_offers'] = existing + added
            cursor = connection.execute('UPDATE market_observations SET body=? WHERE id=? AND body=?',
                                        (json.dumps(observation, ensure_ascii=False), run_id, latest[1]))
            if cursor.rowcount != 1:
                raise ValueError('browser_observation_changed')
    return dict(run_id=run_id, added=len(added), skipped_existing=len(slots) - len(added),
                written=bool(apply and added), capture='windows_browser_readback')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    sys.path.insert(0, '/opt/fs-fc-control/code')
    sys.path.insert(0, '/opt/fc27-cloud-browser')
    if LIVE_DB.is_symlink():
        raise ValueError('browser_observation_database_link')
    payload = sys.stdin.buffer.read(MAX_INPUT + 1)
    if len(payload) > MAX_INPUT:
        raise ValueError('browser_observation_batch_too_large')
    print(json.dumps(import_quotes(LIVE_DB, json.loads(payload), datetime.now(timezone.utc), args.apply)))


if __name__ == '__main__':
    main()
