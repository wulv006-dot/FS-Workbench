"""Exact actual-profit adapter; reuse original CAS, fence, backup and rollback."""
SCOPE='business-dashboard-refresh-20261025'
TARGETS={'source/business.js': '/var/lib/fs-navigation-formal-static/dashboard-refresh-20261025-4b28008012cf/business.js', 'source/home-business.js': '/var/lib/fs-navigation-formal-static/dashboard-refresh-20261025-4b28008012cf/home-business.js', 'source/legacy-business.js': '/var/lib/fs-navigation-formal-static/dashboard-refresh-20261025-4b28008012cf/legacy-business.js', 'source/shell.js': '/var/lib/fs-navigation-formal-static/dashboard-refresh-20261025-4b28008012cf/shell.js', 'source/range_api.py': '/opt/fs-exact-range-20261001/range_api.py', 'source/live_summary.py': '/opt/fs-exact-range-20261001/live_summary.py', 'source/channel_effects.py': '/opt/fs-hermes-fc/channel_effects.py', 'source/rs_backlog.py': '/opt/fs-exact-range-20261001/rs_backlog.py', 'source/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md', 'source/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/business.js', 'source/home-business.js', 'source/legacy-business.js', 'source/shell.js', 'source/rs_backlog.py'])

def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    base=release.load_base();base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    original_group=base.approved_daily_group
    def existing_knowledge_group(manifest,root,item,info):
        scoped=dict(manifest,scope=base.HERMES_NIGHT_SCOPE) if manifest.get('scope')==SCOPE and item==base.rooted(root,'/var/lib/fs-hermes-fc') else manifest
        return original_group(scoped,root,item,info)
    base.approved_daily_group=existing_knowledge_group
    from shipping_readiness import extend
    extend(base,SCOPE)
    return base
if __name__=='__main__':load_base().main()
