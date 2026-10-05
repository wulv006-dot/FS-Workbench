"""Approval-gated atomic export of sanitized readonly marketing assets only."""
import datetime as dt,json,os,shutil,uuid
from pathlib import Path
ROOT=Path('/opt/mmoexp-marketing');TARGET=Path('/var/www/mmoexp-marketing')
FILES=['index.html','marketing-module.js','marketing-module.css','business-module.js','data.json']

def public_directory(path):
    # mkdir mode is filtered by UMask=0077. Only sanitized export directories
    # need nginx traversal; private source/config/credential permissions stay intact.
    if path.is_symlink():raise SystemExit('EXPORT_DIRECTORY_REQUIRES_REVIEW')
    path.mkdir(exist_ok=True,mode=0o755)
    if not path.is_dir() or path.stat().st_uid!=0:raise SystemExit('ROOT_OWNED_EXPORT_DIRECTORY_REQUIRED')
    path.chmod(0o755)

def main():
    if os.getenv('MMOEXP_MARKETING_PUBLISH')!='approved':raise SystemExit('PUBLICATION_DISABLED')
    source=ROOT/'staged-marketing-module';model=json.loads((source/'data.json').read_text())
    if model.get('isMock') is not False or model.get('schemaVersion')!=1:raise SystemExit('REAL_SCOPE_REQUIRED')
    if {s['id'] for s in model['sources']}!={'ga4','gsc'} or {s['resource'] for s in model['adsAccounts']}!={'1430398974','8154986819'}:raise SystemExit('REVIEWED_SCOPE_REQUIRED')
    details=model.get('details')
    if details:
        if details.get('isMock') is not False or set(details.get('allowed_customers',[]))!={'1430398974','8154986819','3552474396'}:raise SystemExit('REVIEWED_DETAILS_REQUIRED')
        for period in details.get('periods',[]):
            if {a['customerId'] for a in period['adsAccounts']}!={'1430398974','8154986819','3552474396'}:raise SystemExit('REVIEWED_DETAIL_SCOPE_REQUIRED')
    if TARGET.is_symlink() or (TARGET/'releases').is_symlink():raise SystemExit('TARGET_REQUIRES_REVIEW')
    current=TARGET/'current'
    if current.exists() and not current.is_symlink():raise SystemExit('UNKNOWN_TARGET_DO_NOT_OVERWRITE')
    if current.is_symlink() and not current.resolve().is_relative_to((TARGET/'releases').resolve()):raise SystemExit('UNKNOWN_TARGET_DO_NOT_OVERWRITE')
    public_directory(TARGET);releases=TARGET/'releases';public_directory(releases)
    release=releases/(dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+uuid.uuid4().hex[:8]);public_directory(release)
    for name in FILES:
        item=source/name
        if item.is_symlink() or not item.is_file():raise SystemExit('SAFE_FILE_REQUIRED')
        shutil.copyfile(item,release/name);(release/name).chmod(0o644)
    weekly=Path('/opt/mmoexp-weekly-report/public')
    if weekly.exists():
        if weekly.is_symlink() or not weekly.is_dir() or weekly.stat().st_uid!=0:raise SystemExit('WEEKLY_EXPORT_REQUIRES_REVIEW')
        state=json.loads((weekly/'current.json').read_text())
        if state.get('schemaVersion')!=1 or state.get('status') not in ['ready','waiting_for_exact_business_range']:raise SystemExit('WEEKLY_STATE_REQUIRES_REVIEW')
        (release/'weekly').symlink_to(weekly)
    temporary=TARGET/('current-'+uuid.uuid4().hex+'.tmp');temporary.symlink_to(release);temporary.replace(current)
    print(json.dumps({'published':True,'path':str(current),'files':FILES,'secret_files_exported':False}))

if __name__=='__main__':main()
