"""One-shot reader update; reuse the original locked publisher without service restarts."""
SCOPE='management-partial-recheck-20261025'
TARGETS={'source/management_v2_runner.py': '/opt/fs-boss-workspaces/backend/management_v2_runner.py', 'source/management_facts.py': '/opt/fs-boss-workspaces/backend/management_facts.py'}
def load_base():
    import release
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    base=release.load_base();base.TARGETS_CHANGED_NAV=set(TARGETS.values())
    original=base.restart_for
    def restart(manifest,admission_fence=None):
        if manifest.get('scope')==SCOPE:
            if {r['target'] for r in manifest['files']}!=set(TARGETS.values()):raise ValueError('exact_idle_oneshot_required')
            return
        return original(manifest,admission_fence)
    base.restart_for=restart
    return base
if __name__=='__main__':load_base().main()
