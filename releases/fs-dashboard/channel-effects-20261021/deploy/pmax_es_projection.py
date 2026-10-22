"""Refresh only the current parser; retained exports and session authentication stay intact."""
import release
SCOPE='fs-pmax-es-projection-20261022'
TARGETS={'runtime/es_order_structure.py':'/opt/fs-hermes-fc/es_order_structure.py'}

def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    return release.load_base()

if __name__=='__main__':load_base().main()
