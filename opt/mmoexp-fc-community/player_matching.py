"""Conservative FC27 identity matching against EasySBC's public, credential-free data.

No Discord calls or writes. FUTBIN IDs are never used as EasySBC resource IDs.
"""
import json
import re
import time
import unicodedata
import urllib.request
from urllib.parse import urlsplit, parse_qs

API = 'https://api-fc27.easysbc.io'
SITE = 'https://www.easysbc.io'
MAX_BYTES = 4 * 1024 * 1024


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError('Unexpected source redirect')


class PublicSource:
    """Only the three paths observed in the official FC27 website bundle."""
    def __init__(self):
        self._base = None
        self._base_at = 0

    def _request(self, path, payload=None):
        data = None if payload is None else json.dumps(payload).encode('utf-8')
        request = urllib.request.Request(API + path, data=data,
                                        headers={'Content-Type': 'application/json', 'User-Agent': 'MMOEXP-FC27/1.0'})
        with urllib.request.build_opener(_NoRedirect).open(request, timeout=6) as response:
            body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('Source response too large')
        return json.loads(body)

    def base_data(self):
        if self._base is None or time.monotonic() - self._base_at > 600:
            value = self._request('/base-data')
            if not isinstance(value, dict) or not isinstance(value.get('versionAssets'), dict):
                raise ValueError('Invalid version dictionary')
            self._base, self._base_at = value, time.monotonic()
        return self._base

    def search(self, name):
        # Official UI uses page=1. Live probes show subsequent pages repeat the same response.
        rows = self._request('/players/search', {'searchText': name, 'page': 1, 'platform': 'Playstation'})
        if not isinstance(rows, list) or len(rows) > 100:
            raise ValueError('Invalid search response')
        seen = set()
        for row in rows:
            key = str(row.get('resourceId')) if isinstance(row, dict) else ''
            if key in seen or not key.isdigit():
                return {'items': rows, 'complete': False}
            seen.add(key)
        return {'items': rows, 'complete': True}

    def detail(self, resource_id, role_id):
        if not re.fullmatch(r'[1-9][0-9]{0,11}', str(resource_id)) or not re.fullmatch(r'[1-9][0-9]{0,11}', str(role_id)):
            raise ValueError('Invalid source identity')
        return self._request('/players/' + str(resource_id) + '?v2&player-role-id=' + str(role_id))


_SOURCE = PublicSource()


def _normal(value):
    value = unicodedata.normalize('NFKD', str(value)).casefold()
    return ''.join(c for c in value if c.isalnum() and not unicodedata.combining(c))


def _name_compatible(first, second):
    if _normal(first) == _normal(second):
        return True
    left = {_normal(word) for word in str(first).split()}
    right = {_normal(word) for word in str(second).split()}
    return min(len(left), len(right)) >= 2 and (left <= right or right <= left)


def _version(value):
    value = _normal(value)
    aliases = {'uclrttk': 'uefachampionsleaguerttk', 'uwclrttk': 'uefawomenschampionsleaguerttk',
               'uelrttk': 'uefaeuropaleaguerttk', 'ueclrttk': 'uefaconferenceleaguerttk'}
    return aliases.get(value, value)


def _target(card):
    if not isinstance(card, dict) or card.get('season', 27) not in (27, '27', 'FC27', 'fc27') or card.get('gid', 1327) != 1327:
        raise ValueError('Wrong season')
    mid = card.get('model_id', str(card.get('id', '')).removeprefix('players:'))
    if isinstance(mid, bool) or not re.fullmatch(r'[1-9][0-9]{0,11}', str(mid)):
        raise ValueError('Invalid model ID')
    parts = str(card.get('title', '')).split('/')
    name = card.get('name') or (parts[0].strip() if len(parts) >= 4 else '')
    rating = card.get('rating') or (parts[1].strip() if len(parts) >= 4 else '')
    position = card.get('position') or (parts[2].strip() if len(parts) >= 4 else '')
    version = card.get('card_version') or (parts[3].strip() if len(parts) >= 4 else '')
    kind = card.get('card_type') or (parts[4].strip() if len(parts) == 5 else '')
    if not isinstance(name, str) or not 2 <= len(name) <= 100 or any(ord(c) < 32 for c in name) or not str(rating).isdigit() or not 1 <= int(rating) <= 99 or not version:
        raise ValueError('Incomplete card identity')
    return {'model_id': int(mid), 'name': name, 'rating': int(rating), 'position': re.sub(r'\++$', '', position),
            'version': version, 'kind': kind}


def _candidate(row, target, versions, role=None):
    rid = str(row['resourceId'])
    if not re.fullmatch(r'[1-9][0-9]{0,11}', rid):
        raise ValueError('Invalid resource ID')
    version = versions.get(str(row['versionId']), {}).get('name', '')
    roles = [str(item['playerRoleId']) for item in row.get('metaRatings', []) if isinstance(item, dict) and str(item.get('playerRoleId', '')).isdigit()]
    if role is None:
        # The official search UI uses the first metaRatings entry as its default role.
        role = roles[0] if roles else str(row.get('playerRoleId', ''))
    if not re.fullmatch(r'[1-9][0-9]{0,11}', role) or role not in roles and role != str(row.get('playerRoleId', '')):
        raise ValueError('Unknown player role')
    positions = row.get('possiblePositions', row.get('positions', []))
    core = (row['rating'] == target['rating'] and _version(version) == _version(target['version'])
            and target['position'] in positions)
    exact = _normal(row['name']) == _normal(target['name']) and core
    compatible = _name_compatible(row['name'], target['name']) and core
    cosmetic = bool(row.get('foil') or row.get('cosmetics'))
    # Foil is observed, but no public Signature label was verified. Do not invent one.
    automatic = bool(exact and _normal(target['kind']) in ('', 'signature'))
    return {'model_id': target['model_id'], 'easysbc_id': rid, 'easysbc_role_id': role,
            'easysbc_url': SITE + '/players/' + rid + '?player-role-id=' + role,
            'label': str(row['name']) + ' · ' + str(row['rating']) + ' · ' + (version or 'Unknown version') + (' · Special cosmetic' if cosmetic else ''),
            'name': row['name'], 'rating': row['rating'], 'version': version, 'season': 27,
            'asset_id': str(row.get('assetId', '')), 'cosmetic': cosmetic, 'identity_exact': bool(exact), 'identity_compatible': bool(compatible),
            'automatic_eligible': automatic}


def _mapping(candidate):
    return {key: candidate[key] for key in ('model_id', 'easysbc_id', 'easysbc_role_id', 'easysbc_url')}


def _existing_identity(value):
    if not isinstance(value, dict):
        return None
    rid, role = str(value.get('easysbc_id', '')), str(value.get('easysbc_role_id', ''))
    url = value.get('easysbc_url')
    if url:
        parsed = urlsplit(url)
        match = re.fullmatch(r'/players/(?:[A-Za-z0-9_-]+/){0,2}([1-9][0-9]{0,11})/?', parsed.path)
        query_roles = parse_qs(parsed.query).get('player-role-id', [])
        if parsed.scheme != 'https' or parsed.hostname not in ('www.easysbc.io', 'easysbc.io') or parsed.username or parsed.password or parsed.port not in (None, 443) or not match or len(query_roles) != 1:
            return None
        if rid and rid != match[1] or role and role != query_roles[0]:
            return None
        rid, role = match[1], query_roles[0]
    return (rid, role) if re.fullmatch(r'[1-9][0-9]{0,11}', rid) and re.fullmatch(r'[1-9][0-9]{0,11}', role) else None


def resolve(card, existing_mapping=None, *, source=None):
    """Return matched / ambiguous / unavailable; no mutations, tokens, or guessed IDs.

    Inject a source with base_data(), search(name)->{items,complete}, detail(id,role).
    Scope is FC27 only; callers supply an FC27 Admin card (model_id or players:id).
    """
    source = source or _SOURCE
    result = {'status': 'unavailable', 'candidates': [], 'reason': 'invalid_card'}
    try:
        target = _target(card)
        base = source.base_data()
        versions = base['versionAssets']
        found = source.search(target['name'])
        if not isinstance(found, dict) or not isinstance(found.get('items'), list):
            raise ValueError('Invalid source response')
        candidates = []
        for row in found['items']:
            try:
                candidate = _candidate(row, target, versions)
                # Only plausible same-person / same-rating results are offered for confirmation.
                if candidate['identity_compatible']:
                    candidates.append(candidate)
            except (KeyError, TypeError, ValueError):
                continue
        unique = {c['easysbc_id']: c for c in candidates}
        result['candidates'] = list(unique.values())
        if not result['candidates']:
            result['reason'] = 'no_trustworthy_candidates'
            return result
        result.update(status='ambiguous', reason='confirm_version_or_cosmetic')
        if found.get('complete') is not True:
            result['reason'] = 'incomplete_search'
            return result
        identity = _existing_identity(existing_mapping)
        chosen = None
        previously_confirmed = False
        if identity and int(existing_mapping.get('model_id', target['model_id'])) == target['model_id']:
            rid, role = identity
            row = next((r for r in found['items'] if str(r.get('resourceId')) == rid), None)
            if row is not None:
                checked = _candidate(row, target, versions, role)
                # Previously confirmed cosmetic choice can be retained only with exact core identity.
                if checked['identity_compatible']:
                    chosen = checked
                    previously_confirmed = True
        automatic = [c for c in result['candidates'] if c['automatic_eligible']]
        normal = [c for c in automatic if not c['cosmetic']]
        preferred = normal if normal else automatic
        # The user treats standard and animated/Signature cards as one base item.
        # Never extend this tie-break to different players, ratings, versions, or unknown kinds.
        same_asset = (preferred and all(c['asset_id'].isdigit() for c in preferred)
                      and len({c['asset_id'] for c in preferred}) == 1)
        if len(normal) == 1 and (chosen is None or chosen['cosmetic'] and chosen['asset_id'] == normal[0]['asset_id']):
            chosen = normal[0]
            previously_confirmed = False
        elif chosen is None and preferred and (len(preferred) == 1 or same_asset and all(c['cosmetic'] for c in preferred)):
            chosen = min(preferred, key=lambda c: int(c['easysbc_id']))
        elif chosen and chosen['cosmetic'] and _normal(target['kind']) in ('', 'signature'):
            compatible_normal = [c for c in result['candidates'] if not c['cosmetic'] and c['identity_compatible']
                                 and c['asset_id'].isdigit() and c['asset_id'] == chosen['asset_id']]
            if len(compatible_normal) == 1:
                chosen = compatible_normal[0]
                previously_confirmed = True
        if chosen is None:
            return result
        detail = source.detail(chosen['easysbc_id'], chosen['easysbc_role_id'])
        alternatives = detail.get('alternativeVersions')
        if not isinstance(alternatives, list):
            result['reason'] = 'alternative_versions_unknown'
            return result
        matching_alternatives = {str(row['resourceId']) for row in alternatives
                                 if row.get('rating') == target['rating'] and row.get('versionId') == detail.get('versionId')}
        if not matching_alternatives or not matching_alternatives <= set(unique):
            result['reason'] = 'incomplete_card_variants'
            return result
        confirmed = _candidate(detail, target, versions, chosen['easysbc_role_id'])
        if (confirmed['easysbc_id'] != chosen['easysbc_id'] or not confirmed['identity_compatible' if previously_confirmed else 'identity_exact']
                or confirmed['cosmetic'] != chosen['cosmetic'] or confirmed['asset_id'] != chosen['asset_id']):
            result['reason'] = 'detail_mismatch'
            return result
        result.update(status='matched', mapping=_mapping(confirmed), reason='public_identity_verified',
                      selection_policy='same_base_standard_first_else_cosmetic')
        return result
    except Exception:
        result['reason'] = 'source_unavailable_or_invalid'
        return result
