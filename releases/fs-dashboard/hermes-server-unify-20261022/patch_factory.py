"""Exact native image build patch, not a running-process monkeypatch."""
import ast
import hashlib
from pathlib import Path

SOURCE_SHA = '5e51f2b4ad33af95044be68a001d0ae66948d8c116fe8ff28a8e70b378ca3be1'


def patch_source(raw):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('native_factory_source_drift')
    source = raw.decode('utf-8')
    functions = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == '_make_agent']
    if len(functions) != 1:
        raise ValueError('native_factory_symbol_drift')
    function = ast.get_source_segment(source, functions[0])
    anchor = '    agent = AIAgent('
    if function.count(anchor) != 1:
        raise ValueError('native_factory_call_drift')
    changed = function.replace(anchor, '    from fs_native_entry import construct_fs_agent\n    agent = construct_fs_agent(AIAgent,', 1)
    result = source.replace(function, changed, 1)
    ast.parse(result)
    return result.encode('utf-8')


if __name__ == '__main__':
    path = Path('/opt/hermes/tui_gateway/server.py')
    path.write_bytes(patch_source(path.read_bytes()))
