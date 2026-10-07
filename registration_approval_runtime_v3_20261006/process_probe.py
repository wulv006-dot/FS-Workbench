"""Synthetic subprocess restart/crash probe. Never connects to production."""
import json
import os
from pathlib import Path
import sqlite3
import sys
from contextlib import closing
import runtime as r
from native_integration import bind_functions


def portal(root):
    return bind_functions({'secret':'Synthetic-process-key-only-42', 'secure':True,
        'cookie':'SYNTHETIC_AUTH'}, {'dashboard':str(root / 'synthetic-members')})


def main():
    phase, directory = sys.argv[1:3]
    root = Path(directory); native = portal(root)
    if phase in ('prepare', 'prepare-registered'):
        encoded = native.apr1_md5('Synthetic-password-42', 'qa123456')
        (root / 'synthetic-members').write_text('fstech:' + encoded + '\n')
        r.RuntimeStore.initialize_fresh(root, native, isolated=True)
        store, adapter, app = r.build(root, native, 'https://synthetic.invalid', isolated=True)
        token, proof = adapter.native_login('fstech', 'Synthetic-password-42')
        session, csrf = store.new_session(legacy_user=proof.user)
        # This is synthetic local test state, never packaged or reported.
        state = {'token':token,'session':session}
        if phase == 'prepare-registered':
            request = store.register('newreader','Synthetic-password-42','QA','Read')
            store.decide(proof,request['request_id'],0,'approve','QA')
            registered, _ = store.login('newreader','Synthetic-password-42')
            state.update(registered=registered,request_id=request['request_id'])
        (root / 'synthetic-token.json').write_text(json.dumps(state))
        with store.connection() as db, closing(sqlite3.connect(root / 'old-backup.sqlite3')) as old:
            db.backup(old)
        print('PREPARED'); return
    if phase == 'verify':
        try:
            store, adapter, app = r.build(root, native, 'https://synthetic.invalid', isolated=True)
            state = json.loads((root / 'synthetic-token.json').read_text())
            cookies = {r.core.COOKIE:state['registered']} if 'registered' in state else {'SYNTHETIC_AUTH':state['token']}
            code, headers = adapter.verify(cookies, 'GET', '/dashboard/')
            print('TOKEN_DENIED' if code == 401 else 'TOKEN_ACCEPTED' if code == 200 else 'VERIFY_DENIED')
        except Exception:
            print('BOOT_DENIED')
        return
    if phase == 'init-crash':
        def interrupted(*args, **kw): os._exit(75)
        r.checkpoint.write = interrupted
        r.RuntimeStore.initialize_fresh(root, native, isolated=True)
        raise AssertionError('crash hook did not execute')
    store, adapter, app = r.build(root, native, 'https://synthetic.invalid', isolated=True)
    state = json.loads((root / 'synthetic-token.json').read_text())
    if phase == 'revoke-registered':
        proof = adapter.resolve_native({'SYNTHETIC_AUTH':state['token']})
        store.decide(proof,state['request_id'],1,'revoke','QA')
        print('REVOKED');return
    if phase in ('pending-crash', 'committed-crash'):
        original = r.checkpoint.write
        def interrupted(path, value, sync):
            if phase == 'committed-crash' and value['status'] == 'ready': os._exit(74)
            original(path, value, sync)
            if phase == 'pending-crash' and value['status'] == 'pending': os._exit(73)
        r.checkpoint.write = interrupted
    adapter.logout(state['session'], {'SYNTHETIC_AUTH':state['token']})
    print('LOGGED_OUT')


if __name__ == '__main__': main()
