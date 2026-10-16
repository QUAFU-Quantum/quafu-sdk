# -*- coding: utf-8 -*-
"""任务组的输入规整（quafu._inputs）与列式结果表（ResultTable），不经网络。端到端行为在 contract/test_core_contract.py。"""
import sys

import pytest

from quafu import ResultTable as JobResults
from quafu._inputs import normalize_circuit, normalize_parameters, normalize_points

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py

PAYLOAD = {
    'schema_version': '1', 'job_id': 'u7-260911-153000', 'bit_order': 'c0_rightmost',
    'parameters': [{'name': 'theta', 'unit': 'rad', 'symbol': 'θ'}, {'name': 'status', 'unit': '1'}],
    'n_clbits': [1, 2, 2], 'seq': [0, 1, 2], 'replicate_index': [0, 0, 1], 'evaluation_index': [0, 0, 0],
    'task_ids': ['u7-260911-153000-0', 'u7-260911-153000-1', 'u7-260911-153000-2'], 'points': [[0.0, 1.0], [0.5, 1.0], None], 'names': ['', '', 'x'],
    'iterations': [None, 1, 1], 'status': ['Finished', 'Failed', 'Finished'], 'shots_returned': [10, None, 4],
    'counts': [{'1': 10}, None, {'01': 3, '10': 1}],
    'errors': [None, {'category': 'runtime.deviceUnavailable', 'stage': 'dispatch', 'retryable': True}, None],
    'offset': 0, 'limit': 200, 'total': 3}


def test_points_accept_lists_scalars_and_array_likes():
    class Arr(object):
        def __init__(self, v):
            self.v = v

        def tolist(self):
            return self.v
    assert normalize_points([[0, 1], (2, 3)]) == [[0.0, 1.0], [2.0, 3.0]]
    assert normalize_points([0.5, 1]) == [[0.5], [1.0]]
    assert normalize_points(Arr([[1, 2]])) == [[1.0, 2.0]]
    with pytest.raises(ValueError):
        normalize_points([[float('nan')]])
    with pytest.raises(ValueError, match='双精度'):
        normalize_points([[10 ** 400]])
    with pytest.raises(TypeError):
        normalize_points([['a']])


def test_round_indexes_are_non_negative_int32():
    assert normalize_circuit('q', iteration=2 ** 31 - 1)['iteration'] == 2 ** 31 - 1
    for bad in (-1, 2 ** 31):
        with pytest.raises(ValueError):
            normalize_circuit('q', iteration=bad)
        with pytest.raises(ValueError):
            normalize_circuit({'qasm': 'q', 'evaluation_index': bad})


def test_parameters_require_a_unit():
    assert normalize_parameters([('theta', 'rad'), {'name': 'n', 'unit': '1', 'symbol': None}]) == [
        {'name': 'theta', 'unit': 'rad'}, {'name': 'n', 'unit': '1'}]
    assert normalize_parameters([('theta', 'rad', 'θ')]) == [{'name': 'theta', 'unit': 'rad', 'symbol': 'θ'}]
    for bad in (['theta'], [{'name': 'theta'}], [{'name': 'theta', 'unit': 'rad', 'min': 0}]):
        with pytest.raises(TypeError):
            normalize_parameters(bad)


def test_circuits_are_text_or_contract_dicts():
    assert normalize_circuit('q') == {'qasm': 'q'}
    assert normalize_circuit({'qasm': 'q', 'shots': 2048, 'parameter_values': {'θ': 1}, 'name': None}) == {
        'qasm': 'q', 'shots': 2048, 'parameter_values': {'θ': 1.0}}
    assert normalize_circuit({'qasm': 'q', 'iteration': 5}, iteration=1, evaluation_index=2) == {
        'qasm': 'q', 'iteration': 5, 'evaluation_index': 2}
    for bad in (object(), {'qasm': 'q', 'label': 'x'}, {'shots': 1}):
        with pytest.raises(TypeError):
            normalize_circuit(bad)


def test_results_are_columns_aligned_by_seq():
    res = JobResults(PAYLOAD)
    assert len(res) == 3 and res.parameter_names == ['theta', 'status'] and res.ok == [True, False, True]
    assert res.column('theta') == [0.0, 0.5, None] and res.column('task_id') == ['u7-260911-153000-0', 'u7-260911-153000-1', 'u7-260911-153000-2']
    assert res.parameter_values(1) == {'theta': 0.5, 'status': 1.0} and res.parameter_values(2) is None
    row = res.rows()[1]
    assert row['counts'] is None and row['error']['category'] == 'runtime.deviceUnavailable' and row['iteration'] == 1
    assert [r['seq'] for r in res] == [0, 1, 2]


def test_row_helpers_follow_each_rows_width():
    res = JobResults(PAYLOAD)
    assert res.reordered('c0_leftmost') == [{'1': 10}, None, {'10': 3, '01': 1}]
    assert res.expectation_z([0]) == [-1.0, None, pytest.approx((1 - 3) / 4)]
    assert res.probabilities()[2] == {'01': 0.75, '10': 0.25}


def test_to_dict_is_dataframe_ready():
    d = JobResults(PAYLOAD).to_dict()
    assert list(d)[:4] == ['seq', 'task_id', 'theta', 'param:status']
    assert d['status'] == ['Finished', 'Failed', 'Finished'] and d['param:status'] == [1.0, 1.0, None]
    assert d['error_category'] == [None, 'runtime.deviceUnavailable', None]
    assert len({len(v) for v in d.values()}) == 1


def test_to_pandas_explains_missing_dependency(monkeypatch):
    monkeypatch.setitem(sys.modules, 'pandas', None)
    with pytest.raises(ImportError) as e:
        JobResults(PAYLOAD).to_pandas()
    assert 'pip install pandas' in str(e.value)


def test_missing_bit_order_refuses_reordering():
    res = JobResults(dict(PAYLOAD, bit_order=None))
    with pytest.raises(ValueError):
        res.reordered([0])
