import json
import tempfile
import unittest
from pathlib import Path

import package_dashboard
import prepare_release


class DashboardReleaseTests(unittest.TestCase):
    def test_portable_and_production_data_are_separate(self):
        marker = "</script><script>alert('data')</script>"
        page = package_dashboard.build({"packets": [], "sources": [marker]})
        self.assertNotIn(marker, page)
        self.assertIn(r"\u003c/script", page)
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "frontend"
            package_dashboard.build_production(target)
            production = (target / "index.html").read_text(encoding="utf-8")
            self.assertIn('"packets":[]', production)
            self.assertIn('mode=fc-project-review', production)
            self.assertEqual({file.name for file in target.iterdir()}, set(prepare_release.STATIC_FILES))

    def test_manifest_routes_preserve_session_guard(self):
        release = prepare_release.routes("/opt/checked", "build-abcdef")
        self.assertEqual(release.count("auth_request /__nav_formal_native_session;"), len(prepare_release.STATIC_FILES))
        self.assertEqual(release.count('Cache-Control "private, no-store"'), len(prepare_release.STATIC_FILES))
        self.assertIn(prepare_release.ROUTE + "index.html last;", release)
        self.assertNotIn("proxy_pass", release)
        self.assertNotIn("/var/lib/fs-fc-project-review", release)

    def test_sidebar_registry_checks_live_baseline(self):
        original = {"sections":[{"id":"sports", "ids":["ops","players"]}],
                    "tools":[{"id":"ops"},{"id":"players"}]}
        new = prepare_release.register(json.loads(json.dumps(original)))
        self.assertEqual(new["sections"][0]["ids"], ["fc-project-review","ops","players"])
        self.assertEqual(new["tools"][1:], original["tools"])
        source = "const registry=" + json.dumps(original) + ";\n"
        self.assertIn(prepare_release.ROUTE, prepare_release.patch_registry_script(source, original, new))
        with self.assertRaises(ValueError):
            prepare_release.patch_registry_script(source, new, original)


if __name__ == "__main__":
    unittest.main()
