"""Native live platform scope and explicit views of original historical records."""
PLATFORMS = ('PS', 'XBOX', 'PC')
PRICE_SCOPE_CONTRACT = 'fc27_three_platform_v1'
SMART_VERSION = 'smart-three-platform-v3'
LEGACY_SMART_VERSION = 'smart-bidirectional-v2'
SMART_VERSIONS = (LEGACY_SMART_VERSION, SMART_VERSION)
NATIVE_GROUPS = {p: (p,) for p in PLATFORMS}
LEGACY_GROUPS = {'console': ('PS', 'XBOX'), 'pc': ('PC',)}


def groups_for(record):
    action = record.get('action', record)
    return NATIVE_GROUPS if (record.get('smart_strategy_version') == SMART_VERSION or record.get('price_scope_contract') == PRICE_SCOPE_CONTRACT or set((action.get('base_prices') or {})) == set(PLATFORMS)) else LEGACY_GROUPS


def action_key(action, platform):
    """Decode an original action; never use this to accept a new live quote."""
    prices = action.get('base_prices') or {}
    if platform in prices:
        return platform
    if set(prices).issubset({'console', 'pc'}):
        return 'pc' if platform == 'PC' else 'console'
    raise ValueError('pricing_platform_action_invalid')


def native_resources(resources):
    expanded = []
    for resource in resources:
        expanded.extend(('base:PS', 'base:XBOX') if resource == 'base:console' else ('base:PC',) if resource == 'base:pc' else (resource,))
    return sorted(set(expanded))


def native_action(action):
    """Explicit migration of a stored anchor, never a live evidence fallback."""
    from copy import deepcopy
    result = deepcopy(action)
    result['base_prices'] = {p: action['base_prices'][action_key(action, p)] for p in PLATFORMS}
    return result
