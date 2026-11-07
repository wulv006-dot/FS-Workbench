"""Download bounded, explicitly observed public reference assets; never execute target JS."""
import hashlib, json, pathlib, re, struct, urllib.request, xml.etree.ElementTree as ET
ROOT = pathlib.Path(__file__).resolve().parent
BUNDLE_URL = 'https://www.easysbc.io/assets/index-Dhfro0H2.js'
source = (ROOT/'source/index-Dhfro0H2.js').read_text(encoding='utf-8')
assets = [
 ('coin','misc/coin-tmp.png','runtime'), ('sbc','misc/sbc-tmp.png','runtime'),
 ('objective','misc/obj-tmp.png','runtime'), ('season-points','misc/sp-tmp.png','runtime'),
 ('pack-tradable','misc/pack-tradable.png','runtime'), ('sbc-set-108','fc27/sbcs/sets/icons/108.png','runtime'),
 ('pack-4','fc27/packs/4.png','runtime'), ('event-token-1','fc27/eventtokens/1.png','runtime'),
 ('sbc-purple','misc/ea/sbc-purple.png','bundle literal'), ('objective-ea','misc/ea/obj.png','bundle literal'),
 ('season-points-ea','misc/ea/sp.png','bundle literal'), ('points-ea','misc/ea/points.png','bundle literal'),
 ('ball','misc/ea/ball.png','bundle literal'), ('default-sbc','misc/default-sbc.png','bundle literal'),
 ('player-pick','misc/playerpick_v2.png','bundle literal'), ('coin-large','misc/fut-coin-large.png','bundle literal'),
 ('pitch','misc/pitch.svg','bundle literal')]
rows=[]
for name,path,evidence in assets:
 url='https://assets.easysbc.io/'+path
 row={'name':name,'source_url':url,'provenance':evidence,'license':'unknown; no reuse license established','production_ready':False}
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=20) as r:
   data=r.read(4000000); row['content_type']=r.headers.get('Content-Type')
  if len(data)>=4000000: raise ValueError('size limit')
  ext=pathlib.Path(path).suffix; out=ROOT/'images'/(name+ext);out.parent.mkdir(exist_ok=True);out.write_bytes(data)
  row.update(file=out.relative_to(ROOT).as_posix(),bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),format=ext[1:])
  if data.startswith(b'\x89PNG'): row['dimensions']=list(struct.unpack('>II',data[16:24]))
  elif ext=='.svg':
   root=ET.fromstring(data);row['dimensions']={k:root.attrib.get(k) for k in ['width','height','viewBox']}
 except Exception as ex: row['error']=str(ex)
 rows.append(row)
# Extract only literal Lucide shape arrays. No eval of downloaded application code.
for name in ['Clock','Dna','Images','GalleryVerticalEnd','Puzzle','Target','Gamepad2','Monitor','Package','Newspaper','Search','ExternalLink']:
 match=re.search(r'tt\("'+name+r'",(\[\[.*?\]\])\)',source)
 if not match: continue
 literal=re.sub(r'([,{])([A-Za-z][A-Za-z0-9]*):',r'\1"\2":',match.group(1))
 shapes=json.loads(literal)
 svg=ET.Element('svg',{'xmlns':'http://www.w3.org/2000/svg','width':'24','height':'24','viewBox':'0 0 24 24','fill':'none','stroke':'currentColor','stroke-width':'2','stroke-linecap':'round','stroke-linejoin':'round'})
 for tag,attrs in shapes:
  attrs.pop('key',None);ET.SubElement(svg,tag,attrs)
 data=ET.tostring(svg,encoding='utf-8');out=ROOT/'lucide'/(name+'.svg');out.parent.mkdir(exist_ok=True);out.write_bytes(data)
 rows.append({'name':name,'source_url':BUNDLE_URL,'provenance':'literal Lucide shape array extracted from public bundle','bundle_char_offset':match.start(),'file':out.relative_to(ROOT).as_posix(),'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest(),'format':'svg','dimensions':[24,24],'license':'ISC (lucide-react v0.454.0 per adjacent bundle license comment); retain LICENSE','production_ready':True})
(ROOT/'manifest.json').write_text(json.dumps({'checked_at':'2026-11-08 Asia/Shanghai','evidence_id':'ev_73fce2447dddebcceb4967486222d7cb8a29b737fea3cb05b210e876fa5594cc','scope':'homepage network + downloaded public bundle literals; not full site or Discord app','assets':rows},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'assets':len(rows),'downloads':sum('file' in r for r in rows),'errors':[r for r in rows if 'error'in r]},ensure_ascii=False))
