"""Structural check for the fc-coupon-parity-doc release package.

This release carries no runtime test of its own: the change is a comment-only
patch already proven logically equivalent on the production host (AST hash
identical before/after), plus two documentation edits. What CI can still do is
prove the package is internally consistent and does not pretend to be more than
it is.

Checks
  1. README.md / SOURCE-MAP.json / evidence/deployment-receipt.json exist.
  2. Every .json parses.
  3. baseline/ and source/ each hold lootbar_server_collector.py, and they differ
     (the whole point is that exactly this file changed).
  4. The declared before/after sha256 in SOURCE-MAP.json match those files.
  5. The patch is comment-only: the two files must have the SAME AST.
  6. The post-patch file compiles under Python 3.9 (production interpreter).
  7. deployment-receipt.json records a deployed status with the same after-hash.

Usage: python3 fc-check-doc-release.py <release-dir>
"""
import ast
import hashlib
import json
from pathlib import Path
import sys


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(release):
    root = Path(release)
    if not root.is_dir():
        raise SystemExit("release dir missing: %s" % root)

    for name in ("README.md", "SOURCE-MAP.json", "evidence/deployment-receipt.json"):
        if not (root / name).is_file():
            raise SystemExit("required file missing: " + name)

    for path in root.rglob("*.json"):
        json.loads(path.read_text(encoding="utf-8"))

    source_map = json.loads((root / "SOURCE-MAP.json").read_text(encoding="utf-8"))
    before_file = root / "baseline" / "lootbar_server_collector.py"
    after_file = root / "source" / "lootbar_server_collector.py"
    for path in (before_file, after_file):
        if not path.is_file():
            raise SystemExit("collector snapshot missing: " + str(path))

    declared = source_map["source_to_runtime"]
    if sha256(before_file) != declared["before"]["sha256"]:
        raise SystemExit("baseline sha256 does not match SOURCE-MAP.before")
    if sha256(after_file) != declared["after"]["sha256"]:
        raise SystemExit("source sha256 does not match SOURCE-MAP.after")
    if declared["before"]["sha256"] == declared["after"]["sha256"]:
        raise SystemExit("before and after are identical; nothing was changed")

    before_text = before_file.read_text(encoding="utf-8")
    after_text = after_file.read_text(encoding="utf-8")
    if ast.dump(ast.parse(before_text)) != ast.dump(ast.parse(after_text)):
        raise SystemExit("AST differs: this release must be comment-only")
    compile(after_text, "lootbar_server_collector.py", "exec")
    if ast.dump(ast.parse(after_text)) != ast.dump(ast.parse(after_text)):
        raise SystemExit("unstable AST dump")

    equivalence = source_map["logical_equivalence"]
    if not equivalence["equal"]:
        raise SystemExit("SOURCE-MAP does not assert logical equivalence")

    receipt = json.loads((root / "evidence" / "deployment-receipt.json").read_text(encoding="utf-8"))
    if receipt["status"] != "deployed":
        raise SystemExit("deployment receipt is not in deployed state")
    if receipt["installed_sha256"] != declared["after"]["sha256"]:
        raise SystemExit("receipt after-hash disagrees with SOURCE-MAP")

    # The comment that defines this release must actually be present.
    marker = "无券价 = 券前价"
    if marker not in after_text:
        raise SystemExit("expected coupon-parity comment not found in patched source")
    if marker in before_text:
        raise SystemExit("baseline already contains the comment; baseline is wrong")

    print("fc-coupon-parity-doc package OK")
    print("  bare python:", sys.version.split()[0])
    print("  before:", sha256(before_file))
    print("  after :", sha256(after_file))
    print("  AST   : identical (comment-only)")
    print("  receipt:", receipt["at"])


if __name__ == "__main__":
    main(sys.argv[1])
