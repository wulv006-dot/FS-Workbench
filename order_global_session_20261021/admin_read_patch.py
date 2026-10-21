"""Prepare the Admin read-lock fix against the current source, without restarting it."""
import ast
import textwrap


def transform(source):
    tree = ast.parse(source)
    changes = []
    for method in ('business_summary', 'marketing_summary'):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
        reader = next(n for n in fn.body if isinstance(n, ast.FunctionDef) and n.name == 'existing_read')
        changes.append((reader.lineno, reader.end_lineno, textwrap.indent('''def existing_read(path, **kwargs):
    with self.lock:
        if self.status != "ready" or not self.token:
            raise OSError("existing_session_unavailable")
        token = self.token
    kwargs.setdefault("timeout", 90)
    return self.request(path, token=token, **kwargs)
''', ' ' * reader.col_offset)))
    for method in ('new_customers', 'daily_summary'):
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == method)
        block = next(n for n in fn.body if isinstance(n, ast.With)
                     and ast.unparse(n.items[0].context_expr) == 'self.lock')
        expected = ['self.ensure', 'RuntimeError', 'self.request']
        calls = [ast.unparse(n.func) for n in ast.walk(block) if isinstance(n, ast.Call)]
        if sorted(calls) != sorted(expected):
            raise RuntimeError('admin_read_source_changed')
        changes.append((block.lineno, block.end_lineno, textwrap.indent('''with self.lock:
    if not self.ensure():
        raise RuntimeError("admin_es_auth_unavailable")
    token = self.token
status, raw = self.request(
    "/admin/order.Order/orderStaticsDetailByEs",
    data=payload, token=token, timeout=90,
)
''', ' ' * block.col_offset)))
    lines = source.splitlines(keepends=True)
    for start, end, replacement in sorted(changes, reverse=True):
        lines[start - 1:end] = [replacement]
    result = ''.join(lines)
    # Existing capability queries have their own budgets and completeness checks.
    replacements = (
        ('''            with self.lock:
                if not self.identity_ok(self.token):
                    return {'kind':'cohort_paid_orders','query':args,'status':'unavailable','reason':'existing_auth_unavailable'}
                return collect(lambda path,timeout:self.request(path,token=self.token,timeout=timeout),args)
''', '''            with self.lock:
                token=self.token
                if not self.identity_ok(token):
                    return {'kind':'cohort_paid_orders','query':args,'status':'unavailable','reason':'existing_auth_unavailable'}
            return collect(lambda path,timeout:self.request(path,token=token,timeout=timeout),args)
'''),
        ('''                if 'model_id' in checked and 'platform' not in checked:
                    # The 540-second read runs after manager.lock is released.
                    pass
                else:
                    return collect(lambda path,timeout:self.request(path,token=token,timeout=timeout),args)
            return self.model_product(checked,token)
''', '''            if 'model_id' in checked and 'platform' not in checked:
                return self.model_product(checked,token)
            return collect(lambda path,timeout:self.request(path,token=token,timeout=timeout),args)
'''),
    )
    if any(isinstance(n, ast.FunctionDef) and n.name == 'fc_capability' for n in ast.walk(tree)):
        for old, new in replacements:
            if result.count(old) != 1:
                raise RuntimeError('admin_capability_source_changed')
            result = result.replace(old, new, 1)
    compile(result, '<admin-read-lock-patch>', 'exec')
    return result
