# -*- coding: utf-8 -*-
"""位序工具：重排、边缘分布、按物理比特取、概率、Z 串期望值。位序必须显式给。"""
import pytest

from quafu import bits

COUNTS = {'001': 50, '110': 30, '111': 20}     # 最右一位是 c[0]
MEAS = [{'cbit': 0, 'physical_qubit': 108, 'virtual_qubit': 108},
        {'cbit': 1, 'physical_qubit': 109, 'virtual_qubit': 109},
        {'cbit': 2, 'physical_qubit': 7, 'virtual_qubit': 7}]


def test_reorder_to_c0_leftmost_reverses_each_key():
    assert bits.reorder_counts(COUNTS, 'c0_leftmost', 'c0_rightmost', 3) == {'100': 50, '011': 30, '111': 20}
    assert bits.reorder_counts(COUNTS, 'c0_rightmost', 'c0_rightmost') == COUNTS


def test_listed_order_reads_left_to_right_and_subsets_marginalize():
    assert bits.reorder_counts(COUNTS, [0], 'c0_rightmost') == {'1': 70, '0': 30}
    assert bits.reorder_counts(COUNTS, [2, 0], 'c0_rightmost') == {'01': 50, '10': 30, '11': 20}


def test_counts_by_physical_qubit_goes_through_measurements():
    assert bits.counts_by_qubit(COUNTS, MEAS, [108, 7], 'c0_rightmost') == {'10': 50, '01': 30, '11': 20}
    with pytest.raises(ValueError):
        bits.counts_by_qubit(COUNTS, MEAS, [5], 'c0_rightmost')


def test_probabilities_and_z_expectation():
    assert bits.probabilities({'0': 3, '1': 1}) == {'0': 0.75, '1': 0.25}
    assert bits.expectation_z(COUNTS, [0], 'c0_rightmost') == pytest.approx((30 - 70) / 100)
    assert bits.expectation_z(COUNTS, [1, 2], 'c0_rightmost') == pytest.approx(1.0)


def test_none_rows_pass_through():
    assert bits.reorder_counts(None, [0], 'c0_rightmost') is None
    assert bits.probabilities(None) is None and bits.expectation_z(None, [0], 'c0_rightmost') is None


def test_refuses_unknown_order_bad_width_and_out_of_range():
    with pytest.raises(ValueError):
        bits.reorder_counts(COUNTS, [0], 'c0_leftmost_maybe')
    with pytest.raises(ValueError):
        bits.reorder_counts(COUNTS, [0], 'c0_rightmost', n_clbits=4)
    with pytest.raises(ValueError):
        bits.reorder_counts(COUNTS, [3], 'c0_rightmost')
    with pytest.raises(ValueError):
        bits.reorder_counts(COUNTS, 'backwards', 'c0_rightmost')
    with pytest.raises(ValueError):
        bits.probabilities({'0': 0})


@pytest.mark.parametrize('bad', [{'1 0': 5}, {'1x': 5}, {'': 5}, {'0b1': 5}])
def test_malformed_keys_are_rejected_not_repaired(bad):
    with pytest.raises(ValueError):
        bits.reorder_counts(bad, 'c0_leftmost', 'c0_rightmost')
    with pytest.raises(ValueError):
        bits.expectation_z(bad, [0], 'c0_rightmost')
