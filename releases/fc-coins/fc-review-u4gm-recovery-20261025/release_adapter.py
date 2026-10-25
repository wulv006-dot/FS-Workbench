"""Four exact targets on the frozen house publisher; preserve existing identity."""
import importlib.util,json,stat
from pathlib import Path
HERE=Path(__file__).resolve().parent


def approved_boundary(original,manifest,root,item,info):
    return original(manifest,root,item,info) or (
        manifest.get('scope')=='fc-review-u4gm-recovery-20261025' and
        item==root/'opt/fs-sports-outbound' and info.st_uid==0 and info.st_gid==11028 and
        stat.S_IMODE(info.st_mode)==0o750)


def load_base():
    spec=importlib.util.spec_from_file_location('original_adapter',HERE/'fc_v2_release_adapter.py')
    adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
    adapter.HERE=HERE;adapter.SCOPE='fc-review-u4gm-recovery-20261025';adapter.RESTART_FC=True
    adapter.TARGETS={
        'source/business_context.py':'/opt/fs-hermes-fc/business_context.py',
        'source/conversation_service.py':'/opt/fs-hermes-fc/conversation_service.py',
        'source/hermes_pricing_bridge.py':'/opt/fc27-cloud-browser/hermes_pricing_bridge.py',
        'source/collect_fc_u4gm.py':'/opt/fs-sports-outbound/collect_fc_u4gm.py'}
    adapter.NEW=frozenset()
    base=adapter.load_base();original=base.approved_daily_group
    base.approved_daily_group=lambda m,r,p,s:approved_boundary(original,m,r,p,s)
    return base


if __name__=='__main__':load_base().main()
