"""Exact in-place browser bindings patch; original business source stays on server."""
import ast


def python_source(source, closes):
    tree=ast.parse(source)
    calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='connect_over_cdp']
    if len(calls)!=1 or ast.unparse(calls[0].func.value)!='playwright.chromium':
        raise ValueError('one_original_backend_connection_required')
    if 'from isolated_backend import' in source:
        raise ValueError('original_backend_source_required')
    prefix=0
    for node in tree.body:
        if (isinstance(node,ast.ImportFrom) and node.module=='__future__') or (isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)):
            prefix=node.end_lineno
        else:break
    original=ast.get_source_segment(source,calls[0])
    result=source.replace(original,'open_backend(playwright)',1)
    lines=result.splitlines(keepends=True)
    addition='from isolated_backend import open_backend, close_backend\n'
    result=''.join(lines[:prefix])+addition+''.join(lines[prefix:])
    for name,count in closes.items():
        if result.count(name+'.close()')!=count:raise ValueError('owned_page_cleanup_shape_changed')
        result=result.replace(name+'.close()','close_backend('+name+')')
    ast.parse(result)
    restored=result.replace(addition,'',1).replace('open_backend(playwright)',original,1)
    for name in closes:restored=restored.replace('close_backend('+name+')',name+'.close()')
    if restored!=source:raise ValueError('unrelated_business_source_changed')
    return result


def launcher(source):
    marker='docker run --rm'
    if source.count(marker)!=1 or '--memory' in source or 'PYTHONPATH=' in source or 'isolated_backend.py' in source:
        raise ValueError('one_original_backend_launcher_required')
    if 'src=/opt/fs-order-session' not in source or 'src=/run/fs-order-session' not in source:
        raise ValueError('original_shared_identity_mounts_required')
    flags=(' --init --memory 2g --memory-swap 2g --env PYTHONPATH=/opt:/opt/fs-order-session'
           ' --mount type=bind,src=/opt/fc27-cloud-browser/isolated_backend.py,dst=/opt/isolated_backend.py,readonly')
    result=source.replace(marker,marker+flags,1)
    if result.count('/tmp:rw,noexec,nosuid,size=64m')!=1:raise ValueError('original_tmp_budget_required')
    result=result.replace('/tmp:rw,noexec,nosuid,size=64m','/tmp:rw,noexec,nosuid,size=256m',1)
    if result.replace(marker+flags,marker,1).replace('/tmp:rw,noexec,nosuid,size=256m','/tmp:rw,noexec,nosuid,size=64m',1)!=source:
        raise ValueError('unrelated_launcher_arguments_changed')
    return result
