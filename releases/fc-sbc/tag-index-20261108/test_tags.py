import ast
import unittest
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[3]
TARGETS = [Path(value) for value in sys.argv[1:]] if len(sys.argv) > 1 else [
    ROOT / 'fc27_players_cloud/球员维护工具/admin_client.py',
    ROOT / 'releases/fc-players/direct-json-20261029/source/admin_client.py']

class ContractError(Exception):
    pass

def method(path):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AdminClient')
    fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'list_tags')
    ns = dict(Any=Any, Mapping=Mapping, AdminContractError=ContractError,
              GID_FC27=1327, CID_SBC=9625, SUPPORTED_GID=1327, SUPPORTED_CID=9627,
              TAG_CONTROLLER='/admin/goods.GoodsTag/', _check_scope=lambda *args: None)
    exec(compile(ast.Module(body=[fn], type_ignores=[]), str(path), 'exec'), ns)
    return ns['list_tags']

class Client:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.calls = []
    def _json(self, method, path, *, params):
        self.calls.append((method, path, params))
        return {'data': next(self.pages)}
    _request_json = _json

def row(i, gid=1327, cate_id=9627):
    return dict(id=i, gid=gid, cate_id=cate_id, name='tag')

class TagsTest(unittest.TestCase):
    def run_case(self, pages, expected=None, error=False):
        for path in TARGETS:
            with self.subTest(path=path):
                c = Client(pages)
                if error:
                    with self.assertRaises(ContractError): method(path)(c, gid=1327, cid=9627)
                else:
                    result = method(path)(c, gid=1327, cid=9627)
                    self.assertEqual([x['id'] for x in result], expected)
                for verb, endpoint, params in c.calls:
                    self.assertEqual((verb, endpoint), ('GET', '/admin/goods.GoodsTag/index'))
                    self.assertEqual(params['quick_search'], '%')
    def test_scoped_complete_pages(self):
        self.run_case([{'total':4,'list':[row(1),row(2, gid=9)]},
                       {'total':4,'list':[row(3,cate_id='9625,9627'),row(4,cate_id=[9627])]}], [1,3,4])
    def test_empty_catalog(self): self.run_case([{'total':0,'list':[]}], [])
    def test_early_empty_rejected(self): self.run_case([{'total':1,'list':[]}], error=True)
    def test_total_drift_rejected(self):
        self.run_case([{'total':2,'list':[row(1)]},{'total':3,'list':[row(2)]}], error=True)
    def test_duplicate_rejected(self):
        self.run_case([{'total':2,'list':[row(1)]},{'total':2,'list':[row(1)]}], error=True)
    def test_cap_rejected(self): self.run_case([{'total':41,'list':[row(i)]} for i in range(1,41)], error=True)
    def test_over_total_rejected(self): self.run_case([{'total':1,'list':[row(1),row(2)]}], error=True)
    def test_bad_total_rejected(self): self.run_case([{'total':1.5,'list':[row(1)]}], error=True)
    def test_allowlist_removes_old_endpoint(self):
        for path in TARGETS:
            tree = ast.parse(path.read_text(encoding='utf-8'))
            cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'AdminClient')
            allowed = next(n for n in cls.body if isinstance(n, ast.AnnAssign) and getattr(n.target,'id',None) == '_ALLOWED')
            source = ast.unparse(allowed)
            self.assertNotIn('tagSelect', source)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        TARGETS = [Path(value) for value in sys.argv[1:]]
        sys.argv = [sys.argv[0]]
    unittest.main()
