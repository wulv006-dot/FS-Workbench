"""Build the exact original campaign reference list; emit no prices or raw product objects."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

MODULE = 'releases/fs-dashboard/campaign-analytics-20261023'
EXTRACT = r"""
const fs=require('node:fs'),vm=require('node:vm'),path=require('node:path'),root=process.argv[1];
const fc=JSON.parse(fs.readFileSync(path.join(root,'app/catalog.json'),'utf8')),box={};
vm.runInNewContext(fs.readFileSync(path.join(root,'app/seasonal/campaign-data.js'),'utf8'),box,{timeout:1000});
const refs=[];
for(const p of Object.values(fc.products))for(const [platform,row] of Object.entries(p.platforms||{})){
 refs.push({reference_key:'fc-'+p.key+'-'+platform,family:'fc',game_key:'fc',original_key:p.key,kind:p.kind,
 product_ref:{site_id:String(fc.siteId),game_id:String(fc.gameId),goods_id:String(row.id)},
 expected_platform:{code:platform,attribute_id:String(row.aid)},
 expected_quantity:{value:String(row.quantity),group:String(row.group),source_unit:null},
 category_id:String(p.cid),public_path:new URL(p.listingUrl).pathname,source_artifact:'app/catalog.json'});
}
for(const p of box.SeasonalData.products){const s=p.source;
 refs.push({reference_key:'seasonal-'+p.id,family:'seasonal',game_key:p.game,kind:s.category,
 product_ref:{site_id:String(s.siteId),game_id:String(s.gid),goods_id:String(s.goodsId)},
 expected_platform:{code:'area-'+s.aid,attribute_id:String(s.aid)},server_id:String(s.sid),category_id:String(s.cid),
 expected_quantity:{value:String(s.quantity),source_unit:s.unit},display_bonus:String(s.bonus),
 public_path:new URL(s.url).pathname,source_artifact:'app/seasonal/campaign-data.js'});
}
process.stdout.write(JSON.stringify(refs));
"""


def build_seed(module):
    module = Path(module).resolve()
    refs = json.loads(subprocess.check_output(['node', '-e', EXTRACT, str(module)], text=True))
    artifacts = {name: hashlib.sha256((module / name).read_bytes()).hexdigest()
                 for name in sorted({r['source_artifact'] for r in refs})}
    if len(refs) < 126 or len({r['reference_key'] for r in refs}) != len(refs):
        raise ValueError('ORIGINAL_REFERENCE_COUNT_CHANGED')
    goods = {(r['product_ref']['site_id'], r['product_ref']['game_id'],
              r['product_ref']['goods_id']) for r in refs}
    if len(goods) < 116 or len({r['game_key'] for r in refs}) != 6:
        raise ValueError('ORIGINAL_PRODUCT_SCOPE_CHANGED')
    return dict(schema_version=1, source_revision='29ed99af85dc4aa7a302e63ae36c06e5da495369',
                source_artifacts=artifacts, reference_count=len(refs), unique_goods_count=len(goods),
                game_count=6, verification_status='original_reference_only',
                authoritative=False, checkout_enabled=False, references=refs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', default=Path(__file__).resolve().parents[1] / MODULE)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    raw = json.dumps(build_seed(args.module), ensure_ascii=False, indent=2) + '\n'
    if args.out:
        args.out.write_text(raw, encoding='utf-8', newline='\n')
    else:
        print(raw, end='')


if __name__ == '__main__':
    main()
