"""Publish the two FS reviewed-skill helpers through the original learning publisher."""
import hashlib
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
LEARNING_SCOPE_SHA = '88d9a96f20b14324c27d75d688d5ffdf3030fa2dc030219a23df4cd54d5b55de'
TARGETS = {
    'approval/reviewed_skills.py': '/opt/fs-hermes-memory-approval/reviewed_skills.py',
    'runtime/reviewed_skills.py': '/opt/fs-hermes-fc/reviewed_skills.py',
}


def targets(manifest):
    rows = manifest.get('files', [])
    if (len(rows) != len(TARGETS)
            or {row['candidate']: row['target'] for row in rows} != TARGETS
            or manifest.get('businessWrites') is not False or manifest.get('timersChanged') is not False
            or any(not row.get('beforeSha256') for row in rows)
            or len({row.get('sha256') for row in rows}) != 1):
        raise ValueError('learning_exact_reviewed_skill_isolation_targets')
    return dict(TARGETS)


def load_base():
    original = HERE / 'release_learning_base.py'
    if hashlib.sha256(original.read_bytes()).hexdigest() != LEARNING_SCOPE_SHA:
        raise ValueError('original_learning_publisher_drift')
    spec = importlib.util.spec_from_file_location('original_learning_scope', original)
    publisher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(publisher)
    publisher.HERE = HERE
    publisher.targets = targets
    publisher.RUNTIME = TARGETS
    publisher.NEW_RUNTIME = frozenset()
    return publisher.load_base()


if __name__ == '__main__':
    load_base().main()
