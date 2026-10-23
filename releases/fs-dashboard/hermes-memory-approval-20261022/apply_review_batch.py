"""Apply only the explicit Codex decisions supplied, sequentially; stop on unknown."""
import json
from pathlib import Path
import subprocess
import sys

source=Path(sys.argv[1])
decisions=json.loads(source.read_text(encoding='utf-8'))
directory=source.parent/'individual';directory.mkdir(mode=0o700,exist_ok=True)
completed=[]
for decision in decisions:
    name=decision['id'].replace(':','-')+'.json'
    path=directory/name;path.write_text(json.dumps(decision,ensure_ascii=False),encoding='utf-8')
    process=subprocess.run([sys.executable,'/opt/fs-hermes-memory-approval/review_queue.py','decide','--decision-file',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=120)
    if process.returncode:
        print(json.dumps(dict(completed=completed,stopped_at=decision['id'],error=process.stderr[-1800:]),ensure_ascii=True));sys.exit(1)
    result=json.loads(process.stdout)
    completed.append(dict(id=decision['id'],decision=decision['decision'],**result))
    if result['status']!='completed':
        print(json.dumps(dict(completed=completed,stopped_at=decision['id'],reason='not_completed_inspect_original_receipt'),ensure_ascii=True));sys.exit(1)
print(json.dumps(dict(completed=completed),ensure_ascii=True))
