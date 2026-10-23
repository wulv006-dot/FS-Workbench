"""Exact native image build patch, not a running-process monkeypatch."""
import ast
import hashlib
from pathlib import Path

SOURCE_SHA = '5e51f2b4ad33af95044be68a001d0ae66948d8c116fe8ff28a8e70b378ca3be1'
GATEWAY_SHA = '6ec879a91aa09765515a69368c886d1ce4d3174b159868c966e8740e9cf1b347'


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


def patch_gateway(raw):
    if hashlib.sha256(raw).hexdigest() != GATEWAY_SHA:
        raise ValueError('native_gateway_source_drift')
    source = raw.decode('utf-8')
    methods = {node.name: node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.FunctionDef)}
    replacements = {
        '_build_fresh_agent': ('        return ctx.AIAgent(',
            '        from fs_native_entry import construct_fs_agent\n        return construct_fs_agent(ctx.AIAgent,'),
        '_run_conversation_with_approval': ('                return agent.run_conversation(api_message, **kwargs)',
            '                from fs_native_entry import run_gateway_conversation\n'
            '                return run_gateway_conversation(agent, ctx.source, ctx.inbound_message_id, api_message, **kwargs)'),
    }
    snippets = {symbol: ast.get_source_segment(source, methods[symbol]) for symbol in replacements if symbol in methods}
    for symbol, (anchor, replacement) in replacements.items():
        if symbol not in methods:
            raise ValueError('native_gateway_symbol_drift')
        method = snippets[symbol]
        if method.count(anchor) != 1:
            raise ValueError('native_gateway_call_drift')
        source = source.replace(method, method.replace(anchor, replacement, 1), 1)
    ast.parse(source)
    return source.encode('utf-8')


if __name__ == '__main__':
    path = Path('/opt/hermes/tui_gateway/server.py')
    path.write_bytes(patch_source(path.read_bytes()))
    path = Path('/opt/hermes/gateway/run_turn_runner.py')
    path.write_bytes(patch_gateway(path.read_bytes()))
