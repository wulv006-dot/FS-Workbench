import json
import tempfile
import unittest
from hashlib import sha256
from pathlib import Path
from unittest.mock import patch

import connector_release
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


    def test_connector_revision_release_preserves_live_catalog_and_pins_both_files(self):
        self.addCleanup(connector_release.select_release, connector_release.FC_REVIEW)
        repo = connector_release.REPO
        candidate = json.loads((repo / "fs_mcp_connector/catalog.json").read_bytes())
        operation = next(item for item in candidate["operations"] if item["name"] == "business.fc_project_review")
        revision = operation["input_schema"]["properties"].pop("revision")
        operation["description"] = "Existing live description"
        candidate["operations"].append({"name": "fixture.live_only"})
        expected_view = (repo / "fs_mcp_connector/response_view.py").read_bytes().replace(b"\r\n", b"\n")
        active_view = expected_view[:expected_view.index(b"        fields = CONTEXT_FIELDS")] + (
            b"        for key in CONTEXT_FIELDS:\n"
        ) + expected_view[expected_view.index(b"            if key in ancestor:"):]
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            active = root / "active.json"
            active.write_text(json.dumps(candidate), encoding="utf-8")
            view = root / "active.py"
            view.write_bytes(active_view)
            image_id, unit_sha = "sha256:" + "1" * 64, "2" * 64
            with patch("sys.argv", ["connector_release.py", "prepare", str(root / "release"),
                                   "--operation", "fc-project-review-revision", "--active-catalog", str(active),
                                   "--active-response-view", str(view), "--base-image", image_id, "--unit-sha", unit_sha,
                                   "--source-commit", "a" * 40, "--merged-commit", "b" * 40]):
                connector_release.main()
            directory = root / "release"
            metadata = connector_release.load_release(directory)
            result = json.loads((directory / "image/catalog.json").read_bytes())
            revised = next(item for item in result["operations"] if item["name"] == operation["name"])
            self.assertEqual(revised["input_schema"]["properties"].pop("revision"), revision)
            self.assertIn("data_context", revised["description"])
            revised["description"] = operation["description"]
            self.assertEqual(result, candidate)
            self.assertEqual((directory / "image/response_view.py").read_bytes(), expected_view)
            self.assertEqual(metadata["base_image"], image_id)
            self.assertEqual(metadata["unit_before_sha256"], unit_sha)
            self.assertEqual(metadata["base_response_view_sha256"], sha256(active_view).hexdigest())
            self.assertEqual(metadata["response_view_sha256"], sha256(expected_view).hexdigest())
            self.assertIn("COPY catalog.json response_view.py /app/fs_mcp_connector/",
                          (directory / "image/Dockerfile").read_text(encoding="utf-8"))

            paths = ("/app/fs_mcp_connector/catalog.json", "/app/fs_mcp_connector/response_view.py")
            checked = f"{metadata['catalog_sha256']}  {paths[0]}\n{metadata['response_view_sha256']}  {paths[1]}\n"
            with patch.object(connector_release.subprocess, "check_output", return_value=checked) as docker:
                connector_release.verify_payload_image(image_id, metadata)
                self.assertEqual(docker.call_args.args[0][-2:], list(paths))
                docker.return_value = checked.splitlines()[0] + "\n"
                with self.assertRaisesRegex(ValueError, "connector_payload_readback_failed"):
                    connector_release.verify_payload_image(image_id, metadata)

            (directory / "image/response_view.py").write_bytes(b"# drift\n")
            with self.assertRaisesRegex(ValueError, "release_response_view_changed"):
                connector_release.load_release(directory)


if __name__ == "__main__":
    unittest.main()
