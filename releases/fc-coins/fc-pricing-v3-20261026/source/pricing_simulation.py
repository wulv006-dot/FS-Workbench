"""Read-only FS research bridge for pinned V3 and frozen historical selectors."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from pricing_operations import native


V3_VERSION = 'fc-pricing-v3-20261026'
ENGINE_SHA = 'ab93ebee23751e04f7950c9a165881bd3f15ac839aed72a3de5d9b72eeb29f16'
FINANCIAL_SHA = 'fe6de2126a8da920e4994895dd68bcddff51c65bd10f4b521d3830b104193729'
LEGACY_SHA = {
    'legacy_80_15_5': '91f8d143e21e05544b17442bd8a20d3735f62caa4aa5b182584a4fd4c4ec993a',
    'legacy_itemd2r_parity': 'f68459feb07ff59690a4a6b716e9760a7c556e74b92b7e02dfa4c57d23eb0a42',
}


class SimulationBridge:
    def __init__(self, root='/var/lib/fc27-cloud', code=None, clock=None, request=native):
        self.root = Path(root)
        self.code = Path(code) if code else Path(__file__).parent / 'fc_pricing_v3'
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.request = request

    def versions(self):
        local = {
            'engine_sha256': hashlib.sha256((self.code / 'engine.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
            'financial_sha256': hashlib.sha256((self.code / 'financial.py').read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
        }
        if local != {'engine_sha256': ENGINE_SHA, 'financial_sha256': FINANCIAL_SHA}:
            raise ValueError('simulation_v3_code_changed')
        for name, (filename, expected) in self.legacy_sources().items():
            if expected != LEGACY_SHA[name] or hashlib.sha256((self.code / 'legacy_simulation' / filename).read_bytes().replace(b'\r\n',b'\n')).hexdigest() != expected:
                raise ValueError('simulation_legacy_code_changed')
        remote = self.request('/pricing/v3/versions', 'wulv')
        if remote.get('version') != V3_VERSION or any(remote.get(key) != value for key, value in local.items()) or remote.get('legacy_sources') != LEGACY_SHA:
            raise ValueError('simulation_runtime_version_changed')
        return dict(remote, **local)

    def legacy_sources(self):
        from fc_pricing_v3.legacy_simulation import SOURCES
        return SOURCES

    def baseline(self):
        self.versions()
        raw = (self.root / 'config' / 'automation.json').read_bytes()
        policy = json.loads(raw)
        identity = dict(revision=policy['revision'], sha256=hashlib.sha256(raw).hexdigest())
        return self, policy, identity

    def capabilities(self):
        versions = self.versions()
        state = self.request('/pricing/v3/state', 'wulv')
        identity = self.baseline()[2] if (self.root / 'config' / 'automation.json').is_file() else dict(status='legacy_policy_not_mounted')
        return dict(contract='fc27-v3-readonly-pinned-research', baseline_policy=identity,
                    baseline_policy_role='historical_source_identity_only',
                    engine_sha256=versions['engine_sha256'], financial_sha256=versions['financial_sha256'],
                    legacy_sources=versions['legacy_sources'], snapshot_id=state.get('snapshot_id'),
                    pricing_rules=None, pricing_rules_status='legacy_bands_retired_for_v3_decisions', minimum_gross_margin_pct='20',
                    granularity='three_independent_platforms_global_uniform_price',
                    rule_ideas_supported=False, candidate_evaluator='v3_two_strategy_current_evaluate',
                    candidate_evaluator_sha256=versions['engine_sha256'],
                    platforms=['PS', 'XBOX', 'PC'],
                    unsupported=['legacy_band_numerical_simulation', 'new_products'],
                    current_candidate_tool='fs.pricing.control compare_strategies/recommend',
                    historical_tool='fs.pricing.control simulate/simulation_read',
                    write_performed=False, execution_authorized=False)

    def rules(self, engine, policy, changes):
        raise ValueError('simulation_legacy_bands_retired_use_fs_pricing_control_evaluate')

    def evaluate(self, mode):
        self.versions()
        result = self.request('/pricing/v3/evaluate', 'wulv', dict(mode=mode))
        if result.get('execution_authorized') is not False or result.get('write_performed') is not False:
            raise ValueError('simulation_evaluate_not_read_only')
        return result

    def historical(self, kind, request_key, closed_days=7):
        self.versions()
        return self.request('/pricing/v3/simulations', 'wulv',
                            dict(request_key=request_key, kind=kind, closed_days=closed_days))

    def historical_result(self, simulation_id):
        self.versions()
        result = self.request('/pricing/v3/simulations/'+str(simulation_id), 'wulv')
        if (result.get('execution_authorized') not in (None,False) or
                'records' in result and result.get('execution_authorized') is not False):
            raise ValueError('simulation_result_not_read_only')
        return result

    def legacy_replay(self, snapshot_id, name):
        self.versions()
        if name not in LEGACY_SHA or not re.fullmatch(r'[0-9a-f-]{36}', snapshot_id):
            raise ValueError('simulation_legacy_request_invalid')
        result=self.request('/pricing/v3/legacy-replay/'+snapshot_id+'/'+name,'wulv')
        if (result.get('snapshot_id')!=snapshot_id or result.get('legacy_policy')!=name or
                result.get('read_only') is not True or result.get('execution_authorized') is not False):
            raise ValueError('simulation_legacy_reply_scope_invalid')
        return result

    def simulate(self, draft, snapshot_id, expected_policy):
        # The old shared-band numerical tool was already retired before V3.
        raise ValueError('simulation_legacy_bands_retired_use_fs_pricing_control_evaluate')
