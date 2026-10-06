"""Read-only byte/set verification for this isolated repository addition."""
import hashlib
import json
from pathlib import Path

def main():
    here = Path(__file__).resolve().parent
    root = here.parents[2]
    map_path = here / "REPOSITORY-SOURCE-MAP.json"
    manifest = json.loads(map_path.read_text(encoding="utf-8"))
    expected = set(manifest["files"]) | {map_path.relative_to(root).as_posix()}
    actual = set()
    for relative in manifest["allowedRoots"]:
        for path in (root / relative).rglob("*"):
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise SystemExit("Symlink rejected: " + path.relative_to(root).as_posix())
            if path.is_file():
                actual.add(path.relative_to(root).as_posix())
    if actual != expected:
        raise SystemExit("Missing or unexpected files: " + repr(sorted(actual ^ expected)))
    for name, item in manifest["files"].items():
        path = root / name
        data = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item["sha256"] or blob != item["gitBlob"]:
            raise SystemExit("Byte mismatch: " + name)
    if manifest["releaseReady"] is not False or manifest["productionAction"] is not False:
        raise SystemExit("Unexpected readiness claim")
    print(json.dumps({"mapped_files_verified": len(manifest["files"]), "batch_files": len(expected), "releaseReady": False, "external_reads": False}))

if __name__ == "__main__":
    main()

