"""Hermetic regression entry: check frozen inputs, forbid network/subprocess actions."""
from pathlib import Path
import hashlib
import json
import sys
import unittest

ROOT=Path(__file__).resolve().parent

def deny_external_actions(event,args):
    if event in {'subprocess.Popen','socket.connect','socket.bind','os.system',
                 'os.exec','os.posix_spawn','os.spawn'}:
        raise RuntimeError('offline_qa_external_action_forbidden')

def main():
    manifest=json.loads((ROOT/'INPUT-MANIFEST.json').read_text(encoding='utf-8'))
    for item in manifest['files']:
        p=ROOT/item['path']
        if not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=item['sha256']:
            raise RuntimeError('offline_qa_input_sha_mismatch')
    sys.addaudithook(deny_external_actions)
    suite=unittest.defaultTestLoader.discover(str(ROOT/'tests'),pattern='test_*.py')
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if result.testsRun!=90:raise RuntimeError('offline_qa_method_count_mismatch')
    return 0 if result.wasSuccessful() else 1

if __name__=='__main__':sys.exit(main())
