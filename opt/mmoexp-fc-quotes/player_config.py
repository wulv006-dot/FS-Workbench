"""Credential-free Player configuration validation shared with FS."""
import re
from urllib.parse import urlsplit, parse_qs

AREAS = {21587, 21585, 21589}

GUILDS = (1565922092518613064, 1041923524601851914)


def validate_player_config(value):
    keys = {'enabled', 'guild_id', 'channel_id', 'featured_model_ids', 'allowed_tag_ids', 'verified_prices'}
    if not isinstance(value, dict) or set(value) not in (keys, keys | {'easysbc'}) or type(value['enabled']) is not bool:
        raise ValueError('Invalid player configuration')
    if type(value['guild_id']) is not int or value['guild_id'] not in GUILDS:
        raise ValueError('Invalid player guild')
    if type(value['channel_id']) is not int or not 10**16 <= value['channel_id'] < 10**20:
        raise ValueError('Invalid player channel')
    for key in ('featured_model_ids', 'allowed_tag_ids'):
        ids = value[key]
        if (not isinstance(ids, list) or len(ids) > 25 or any(type(v) is not int or not 1 <= v < 10**12 for v in ids)
                or len(set(ids)) != len(ids)):
            raise ValueError('Invalid player list')
    prices = value['verified_prices']
    if not isinstance(prices, dict) or len(prices) > 500:
        raise ValueError('Invalid verified players')
    for mid, platforms in prices.items():
        if (not isinstance(mid, str) or not mid.isascii() or not mid.isdigit() or not 1 <= int(mid) < 10**12 or str(int(mid)) != mid
                or not isinstance(platforms, list) or not platforms
                or any(type(a) is not int or a not in AREAS for a in platforms)
                or len(set(platforms)) != len(platforms)):
            raise ValueError('Invalid verified platforms')
    if 'easysbc' in value:
        validate_easysbc_config(value['easysbc'])
    return value



def validate_easysbc_config(value):
    if (not isinstance(value, dict) or set(value) not in ({'template', 'selection', 'tag_match', 'mappings'},
                {'template', 'selection', 'tag_match', 'mappings', 'with_card'})
            or type(value.get('with_card', False)) is not bool
            or value['template'] not in ('card', 'price', 'info', 'meta')
            or value['selection'] not in ('featured', 'tags') or value['tag_match'] not in ('any', 'all')
            or not isinstance(value['mappings'], list) or len(value['mappings']) > 500):
        raise ValueError('Invalid EasySBC configuration')
    seen_models, seen_ids, seen_urls = set(), set(), set()
    for mapping in value['mappings']:
        if (not isinstance(mapping, dict) or set(mapping) != {'model_id', 'easysbc_id', 'easysbc_role_id', 'easysbc_url'}
                or type(mapping['model_id']) is not int or not 1 <= mapping['model_id'] < 10**12
                or mapping['model_id'] in seen_models):
            raise ValueError('Invalid EasySBC mapping')
        ident, role, url = mapping['easysbc_id'], mapping['easysbc_role_id'], mapping['easysbc_url']
        if (not isinstance(ident, str) or not isinstance(url, str) or not (ident or url)
                or not isinstance(role, str) or role and not re.fullmatch(r'[1-9][0-9]{0,11}', role)
                or ident and not url and not role
                or ident and not re.fullmatch(r'[A-Za-z0-9:_-]{1,120}', ident)):
            raise ValueError('Invalid explicit EasySBC identity')
        if url:
            parts = urlsplit(url)
            if (len(url) > 600 or any(c.isspace() or ord(c) < 32 for c in url)
                    or parts.scheme != 'https' or parts.hostname not in ('easysbc.io', 'www.easysbc.io')
                    or parts.username or parts.password or parts.port not in (None, 443)
                    or parts.path in ('', '/') or parts.fragment):
                raise ValueError('Invalid EasySBC URL')
            url_roles = parse_qs(parts.query).get('player-role-id', [])
            if (len(url_roles) > 1 or url_roles and not re.fullmatch(r'[1-9][0-9]{0,11}', url_roles[0])
                    or role and url_roles and role != url_roles[0]):
                raise ValueError('Conflicting EasySBC role')
        if ident and (ident, role) in seen_ids or url and url in seen_urls:
            raise ValueError('Ambiguous EasySBC identity')
        seen_models.add(mapping['model_id'])
        if ident:
            seen_ids.add((ident, role))
        if url:
            seen_urls.add(url)
    return value
