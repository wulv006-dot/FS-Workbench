"""Real repository sources assembled offline; no production profile, service or model."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch
from contextlib import contextmanager
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[4]
SOURCE = Path(__file__).resolve().parents[1] / 'source'
sys.path[:0] = [str(SOURCE), str(ROOT / 'releases/fs-dashboard/hermes-fc-pilot-20261013')]
import knowledge_catalog as kc
import business_context as bc

BASE = '6a0f424ac020694e67f8ae5d825ce871d1a7faf1'
BASELINE = 'releases/fs-dashboard/dashboard-refresh-20261025/source/business-baseline.md'
HISTORY = 'knowledge/history/fc-business-baseline-before-aion2-20261023.md'
CURRENT_IDS = {'fs.data.sources', 'fs.data.currency', 'fs.customer.identity', 'fc.marketing.attribution',
               'fs.finance.procurement', 'fc.pricing.constraints', 'fs.procurement.inputs',
               'fs.pricing.parameter-identity', 'fs.product.identity', 'fs.customer.lifecycle',
               'fs.learning.methods', 'fs.project.execution', 'fc.pricing.reference-weighting',
               'fs.dashboard.shipping-profit'}


def lf(path):
    return path.read_bytes().replace(b'\r\n', b'\n')


def catalog():
    return json.loads((ROOT / 'knowledge/index.json').read_text(encoding='utf-8'))


def assemble_real_sources(root):
    """Use a clearly synthetic publication identity solely to exercise published-only readers."""
    index = kc.validate(catalog())
    index = copy.deepcopy(index)
    prefix = 'knowledge-releases/offline-assembly-only'
    index.update(release='offline-assembly-only', release_state='published', source_commit='f'*40,
                 source_root=prefix+'/sources')
    for row in index['entries']:
        if row['source_commit'] is None:
            row['source_commit'] = 'f'*40
        if row['layer'] == 'candidate':
            continue
        data = lf(ROOT / row['source']['path'])
        if hashlib.sha256(data).hexdigest() != row['source']['sha256']:
            raise ValueError('actual_repository_source_drift:'+row['id'])
        target = root / index['source_root'] / row['source']['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    path = root / prefix / 'index.json'
    path.write_text(json.dumps(index, ensure_ascii=False), encoding='utf-8')
    runtime = root / 'runtime'
    runtime.mkdir()
    (runtime / 'business_context.py').write_bytes(lf(SOURCE / 'business_context.py'))
    (runtime / 'business-baseline.md').write_bytes(lf(ROOT / BASELINE))
    (runtime / 'data-archive-first.md').write_bytes(lf(ROOT / 'releases/fs-dashboard/daily-archive-20261021/skills/data-archive-first/SKILL.md'))
    (runtime / 'learning-loop.md').write_bytes(lf(ROOT / 'releases/fs-dashboard/fs-business-baseline-20261021/source/hermes/learning-loop.md'))
    skills_root = root / 'profile/skills'
    old_skills = ROOT / 'releases/fs-dashboard/hermes-data-workspace-20261018/skills'
    for name in bc.FILES:
        source = old_skills / name
        if source.is_file() and not name.startswith('reviewed-business-20261015/'):
            target = skills_root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(lf(source))
    method = ROOT / 'releases/fs-dashboard/hermes-data-workspace-20261018/method'
    manifest = json.loads((method / 'manifest.json').read_text(encoding='utf-8'))
    texts = {}
    for row in manifest['files']:
        data = lf(method / row['path'])
        if hashlib.sha256(data).hexdigest() != row['sha256']:
            raise ValueError('actual_method_source_drift')
        target = skills_root / 'report-html-authoring' / row['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        texts[row['path']] = data.decode('utf-8')
    skills = dict(version='offline-repository-method-'+manifest['version'], sha256=hashlib.sha256(lf(method/'manifest.json')).hexdigest(),
                  text=texts['SKILL.md'], methods_text=texts['METHOD.md']+'\n'+texts['APPLICATIONS.md'],
                  governance_text=texts['ACCEPTANCE.md'], permissions=[])
    policy = dict(contract='fs-knowledge-load-policy-v1', requests={}, task_routes=dict(enabled=True, routes=[
        dict(owner='wulv', project='FS', channel='fs', task_types=['report', 'data', 'conversation'],
             catalog=prefix+'/index.json', sha256=hashlib.sha256(path.read_bytes()).hexdigest(), modules=['FS', 'FC27'],
             baseline_compatibility=dict(mode='retain_full_baseline', sha256=hashlib.sha256(lf(ROOT/BASELINE)).hexdigest()))]))
    (root / 'knowledge-load-policy.json').write_text(json.dumps(policy), encoding='utf-8')
    (root / 'knowledge-load-policy.json').chmod(0o600)
    selection = kc.task_selection(root, owner='wulv', project='FS', channel='fs', task_type='report')
    with patch.object(bc, '__file__', str(runtime/'business_context.py')):
        knowledge = bc.freeze_learning(root, skills, {}, 'daily', selection=selection, skill_root=skills_root, owner='wulv')
    return selection, knowledge


def read_all_sections(root, knowledge):
    source = ROOT / 'releases/fc-coins/fc-pricing-v2-20261022/source/conversation_service.py'
    function = next(x for x in ast.parse(source.read_text(encoding='utf-8')).body
                    if isinstance(x, ast.FunctionDef) and x.name == 'attach_current_learning')
    namespace = dict(re=re)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])), str(source), 'exec'), namespace)
    book = types.SimpleNamespace(call=lambda name, args: dict(original_tool=name))
    modules = {'report_method': types.SimpleNamespace(method_bundle=lambda _: knowledge['skills']),
               'learning_registry': types.SimpleNamespace(context=lambda _: '')}
    sections = []
    with patch.dict(sys.modules, modules):
        namespace['attach_current_learning'](book, root, knowledge)
        page = 'page:1'
        while page:
            index = book.call('fc.read_skill', dict(topic='methods', section_id=page))
            for row in index['sections']:
                sections.append(book.call('fc.read_skill', dict(topic='methods', section_id=row['section_id'])))
            page = index['next_page']
    return sections


def source_budget_probe(root, knowledge):
    before = list(sys.path)
    try:
        sys.path[:0] = [str(ROOT/p) for p in (
            'releases/fc-coins/fc-pricing-v2-20261022/source',
            'releases/fs-dashboard/fc-coins-workflow-20261022/source',
            'releases/fs-dashboard/fc-coins-evidence-20261021/source',
            'releases/fs-dashboard/user-analytics-20261022/source',
            'releases/fs-dashboard/hermes-customer-tracking-20261018/source',
            'releases/fs-dashboard/hermes-generic-data-20261018/source',
            'releases/fs-dashboard/admin-data-tools-20261018/candidate/hermes',
            'releases/fs-dashboard/hermes-data-workspace-20261018/source')]
        with patch.dict(sys.modules):
            sources = {
                'research': 'releases/fs-dashboard/fc-coins-workflow-20261022/source/research.py',
                'strategy_tools': 'releases/fc-coins/fc-pricing-v2-20261022/source/strategy_tools.py',
                'runs_contract': 'releases/fc-coins/fc-pricing-v2-20261022/source/runs_contract.py',
                'proxy_gateway': 'releases/fs-dashboard/hermes-v2-strategy-20261021/source/proxy_gateway.py',
                'direct_provider': 'releases/fs-dashboard/hermes-v2-core-20261020/source/direct_provider.py'}
            for name, relative in sources.items():
                spec = importlib.util.spec_from_file_location(name, ROOT/relative)
                module = importlib.util.module_from_spec(spec)
                sys.modules[name] = module
                spec.loader.exec_module(module)
            probe = _source_budget_probe(root, knowledge)
            probe['source_hashes'] = {p: hashlib.sha256(lf(ROOT/p)).hexdigest() for p in sources.values()}
            return probe
    finally:
        sys.path[:] = before


def _source_budget_probe(root, knowledge):
    """Exercise actual admission, request builder, preflight and empty local budget ledger."""
    import proxy_gateway as pg
    import direct_provider as dp
    from background import import_background, task_context
    method_source = ROOT / 'releases/fs-dashboard/hermes-data-workspace-20261018/source/report_method.py'
    method_tree = ast.parse(method_source.read_text(encoding='utf-8'))
    method_function = next(n for n in method_tree.body if isinstance(n, ast.FunctionDef) and n.name=='html_design_context')
    manifest = json.loads((ROOT/'releases/fs-dashboard/hermes-data-workspace-20261018/method/manifest.json').read_text(encoding='utf-8'))
    method_hash = next(n.value.value for n in method_tree.body if isinstance(n, ast.Assign)
                       and any(isinstance(t, ast.Name) and t.id=='HTML_DESIGN_MANIFEST_SHA256' for t in n.targets))
    namespace = dict(chunks=[], HTML_DESIGN_MANIFEST_SHA256=method_hash)
    append = next(n for n in ast.walk(method_function) if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                  and isinstance(n.value.func, ast.Attribute) and isinstance(n.value.func.value, ast.Name)
                  and n.value.func.value.id=='chunks' and n.value.func.attr=='append')
    for row in manifest['files']:
        namespace.update(row=row, text=lf(ROOT/'releases/fs-dashboard/hermes-data-workspace-20261018/method'/row['path']).decode())
        exec(compile(ast.fix_missing_locations(ast.Module(body=[append], type_ignores=[])), str(method_source), 'exec'), namespace)
    # Reuse the source's pure assembly expressions; production filesystem checks are not bypassed or changed.
    for name in ('instruction', 'context'):
        assignment = next(n for n in ast.walk(method_function) if isinstance(n, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id==name for t in n.targets))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[assignment], type_ignores=[])), str(method_source), 'exec'), namespace)
    design_text = namespace['context']
    background_root = ROOT/'releases/fs-dashboard/hermes-fc-pilot-20261013/assets'
    metadata = json.loads((background_root/'knowledge-derived.json').read_text(encoding='utf-8'))
    background = import_background(lf(background_root/'knowledge-derived.md').decode(), approved_sha256=metadata['sha256'],
                                   version=metadata['version'], source_reference=metadata['source_reference'])
    background_text, _ = task_context(background, knowledge['skills'])
    prompt_path = ROOT/'releases/fs-dashboard/hermes-report-method-20261017/source/skill_bundle.py'
    prompt_function = next(n for n in ast.parse(prompt_path.read_text(encoding='utf-8')).body
                           if isinstance(n, ast.FunctionDef) and n.name=='prompt')
    prompt_namespace = dict(json=json)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[prompt_function], type_ignores=[])), str(prompt_path), 'exec'), prompt_namespace)
    task_prompt = prompt_namespace['prompt'](knowledge['skills'], dict(instruction='只验证本地装配范围，不调用模型。'+design_text))
    system = background_text+'\n'+task_prompt+'\n'+knowledge['text']
    request = pg.request_body(dict(messages=[dict(role='system', content=system), dict(role='user', content='装配检查')],
                                   max_tokens=pg.MAX_HERMES_OUTPUT_TOKENS, reasoning_effort='high'), dp.MODEL)
    wire = dp.prepare_request(request, request['tools'])
    worker_path = ROOT/'releases/fs-dashboard/hermes-v2-core-20261020/source/hermes_worker.py'
    spec = importlib.util.spec_from_file_location('offline_budget_worker', worker_path)
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    admission_root = root/'admissions'
    admission_root.mkdir()
    session = 'fc_'+'a'*64
    admission = dict(session_id=session, token='b'*40, model=dp.MODEL, prompt=task_prompt, reasoning_effort='high',
                     frozen_skills=knowledge['skills'], learning_text=knowledge['text'],
                     learning_receipt={k: knowledge[k] for k in ('version','identity','files','memory_path','native_skip_reason')})
    admission_raw = json.dumps(admission, ensure_ascii=False).encode()
    (admission_root/(session+'.json')).write_bytes(admission_raw)
    with patch.object(worker, 'ADMISSIONS', admission_root):
        accepted = worker.admission(session)
    @contextmanager
    def db():
        conn = sqlite3.connect(root/'budget-fixture.sqlite3')
        conn.row_factory = sqlite3.Row
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    with db() as conn:
        conn.execute('CREATE TABLE model_calls(fingerprint TEXT PRIMARY KEY,day TEXT,state TEXT,content TEXT)')
    policy = dict(id=dp.POLICY_ID, model=dp.MODEL, price_version='deepseek-direct-no-cny-invoice-or-fx-v1',
                  input_microcny=None, output_microcny=None)
    budget = pg.UnifiedBudget(db, policy, lambda: datetime.now(timezone.utc), allow_unknown_costs=True)
    bound = pg.conservative_input_bound(request)
    budget.reserve('wulv', 'offline-task', 0, request, bound, daily_limit=0)
    with db() as conn:
        reserved = conn.execute('SELECT tokens FROM hermes_reservations').fetchone()['tokens']
    return dict(admission_accepted=accepted['learning_text']==knowledge['text'], admission_bytes=len(admission_raw),
                provider_preflight_accepted=True, provider_wire_bytes=len(wire), provider_wire_limit_bytes=dp.WIRE_BYTES,
                output_tokens=json.loads(wire)['max_tokens'], configured_joint_context_tokens=pg.MAX_PROVIDER_CONTEXT_TOKENS,
                input_reservation_bound=bound, reserved_input_plus_output=reserved, system_bytes=len(system.encode()),
                worker_lf_sha256=hashlib.sha256(lf(worker_path)).hexdigest(), tool_schema_count=len(request['tools']),
                model_requests=0, live_usage_hold_or_daily_limit_or_provider_lock_checked=False,
                actual_native_base_prompt_and_business_evidence_included=False,
                scope='repository learning/method/background/tool layers; actual tokenization/provider acceptance not executed')


class LearningCatalog(unittest.TestCase):
    def test_candidate_identity_is_honest_and_published_still_requires_exact_commit(self):
        value = catalog()
        self.assertIsNone(value['source_commit'])
        self.assertEqual(value['base_commit'], BASE)
        kc.validate(value)
        value['release_state'] = 'published'
        with self.assertRaisesRegex(ValueError, 'source_version'):
            kc.validate(value)
        value.update(release_state='candidate', base_commit='not-a-commit')
        with self.assertRaisesRegex(ValueError, 'source_version'):
            kc.validate(value)

    def test_fourteen_current_entries_cover_rules_and_twenty_four_preserve_history(self):
        entries = catalog()['entries']
        self.assertEqual(len(entries), 24)
        self.assertEqual({r['id'] for r in entries if r['layer']=='current' and r['status']=='effective'}, CURRENT_IDS)
        self.assertEqual(len({(r['id'], r['revision']) for r in entries}), 24)

    def test_user_approved_reference_rule_is_indexed_without_changing_margin_constraints(self):
        entries = catalog()['entries']
        row = next(r for r in entries if r['id']=='fc.pricing.reference-weighting')
        self.assertEqual(row['revision'], 'fc-reference-weighting-20261024-v2')
        text = lf(ROOT/row['source']['path']).decode('utf-8')
        for required in ('80%', '15%', '5%', '缺项贡献为0', 'model_unavailable_fallback_usd', 'v15'):
            self.assertIn(required, text)
        margin = next(r for r in entries if r['id']=='fc.pricing.constraints')
        self.assertEqual(margin['revision'], 'v15')

    def test_actual_profit_replaces_shipping_primary_and_preserves_on_demand_history(self):
        path = ROOT / 'knowledge/index.json'
        result = kc.select(ROOT, 'knowledge/index.json', hashlib.sha256(lf(path)).hexdigest(),
                           ['FS'], ['fs.data.sources', 'fs.dashboard.shipping-profit'], preview=True)
        self.assertEqual(result['status'], 'available_preview')
        rows = {r['id']: r for r in result['entries']}
        rule = rows['fs.dashboard.shipping-profit']
        self.assertEqual(rule['revision'], 'dashboard-refresh-20261025-v3')
        self.assertEqual(rule['source_commit'], '34ebc6903b705ebd2418b879e40364e1b50b9a33')
        for required in ('逐单实际成本毛利', '付款时间', '不平均订单/游戏/每日比例', '缺成本',
                         'FC客户', '逐日金额和数量加总须等于区间值', 'Hermes按需能力保留', '八张大卡', '权限拒绝', '2 小时', '独立5分钟缓存'):
            self.assertIn(required, rule['content'])
        self.assertIn('逐单实际成本毛利', rows['fs.data.sources']['content'])
        historical = kc.select(ROOT, 'knowledge/index.json', hashlib.sha256(lf(path)).hexdigest(),
                               ['FS'], ['fs.dashboard.shipping-profit'], revision='shipping-profit-20261024-v1',history=True,preview=True)
        self.assertEqual(historical['entries'][0]['status'], 'retired')
        self.assertIn('/stats/admin_index/delivery.html', historical['entries'][0]['content'])
        self.assertEqual(catalog()['release_state'], 'candidate')

    def test_every_source_hash_and_selector_resolves_against_real_files(self):
        for row in catalog()['entries']:
            with self.subTest(id=row['id'], revision=row['revision']):
                data = lf(ROOT / row['source']['path'])
                self.assertEqual(hashlib.sha256(data).hexdigest(), row['source']['sha256'])
                self.assertTrue(kc.extract(data.decode('utf-8-sig'), row['source'].get('selector')).strip())

    def test_historical_copy_tracks_original_location_without_claiming_old_commit_contains_new_path(self):
        row = next(r for r in catalog()['entries'] if r['source']['path']==HISTORY)
        self.assertIsNone(row['source_commit'])
        self.assertEqual(row['original_source']['source']['path'], 'releases/fc-coins/fc-pricing-v2-20261022/source/business-baseline.md')
        self.assertEqual(row['original_source']['source']['sha256'], row['source']['sha256'])
        self.assertEqual(row['original_source']['source_commit'], '4722f20e231ffe306095a211009d25770c478d24')
        self.assertEqual(hashlib.sha256(lf(ROOT/HISTORY)).hexdigest(), '1c586eb45460f6209703a747191cfc21e506d4ce796d63eae3c01accd8883ecb')

    def test_existing_contract_index_dates_do_not_invent_original_policy_effective_dates(self):
        rows = [r for r in catalog()['entries'] if r['revision']=='existing-contract-20261023']
        self.assertEqual(len(rows), 6)
        for row in rows:
            self.assertEqual(row['effective_at'], '2026-10-23')
            self.assertEqual(row['effective_at_basis'], '本知识修订截至日')
            self.assertIsNone(row['original_effective_at'])

    def test_aion2_correction_is_current_and_prior_attribution_remains_explicit_history(self):
        path = ROOT / 'knowledge/index.json'
        sha = hashlib.sha256(lf(path)).hexdigest()
        current = kc.select(ROOT, 'knowledge/index.json', sha, ['FC27'], ['fc.marketing.attribution'], preview=True)
        self.assertEqual(current['entries'][0]['revision'], 'v15-pmax-aion2-20261023')
        self.assertIn('优惠码 `Aion2` 由 TikTok 改归**分销**', current['entries'][0]['content'])
        old = kc.select(ROOT, 'knowledge/index.json', sha, ['FC27'], ['fc.marketing.attribution'],
                        revision='v15-pmax-20261022', history=True, preview=True)
        self.assertNotIn('2026-10-23用户更正覆盖', old['entries'][0]['content'])
        self.assertEqual(old['entries'][0]['source']['path'], HISTORY)
        self.assertEqual(kc.select(ROOT, 'knowledge/index.json', sha, ['FC27'])['status'], 'not_published')

    def test_real_baseline_methods_catalog_freeze_effective_input_budget_and_paginated_bodies(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            selection, knowledge = assemble_real_sources(root)
            self.assertEqual({r['id'] for r in selection['entries']}, CURRENT_IDS)
            self.assertIn(lf(ROOT/BASELINE).decode('utf-8').strip(), knowledge['text'])
            self.assertIn('data-storytelling/SKILL.md', '\n'.join(r['path'] for r in knowledge['files']))
            self.assertIn('report-html-authoring/SKILL.md', '\n'.join(r['path'] for r in knowledge['files']))
            self.assertLess(len(knowledge['text'].encode()), bc.MAX_TOTAL)
            loaded = bc.loaded_learning(root, knowledge['version'])
            receipt = bc.effective_learning(loaded, [dict(role='system', content=loaded['text'])])
            self.assertEqual(len(receipt['knowledge_entries']), 14)
            sections = read_all_sections(root, loaded)
            for row in selection['entries']:
                path = 'knowledge/'+row['id']+'@'+row['revision']
                body = ''.join(r['text'] for r in sections if r['path']==path)
                self.assertEqual(body, row['content'])
            self.assertTrue(all(len(r['text'])<=1400 for r in sections))
            self.assertGreater(len(sections), 12)
            # This existing byte/framing reservation is not an exact tokenizer or admission gate.
            from proxy_gateway import conservative_input_bound
            bound = conservative_input_bound(dict(messages=[dict(role='system', content=loaded['text'])]))
            self.assertGreater(bound, len(loaded['text'].encode()))

    def test_current_fs_admission_and_model_preflight_accept_context_without_reducing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _, knowledge = assemble_real_sources(root)
            probe = source_budget_probe(root, knowledge)
            self.assertTrue(probe['admission_accepted'])
            self.assertTrue(probe['provider_preflight_accepted'])
            self.assertLess(probe['admission_bytes'], probe['provider_wire_limit_bytes'])
            self.assertLess(probe['provider_wire_bytes'], probe['provider_wire_limit_bytes'])
            self.assertEqual(probe['output_tokens'], 393216)
            self.assertEqual(probe['configured_joint_context_tokens'], 1048576)
            self.assertEqual(probe['reserved_input_plus_output'], probe['input_reservation_bound']+probe['output_tokens'])
            self.assertEqual(probe['worker_lf_sha256'], '27a1c87f18a621739a83c048c68f22090426f1e24bad9c13d492c8fe38561a00')


if __name__ == '__main__':
    unittest.main()

