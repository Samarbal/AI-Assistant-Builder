"""An approved function is not a general exemption for public functions."""
import importlib.util
from pathlib import Path
from unittest.mock import MagicMock

import pytest

path = Path(__file__).resolve().parents[1] / 'scripts/phase1_baseline.py'
spec = importlib.util.spec_from_file_location('reviewed_baseline', path)
baseline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(baseline)


def records():
    return ([dict(oid=1, proname='rls_auto_enable', owner='postgres', prosecdef=True,
                  proconfig=['search_path=pg_catalog'], definition=baseline.REVIEWED_DEFINITION)],
            [dict(evtname='ensure_rls', evtevent='ddl_command_end', evtenabled='O',
                  owner='postgres', evttags=['CREATE TABLE','CREATE TABLE AS','SELECT INTO'])])


def connection(functions, triggers):
    conn = MagicMock()
    first, second = MagicMock(), MagicMock()
    first.mappings.return_value.all.return_value = functions
    second.mappings.return_value.all.return_value = triggers
    conn.execute.side_effect = [first, second]
    return conn


def test_exact_baseline_is_accepted():
    baseline.verify_baseline(connection(*records()))


@pytest.mark.parametrize('change', ['body','owner','search_path','security_definer','extra_function','trigger_status','trigger_events'])
def test_baseline_drift_stops_deployment(change):
    functions, triggers = records()
    if change == 'body': functions[0]['definition'] += '\n-- unreviewed change'
    elif change == 'owner': functions[0]['owner'] = 'another_role'
    elif change == 'search_path': functions[0]['proconfig'] = ['search_path=public']
    elif change == 'security_definer': functions[0]['prosecdef'] = False
    elif change == 'extra_function': functions.append(dict(functions[0]))
    elif change == 'trigger_status': triggers[0]['evtenabled'] = 'D'
    elif change == 'trigger_events': triggers[0]['evttags'].append('ALTER TABLE')
    with pytest.raises(RuntimeError):
        baseline.verify_baseline(connection(functions, triggers))
