# -*- coding: utf-8 -*-
"""计数的位序工具：按指定经典位或物理比特重排、取边缘分布、算概率与 Z 串期望值。纯函数，只用标准库。

每份结果都声明位序 bit_order（目前全平台是 'c0_rightmost'：键的最右一位是 c[0]）与键长 n_clbits；
经典位 → 物理比特的对应在 measurements（[{cbit, physical_qubit, virtual_qubit}]），它是解释 counts 的唯一依据。
契约保证键恰好 n_clbits 位、只含 0 和 1、不含空格；不合规的键直接报错，不静默修正。
这里的函数都要求显式传入 bit_order，不靠默认去猜；counts 为 None（没结果的点）时原样返回 None。"""

from ._i18n import t

C0_RIGHTMOST = 'c0_rightmost'
ORDER_WORDS = ('c0_leftmost', 'c0_rightmost')
_BITS = frozenset('01')


def _check_key(key, n_clbits=None):
    if not isinstance(key, str) or not key or not set(key) <= _BITS:
        raise ValueError(t('bits.bad_key', key))
    if n_clbits is not None and len(key) != n_clbits:
        raise ValueError(t('bits.key_length', key, len(key), n_clbits))


def _position(bit_order, width, cbit):
    """经典位 cbit 在长 width 的键里的下标。"""
    if bit_order != C0_RIGHTMOST:
        raise ValueError(t('bits.unknown_order', bit_order, C0_RIGHTMOST))
    if not 0 <= cbit < width:
        raise ValueError(t('bits.cbit_range', cbit, width))
    return width - 1 - cbit


def _cbits(order, width):
    if order == 'c0_leftmost':
        return list(range(width))
    if order == 'c0_rightmost':
        return list(range(width - 1, -1, -1))
    if isinstance(order, str):
        raise ValueError(t('bits.order_type', ' / '.join(ORDER_WORDS)))
    return [int(c) for c in order]


def reorder_counts(counts, order, bit_order, n_clbits=None):
    """把 counts 的键改写成「从左到右依次是 order 里的经典位」。

    order：经典位下标列表（只列一部分就是边缘分布，映射到同一个新键的计数相加），或 'c0_leftmost' / 'c0_rightmost'。
    n_clbits 给了就核对每个键的长度，对不上抛 ValueError。"""
    if counts is None:
        return None
    out = {}
    for key, n in counts.items():
        _check_key(key, n_clbits)
        new = ''.join(key[_position(bit_order, len(key), c)] for c in _cbits(order, len(key)))
        out[new] = out.get(new, 0) + n
    return out


def cbits_of_qubits(measurements, qubits):
    """物理比特 → 测到它的经典位。没被测量的比特抛 ValueError。"""
    table = {m['physical_qubit']: m['cbit'] for m in measurements}
    missing = [q for q in qubits if q not in table]
    if missing:
        raise ValueError(t('bits.not_measured', missing))
    return [table[q] for q in qubits]


def counts_by_qubit(counts, measurements, qubits, bit_order, n_clbits=None):
    """键从左到右依次是 qubits 里各物理比特的测量值（经 measurements 找到各自的经典位）。"""
    return reorder_counts(counts, cbits_of_qubits(measurements, qubits), bit_order, n_clbits)


def probabilities(counts):
    """counts / Σcounts（归一化用实际纳入的次数 shots_returned，不用请求数）。"""
    if counts is None:
        return None
    total = sum(counts.values())
    if total <= 0:
        raise ValueError(t('bits.zero_total_norm'))
    return {k: v / total for k, v in counts.items()}


def expectation_z(counts, cbits, bit_order):
    """Z 串期望值 <Z_S> = Σ_x p(x)·(−1)^(x 在经典位 S 上的奇偶)。只对原始 counts 成立，不给不确定度。"""
    if counts is None:
        return None
    total = acc = 0
    for key, n in counts.items():
        _check_key(key)
        parity = sum(int(key[_position(bit_order, len(key), c)]) for c in cbits) % 2
        acc += -n if parity else n
        total += n
    if total <= 0:
        raise ValueError(t('bits.zero_total_exp'))
    return acc / total
