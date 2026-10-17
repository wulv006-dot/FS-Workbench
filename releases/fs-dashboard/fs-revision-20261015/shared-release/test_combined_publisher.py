"""Run account and AI boundary cases against the actual combined publisher."""
import importlib.util
from pathlib import Path
import types
import unittest
from unittest.mock import patch
HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module
publisher=load('combined',HERE/'release_navigation.py')
accounts=load('account_contracts',HERE.parent/'accounts/tests/test_publisher.py')
ai=load('ai_contracts',HERE.parent/'accounts/integration/test_ai_publisher.py')
accounts.publisher=publisher;ai.publisher=publisher
class AccountBoundary(accounts.PublisherTests):pass
class AIBoundary(ai.PublisherTests):
    def setUp(self):
        super().setUp()
        row=next(row for row in self.files if row['candidate'].endswith('.timer'))
        self.timer=self.stage/'candidate'/row['candidate']
        self.timer.write_text(ai.TIMER.replace('06:30:00 Asia/Shanghai','06:30:00'))
        row['sha256']=publisher.digest(self.timer)
        self.localtime=publisher.rooted(self.root,'/etc/localtime')
        self.shanghai=publisher.rooted(self.root,'/usr/share/zoneinfo/Asia/Shanghai')
        for path in (self.localtime,self.shanghai):
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_bytes(b'synthetic-Shanghai-zoneinfo')

    def timezone_guard(self):
        # Isolate the real filesystem timezone check from unrelated live-service guards.
        with patch.object(publisher,'revision_ai_quiescent'),patch.object(publisher,'hermes_quiescent'),patch.object(publisher,'AI_REVISION_TARGETS',{}):
            publisher.guards(dict(scope=publisher.AI_REVISION_SCOPE,unchangedRequired=[]),self.root)

    def test_server_timezone_matching_shanghai_bytes_passes(self):
        self.timezone_guard()

    def test_server_timezone_mismatch_or_missing_rejected(self):
        self.localtime.write_bytes(b'synthetic-UTC-zoneinfo')
        with self.assertRaisesRegex(ValueError,'server timezone must be Asia/Shanghai'):
            self.timezone_guard()
        self.localtime.unlink()
        with self.assertRaises(OSError):self.timezone_guard()
        self.localtime.write_bytes(self.shanghai.read_bytes())
        self.shanghai.unlink()
        with self.assertRaises(OSError):self.timezone_guard()

    def test_old_systemd_calendar_rejects_timezone_suffix(self):
        row=next(row for row in self.files if row['candidate'].endswith('.timer'))
        self.timer.write_text(ai.TIMER)
        row['sha256']=publisher.digest(self.timer)
        with self.assertRaisesRegex(ValueError,'exact nonpersistent cleanup timer'):
            publisher.validate(self.manifest,self.stage)

    def test_nonpersistent_idle_timer_required(self):
        row=next(row for row in self.files if row['candidate'].endswith('.timer'))
        self.timer.write_text(self.timer.read_text().replace('Persistent=false','Persistent=true'))
        row['sha256']=publisher.digest(self.timer)
        with self.assertRaisesRegex(ValueError,'exact nonpersistent cleanup timer'):
            publisher.validate(self.manifest,self.stage)

    def test_systemd219_timer_never_requests_service_mainpid(self):
        commands=[]
        def show(command,**kwargs):
            commands.append(command)
            service=command[2].endswith('.service')
            output='ActiveState=inactive\nUnitFileState=disabled\nLoadState=loaded\n'
            if service:output+='MainPID=0\n'
            return types.SimpleNamespace(returncode=1 if not service and 'MainPID' in command else 0,stdout=output,stderr='')
        with patch.object(publisher.subprocess,'run',side_effect=show):
            publisher.revision_units_inactive(publisher.AI_REVISION_BOSS_UNITS+publisher.AI_REVISION_CLEAN_UNITS)
        for command in commands:
            expected=['systemctl','show',command[2],'--no-pager','-p','ActiveState','-p','UnitFileState','-p','LoadState']
            if command[2].endswith('.service'):expected+=['-p','MainPID']
            self.assertEqual(command,expected)

    def test_nonzero_loaded_or_unknown_missing_state_still_rejected(self):
        complete='ActiveState=inactive\nUnitFileState=disabled\nLoadState=loaded\n'
        cases=[(1,complete),(0,complete.replace('loaded','unknown'))]
        cases += [(0,complete.replace(line+'\n','')) for line in complete.splitlines()]
        for code,output in cases:
            with self.subTest(code=code,output=output),patch.object(publisher.subprocess,'run',return_value=types.SimpleNamespace(returncode=code,stdout=output,stderr='')):
                with self.assertRaises(ValueError):
                    publisher.revision_units_inactive(('fs-maintenance-cleanup.timer',))
        missing=types.SimpleNamespace(returncode=1,stdout='ActiveState=inactive\nUnitFileState=\nLoadState=not-found\n',stderr='')
        with patch.object(publisher.subprocess,'run',return_value=missing):
            publisher.revision_units_inactive(('fs-maintenance-cleanup.timer',))

    def test_service_mainpid_must_be_explicit_zero(self):
        common='ActiveState=inactive\nUnitFileState=static\nLoadState=loaded\n'
        for pid in ('','MainPID=1\n','MainPID=unknown\n'):
            with self.subTest(pid=pid),patch.object(publisher.subprocess,'run',return_value=types.SimpleNamespace(returncode=0,stdout=common+pid,stderr='')):
                with self.assertRaises(ValueError):
                    publisher.revision_units_inactive(('fs-boss-management.service',))
if __name__=='__main__':unittest.main()
