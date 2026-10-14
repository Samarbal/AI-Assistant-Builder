"""Reject an unverified, duplicated or mismatched cleanup manifest before I/O."""
import copy
import sys
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from verify_phase2_cleanup import validate_manifest
from assistant_builder.knowledge_recovery import RecoveryBlocked


@pytest.fixture
def manifest():
    run = str(uuid4())
    assistants = {label: str(uuid4()) for label in ('A', 'B')}
    return {'run_id': run, 'status': 'verified', 'assistants': assistants,
            'assistant_names': {label: f'Phase2-live-{run}-{label}' for label in assistants},
            'files': [{'file_id': str(uuid4()), 'owner': label, 'assistant_id': assistants[label]}
                      for label in ['A'] * 6 + ['B']]}


def test_accepts_complete_manifest_without_mutating_it(manifest):
    original = copy.deepcopy(manifest)
    validate_manifest(manifest)
    assert manifest == original


@pytest.mark.parametrize('case', ['failed', 'duplicate', 'wrong_assistant', 'wrong_marker', 'missing_file'])
def test_rejects_unsafe_manifest(manifest, case):
    if case == 'failed':
        manifest['status'] = 'failed'
    elif case == 'duplicate':
        manifest['files'][1] = manifest['files'][0].copy()
    elif case == 'wrong_assistant':
        manifest['files'][0]['assistant_id'] = str(uuid4())
    elif case == 'wrong_marker':
        manifest['assistant_names']['A'] = 'Real business assistant'
    else:
        manifest['files'].pop()
    with pytest.raises(RecoveryBlocked):
        validate_manifest(manifest)
