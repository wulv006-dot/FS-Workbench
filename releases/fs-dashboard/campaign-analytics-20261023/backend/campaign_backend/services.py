"""Trusted management service composition. No HTTP-supplied configuration or filesystem paths."""
import json
import os
from pathlib import Path

from . import benefits
from .analysis import AnalysisStore, reconcile
from .catalog import positive_id
from .core import ContractError
from .ledger import OperationLedger


class BackendServices:
    def __init__(self, state_dir, policy=None):
        self.state_dir = Path(state_dir)
        if policy is None:
            path = self.state_dir / 'policy.json'
            policy = json.loads(path.read_text('utf-8')) if path.is_file() else {}
        if not isinstance(policy, dict):
            raise ContractError('PRIVATE_POLICY_INVALID')
        self.policy = policy

    @classmethod
    def from_environment(cls):
        return cls(os.environ.get('CAMPAIGN_BACKEND_STATE_DIR', '/var/lib/fs-campaign-dashboard/backend'))

    def _directory(self):
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.state_dir.is_symlink():
            raise ContractError('PRIVATE_STATE_DIRECTORY_REQUIRED')

    def handle(self, request, reader_factory):
        allowed = {'action', 'site_id', 'kind', 'native_id', 'operation_id', 'before_hash', 'changes', 'enabled',
                   'from', 'to', 'activity_id', 'restore_of'}
        if set(request) - allowed:
            raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
        site_id = positive_id(request.get('site_id'))
        if site_id != '266':
            raise ContractError('PROJECT_SITE_REQUIRED')
        action = request['action']
        if action == 'analysis_summary':
            path = self.state_dir / 'analysis.sqlite3'
            store = AnalysisStore(path if path.is_file() else ':memory:')
            try:
                return store.summary(site_id, request.get('activity_id'))
            finally:
                store.close()
        if action == 'operation_lookup':
            path = self.state_dir / 'operations.sqlite3'
            if not path.is_file():
                raise ContractError('OPERATION_NOT_FOUND')
            return benefits.operation(OperationLedger(path), None, site_id, request.get('operation_id'))
        reader = reader_factory()
        try:
            if action == 'benefit_detail':
                return benefits.detail(reader, self.policy, request.get('kind'), request.get('native_id'), site_id)
            if action in ('benefit_edit', 'benefit_toggle', 'benefit_restore', 'operation_reconcile'):
                self._directory()
                ledger = OperationLedger(self.state_dir / 'operations.sqlite3')
                if action == 'operation_reconcile':
                    return benefits.operation(ledger, reader, site_id, request.get('operation_id'), True)
                return benefits.mutate(reader, ledger, self.policy, request)
            if action == 'analysis_reconcile':
                self._directory()
                store = AnalysisStore(self.state_dir / 'analysis.sqlite3')
                try:
                    return reconcile(reader, store, site_id, request.get('from'), request.get('to'),
                                     self.policy.get('analysis', {}).get(site_id, {}))
                finally:
                    store.close()
            raise ContractError('ACTION_NOT_ALLOWED')
        finally:
            reader.close()
