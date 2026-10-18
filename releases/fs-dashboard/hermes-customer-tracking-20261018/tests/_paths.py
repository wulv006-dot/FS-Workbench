"""Exact private FS-Workbench source layout used by these isolated tests."""
from pathlib import Path
import sys

RELEASE = Path(__file__).resolve().parents[1]
ROOT = RELEASE.parents[2]
FS = ROOT / "releases/fs-dashboard"
SOURCES = (
    RELEASE / "source",
    FS / "hermes-generic-data-20261018/source",  # current Admin product reader
    FS / "admin-data-tools-20261018/candidate/hermes",  # frozen ES structure
    FS / "hermes-data-workspace-20261018/source",  # cohort contract
    FS / "hermes-conversation-20261018/source",  # private artifact store
    FS / "hermes-fc-pilot-20261013",  # pinned protocol, proxy and pilot
)
for source in SOURCES:
    if not source.is_dir():
        raise RuntimeError(f"required_private_source_missing:{source.relative_to(ROOT)}")
sys.path[:0] = [str(source) for source in SOURCES]
