"""Fixed one-file session image lifecycle, invoked inside the inherited release lock."""

import hashlib
import json
import os
import re
import subprocess
import time
import urllib.request
from pathlib import Path

BASE = "sha256:9f4ce8ee2621e5f044a060926df1968aef66a970ab5c1d6e2c072b1e754a8053"
OLD = "fc27-cloud-session:hermes-generic-data-20261018-v1"
NEW = "fc27-cloud-session:hermes-product-match-20261018-v1"
NAMES = ("admin_product_orders.py",)
HOST = "/opt/fc27-cloud/marketing-session-20261009/"
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")


def image_id(tag, absent=False):
    result = subprocess.run(["docker", "image", "inspect", "-f", "{{.Id}}", tag],
                            capture_output=True, text=True, timeout=15)
    if result.returncode:
        if absent and "No such image" in result.stderr:
            return None
        raise ValueError("session_image_inspection_failed")
    value = result.stdout.strip()
    if not IMAGE.fullmatch(value):
        raise ValueError("session_image_identity_invalid")
    return value


def container():
    result = subprocess.run(["docker", "inspect", "fc27-p2pah-session"],
                            capture_output=True, text=True, timeout=15, check=True)
    rows = json.loads(result.stdout)
    if len(rows) != 1:
        raise ValueError("session_container_identity_invalid")
    return rows[0]


def baseline(manifest):
    contract = manifest["sessionImage"]
    if contract["baseImage"] != BASE or contract["oldTag"] != OLD or contract["newTag"] != NEW:
        raise ValueError("session_image_contract_drift")
    if image_id(BASE) != BASE or image_id(OLD) != BASE or image_id(NEW, True) is not None:
        raise ValueError("session_image_baseline_drift")
    row = container()
    if row["Image"] != BASE or row["Config"]["Image"] != OLD:
        raise ValueError("session_container_baseline_drift")


def healthy(expected):
    subprocess.run(["systemctl", "daemon-reload"], check=True, timeout=15)
    subprocess.run(["systemctl", "restart", "fc27-p2pah-session.service"], check=True, timeout=45)
    subprocess.run(["systemctl", "is-active", "--quiet", "fc27-p2pah-session.service"], check=True, timeout=10)
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:8767/health", timeout=2) as response:
                health = json.load(response)
            if health.get("ready") is True or health.get("status") == "ready":
                break
        except (OSError, ValueError):
            pass
        time.sleep(1)
    else:
        raise ValueError("session_health_not_ready")
    if container()["Image"] != expected:
        raise ValueError("session_running_image_readback_failed")


def apply(manifest, stage, backup, journal, root, atomic, write_journal, digest, no_link):
    baseline(manifest)
    contract = manifest["sessionImage"]
    context = stage / "image-inputs/session-build"
    desired = {row["target"]: row["sha256"] for row in manifest["files"]}
    expected = {}
    for name in NAMES:
        source = root / (HOST + name).lstrip("/")
        no_link(source)
        if digest(source) != desired[HOST + name]:
            raise ValueError("session_host_source_drift:" + name)
        candidate = context / name
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != desired[HOST + name]:
            raise ValueError("session_build_input_drift:" + name)
        expected["/usr/local/bin/" + name] = desired[HOST + name]
    dockerfile = context / "Dockerfile"
    if hashlib.sha256(dockerfile.read_bytes()).hexdigest() != contract["dockerfileSha256"]:
        raise ValueError("session_dockerfile_drift")
    journal.update(sessionBuildIntent=True, sessionBuildOutcome="UNKNOWN")
    write_journal(backup, journal)
    try:
        result = subprocess.run(["docker", "build", "--network", "none", "--pull=false",
                                 "-f", str(dockerfile), "-t", NEW, str(context)],
                                capture_output=True, timeout=120, env={**os.environ, "DOCKER_BUILDKIT": "0"})
        if result.returncode:
            payload = b"stdout\n" + result.stdout + b"\nstderr\n" + result.stderr
            atomic(backup / "session-build-failure.log", payload, 0o600)
            journal.update(sessionBuildOutcome="FAILED", sessionBuildDiagnosticSha256=hashlib.sha256(payload).hexdigest())
            write_journal(backup, journal)
            raise ValueError("session_build_failed_private_diagnostic")
        built = image_id(NEW)
        journal.update(sessionBuiltImage=built, sessionBuildOutcome="built_unverified")
        write_journal(backup, journal)
        actual = subprocess.check_output(["docker", "run", "--rm", "--network", "none", "--entrypoint", "sha256sum", NEW,
                                          *expected], text=True, timeout=45)
        if {line.split()[1]: line.split()[0] for line in actual.splitlines()} != expected:
            raise ValueError("session_image_source_readback_failed")
    except subprocess.TimeoutExpired:
        journal["sessionBuildOutcome"] = "UNKNOWN"
        write_journal(backup, journal)
        raise ValueError("session_image_operation_unknown_requires_reconcile")
    if image_id(OLD) != BASE or container()["Image"] != BASE:
        raise ValueError("old_session_image_or_container_drift")
    journal.update(sessionBuildOutcome="verified", sessionRestartIntent=True)
    write_journal(backup, journal)
    healthy(built)
    journal["sessionImageWritten"] = True
    write_journal(backup, journal)


def restore(backup, journal, write_journal):
    if not journal.get("sessionBuildIntent"):
        return
    if image_id(OLD) != BASE or container()["Image"] not in (BASE, journal.get("sessionBuiltImage")):
        raise ValueError("session_rollback_image_drift")
    journal["sessionRollbackIntent"] = True
    write_journal(backup, journal)
    healthy(BASE)
    journal["sessionImageRestored"] = True
    write_journal(backup, journal)
