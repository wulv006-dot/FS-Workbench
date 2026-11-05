"""Bind only the existing IAM, shared accounting exclusions and private module store."""
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import RLock

from user_store import Store, safe, require_database

ROOT = Path('/var/lib/fs-user-analytics')
CONFIG = Path(__file__).with_name('user_config.json')
ACCOUNTING = Path('/var/lib/fs-channel-effects/accounting-overrides.json')
STATUSES = ROOT / 'reviewed-source-statuses.json'
_service = None
_lock = RLock()


def configuration(path=CONFIG, accounting=ACCOUNTING, statuses=STATUSES):
    value = json.loads(Path(path).read_text('utf-8'))
    if value.get('activation_status') != 'W0_verified':
        raise ValueError('W0_live_contract_required')
    accounting = Path(accounting)
    safe(accounting)
    if not accounting.is_file() or accounting.stat().st_uid != os.geteuid() or accounting.stat().st_mode & 0o077:
        raise ValueError('existing_accounting_rules_required')
    raw = accounting.read_bytes()
    rules = json.loads(raw)
    if rules.get('contract') != 'channel-zero-cost-v1' or not isinstance(rules.get('testOrders'), dict):
        raise ValueError('accounting_rule_contract')
    value['verified_test_rules'] = rules['testOrders']
    value['accounting_rule_sha256'] = hashlib.sha256(raw).hexdigest()
    statuses = Path(statuses)
    safe(statuses)
    if statuses.exists():
        if statuses.stat().st_uid != os.geteuid() or statuses.stat().st_mode & 0o077:
            raise ValueError('private_source_status_permissions')
        raw = statuses.read_bytes(); reviewed = json.loads(raw)
        if reviewed.get('contract') != 'fs-users-reviewed-order-status-v1' or not isinstance(reviewed.get('statuses'),dict):
            raise ValueError('reviewed_status_contract')
        for code, proof in reviewed['statuses'].items():
            if (not code.isdigit() or not 0 < int(code) < 10000 or not isinstance(proof,dict)
                    or proof.get('classification') != 'existing_payment_projection_unchanged'
                    or not isinstance(proof.get('label'),str) or not proof['label'] or len(proof['label']) > 120
                    or type(proof.get('observed_rows')) is not int or proof['observed_rows'] <= 0
                    or len(proof.get('source_sha256','')) != 64):
                raise ValueError('reviewed_status_evidence_required')
        value['known_order_statuses'] = sorted(set(value['known_order_statuses']) | set(reviewed['statuses']))
        value['source_status_rule_sha256'] = hashlib.sha256(raw).hexdigest()
    value['update_cadence'] = 'daily-v1'
    value.setdefault('snapshot_storage', 'recipe-v1')
    return value


def load_store(root=ROOT, config=None, *, initialize=False):
    root = Path(root)
    safe(root)
    # Boot/query/weekly runs must not bootstrap replacement facts after data loss.
    # Initial provisioning is explicit and is not exposed through HTTP or Hermes.
    if not initialize:
        require_database(root / 'customers.sqlite3')
    import fcntl
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    if root.stat().st_uid != os.geteuid() or root.stat().st_mode & 0o077:
        raise ValueError('private_directory_permissions')
    key_path = root / 'identity.key'
    safe(key_path)
    with (root / 'init.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not key_path.exists():
            if not initialize:
                raise ValueError('existing_identity_key_missing')
            if (root / 'customers.sqlite3').exists():
                raise ValueError('existing_identity_key_missing')
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(os.urandom(32)); output.flush(); os.fsync(output.fileno())
        if key_path.stat().st_uid != os.geteuid() or key_path.stat().st_mode & 0o077 or key_path.stat().st_size != 32:
            raise ValueError('private_identity_key_permissions')
        key = key_path.read_bytes()
        return Store(root, key, configuration() if config is None else config, create=initialize)


def authorize(user, query, private=False, *, resource='/dashboard/users/'):
    if not isinstance(user, str) or not user:
        return False
    if resource not in ('/dashboard/users/','/dashboard/analytics/','/dashboard/data-tools/'):
        return False
    sys.path.insert(0, '/opt/fs-access-policy')
    import rbac
    if not Path(rbac.LIVE_POLICY).is_file():
        return False
    policy = rbac.load_policy()
    if rbac.authorize(policy, user, 'GET', resource) != 200:
        return False
    return rbac.is_admin(policy, user) if private else True


def build():
    global _service
    from user_query import Service
    with _lock:
        if _service is None:
            from user_customer_types import read_flags
            _service = Service(load_store(), authorize, customer_type_reader=read_flags)
        return _service
