"""Same-version incompatible synthetic databases reject without repair/data changes."""
from contextlib import closing
import hashlib
from pathlib import Path
import sqlite3
import tempfile
import unittest
from auth_candidate import SCHEMA, Store
from integrated_server import Environment, SYNTHETIC_PASSWORD
from native_integration import bind_functions
from schema_contract import NATIVE_SCHEMA, fingerprint, validate

EVIDENCE=[]


class SchemaTests(unittest.TestCase):
    def bad(self, label, schema=SCHEMA, extra='', version=3):
        with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
            root=Path(root); p=root/'candidate.sqlite3'
            with closing(sqlite3.connect(p)) as db:
                db.executescript(schema+'\n'+(NATIVE_SCHEMA+';' if version==3 else '')+'\n'+extra+'\nPRAGMA user_version='+str(version)+';')
                # Preserve a real row in an unrelated original table as well as
                # every DB byte, including schema objects, on failed reopening.
                db.execute("INSERT INTO limits VALUES('synthetic-sentinel',2,99)");db.commit()
            groups={g:str(root/(g+'.synthetic-htpasswd')) for g in ('dashboard','deploy')}
            portal=bind_functions({'secret':'synthetic-schema-check-only','cookie':'MMOEXP_AUTH'},groups)
            for path in groups.values(): Path(path).write_text('fstech:'+portal.apr1_md5(SYNTHETIC_PASSWORD,'local123')+'\n')
            before=p.read_bytes()
            with self.assertRaisesRegex(ValueError,'schema conflict|incomplete database|migration'):
                Environment(root)
            self.assertEqual(p.read_bytes(),before,label)
            self.assertFalse((root/'synthetic-init.json').exists())
            with self.assertRaisesRegex(ValueError,'schema conflict|migration'):
                Store(root,reserved_names=lambda:set(),allow_existing=True)
            self.assertEqual(p.read_bytes(),before,label)
            EVIDENCE.append({'case':label,'version':version,'reopen':'rejected','database_bytes_preserved':True,
                             'synthetic_database_sha256':hashlib.sha256(before).hexdigest()})

    def test_same_version_missing_column(self): self.bad('missing-column',SCHEMA.replace('team TEXT NOT NULL, purpose TEXT NOT NULL,','purpose TEXT NOT NULL,'))
    def test_same_version_wrong_column_type(self): self.bad('column-type',SCHEMA.replace('epoch INTEGER NOT NULL DEFAULT 0','epoch TEXT NOT NULL DEFAULT 0'))
    def test_same_version_removed_notnull(self): self.bad('notnull',SCHEMA.replace('csrf TEXT NOT NULL','csrf TEXT'))
    def test_same_version_changed_default(self): self.bad('default',SCHEMA.replace('epoch INTEGER NOT NULL DEFAULT 0','epoch INTEGER NOT NULL DEFAULT 1'))
    def test_same_version_removed_primary_key(self): self.bad('primary-key',SCHEMA.replace('token_hash TEXT PRIMARY KEY, user_id','token_hash TEXT, user_id'))
    def test_same_version_removed_unique(self): self.bad('unique',SCHEMA.replace('name_key TEXT NOT NULL UNIQUE','name_key TEXT NOT NULL'))
    def test_same_version_removed_foreign_key(self): self.bad('foreign-key',SCHEMA.replace('user_id TEXT NOT NULL REFERENCES users(id)','user_id TEXT NOT NULL'))
    def test_same_version_removed_check_constraint(self): self.bad('check',SCHEMA.replace("state TEXT NOT NULL CHECK(state IN ('pending','readonly','rejected','revoked'))","state TEXT NOT NULL"))
    def test_same_version_missing_pending_unique_index(self): self.bad('pending-index',SCHEMA.replace("CREATE UNIQUE INDEX one_pending ON requests(user_id) WHERE status='pending';",''))
    def test_same_version_changed_partial_index(self): self.bad('partial-index',SCHEMA.replace("WHERE status='pending';","WHERE status='approved';"))
    def test_same_version_missing_required_trigger(self): self.bad('missing-trigger',extra='DROP TRIGGER request_snapshot_immutable;')
    def test_same_version_modified_required_trigger(self):
        self.bad('modified-trigger',extra="DROP TRIGGER audit_append_only_update; CREATE TRIGGER audit_append_only_update BEFORE UPDATE ON audit BEGIN SELECT 1; END;")
    def test_same_version_extra_trigger_rejected(self):
        self.bad('extra-trigger',extra='CREATE TRIGGER extra_control AFTER INSERT ON users BEGIN UPDATE users SET state=\'readonly\'; END;')
    def test_extra_index_table_view_rejected(self):
        for label,sql in [('extra-index','CREATE INDEX unexpected ON users(team);'),('extra-table','CREATE TABLE sqlitefoo(x);'),('extra-view','CREATE VIEW unknown_view AS SELECT name FROM users;')]:
            with self.subTest(label=label):self.bad(label,extra=sql)
    def test_version2_constraints_rejected_before_migration(self): self.bad('schema2-unknown-trigger',extra='DROP TRIGGER audit_append_only_delete;',version=2)
    def test_normal_initialization_restarts_preserve_data_and_schema(self):
        with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
            env=Environment(root,'synthetic-normal-restart');env.store.register('schema.reader',SYNTHETIC_PASSWORD,'synthetic','pending')
            with env.store.connection() as db: before=fingerprint(db); validate(db,SCHEMA,3)
            env.close();contents=(Path(root)/'candidate.sqlite3').read_bytes()
            env=Environment(root,'synthetic-normal-restart')
            try:
                with env.store.connection() as db:
                    self.assertEqual(fingerprint(db),before)
                    self.assertEqual(db.execute('SELECT state FROM users').fetchone()[0],'pending')
                self.assertEqual((Path(root)/'candidate.sqlite3').read_bytes(),contents)
            finally: env.close()
    def test_valid_schema2_additive_migration_retains_existing_data(self):
        with tempfile.TemporaryDirectory(prefix='fs-registration-') as root:
            store=Store(root,reserved_names=lambda:set());store.register('migration.reader',SYNTHETIC_PASSWORD,'t','p')
            portal=bind_functions({'secret':'synthetic','cookie':'MMOEXP_AUTH'}, {})
            for group in ('dashboard','deploy'):(Path(root)/(group+'.synthetic-htpasswd')).write_text('fstech:'+portal.apr1_md5(SYNTHETIC_PASSWORD,'local123')+'\n')
            env=Environment(root)
            try:
                with env.store.connection() as db:
                    validate(db,SCHEMA,3);self.assertEqual(db.execute('SELECT state FROM users').fetchone()[0],'pending')
            finally:env.close()


if __name__=='__main__': unittest.main()
