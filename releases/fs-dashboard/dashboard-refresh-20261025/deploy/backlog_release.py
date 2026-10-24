"""Current RS site membership fix via the existing exact publisher."""
def load_base():
 import actual_release
 actual_release.SCOPE='business-dashboard-backlog-20261025'
 actual_release.TARGETS={'source/rs_backlog.py':'/opt/fs-exact-range-20261001/rs_backlog.py'}
 actual_release.NEW=frozenset()
 return actual_release.load_base()
if __name__=='__main__':load_base().main()
