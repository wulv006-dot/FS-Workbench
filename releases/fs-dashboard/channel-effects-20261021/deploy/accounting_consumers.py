"""Keep status refresh and financial provenance consistent across direct consumers."""
import release
SCOPE='fs-channel-accounting-consumers-20261022'
SOURCES={
 'runtime/channel_effects.py':'releases/fs-dashboard/channel-effects-20261021/source/channel_effects.py',
 'runtime/channel_cache.py':'releases/fs-dashboard/channel-effects-20261021/source/channel_cache.py',
 'runtime/coins_evidence.py':'releases/fs-dashboard/fc-coins-evidence-20261021/source/coins_evidence.py',
 'runtime/pricing_workflow.py':'releases/fs-dashboard/fc-coins-workflow-20261022/source/pricing_workflow.py'}
TARGETS={name:'/opt/fs-hermes-fc/'+name.split('/')[-1] for name in SOURCES}
def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    return release.load_base()
if __name__=='__main__':load_base().main()
