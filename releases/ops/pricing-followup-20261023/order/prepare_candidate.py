"""Replace only the read strategy in the exact active source; never deploy."""
import argparse
import ast
import hashlib
from pathlib import Path

BASELINE_SHA256 = "120045f794f78bef4c4aaeb8dbc27d0049a30a2546ebb24a73193370f2c20593"


def prepare(baseline, output):
    raw = baseline.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("active_baseline_sha_mismatch")
    source = raw.decode("utf-8")
    tree = ast.parse(source)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fetch_all_needed"]
    if len(nodes) != 1:
        raise ValueError("one_read_entry_required")
    node = nodes[0]
    lines = source.splitlines(keepends=True)
    replacement = Path(__file__).with_name("query_read.py").read_text(encoding="utf-8").rstrip() + "\n"
    candidate = "".join(lines[:node.lineno - 1]) + replacement + "".join(lines[node.end_lineno:])
    changed = ast.parse(candidate)
    before = [n for n in tree.body if n is not node]
    after = [n for n in changed.body if not (isinstance(n, ast.FunctionDef) and n.name == node.name)]
    if ast.dump(ast.Module(body=before, type_ignores=[])) != ast.dump(ast.Module(body=after, type_ignores=[])):
        raise ValueError("unrelated_ast_changed")
    output.write_bytes(candidate.encode("utf-8"))
    return hashlib.sha256(output.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.baseline, args.output))
