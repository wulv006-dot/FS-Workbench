"""Keep actual-profit cache compatibility through the original exact publisher."""
def load_base():
 import actual_release
 actual_release.SCOPE='business-filter-cache-compat-20261025'
 actual_release.TARGETS={'source/actual_profit.py':'/opt/fs-exact-range-20261001/actual_profit.py'}
 actual_release.NEW=frozenset()
 return actual_release.load_base()
if __name__=='__main__':load_base().main()
