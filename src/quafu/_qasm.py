# -*- coding: utf-8 -*-
"""线路输入 → OpenQASM 2.0 文本。

收两种：OpenQASM 2.0 字符串（原样交给平台），或 qiskit 的 QuantumCircuit（用 qiskit.qasm2 导出）。
核心包不 import qiskit：只有调用方传进来的就是 qiskit 对象时（此时 qiskit 必然已经装好、已经加载）才用它。
这里不判线路合不合规（由平台判）；提交前只按目标公开的 limits 查比特数（见 _limits）。"""
import logging
import sys

from ._i18n import t

log = logging.getLogger('quafu')
INSTALL_HINT = 'pip install "quafu-sdk[qiskit]"'


def is_qiskit_circuit(obj):
    """不 import qiskit 就能判断：qiskit 没加载过，obj 就不可能是它的线路。"""
    if 'qiskit' not in sys.modules:
        return False
    try:
        from qiskit import QuantumCircuit
    except ImportError:
        return False
    return isinstance(obj, QuantumCircuit)


def to_qasm(circuit, where=None):
    where = where or t('client.where_circuit')
    if isinstance(circuit, str):
        if not circuit.strip():
            raise ValueError(t('qasm.empty', where))
        return circuit
    if is_qiskit_circuit(circuit):
        return qiskit_to_qasm(circuit)
    raise TypeError(t('qasm.type', where, type(circuit).__name__, INSTALL_HINT))


def qiskit_to_qasm(qc):
    """导出 OpenQASM 2（qasm2.dumps）。真机要求 measure 语句按经典位升序出现，所以线路末尾那段
    连续的 measure 若两两作用在不同比特、写入不同经典位，就按经典位下标升序输出：它们彼此对易，重排不改变结果，
    语句顺序只是序列化方式。有比特或经典位重复时原样导出，由平台判（重复测量等照样会被拒）。
    别处的 measure 不动；没被写入的经典位也不补——补了就改了线路的意思。
    带未绑定参数的线路导出时会被 qiskit 拒绝：先 assign_parameters 再交。"""
    from qiskit import qasm2
    data = list(qc.data)
    k = len(data)
    while k and data[k - 1].operation.name == 'measure':
        k -= 1
    tail = data[k:]
    qubits = {qc.find_bit(ci.qubits[0]).index for ci in tail}
    clbits = {qc.find_bit(ci.clbits[0]).index for ci in tail}
    ordered = sorted(tail, key=lambda ci: qc.find_bit(ci.clbits[0]).index)
    if len(qubits) == len(clbits) == len(tail) and any(a is not b for a, b in zip(ordered, tail)):
        out = qc.copy_empty_like()
        for ci in data[:k] + ordered:
            out.append(ci.operation, ci.qubits, ci.clbits)
        qc = out
        log.debug('exported terminal measurements in ascending clbit order')
    return qasm2.dumps(qc)
