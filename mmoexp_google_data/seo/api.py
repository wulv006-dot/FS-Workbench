"""Mount inside the existing authenticated FS host; never derive actors from request headers."""
import csv
import io
import re

from .contracts import game
from . import snapshot


class Service:
    def __init__(self, root, policy):
        self.root, self.policy = root, policy

    def handle(self, method, path, query, actor, *, body=None, mutation_authorized=False):
        if actor is None or not actor.id:
            return 401, dict(error='LOGIN_REQUIRED')
        try:
            if path == '/api/seo/v1/ai-policy':
                if query:
                    raise ValueError('INVALID_POLICY_QUERY')
                if method == 'PATCH':
                    if not mutation_authorized:
                        return 403, dict(error='CSRF_REQUIRED')
                    if not isinstance(body, dict) or set(body) != {'patch', 'expected_revision'}:
                        raise ValueError('INVALID_POLICY_BODY')
                    return 200, self.policy.update(body['patch'], body['expected_revision'], actor)
                if method != 'GET':
                    return 405, dict(error='METHOD_NOT_ALLOWED')
                value = self.policy.read()
                value['projects'] = {g:p for g,p in value['projects'].items() if g in actor.games}
                value['can_manage'] = actor.manage
                value['runtime_status'] = 'not_configured'
                return 200, value
            if method != 'GET':
                return 405, dict(error='METHOD_NOT_ALLOWED')
            if path == '/api/seo/v1/snapshots/current':
                if query:
                    raise ValueError('INVALID_CURRENT_QUERY')
                value = snapshot.current(self.root)
                if not value:
                    return 404, dict(error='NO_PUBLISHED_SNAPSHOT')
                value = dict(value, games=[g for g in value['games'] if g in actor.games])
                return 200, value
            manifest = re.fullmatch(r'/api/seo/v1/snapshots/(seo-\d{4}-\d{2}-\d{2})/manifest', path)
            if manifest:
                if query:
                    raise ValueError('INVALID_MANIFEST_QUERY')
                db, value = snapshot.open_snapshot(self.root, manifest[1])
                db.close()
                return 200, dict(value, games=[g for g in value['games'] if g in actor.games])
            match = re.fullmatch(r'/api/seo/v1/snapshots/(seo-\d{4}-\d{2}-\d{2})/(summary|history|sources|rankings|markets|calendar|pages|orders|rules)', path)
            if not match:
                return 404, dict(error='NOT_FOUND')
            if not isinstance(query, dict) or set(query)-{'game', 'cursor', 'limit'}:
                raise ValueError('INVALID_SNAPSHOT_QUERY')
            scope = game(query.get('game'))
            if scope not in actor.games:
                return 403, dict(error='SEO_GAME_DENIED')
            return 200, snapshot.read(self.root, match[1], match[2], scope, int(query.get('cursor', 0)), int(query.get('limit', 100)))
        except PermissionError:
            return 403, dict(error='SEO_PERMISSION_DENIED')
        except (ValueError, TypeError) as error:
            if str(error) == 'POLICY_REVISION_CONFLICT':
                return 409, dict(error='POLICY_REVISION_CONFLICT')
            return 422, dict(error='INVALID_SEO_REQUEST')
        except FileNotFoundError:
            return 410, dict(error='SNAPSHOT_EXPIRED')

    def export(self, ident, scope, actor):
        if actor is None or scope not in actor.games:
            raise PermissionError('SEO_EXPORT_DENIED')
        cursor = 0
        yield 'snapshot_id,facts_hash,game,source_date,gsc_clicks,gsc_impressions,ga4_sessions,purchase_events,admin_customer_price_usd,estimated_seo_revenue_usd,estimate_status,gsc_data_status,gsc_timezone,ga4_data_status,ga4_timezone,admin_data_status,admin_timezone\r\n'
        while cursor is not None:
            result = snapshot.read(self.root, ident, 'history', scope, cursor=cursor)
            for row in result['rows']:
                m = row['metrics']
                values = [ident, result['facts_hash'], scope, row['source_date'],
                    (m['gsc'] or {}).get('clicks'), (m['gsc'] or {}).get('impressions'),
                    (m['ga4'] or {}).get('sessions'), (m['ga4'] or {}).get('purchase_events'),
                    (m.get('admin') or {}).get('admin_customer_price_usd'), row['estimate']['revenue_usd'], row['estimate']['status'],
                    row['source_status']['gsc']['status'],row['source_status']['gsc'].get('source_timezone'),
                    row['source_status']['ga4']['status'],row['source_status']['ga4'].get('source_timezone'),
                    row['source_status']['admin']['status'],row['source_status']['admin'].get('source_timezone')]
                text = io.StringIO(newline='')
                csv.writer(text).writerow(values)
                yield text.getvalue()
            cursor = result['next_cursor']
