from pathlib import Path
import re,json,sys
patterns={
 'private-key':r'-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----',
 'github-token':r'\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{35,})\b',
 'aws-access-key':r'\b(?:AKIA|ASIA)[A-Z0-9]{16}\b',
 'google-api-key':r'\bAIza[A-Za-z0-9_-]{30,}\b',
 'oauth-token':r'\bya29\.[A-Za-z0-9_-]{20,}\b',
 'jwt':r'\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b',
 'credentials-in-url':r'https?://[^\s/\"\']+:[^\s/@\"\']+@',
 'password-hash':r'\$(?:apr1|2[aby]|6)\$[A-Za-z0-9./$]{20,}',
 'email':r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
 'literal-credential':r'(?i)[\"\']?(?:password|passwd|client_secret|refresh_token|access_token|api_key|session_token)[\"\']?\s*[:=]\s*[\"\']([^\"\'\n]{4,})[\"\']',
}
fake={'password','test','test-token','test_token','dummy','secret','example','not-a-secret','fake-token','token','placeholder'}
def scan(rel,data,kind):
 if Path(rel).suffix=='.png':return []
 s=data.decode('utf-8-sig');out=[]
 for typ,pattern in patterns.items():
  for m in re.finditer(pattern,s):
   if typ=='email' and (m.group().endswith(('.example.com','@example.com','@example.invalid')) or m.group().startswith('root@')):continue
   if typ=='literal-credential':
    v=m.group(1)
    if v in fake or v.startswith(('REPLACE_','EXAMPLE_','TEST_','FAKE_','${','<')):continue
   out.append({'path':rel,'line':s.count('\n',0,m.start())+1,'type':typ})
 return out

root=Path(__file__).resolve().parents[1]
rows=[];files=[]
for f in root.rglob('*'):
 if not f.is_file() or any(part in {'.git','.venv','node_modules','__pycache__','.checks'} for part in f.relative_to(root).parts):continue
 files.append(f)
 try:rows.extend(scan(f.relative_to(root).as_posix(),f.read_bytes(),'candidate'))
 except UnicodeDecodeError:rows.append({'path':f.relative_to(root).as_posix(),'line':0,'type':'unsupported-binary-content'})
print(json.dumps({'files':len(files),'findings':rows,'limitations':'heuristic rules plus explicit allowlist; no proof about old Git history'},ensure_ascii=True,indent=2))
sys.exit(bool(rows))
