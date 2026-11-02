import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
from backup_inventory import inventory

class Inventory(unittest.TestCase):
    def test_exact_two_directories_read_only_fixture(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for day in ('2026-10-29','2026-10-30','2026-10-31'):
                folder=root/'backups'/day; folder.mkdir(parents=True)
                (folder/'fixture.db').write_bytes(b'fixture')
            before={str(p):p.stat().st_mtime_ns for p in root.rglob('*')}
            value=inventory(root)
            self.assertEqual([x['logical_bytes'] for x in value['targets']],[7,7])
            self.assertFalse(value['deletion_performed'])
            self.assertEqual(before,{str(p):p.stat().st_mtime_ns for p in root.rglob('*')})
            self.assertNotIn('2026-10-31',str(value))

    def test_missing_does_not_create(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'missing'; value=inventory(root)
            self.assertFalse(root.exists())
            self.assertTrue(all(x['status']=='missing' for x in value['targets']))

if __name__=='__main__':unittest.main()
