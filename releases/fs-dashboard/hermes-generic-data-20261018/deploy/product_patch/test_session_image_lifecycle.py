"""Simulate the image build, source readback, restart and rollback contract."""

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import session_image_lifecycle as image


class ImageLifecycle(unittest.TestCase):
    def test_build_readback_restart_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            stage = root / "stage"
            build = stage / "image-inputs/session-build"
            build.mkdir(parents=True)
            sources = {name: ("reviewed:" + name).encode() for name in image.NAMES}
            desired = {}
            for name, data in sources.items():
                (build / name).write_bytes(data)
                target = root / (image.HOST + name).lstrip("/")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                desired[image.HOST + name] = hashlib.sha256(data).hexdigest()
            dockerfile = b"FROM " + image.BASE.encode() + b"\nCOPY exact-three /usr/local/bin/\n"
            (build / "Dockerfile").write_bytes(dockerfile)
            manifest = {"sessionImage": {"baseImage": image.BASE, "oldTag": image.OLD,
                                          "newTag": image.NEW, "dockerfileSha256": hashlib.sha256(dockerfile).hexdigest()},
                        "files": [{"target": target, "sha256": digest} for target, digest in desired.items()]}
            state = {"built": False, "restarts": []}
            built_id = "sha256:" + "a" * 64
            def image_id(tag, absent=False):
                if tag == image.NEW:
                    return built_id if state["built"] else None
                return image.BASE
            def run(argv, **kwargs):
                self.assertEqual(argv[:2], ["docker", "build"])
                state["built"] = True
                return type("Result", (), {"returncode": 0})()
            def check_output(argv, **kwargs):
                self.assertEqual(argv[:3], ["docker", "run", "--rm"])
                return "".join(digest + "  /usr/local/bin/" + name + "\n"
                               for name, digest in ((name, desired[image.HOST + name]) for name in image.NAMES))
            def container():
                return {"Image": image.BASE, "Config": {"Image": image.OLD}}
            def healthy(expected):
                state["restarts"].append(expected)
            def write_journal(_backup, journal):
                json.dumps(journal)
            def atomic(path, data, _mode):
                path.write_bytes(data)
            def digest(path):
                return hashlib.sha256(path.read_bytes()).hexdigest()
            journal = {}
            with (patch.object(image, "image_id", side_effect=image_id),
                  patch.object(image, "container", side_effect=container),
                  patch.object(image, "healthy", side_effect=healthy),
                  patch.object(image.subprocess, "run", side_effect=run),
                  patch.object(image.subprocess, "check_output", side_effect=check_output)):
                image.apply(manifest, stage, root / "backup", journal, root,
                            atomic, write_journal, digest, lambda _: None)
                self.assertEqual(journal["sessionBuildOutcome"], "verified")
                self.assertTrue(journal["sessionImageWritten"])
                image.restore(root / "backup", journal, write_journal)
            self.assertEqual(state["restarts"], [built_id, image.BASE])
            self.assertTrue(journal["sessionImageRestored"])


if __name__ == "__main__":
    unittest.main()
