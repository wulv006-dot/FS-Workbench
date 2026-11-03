"""Trusted management service composition. No HTTP-supplied configuration or filesystem paths."""
import json
import os
import re
import stat
from pathlib import Path

from . import benefits
from .analysis import AnalysisStore, reconcile
from .catalog import positive_id
from .core import ContractError
from .ledger import OperationLedger, private_metadata


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

    def record_manual_compensation(self, reference, reader_factory):
        """Trusted local operator API only; deliberately absent from handle()/bridge actions.

        Policy approval is per exact private artifact digest and must follow human verification
        of its provenance. This method grants no native write or policy activation permission.
        """
        if not isinstance(reference, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{7,79}', reference):
            raise ContractError('COMPENSATION_REFERENCE_INVALID')
        approved = self.policy.get('compensation_proofs', {}).get(reference)
        if not isinstance(approved, str) or not re.fullmatch('[a-f0-9]{64}', approved):
            raise ContractError('COMPENSATION_PROOF_NOT_APPROVED')
        root = self.state_dir / 'compensation-proofs'
        path = root / (reference + '.json')
        for candidate, directory in ((self.state_dir, True), (root, True), (path, False)):
            info = candidate.lstat()
            if candidate.is_symlink() or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)):
                raise ContractError('PRIVATE_COMPENSATION_PROOF_REQUIRED')
            if os.name == 'posix':
                private_metadata(info, directory, os.geteuid())
        descriptor = os.open(str(path), os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0))
        with os.fdopen(descriptor, 'rb') as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ContractError('PRIVATE_COMPENSATION_PROOF_REQUIRED')
            if os.name == 'posix':
                private_metadata(info, False, os.geteuid())
            raw = source.read(300001)
        if len(raw) > 300000:
            raise ContractError('COMPENSATION_PROOF_TOO_LARGE')
        path = self.state_dir / 'operations.sqlite3'
        if not path.is_file():
            raise ContractError('OPERATION_NOT_FOUND')
        ledger = OperationLedger(path)
        def validate(db, proof):
            reader = reader_factory()
            try:
                return benefits.validate_compensation(db, proof, reader)
            finally:
                reader.close()
        return ledger.record_compensation(reference, raw, approved, validate)

    def handle(self, request, reader_factory, *, grant_authorize=None):
        allowed = {'action', 'site_id', 'kind', 'native_id', 'operation_id', 'before_hash', 'changes', 'enabled',
                   'from', 'to', 'activity_id', 'restore_of'}
        if request.get('action') == 'coupon_candidates':allowed |= {'page','limit'}
        if request.get('action') == 'coupon_grant':allowed |= {'email','grant_batch_no'}
        if set(request) - allowed:
            raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
        site_id = positive_id(request.get('site_id'))
        if site_id != '266':
            raise ContractError('PROJECT_SITE_REQUIRED')
        action = request['action']
        if action == 'coupon_candidates' and set(request)-{'action','site_id','page','limit'}:
            raise ContractError('REQUEST_FIELDS_NOT_ALLOWED')
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
            if action == 'coupon_candidates':
                return reader.coupons_page(site_id,page=request.get('page',1),limit=request.get('limit',100))
            if action == 'benefit_detail':
                return benefits.detail(reader, self.policy, request.get('kind'), request.get('native_id'), site_id)
            if action in ('benefit_edit', 'benefit_toggle', 'benefit_restore', 'operation_reconcile','coupon_grant'):
                self._directory()
                ledger = OperationLedger(self.state_dir / 'operations.sqlite3')
                if action=='coupon_grant':
                    from .coupon_grant import execute
                    return execute(reader,ledger,request,authorize=grant_authorize)
                if action == 'operation_reconcile':
                    payload=ledger.request_payload(request.get('operation_id'))
                    if payload.get('action')=='coupon_grant':
                        from .coupon_grant import CouponGrant
                        if payload.get('site_id')!=site_id:raise ContractError('OPERATION_SCOPE_MISMATCH')
                        return ledger.reconcile(request['operation_id'],CouponGrant(reader,ledger))
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
