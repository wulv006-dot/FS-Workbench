"""Read existing Coins accounting without requiring unrelated live paid detail."""
import release
SCOPE='fs-coins-archived-cost-tools-20261022'
SOURCES={'runtime/fs_evidence.py':'releases/fs-dashboard/fc-coins-workflow-20261022/source/fs_evidence.py'}
TARGETS={'runtime/fs_evidence.py':'/opt/fs-hermes-fc/fs_evidence.py'}
def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    return release.load_base()
if __name__=='__main__':load_base().main()
