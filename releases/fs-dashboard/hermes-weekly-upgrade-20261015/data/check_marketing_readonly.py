"""Read-only acceptance: numbers, source dates and hashes; no source free text."""
import argparse
from hashlib import sha256
import json
from pathlib import Path

from marketing_snapshot import MarketingReader


def summary(value):
    out = {k: value.get(k) for k in ('status', 'reason', 'captured_at', 'read_at', 'source_sha256')}
    out['sources'] = {}
    for source, record in value.get('sources', {}).items():
        if source not in ('ga4', 'gsc'):
            continue
        out['sources'][source] = {key: record.get(key) for key in ('resource', 'timezone', 'status', 'coverage', 'metrics')}
        for name in ('country', 'source_medium'):
            table = record.get(name) or {}
            out['sources'][source][name] = {key: table.get(key) for key in ('status', 'row_coverage', 'returned_dimension_rows', 'rejected_rows', 'output_capped')}
            out['sources'][source][name]['projected_rows'] = len(table.get('rows', []))
    out['ads_accounts'] = []
    for account in value.get('ads_accounts', []):
        campaign = account.get('campaigns') or {}
        out['ads_accounts'].append({**{key: account.get(key) for key in ('customer_id', 'brand', 'currency', 'timezone', 'status', 'coverage', 'metrics')},
                                    'campaign_rows': len(campaign.get('rows', [])),
                                    'source_campaign_count': campaign.get('source_campaign_count'),
                                    'campaign_rejected_rows': campaign.get('rejected_rows'),
                                    'campaign_row_cost_coverage': campaign.get('row_cost_coverage')})
    out['ads_geography_available'] = value.get('ads_geography', {}).get('status') == 'available'
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    args = parser.parse_args()
    value = MarketingReader()({'profile': 'FC27', 'start': args.start, 'end': args.end})
    out = summary(value)
    out['runtime_sha256'] = {name: sha256((Path(__file__).resolve().parent/name).read_bytes()).hexdigest()
                             for name in ('marketing_snapshot.py', 'research.py', 'fs_evidence.py')
                             if (Path(__file__).resolve().parent/name).is_file()}
    print(json.dumps(out, ensure_ascii=True, sort_keys=True, allow_nan=False))
    return 0 if value.get('contract') == 'fc-marketing-read-v1' and value.get('sources') else 1


if __name__ == '__main__': raise SystemExit(main())
