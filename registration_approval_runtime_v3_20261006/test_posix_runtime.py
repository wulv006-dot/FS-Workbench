"""Private Linux acceptance cases; all operations are disposable synthetic temp."""
import os
from pathlib import Path
import unittest
import runtime as r
import test_runtime


@unittest.skipUnless(os.name=='posix','POSIX private Linux runner required')
class PosixStorageTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_runtime.RuntimeTests('test_pending_cannot_read');self.fixture.setUp()
        self.root=self.fixture.root;self.store=self.fixture.store;self.portal=self.fixture.portal
    def tearDown(self):self.fixture.tearDown()

    def test_private_modes_uid_and_nonprivate_rejection(self):
        for path in (self.store.path.parent,self.store.witness.parent):
            self.assertEqual(0o700,path.stat().st_mode & 0o777)
            self.assertEqual(os.geteuid(),path.stat().st_uid)
        for path in (self.store.path,self.store.witness):
            self.assertEqual(0o600,path.stat().st_mode & 0o777)
            self.assertEqual(os.geteuid(),path.stat().st_uid)
            os.chmod(path,0o644)
            with self.assertRaises(ValueError):r.build(self.root,self.portal,'https://synthetic.invalid',isolated=True)
            os.chmod(path,0o600)
        self.assertIsNotNone(r.build(self.root,self.portal,'https://synthetic.invalid',isolated=True)[0])

    def test_hardlink_and_symlink_rejected_without_repair(self):
        link=self.root/'synthetic-hardlink.sqlite3'
        os.link(self.store.path,link)
        with self.assertRaises(ValueError):r.build(self.root,self.portal,'https://synthetic.invalid',isolated=True)
        link.unlink()
        backing=self.root/'synthetic-backing.sqlite3'
        self.store.path.rename(backing)
        self.store.path.symlink_to(backing)
        with self.assertRaises(ValueError):r.build(self.root,self.portal,'https://synthetic.invalid',isolated=True)
        self.store.path.unlink();backing.rename(self.store.path)
        self.assertIsNotNone(r.build(self.root,self.portal,'https://synthetic.invalid',isolated=True)[0])
