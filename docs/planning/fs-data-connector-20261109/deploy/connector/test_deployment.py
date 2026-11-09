import importlib.util
from contextlib import nullcontext
import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('connector_installer_test',HERE/'install_connector_187.py')
install=importlib.util.module_from_spec(spec);spec.loader.exec_module(install)
spec=importlib.util.spec_from_file_location('connector_updater_test',HERE/'update_connector_image_187.py')
update=importlib.util.module_from_spec(spec);spec.loader.exec_module(update)


class Clock:
    value=0
    def now(self):return self.value
    def sleep(self,delay):self.value+=delay


class DeploymentTests(unittest.TestCase):
    def test_reload_old_workers_are_only_retried_by_reading_routes(self):
        clock=Clock();calls=[];statuses=iter([404,404,200,200])
        def read(path,timeout):
            calls.append((path,timeout));return next(statuses),{},None
        with patch.object(install,'run',side_effect=AssertionError('no service or reload writes')):
            install.wait_for_public_routes(read,clock=clock.now,sleep=clock.sleep)
        self.assertEqual(len(calls),4)
        self.assertEqual(clock.value,.2)
        self.assertTrue(all(0<timeout<=2 for _,timeout in calls))

    def test_route_wait_is_bounded_and_does_not_hide_failure(self):
        clock=Clock();calls=[]
        def read(path,timeout):calls.append(path);return 404,{},None
        with self.assertRaisesRegex(RuntimeError,'public_routes_not_ready_after_reload'):
            install.wait_for_public_routes(read,timeout=1,clock=clock.now,sleep=clock.sleep)
        self.assertEqual(clock.value,1)
        self.assertLessEqual(len(calls),12)

    def test_invalid_tls_is_not_retried_as_reload_delay(self):
        clock=Clock()
        def read(path,timeout):raise ssl.SSLCertVerificationError('fixture')
        with self.assertRaises(ssl.SSLCertVerificationError):
            install.wait_for_public_routes(read,clock=clock.now,sleep=clock.sleep)
        self.assertEqual(clock.value,0)

    def test_vhost_insert_and_fixed_image_input(self):
        raw=b'server {\n '+install.ANCHOR+b'\n}'
        self.assertEqual(install.make_vhost(raw).count(install.ADDITION),1)
        for invalid in (b'no anchor',raw+raw,install.make_vhost(raw)):
            with self.assertRaises(ValueError):install.make_vhost(invalid)
        for image in (None,'latest','sha256:bad'):
            with self.assertRaises(ValueError):install.unit_bytes(image)
        self.assertNotIn(b'@IMAGE_ID@',install.unit_bytes('sha256:'+'a'*64))

    def test_image_update_only_changes_the_pinned_image_and_rejects_drift(self):
        before=install.unit_bytes(update.OLD_IMAGE);new='sha256:'+'b'*64
        after=update.image_unit(before,new)
        self.assertEqual(after.replace(new.encode(),update.OLD_IMAGE.encode()),before)
        self.assertIn(b'--mount type=bind,src=/var/lib/fs-data-connector',after)
        for raw,image in [(before+b'\n',new),(before,update.OLD_IMAGE),(before,'latest')]:
            with self.assertRaises(ValueError):update.image_unit(raw,image)

    def rollback_fixture(self,run):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name);backup=root/'backup';backup.mkdir();unit=root/'unit'
        before=install.unit_bytes(update.OLD_IMAGE);image='sha256:'+'b'*64
        after=update.image_unit(before,image);unit.write_bytes(after)
        (backup/'unit.before').write_bytes(before)
        (backup/'receipt.json').write_text(json.dumps({'unit_before_sha256':install.sha(before),
            'unit_after_sha256':install.sha(after),'image_after':image}))
        patches=[patch.object(update,'BACKUP',backup),patch.object(update.base,'UNIT',unit),
            patch.object(update.base,'locks',return_value=nullcontext()),patch.object(update.base,'run',side_effect=run),
            patch.object(update,'verify_public',return_value={}),patch.object(update,'write_receipt'),
            patch.object(update.base,'atomic')]
        for item in patches:self.addCleanup(item.stop);item.start()
        return unit,before

    def test_failed_new_service_without_container_can_restore_old_unit(self):
        calls=[]
        def run(command):
            calls.append(command)
            if command[:2]==['docker','ps']:return ''
            if command[:2]==['systemctl','show']:return 'ActiveState=failed\nSubState=failed\n'
            if command[:2]==['docker','inspect']:raise RuntimeError('must not inspect missing container')
            return ''
        unit,before=self.rollback_fixture(run)
        with patch('builtins.print'):update.rollback()
        update.base.atomic.assert_called_once_with(unit,before,0o644)
        self.assertIn(['systemctl','restart','fs-data-connector.service'],calls)

    def test_rollback_rejects_an_unexpected_container_image(self):
        def run(command):
            if command[:2]==['docker','ps']:return 'candidate-id\n'
            if command[:2]==['docker','inspect']:return json.dumps([{'Image':'sha256:'+'c'*64}])
            raise AssertionError('unexpected command')
        self.rollback_fixture(run)
        with self.assertRaisesRegex(ValueError,'running_image_drift'):update.rollback()
        update.base.atomic.assert_not_called()

    def test_docker_failure_is_not_treated_as_missing_container(self):
        def run(command):raise RuntimeError('docker query failed')
        self.rollback_fixture(run)
        with self.assertRaisesRegex(RuntimeError,'docker query failed'):update.rollback()
        update.base.atomic.assert_not_called()

    def test_missing_container_does_not_allow_rollback_of_an_active_unit(self):
        def run(command):
            if command[:2]==['docker','ps']:return ''
            if command[:2]==['systemctl','show']:return 'ActiveState=active\n'
            raise AssertionError('unexpected command')
        self.rollback_fixture(run)
        with self.assertRaisesRegex(ValueError,'missing_container_requires_stopped_or_failed_unit'):update.rollback()
        update.base.atomic.assert_not_called()


if __name__=='__main__':unittest.main()
