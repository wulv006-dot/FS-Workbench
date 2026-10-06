import sqlite3
import unittest
from contextlib import closing
import consumer_seams as seams
from runtime import core
import native_access_policy as policy
import native_taskboard_member as source


class ConsumerTests(unittest.TestCase):
    def test_all_four_admins_and_registered_readonly(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TABLE members(username TEXT,role TEXT,active INTEGER)')
            fn = seams.types.FunctionType(source.member_state.__code__,
                dict(source.__dict__, ROLES=('admin','editor','viewer'),
                    q=lambda conn, sql, args, one=False: conn.execute(sql, args).fetchone()))
            for name in policy.ADMINS:
                self.assertEqual(('admin', True), seams.taskboard_member(db, name, 'admin', fn, policy))
                self.assertEqual((name, True), seams.fc_identity(200, {'X-Auth-User':name, 'X-Auth-Role':'admin'}, policy))
            subject = 'reg:12345678-1234-1234-1234-123456789abc'
            self.assertEqual(('viewer', True), seams.taskboard_member(db, subject, 'readonly', fn, policy))
            self.assertEqual((subject, False), seams.fc_identity(200, {'X-Auth-User':subject,'X-Auth-Role':'readonly'}, policy))
            for name, role in ((subject, 'admin'), ('fstech','readonly'), ('oldreader','admin')):
                with self.assertRaises(core.Denied): seams.taskboard_member(db, name, role, fn, policy)

    def test_native_existing_member_semantics_preserved(self):
        with closing(sqlite3.connect(':memory:')) as db:
            db.row_factory = sqlite3.Row
            db.execute('CREATE TABLE members(username TEXT,role TEXT,active INTEGER)')
            db.execute("INSERT INTO members VALUES('oldreader','editor',1)")
            fn = seams.types.FunctionType(source.member_state.__code__,
                dict(source.__dict__, ROLES=('admin','editor','viewer'),
                    q=lambda conn, sql, args, one=False: conn.execute(sql, args).fetchone()))
            self.assertEqual(('editor',True), seams.taskboard_member(db,'oldreader','readonly',fn,policy))
            self.assertEqual(('viewer',False), seams.taskboard_member(db,'unknownuser','readonly',fn,policy))

    def test_invalid_or_unverified_fc_never_admin(self):
        for code, subject, role in ((401,'wulv','admin'),(200,'reg:wulv','admin'),
                (200,'reg:12345678-1234-1234-1234-123456789ABC','readonly'),
                (200,'fstech','readonly'),(200,'newreader','admin')):
            self.assertEqual((None,False),seams.fc_identity(code,{'X-Auth-User':subject,'X-Auth-Role':role},policy))


if __name__ == '__main__': unittest.main()
