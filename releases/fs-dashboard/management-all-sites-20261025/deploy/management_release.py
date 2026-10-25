"""Exact management scope over the existing locked CAS/backup/rollback publisher."""
SCOPE='management-all-sites-20261025'
TARGETS={'source/management_facts.py': '/opt/fs-boss-workspaces/backend/management_facts.py', 'source/management_v2_runner.py': '/opt/fs-boss-workspaces/backend/management_v2_runner.py', 'source/management_context.py': '/opt/fs-hermes-fc/management_context.py', 'source/management-live.js': '/var/lib/fs-navigation-formal-static/management-all-sites-20261025-f60608d79521/management-live.js', 'source/index.html': '/var/lib/fs-navigation-formal-static/management-all-sites-20261025-f60608d79521/index.html', 'source/business-baseline.md': '/opt/fs-hermes-fc/business-baseline.md', 'source/knowledge-load-policy.json': '/var/lib/fs-hermes-fc/fs/knowledge-load-policy.json', 'generated/navigation.conf': '/etc/nginx/fs-navigation-formal-analytics-20261006.locations.conf'}
NEW=frozenset(['source/management-live.js','source/index.html'])
def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,NEW
    base=release.load_base();base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    original_group=base.approved_daily_group
    def knowledge_parent(manifest,root,item,info):
        scoped=dict(manifest,scope=base.HERMES_NIGHT_SCOPE) if manifest.get('scope')==SCOPE and item==base.rooted(root,'/var/lib/fs-hermes-fc') else manifest
        return original_group(scoped,root,item,info)
    base.approved_daily_group=knowledge_parent
    from shipping_readiness import extend
    extend(base,SCOPE)
    return base
if __name__=='__main__':load_base().main()
