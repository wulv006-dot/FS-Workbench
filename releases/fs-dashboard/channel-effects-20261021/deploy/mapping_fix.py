"""Three existing mapping targets over the original locked publisher."""
import release
SCOPE='fs-channel-aion2-map-20261023'
TARGETS={'runtime/channel_source.py':'/opt/fs-hermes-fc/channel_source.py','runtime/channel_mapping.json':'/opt/fs-hermes-fc/channel_mapping.json','runtime/coupon_channels.json':'/opt/fs-hermes-fc/coupon_channels.json'}
SOURCES={'runtime/channel_source.py':'releases/fs-dashboard/channel-effects-20261021/source/channel_source.py','runtime/channel_mapping.json':'releases/fs-dashboard/channel-effects-20261021/source/channel_mapping.json','runtime/coupon_channels.json':'releases/fs-dashboard/fs-business-baseline-20261021/source/coupon_channels.json'}
def load_base():
    release.SCOPE,release.TARGETS,release.NEW=SCOPE,TARGETS,frozenset()
    release.AUTHORIZED_TIMERS=frozenset()
    base=release.load_base();restart=base.restart_for
    def readers_only(manifest,admission_fence=None):
        if admission_fence is None:raise ValueError('mapping admission fence required')
        admission_fence.stop_then_unlock_database()
        restart(dict(manifest,scope=base.DEEP_SCOPE),admission_fence)
    base.restart_for=readers_only
    return base
if __name__=='__main__':load_base().main()
