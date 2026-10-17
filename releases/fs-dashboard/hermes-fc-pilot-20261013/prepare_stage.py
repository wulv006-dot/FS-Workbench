"""Freeze the pilot production payload after source/tree readback, no Git writes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT=Path(__file__).resolve().parents[1]
CODE=ROOT/'hermes_fc_pilot_20261013'
DEST=ROOT/'.agent_runtime/hermes-pilot-deploy-final-20261013'
BASE={
'range_api.py':'d4a702c54319ba464271587822d6b5e0b5671bfb141af4dc4aefc34024f1a70a',
'ai_advisor_model.py':'02d720bdfbc458ef2f94107bb139e077325f6e8d78fcc677718383d5f0e02a4e',
'boss_insights.py':'ab8e249864fdee350d3d35cdf83995e473112b17f86281a331f14581a65d189c',
'fc_deep_model.py':'15965d1d331444635dd8ef677cacb2f05d2e21fa6c33ff6ae7bf53315b76b067',
'fc_daily.py':'b6f1d4a92e6835aea84b40aaac953b42d0fef6272824b302a64227c17af796f7',
'fc_daily_model.py':'37310fdab22eccebd1a695f27a90016e2fdf6cf8fd6b07c62835a2a0631fb5ec',
'fc_detail.py':'0eb8e37cf6e483f2c14f2f241cbca12c18eb85d9fcaaa4e8bfc8963a6d9e5341',
'fc_detail_model.py':'98b6429ba6c84d3ebbf061b0299703b6d49dc753e7b5ac45c72061b544e568ce',
'fc_detail_reader.py':'90159c3bd57663114fded85e90eb318505e53695b5548561aba32f4154c9464f',
'fc_detail_config.json':'e6c43940d8f5f2da10180ed489d2a4654d5d7fe038f3183787dd47587075d31a',
'fc_deep_sources.py':'f83e7605f08d26052a743ea7ad5cce78c421d9439c67ce29f32415c0dce18c5a',
'summary_bridge.py':'66ff09deef5cd54f9e789bd875b76f26f7c811323645a93396db25d1699cc24c',
}
PROTECTED={('/opt/fs-exact-range-20261001/'+name):sha for name,sha in BASE.items() if name not in ('range_api.py','ai_advisor_model.py')}
PROTECTED.update({
'/var/www/dashboard/index.html':'5c6c217a4353ae9cd8aa9ec0a10f97c1cddac89041a028418a17d2fdb8b603ba',
'/var/www/dashboard/fs-home/index.html':'4666642d58241d37215e6d234675eb7affb0a9aeb45393059a063f21b711478d',
'/var/www/dashboard/fs-home/navigation.js':'b3af7ffe7097b069e8a500170d88214566706956d0e440ead420eeb0a157efa5',
'/opt/fs-access-policy/access_policy.py':'d076ddb81752f2d915c6eaf340a4ce6f42d62ac7c7d240b16e7dfbfcb3796ea2'})

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--commit',required=True);parser.add_argument('--tree',required=True);args=parser.parse_args()
    if DEST.exists():raise ValueError('stage_exists_preserve_previous')
    DEST.mkdir(parents=True)
    files=[];mapping=[]
    targets=json.loads((CODE/'release-targets.json').read_text('utf-8'))
    for rel,target in targets.items():
        source=CODE/('shared_candidate/'+rel.rsplit('/',1)[1] if rel.startswith('hermes/shared/') else rel[len('hermes/runtime/'):] if rel.startswith('hermes/runtime/') else rel[len('hermes/'):])
        raw=source.read_bytes();sha=hashlib.sha256(raw).hexdigest();path=DEST/'candidate'/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
        files.append({'candidate':rel,'target':target,'sha256':sha,'beforeSha256':BASE.get(Path(target).name) if rel.startswith('hermes/shared/') else None})
        gitsha=hashlib.sha1(('blob '+str(len(raw))+'\0').encode()+raw).hexdigest()
        mapping.append({'source':'releases/fs-dashboard/hermes-fc-pilot-20261013/'+source.relative_to(CODE).as_posix(),'artifact':rel,'runtime':target,'sha256':sha,'git_blob':gitsha})
    publisher=CODE/'shared_candidate/release_navigation.py';shutil.copyfile(publisher,DEST/'release_navigation.py')
    shutil.copyfile(CODE/'provision_identity.py',DEST/'provision_identity.py')
    manifest={'schemaVersion':1,'scope':'hermes-fc-readonly-20261013','releaseReady':True,'files':files,
      'unchangedRequired':[{'path':p,'sha256':s} for p,s in PROTECTED.items()], 'runtimeRequired':{'fs-business-range.service':{'ActiveState':'active'}},
      'imageId':'sha256:8251bc53f66565fa9aaf2dea3292ec2ae91db7f3eb57c44f5804ebf6b6853544','businessWrites':False,'timersChanged':False,
      'sourceCommit':args.commit,'sourceTree':args.tree,'baselineReadAt':'2026-10-13T17:13:01Z','businessAcceptance':'not_passed_default_entry_not_replaced'}
    raw=(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n').encode();(DEST/'approved-manifest.json').write_bytes(raw)
    (DEST/'SOURCE-MAP.json').write_text(json.dumps({'sourceCommit':args.commit,'sourceTree':args.tree,'files':mapping,'publisherSha256':hashlib.sha256(publisher.read_bytes()).hexdigest()},indent=2)+'\n',encoding='utf-8')
    archive=DEST.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for p in sorted(DEST.rglob('*')):
            if p.is_file():z.write(p,p.relative_to(DEST).as_posix())
    print(json.dumps({'stage':str(DEST),'zip':str(archive),'archiveSha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'manifestSha256':hashlib.sha256(raw).hexdigest(),'files':mapping},ensure_ascii=False))

if __name__=='__main__':main()
