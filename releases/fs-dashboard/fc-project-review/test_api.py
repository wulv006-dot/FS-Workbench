from datetime import date, timedelta
from importlib import import_module
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent))
api=import_module(HERE.name+".api")
from test_review import core


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.params={"mode":["fc-project-review"],"profile":["FC27"],"start":["2026-11-16"],"end":["2026-11-16"]}
        folder=TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root=Path(folder.name)

    def get(self, permitted=True, **updates):
        return api.get({**self.params,**updates},"reviewer",None,None,lambda _:permitted,self.root)

    def test_access_and_explicit_scope(self):
        self.assertEqual(self.get(False)[0],403)
        self.assertEqual(self.get(profile=["../all"])[0],422)
        self.assertEqual(self.get(site=["266"])[0],422)
        self.assertEqual(self.get(start=["2026-11-17"])[0],422)

    def test_retained_revision_and_readback(self):
        p=api.packet(core())
        first=api.publish(p,self.root)
        self.assertEqual(self.get()[1]["revision"],first["revision"])
        second=api.publish(dict(p,coverage=["source corrected"]),self.root)
        self.assertNotEqual(first["revision"],second["revision"])
        self.assertEqual(len(list((self.root/"FC27"/"versions").glob("*.json"))),2)

    def test_source_shape_and_optional_gaps(self):
        source=core()
        admin=source["admin"]
        admin.update(status="available",normalisedScope="all-websites",effective_scope=admin.pop("scope"))
        def read(_get,game,start,end,mode,actor):
            return {"profile":{"supplement":admin}} if mode=="summary" else {"history":{"daily":[]}}
        with patch.object(api,"read_range",read),patch.object(api,"read_program",side_effect=RuntimeError("offline")),patch.object(api.subprocess,"run",side_effect=OSError):
            p=api.capture("FC27",source["start"],source["end"],"operator",None,None,lambda _:True)
        self.assertEqual(p["kpi"]["orders"],2)
        self.assertTrue(p["coverage"])
