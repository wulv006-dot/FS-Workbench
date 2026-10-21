"""Keep the live 2FA flow, replacing only automated CAPTCHA solving with human input."""
import ast

SOURCE_SHA = '4923240a166b232f3c019c80341017eda1bca237aaf9e36c4020c1042a3499c8'


def patch(source):
    tree = ast.parse(source)
    cls, = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'SessionManager']
    login, = [n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'login']
    loop, = [n for n in login.body if isinstance(n, ast.For)]
    assert len(loop.body) >= 7
    assert isinstance(loop.body[0], ast.AugAssign) and ast.unparse(loop.body[0].target) == 'self.login_attempts'
    assert any(isinstance(n, ast.Attribute) and n.attr == 'classification' for n in ast.walk(loop.body[4]))
    assert isinstance(loop.body[5], ast.If)
    replacement = ast.parse('''from manual_captcha import take
human = take(self)
if human is None:
    return False
captcha_id, code = human
self.login_attempts += 1
''').body
    loop.body[:6] = replacement
    loop.iter = ast.parse('range(1)', mode='eval').body
    assert not any(isinstance(n, ast.Attribute) and n.attr == 'classification' for n in ast.walk(login))
    main, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    class ManualDelay(ast.NodeTransformer):
        changed = 0
        def visit_If(self, node):
            self.generic_visit(node)
            if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Attribute) and ast.unparse(node.test.left) == 'manager.status':
                self.changed += 1
                return ast.If(test=ast.parse('manager.status.startswith("manual_captcha_")',mode='eval').body,
                              body=[ast.Assign(targets=[ast.Name(id='delay',ctx=ast.Store())],value=ast.Constant(value=2))],
                              orelse=[node])
            return node
    delay = ManualDelay()
    main = delay.visit(main)
    assert delay.changed == 1, 'upkeep_contract_changed'
    lines = source.splitlines(keepends=True)
    for node in sorted([login, main], key=lambda n:n.lineno, reverse=True):
        text = ast.unparse(ast.fix_missing_locations(node))
        indent = ' ' * node.col_offset
        lines[node.lineno-1:node.end_lineno] = ['\n'.join(indent+line for line in text.splitlines())+'\n']
    result = ''.join(lines)
    compile(result, '<manual-session>', 'exec')
    return result
