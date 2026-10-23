"""Patch only item-result metadata in an exact live baseline; never deploy."""
import argparse
import ast
import hashlib
from pathlib import Path

BASELINE_SHA256 = '3ade09f1caefbe0deb0d69cdac8f6c5c98e705370bc1ed17cee3de0d595a5be3'
CMD_WRITE_SHA256 = '5bc8fe4a72d97f5985348b4dfb508e0b653e47413c7a946cbac21181dd8f0409'


def transform(source):
    tree = ast.parse(source)
    nodes = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'cmd_write']
    if len(nodes) != 1:
        raise ValueError('one_item_write_entry_required')
    node = nodes[0]
    original = ast.get_source_segment(source, node)
    if hashlib.sha256(original.encode()).hexdigest() != CMD_WRITE_SHA256:
        raise ValueError('item_write_contract_changed')
    replacement = original
    changes = {
        '        want_cache, cache_src = cache_wanted(a, plan)\n':
        '        want_cache, cache_src = cache_wanted(a, plan)\n'
        '        no_price_change = not ok and not fail and not bad\n',
        '             "mismatch": bad, "clearcache_ok": cache_ok,\n':
        '             "mismatch": bad, "clearcache_ok": cache_ok,\n'
        '             "noop": no_price_change,\n'
        '             "clearcache_required": bool(want_cache and not no_price_change),\n'
        '             "clearcache_reason": ("not_required_no_price_change" if no_price_change else\n'
        '                                   "requested_after_price_change" if want_cache else "not_requested"),\n',
    }
    for before, after in changes.items():
        if replacement.count(before) != 1:
            raise ValueError('one_metadata_anchor_required')
        replacement = replacement.replace(before, after)
    lines = source.splitlines(keepends=True)
    candidate = ''.join(lines[:node.lineno-1])+replacement+'\n'+''.join(lines[node.end_lineno:])
    changed = ast.parse(candidate)
    before = [n for n in tree.body if n is not node]
    after = [n for n in changed.body if not (isinstance(n, ast.FunctionDef) and n.name == 'cmd_write')]
    if ast.dump(ast.Module(body=before, type_ignores=[])) != ast.dump(ast.Module(body=after, type_ignores=[])):
        raise ValueError('unrelated_ast_changed')
    return candidate


def prepare(baseline, output):
    raw = baseline.read_bytes()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError('active_baseline_sha_mismatch')
    candidate = transform(raw.decode('utf-8')).encode('utf-8')
    output.write_bytes(candidate)
    return hashlib.sha256(candidate).hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--baseline', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(prepare(args.baseline, args.output))
