"""Host-owned game intelligence and news; replaces the retired monitor collectors."""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import ipaddress
import json
import xml.etree.ElementTree as ET
from pathlib import Path
import socket
import sys
import urllib.error
import urllib.parse
import urllib.request

import game_intelligence as official
import mmoexp_news as news
from boss_daily import atomic, encoded, file_lock

API = 'https://api.deepseek.com'
RESPONSE_BYTES = 10000000


def next_refresh(at):
    local = official.moment(at).astimezone(timezone(timedelta(hours=8)))
    for offset in range(8):
        candidate = (local + timedelta(days=offset)).replace(hour=10, minute=10, second=0, microsecond=0)
        if candidate.weekday() in (1, 4) and candidate > local:
            return candidate.astimezone(timezone.utc)


def refresh_news(root, at):
    # The retired refresh() skips non-Saturdays; reuse its readers and translation on the new schedule.
    root=Path(root)
    try:
        value=news.collect(at)
        if value['documents']:
            try:previous=news.read_snapshot(root)
            except (OSError,ValueError,KeyError,TypeError):previous=None
            value['stale_after']=next_refresh(at).isoformat()
            value=news.enrich_zh(value,previous=previous)
            news.atomic(root/'seo-news.json',value)
        status={k:value[k] for k in ('status','collected_at','version')}
    except (OSError,ValueError,TypeError,ET.ParseError):
        status=dict(status='unavailable',reason='news_fetch_or_parse_failed',collected_at=official.moment(at).isoformat(),last_success_preserved=True)
    status['schema_version']=1
    news.atomic(root/'seo-news.status.json',status)
    return status


class SourceError(Exception):
    """Safe diagnostic codes only; never propagate provider bodies or credentials."""


def public_url(value):
    if not isinstance(value, str) or len(value) > 8192 or any(ord(c) < 32 for c in value):
        raise ValueError('invalid_public_url')
    p = urllib.parse.urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None, 443):
        raise ValueError('invalid_public_url')
    host = p.hostname.rstrip('.').lower()
    if '.' not in host or host.endswith(('.local', '.localhost', '.internal')):
        raise ValueError('invalid_public_url')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return urllib.parse.urlunsplit(p._replace(fragment=''))
    raise ValueError('ip_source_not_allowed')


class DeepSeek:
    def __init__(self, key_reader=None):
        if key_reader is None:
            from direct_provider import _load_key
            key_reader = _load_key
        self.key_reader = key_reader
        self.successful_requests = {'search': 0, 'fetch': 0, 'model': 0}

    def post(self, endpoint, body, kind):
        from direct_provider import NoRedirect
        payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        request = urllib.request.Request(API + endpoint, data=payload, headers={
            'Authorization': 'Bearer ' + self.key_reader(), 'Content-Type': 'application/json'})
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=120) as response:
                raw = response.read(RESPONSE_BYTES + 1)
                if len(raw) > RESPONSE_BYTES:
                    raise SourceError(kind + '_response_too_large')
                result = json.loads(raw)
        except urllib.error.HTTPError as error:
            raise SourceError(kind + '_http_' + str(error.code)) from None
        except (OSError, socket.timeout, ValueError):
            raise SourceError(kind + '_transport_or_json_error') from None
        if not isinstance(result, dict):
            raise SourceError(kind + '_invalid_response')
        return result

    def search(self, query):
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 128:
            raise ValueError('invalid_search_query')
        result = self.post('/v1/tools/search', {'query': query, 'count': 5}, 'search')
        if not isinstance(result.get('results'), list):
            raise SourceError('search_invalid_response')
        if result['results']:
            self.successful_requests['search'] += 1
        return result

    def fetch(self, url):
        result = self.post('/v1/tools/fetch', {'url': public_url(url)}, 'fetch')
        if not isinstance(result.get('content'), str) or not result['content'].strip():
            raise SourceError('fetch_empty_content')
        self.successful_requests['fetch'] += 1
        return result

    def model(self, messages):
        from direct_provider import MODEL, OUTPUT_TOKENS, request_model
        from proxy_gateway import schemas
        result=request_model(dict(model=MODEL,messages=messages,max_tokens=OUTPUT_TOKENS,
            tools=[],stream=False,enable_thinking=True,reasoning_effort='high'),schemas())
        if result.get('status'):
            code=result['status']
            raise SourceError('model_'+code if isinstance(code,str) and code.replace('_','').isalnum() else 'model_invalid_response')
        self.successful_requests['model'] += 1
        return result

    def direct(self, spec):
        raw, _, final = official.fetch(spec['url'], spec['hosts'])
        return official.parse(spec, raw, final)


def collect(game_keys, client, at):
    keys = list(dict.fromkeys(game_keys))
    if not keys or any(key not in official.GAMES for key in keys):
        raise ValueError('unregistered_game')
    at = official.moment(at)
    documents, statuses = [], []
    for key in keys:
        sources = [source for source in official.SOURCES if key in source['games']]
        hosts = sorted({host for source in sources for host in source['hosts']})
        source_id = 'deepseek-' + key
        query = '"' + official.GAMES[key] + '" update season after:' + (at - timedelta(days=14)).date().isoformat()
        steam = next((s for s in sources if s['kind']=='steam'), None)
        if steam:
            app = urllib.parse.parse_qs(urllib.parse.urlsplit(steam['url']).query)['appid'][0]
            query = '"' + official.GAMES[key] + '" after:' + (at-timedelta(days=14)).date().isoformat() + ' site:steamcommunity.com'
        elif sources:
            query += ' site:' + urllib.parse.urlsplit(sources[0]['url']).hostname
        status = dict(source_id=source_id, games=[key], url=sources[0]['url'] if sources else '',
                      status='failed', documents=0, failed_fetches=0, candidate_checks=[], reason=None, method='deepseek_search_fetch')
        seen = set()
        try:
            results = client.search(query)
            if not isinstance(results, dict) or not isinstance(results.get('results'), list):
                raise SourceError('search_invalid_response')
            status['reason'] = 'no_search_matches' if not results['results'] else 'no_verified_official_documents'
            for row in results['results']:
                if not isinstance(row, dict):
                    continue
                try:
                    url = public_url(row.get('url'))
                    if urllib.parse.urlsplit(url).hostname not in hosts or url in seen:
                        continue
                    seen.add(url)
                    page = client.fetch(url)
                    content = page.get('content')
                    title = page.get('title') or row.get('title') or ''
                    host = urllib.parse.urlsplit(url).hostname
                    path = urllib.parse.urlsplit(url).path
                    bound = bool(steam and ((host=='steamcommunity.com' and path.startswith('/games/'+app+'/announcements/detail/')) or (host=='store.steampowered.com' and path.startswith('/news/app/'+app+'/view/'))))
                    # Official domains can host player posts; the real probe returned General Discussion.
                    if host=='www.pathofexile.com' and '/forum/' in path and not title.startswith('Announcements - '):
                        status['candidate_checks'].append(dict(url=url,reason='community_forum_not_official_announcement'))
                        continue
                    if host in ('steamcommunity.com','store.steampowered.com') and not bound:
                        status['candidate_checks'].append(dict(url=url,reason='unbound_steam_page'))
                        continue
                    if host=='forum.netmarble.com' and not path.startswith('/raven2_gb/view/27/'):
                        status['candidate_checks'].append(dict(url=url,reason='community_board_not_official_announcement'))
                        continue
                    if not isinstance(content, str) or not bound and key not in official.named_games(content):
                        status['candidate_checks'].append(dict(url=url, reason='game_name_not_confirmed', content_characters=len(content) if isinstance(content,str) else 0))
                        continue
                    matching = steam if bound else next(s for s in sources if host in s['hosts'])
                    spec = dict(source_id=source_id, hosts=hosts, games=matching['games'], discovery=False)
                    doc = official.document(spec, url, title or official.GAMES[key], content, row.get('date'))
                    if doc:
                        documents.append(doc)
                        status['documents'] += 1
                    else:
                        status['candidate_checks'].append(dict(url=url, reason='empty_or_blocked_original', content_characters=len(content)))
                except ValueError:
                    continue
                except SourceError as error:
                    status['failed_fetches'] += 1
                    status['reason'] = str(error)
            if status['documents']:
                status.update(status='available', reason=None)
        except SourceError as error:
            status['reason'] = str(error)
        if not status['documents'] and sources and hasattr(client,'direct'):
            status['search_reason'] = status['reason']
            try:
                direct = client.direct(steam or sources[0])
                for doc in direct:
                    if key in doc['game_keys']:
                        documents.append(doc)
                        status['documents'] += 1
                if status['documents']:
                    status.update(status='available',reason=None,method='existing_official_reader')
            except (ValueError,OSError,KeyError,TypeError):
                status['direct_reason'] = 'existing_official_reader_failed'
        statuses.append(status)
    # Keep the existing message contract and its explicit partial-coverage accounting.
    accepted, omitted = [], 0
    unique = {doc['document_id']:doc for doc in documents}
    groups = {key:[doc for doc in unique.values() if key in doc['game_keys']] for key in keys}
    ordered, seen_docs = [], set()
    while any(groups.values()):
        for key in keys:
            if groups[key]:
                doc = groups[key].pop(0)
                if doc['document_id'] not in seen_docs:
                    ordered.append(doc);seen_docs.add(doc['document_id'])
    for doc in ordered:
        if len(accepted) >= official.MAX_DOCUMENTS or len(json.dumps(accepted + [doc]).encode()) > official.MAX_DOCUMENT_BYTES:
            omitted += 1
        else:
            accepted.append(doc)
    covered = sorted(set(keys) & {key for doc in accepted for key in doc['game_keys']})
    return dict(collected_at=at.isoformat(), documents=accepted, source_status=statuses,
        coverage=dict(total_games=len(keys), covered_games=covered,
            missing_games=sorted(set(keys) - set(covered)), sources_available=sum(s['status']=='available' for s in statuses),
            total_sources=len(statuses), source_documents_omitted=omitted,
            partial=bool(omitted or len(covered)!=len(keys) or any(s['failed_fetches'] for s in statuses)), basis='verified_official_search_documents_not_event_completeness'))


def run_once(root, game_keys, client, model, at):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    with file_lock(root / '.intelligence.lock'):
        atomic(root/'intelligence.status.json',encoded(dict(schema_version=1,status='pending',
            attempted_at=official.moment(at).isoformat())),0o644)
        batch = collect(game_keys, client, at)
        status = dict(schema_version=1, attempted_at=official.moment(at).isoformat(),
                      status='failed', reason='no_verified_documents', source_status=batch['source_status'])
        if batch['documents']:
            try:
                result = official.validate_response(model(official.messages(batch)), batch)
                previous_file = root / 'intelligence.json'
                previous = json.loads(previous_file.read_bytes()) if previous_file.exists() else None
                snapshot = official.build_snapshot(batch, result, previous)
                snapshot.update(stale_after=next_refresh(at).isoformat(),
                    notice='游戏情报统一采集：每周二、周五北京时间10:10，DeepSeek 搜索/抓取与官方直采，保留原文、日期和游戏归属校验。',
                    method='deepseek_search_fetch', request_counts=getattr(client, 'successful_requests', {}))
                for event in snapshot['events']:
                    event.setdefault('expires_at',next_refresh(event['collected_at']).isoformat())
                snapshot['version'] = 'game-intel-' + sha256(encoded(snapshot)).hexdigest()[:20]
                payload=encoded(snapshot)
                atomic(previous_file, payload, 0o644)
                # The active nightly reader requires this existing snapshot and SHA receipt contract.
                atomic(root/'game-monitor.json',payload,0o644)
                status.update(status='succeeded', reason=None, version=snapshot['version'],
                              events=len(snapshot['events']), request_counts=getattr(client,'successful_requests',{}))
            except (SourceError, ValueError, KeyError, TypeError, OSError) as error:
                status['reason'] = 'snapshot_io_failed' if isinstance(error,OSError) else str(error) if isinstance(error, SourceError) or str(error) in official.EVENT_REJECTION_REASONS else 'event_validation_failed'
        status['request_counts'] = getattr(client, 'successful_requests', {})
        atomic(root / 'intelligence.status.json', encoded(status), 0o644)
        report=dict(status=status['status'],phase='completed',day=official.moment(at).astimezone(timezone(timedelta(hours=8))).date().isoformat(),
            collected_at=official.moment(at).isoformat(),reason=status.get('reason'),collector='fs-game-intelligence')
        if status['status']=='succeeded':
            report['public_sha256']=sha256((root/'game-monitor.json').read_bytes()).hexdigest()
        atomic(root/'game-monitor.status.json',encoded(report),0o644)
        return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--game', choices=sorted(official.GAMES), action='append')
    parser.add_argument('--publish', action='store_true', help='Host-only: atomically update the configured public feed.')
    parser.add_argument('--root', type=Path, default=Path('/var/lib/fs-boss-workspaces/public'))
    args = parser.parse_args()
    client, at = DeepSeek(), datetime.now(timezone.utc)
    keys = args.game or list(official.GAMES)
    if args.publish:
        result = run_once(args.root, keys, client, client.model, at)
        result['seo_news']=refresh_news(args.root,at)
    else:
        result = collect(keys, client, at)
        result['request_counts'] = client.successful_requests
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return 1 if result.get('status') == 'failed' else 0


if __name__ == '__main__':
    sys.exit(main())
