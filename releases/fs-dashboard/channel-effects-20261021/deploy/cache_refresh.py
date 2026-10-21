"""Retain the original refresh cadence while serving archived data immediately."""
import release
SCOPE='fs-channel-cache-refresh-20261021'
TARGETS={'runtime/channel_effects.py':'/opt/fs-hermes-fc/channel_effects.py',
         'runtime/channel_cache.py':'/opt/fs-hermes-fc/channel_cache.py'}


def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    return release.load_base()


if __name__=='__main__':load_base().main()
