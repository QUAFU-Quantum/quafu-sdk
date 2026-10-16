# -*- coding: utf-8 -*-
"""交给平台之前的输入规整：参数点表、参数声明、线路项。只做形状与类型检查，取值合不合规由平台判
（比特数与 shots 另在提交前按目标的 limits 查，见 _limits）。"""
import math
import operator

from ._i18n import t
from ._qasm import is_qiskit_circuit, to_qasm

CIRCUIT_KEYS = ('qasm', 'shots', 'name', 'parameter_values', 'iteration', 'evaluation_index', 'metadata')
PARAMETER_KEYS = ('name', 'unit', 'symbol')


def number(v, where):
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise TypeError(t('inputs.not_number', where, v)) from None
    except OverflowError:
        raise ValueError(t('inputs.overflow', where)) from None
    if not math.isfinite(x):
        raise ValueError(t('inputs.not_finite', where))
    return x


INDEX_MAX = 2 ** 31 - 1        # iteration / evaluation_index 的取值范围 0..2^31−1（契约 D132）


def index(v, where):
    x = operator.index(v)
    if not 0 <= x <= INDEX_MAX:
        raise ValueError(t('inputs.index_range', where, INDEX_MAX, x))
    return x


def normalize_points(points):
    """参数点表 → [[float, ...], ...]。收列表或 numpy 数组；某行是单个数时当作一个参数的点。"""
    if hasattr(points, 'tolist'):
        points = points.tolist()
    rows = []
    for i, row in enumerate(points):
        if hasattr(row, 'tolist'):
            row = row.tolist()
        if not isinstance(row, (list, tuple)):
            row = [row]
        rows.append([number(v, 'points[%d]' % i) for v in row])
    return rows


def normalize_parameters(parameters):
    """参数声明 → [{name, unit[, symbol]}]。每项写 dict 或 (name, unit[, symbol])；unit 必填，无量纲写 "1"。"""
    out = []
    for p in parameters:
        if isinstance(p, dict):
            extra = set(p) - set(PARAMETER_KEYS)
            if extra:
                raise TypeError(t('inputs.param_unknown_fields', ', '.join(sorted(extra))))
            item = {k: p[k] for k in PARAMETER_KEYS if p.get(k) is not None}
        elif isinstance(p, (tuple, list)) and 2 <= len(p) <= 3:
            item = dict(zip(PARAMETER_KEYS, p))
        else:
            raise TypeError(t('inputs.param_shape'))
        if not item.get('name') or not item.get('unit'):
            raise TypeError(t('inputs.param_required', p))
        out.append(item)
    return out


def normalize_circuit(item, iteration=None, evaluation_index=None):
    """一条线路 → 契约的 circuits 项。收 OpenQASM 2 文本或 dict；iteration / evaluation_index 只补给没写的项。"""
    if isinstance(item, str) or is_qiskit_circuit(item):
        item = {'qasm': to_qasm(item)}
    elif not isinstance(item, dict):
        raise TypeError(t('inputs.circuit_type'))
    extra = set(item) - set(CIRCUIT_KEYS)
    if extra:
        raise TypeError(t('inputs.circuit_unknown_fields', ', '.join(sorted(extra))))
    if is_qiskit_circuit(item.get('qasm')):
        item = dict(item, qasm=to_qasm(item['qasm']))
    if not isinstance(item.get('qasm'), str):
        raise TypeError(t('inputs.qasm_type'))
    out = {k: v for k, v in item.items() if v is not None}
    if 'shots' in out:
        out['shots'] = operator.index(out['shots'])
    if 'parameter_values' in out:
        out['parameter_values'] = {str(k): number(v, 'parameter_values[%r]' % k)
                                   for k, v in out['parameter_values'].items()}
    for key, value in (('iteration', iteration), ('evaluation_index', evaluation_index)):
        if value is not None:
            out.setdefault(key, value)
        if key in out:
            out[key] = index(out[key], key)
    return out
