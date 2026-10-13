import json

line = open('/tmp/pb_probe2.log').read().split('\n')[1]
d = json.loads(line)
for r in d['rows']:
    if 'ManCity' in (r.get('title') or '') or 'Paris' in (r.get('title') or ''):
        print(r['id'], r['aid'], r['unit_price'], r['price'], r['discount'], r['status'])
