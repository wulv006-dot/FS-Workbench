"""One-file knowledge-envelope repair through the original nightly publisher."""
import release
release.SCOPE='nightly-knowledge-envelope-20261025'
release.TARGETS={'source/business_context.py':'/opt/fs-hermes-fc/business_context.py'}
if __name__=='__main__':release.load_base().main()
