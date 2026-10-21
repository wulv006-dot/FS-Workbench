"""Replace complete delivery membership and keep automatic late-cost refresh."""
import release
SCOPE='fs-channel-cache-reconcile-20261022'
TARGETS={'runtime/'+name:'/opt/fs-hermes-fc/'+name for name in
         ('channel_source.py','channel_cache.py','channel_effects.py')}


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    return release.load_base()


if __name__=='__main__':load_base().main()
