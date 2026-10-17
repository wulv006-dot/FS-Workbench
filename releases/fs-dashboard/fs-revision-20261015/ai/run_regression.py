"""Run original business tests with candidate paths and official-model fixtures."""
from pathlib import Path
import shutil
import subprocess
import sys

here = Path(__file__).resolve().parent
workspace = here.parents[3]
original = workspace / 'releases/fs-dashboard/boss-workspaces-20261013'
latest = original
stage = here / 'regression'
for folder in ('backend', 'deploy', 'tests'):
    shutil.copytree(original / folder, stage / folder, dirs_exist_ok=True)
for folder in ('backend', 'deploy', 'tests'):
    shutil.copytree(latest / folder, stage / folder, dirs_exist_ok=True)
shutil.copytree(here / 'candidate', stage / 'backend', dirs_exist_ok=True)
(stage / 'source/management').mkdir(parents=True, exist_ok=True)
shutil.copy2(original / 'source/management/targets.json', stage / 'source/management/targets.json')
game = stage / 'tests/test_game_intelligence.py'
text = game.read_text('utf-8')
start = text.index('workspace = Path(__file__)')
end = text.index("AT = datetime", start)
text = text[:start] + "sys.path.insert(0, str(Path(__file__).parents[1] / 'backend'))\nfrom workspace_official_model import MODEL\n" + text[end:]
game.write_text(text, encoding='utf-8')
management = stage / 'tests/management_daily_test.py'
text = management.read_text('utf-8')
start = text.index('MODEL_SOURCES = ')
end = text.index('spec = ', start)
text = text[:start] + "sys.path.insert(0, str(ROOT / 'backend'))\n" + text[end:]
# Old supplier identities in valid mock responses follow the newly selected provider.
text = text.replace('from fc_daily_model import MODEL', 'from workspace_official_model import MODEL')
text = text.replace('m.MAX_TOKENS + 1,', '__import__("workspace_official_model").OUTPUT_TOKENS + 1,').replace('m.MAX_TOKENS + 1}', '__import__("workspace_official_model").OUTPUT_TOKENS + 1}')
management.write_text(text, encoding='utf-8')
for name in ('test_game_intelligence', 'test_boss_daily', 'management_daily_test'):
    code = "import socket,unittest,sys;real=socket.socket.connect;socket.socket.connect=lambda self,address: real(self,address) if isinstance(address,tuple) and address[0] in ('127.0.0.1','localhost','::1') else (_ for _ in ()).throw(AssertionError('offline_test_external_network'));result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.discover('tests',pattern=sys.argv[1]+'.py'));sys.exit(0 if result.testsRun>0 and result.wasSuccessful() and not result.skipped else 1)"
    result = subprocess.run([sys.executable, '-B', '-c', code, name], cwd=stage)
    if result.returncode:raise SystemExit(result.returncode)
