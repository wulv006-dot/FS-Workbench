"""Offline regression for the immutable data-tool module and two mutable routes."""

import hashlib
import json
import tempfile
import sys
import types
import unittest
from pathlib import Path

import prepare_ui_release


class UiRelease(unittest.TestCase):
    def test_stage_contract_and_routes(self):
        with tempfile.TemporaryDirectory() as directory:
            stage = Path(directory) / "stage"
            summary = prepare_ui_release.prepare(stage)
            self.assertEqual((summary["immutableAssets"], summary["mutableTargets"], summary["protectedPaths"]), (2, 2, 345))
            m = json.loads((stage / "release-manifest.json").read_text("utf-8"))
            self.assertFalse(m["releaseReady"])
            module_path = stage / "assets/data-workspace.js"
            self.assertEqual(hashlib.sha256(module_path.read_bytes()).hexdigest(), prepare_ui_release.MODULE_SHA)
            index = (stage / "assets/tools-index.html").read_bytes()
            self.assertIn((prepare_ui_release.URL_PREFIX + m["releaseId"] + "/data-workspace.js").encode(), index)
            self.assertNotIn(prepare_ui_release.OLD_MODULE.encode(), index)
            formal = (stage / "candidate/formal.conf").read_bytes()
            module_route = prepare_ui_release.block(formal, prepare_ui_release.URL_PREFIX + m["releaseId"] + "/data-workspace.js")
            self.assertIn(b"default_type application/javascript;", module_route)
            self.assertIn(b"auth_request /__nav_formal_native_session;", module_route)
            tools_route = prepare_ui_release.block(formal, "/dashboard/data-tools/index.html")
            self.assertIn((prepare_ui_release.PREFIX + m["releaseId"] + "/tools-index.html").encode(), tools_route)
            slash = prepare_ui_release.block(formal, "/dashboard/data-tools/")
            self.assertIn(b"rewrite ^ /dashboard/data-tools/index.html last;", slash)
            self.assertNotIn(b"alias ", slash)
            publisher = stage / "release_workspace.py"
            module = types.ModuleType("_ui_release_test")
            module.__file__ = str(publisher)
            sys.path.insert(0, str(stage))
            try:
                exec(compile(publisher.read_bytes(), str(publisher), "exec"), module.__dict__)
            finally:
                sys.path.remove(str(stage))
            self.assertEqual(len(module.validate(m, None)), 4)
            self.assertEqual(set(module.MUTABLE), {prepare_ui_release.FORMAL, prepare_ui_release.BRAIN})


if __name__ == "__main__":
    unittest.main()
