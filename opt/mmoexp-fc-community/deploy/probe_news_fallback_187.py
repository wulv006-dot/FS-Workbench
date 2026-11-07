import json
import sys
sys.path.insert(0, '/tmp/fc27-news-route-20261108')
from collector_router import collect, fetch_remote_html
from news_feed import parse_source

for source in ('mmoexp', 'ea'):
    calls = []
    def local_fetch(source_id):
        raise TimeoutError('simulated 187 timeout')
    def remote_fetch(source_id):
        calls.append(source_id)
        return parse_source(source_id, fetch_remote_html(source_id,
                            key_path='/etc/mmoexp-fc-news/collector_ed25519',
                            known_hosts='/etc/mmoexp-fc-news/known_hosts'))
    rows, meta = collect(source, 'auto', local_fetch, remote_fetch)
    assert meta['collector'] == '183' and meta['fallback'] is True and calls == [source]
    assert len(rows) > 0
    print(json.dumps({'source':source, 'rows':len(rows), 'metadata':meta, 'remote_calls':len(calls)}))
