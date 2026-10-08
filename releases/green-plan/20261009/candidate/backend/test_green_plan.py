"""Run: python green_plan_20261009/backend/test_green_plan.py"""
import importlib.util
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import green_plan as gp
spec = importlib.util.spec_from_file_location('candidate_taskboard',Path(__file__).with_name('taskboard_server.py'))
host = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = host
spec.loader.exec_module(host)


def reject(code,fn):
    try:
        fn()
    except host.ApiError as exc:
        assert exc.status == code, (exc.status,code)
    else:
        raise AssertionError('expected rejection %s'%code)


def run():
    with tempfile.TemporaryDirectory() as tmp:
        host.CFG.update(data_dir=Path(tmp),db=Path(tmp)/'tasks.db',seed=Path(tmp)/'absent.json')
        host.init_db(False)
        conn=host.db_connect()
        conn.execute("INSERT INTO tasks(project,dept,horizon,title,created_at,updated_at) VALUES('old','old','short','untouched','x','x')")
        conn.execute("INSERT INTO members(username,role,active,created_at,updated_at) VALUES('editor','editor',1,'x','x')")
        conn.execute("INSERT INTO members(username,role,active,created_at,updated_at) VALUES('inactive','editor',0,'x','x')")
        conn.commit()
        old=[tuple(r) for r in conn.execute('SELECT * FROM tasks')]
        gp.init(conn)
        assert len(gp.all_tasks(conn))==50
        assert all(t['status']=='todo' and t['progress']==0 and not t['assignee'] for t in gp.all_tasks(conn).values())
        admin=host.Ctx('wulv','admin')
        editor=host.Ctx('editor','editor')
        viewer=host.Ctx('v','viewer')
        def patch(code,payload,who=admin):
            revision=gp.all_tasks(conn)[code]['revision']
            return gp.mutate(host,who,dict(expectedRevision=revision,**payload),code)
        reject(403,lambda:patch('G01',{'notes':'x'},viewer))
        reject(403,lambda:patch('G01',{'notes':'x'},editor))
        original_guards=host.GUARD_ADMINS
        host.GUARD_ADMINS=tuple(original_guards)+('current_policy_admin',)
        patch('G01',{'assignee':'current_policy_admin'})
        assert any(m['username']=='current_policy_admin' for m in gp.board(host,admin)['members'])
        host.GUARD_ADMINS=original_guards
        patch('G01',{'assignee':'editor'})
        reject(403,lambda:patch('G01',{'title':'x'},editor))
        reject(403,lambda:patch('G01',{'status':'done','evidence':'checked'},editor))
        patch('G01',{'status':'review','progress':100,'evidence':'checked'},editor)
        reject(400,lambda:patch('G01',{'status':'blocked'}))
        reject(400,lambda:patch('G01',{'assignee':'inactive'}))
        reject(400,lambda:patch('G01',{'start':'2026-99-01'}))
        reject(400,lambda:patch('G01',{'progress':True}))
        reject(400,lambda:patch('G01',{'depends':['missing']}))
        reject(409,lambda:patch('G01',{'depends':['G02']}))
        reject(400,lambda:patch('G01',{'evidence':'javascript:alert(1)'}))
        reject(409,lambda:patch('G02',{'status':'done','evidence':'e'}))
        reject(409,lambda:patch('G01',{'status':'done','evidence':''}))
        done=patch('G01',{'status':'done'})
        assert done['acceptedBy']=='wulv' and done['acceptedAt']
        reject(403,lambda:patch('G01',{'evidence':'changed'},editor))
        reject(409,lambda:patch('G01',{'evidence':'changed'}))
        reject(409,lambda:patch('G01',{'title':'changed'}))
        patch('G01',{'notes':'admin commentary'})
        patch('G02',{'status':'done','evidence':'accepted'})
        reject(409,lambda:patch('G01',{'status':'doing'}))
        patch('G02',{'status':'doing'})
        reopened=patch('G01',{'status':'doing'})
        assert not reopened['acceptedBy'] and not reopened['acceptedAt']
        gp.init(conn)
        assert gp.all_tasks(conn)['G01']['status']=='doing'
        revision=gp.all_tasks(conn)['G01']['revision']
        def concurrent(value):
            try:
                gp.mutate(host,admin,dict(expectedRevision=revision,notes=value),'G01')
                return 200
            except host.ApiError as exc:
                return exc.status
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(concurrent,['a','b'])) == [200,409]
        before=gp.all_tasks(conn)['G01']
        count=conn.execute('SELECT COUNT(*) FROM green_plan_events').fetchone()[0]
        conn.execute("CREATE TRIGGER fail_event BEFORE INSERT ON green_plan_events BEGIN SELECT RAISE(ABORT,'simulated audit failure'); END")
        conn.commit()
        try:
            patch('G01',{'notes':'rollback'})
        except sqlite3.IntegrityError:
            pass
        else:
            raise AssertionError('expected transaction abort')
        assert gp.all_tasks(conn)['G01']==before
        assert conn.execute('SELECT COUNT(*) FROM green_plan_events').fetchone()[0]==count
        conn.execute('DROP TRIGGER fail_event')
        conn.commit()
        new=gp.mutate(host,admin,dict(title='new',owner='owner',start='2026-10-12',end='2026-10-13'))
        assert new['id']=='G51' and new['revision']==1 and new['status']=='todo'
        assert [tuple(r) for r in conn.execute('SELECT * FROM tasks')]==old
        from unittest.mock import patch as mock_patch
        from datetime import datetime, timezone, timedelta
        recent=datetime.now(timezone.utc).isoformat()
        stale=(datetime.now(timezone.utc)-timedelta(days=2)).isoformat()
        fixtures={
            '/var/www/dashboard/fs-home/transactions/current.json':{'generatedAt':recent},
            '/var/www/mmoexp-marketing/current/data.json':{'data_generated_at':recent,'isMock':False},
            '/opt/mmoexp-weekly-report/public/current.json':{'generatedAt':recent,'generationInvocation':{'mode':'manual'}},
            '/opt/mmoexp-weekly-report/public/attempt.json':{'status':'success'},
            '/var/lib/fc-ops-readonly-monitor/latest.json':{'status':'healthy','captured_at':recent,'issues':[]}}
        def read_fixture(path,*args,**kwargs):
            return json.dumps(fixtures[str(path).replace('\\','/')])
        with mock_patch.object(gp.Path,'read_text',read_fixture), mock_patch.object(gp.Path,'is_file',lambda _:True):
            caps={x['id']:x for x in gp.probes()}
            assert caps['google']['status']=='ok' and caps['fc-monitor']['status']=='ok'
            assert caps['weekly']['status']=='warning' and 'manual' in caps['weekly']['detail']
            fixtures['/var/www/mmoexp-marketing/current/data.json']['isMock']=True
            fixtures['/var/lib/fc-ops-readonly-monitor/latest.json']['captured_at']=stale
            caps={x['id']:x for x in gp.probes()}
            assert caps['google']['status']=='warning' and caps['fc-monitor']['status']=='warning'
            fixtures['/var/lib/fc-ops-readonly-monitor/latest.json'].update(captured_at=recent,issues=[{'code':'known_warning','level':'warning'}])
            caps={x['id']:x for x in gp.probes()}
            assert caps['fc-monitor']['status']=='warning' and 'known_warning' in caps['fc-monitor']['detail']
        board=gp.board(host,admin)
        assert len(board['tasks'])==51 and len(board['capabilities'])==5
        for headers in ({'Content-Type':'text/plain'}, {'Content-Type':'application/json','Sec-Fetch-Site':'cross-site'}, {'Content-Type':'application/json','Host':'example.com','Origin':'https://evil.com'}, {'Content-Type':'application/json','Host':'example.com','Origin':'null'}):
            reject(415 if headers['Content-Type']=='text/plain' else 403,lambda h=headers:gp.csrf(h,host))
        gp.csrf({'Content-Type':'application/json','Host':'example.com','Origin':'https://example.com','Sec-Fetch-Site':'same-origin'},host)
        gp.csrf({'Content-Type':'application/json'},host)
        import threading
        import http.client
        from http.server import ThreadingHTTPServer
        class LocalHandler(host.Handler):
            # Synthetic identity only in this temporary loopback HTTP test.
            def _ctx(self):
                return admin if self.headers.get('X-Test-Role') != 'viewer' else viewer
            def log_message(self,*args):
                pass
        server=ThreadingHTTPServer(('127.0.0.1',0),LocalHandler)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            client=http.client.HTTPConnection('127.0.0.1',server.server_port)
            client.request('GET','/api/green-plan')
            response=client.getresponse()
            assert response.status==200 and len(json.loads(response.read())['tasks'])==51
            current=gp.all_tasks(conn)['G01']['revision']
            payload=json.dumps({'expectedRevision':current,'notes':'http check'})
            client.request('PATCH','/api/green-plan/tasks/G01',payload,{'Content-Type':'application/json'})
            response=client.getresponse()
            assert response.status==200 and json.loads(response.read())['task']['revision']==current+1
            client.request('PATCH','/api/green-plan/tasks/G01',payload,{'Content-Type':'application/json'})
            response=client.getresponse()
            assert response.status==409
            response.read()
            client.request('PATCH','/api/green-plan/tasks/G01',payload,{'Content-Type':'application/json','Origin':'https://evil.test'})
            response=client.getresponse()
            assert response.status==403
            response.read()
            client.request('PATCH','/api/green-plan/tasks/G01',payload,{'Content-Type':'text/plain'})
            response=client.getresponse()
            assert response.status==415
            response.read()
            client.close()
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
        conn.close()
    print('PASS: permissions, CAS concurrency, transaction rollback, seed idempotency, dates, DAG, evidence, acceptance, CSRF, original tasks unchanged')

if __name__=='__main__':
    run()

