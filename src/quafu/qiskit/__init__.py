# -*- coding: utf-8 -*-
"""Qiskit 适配（需要 pip install "quafu-sdk[qiskit]"）：把 QUAFU 当 Qiskit 后端用，以及参数化线路的扫参。

    from quafu.qiskit import QuafuProvider
    be = QuafuProvider().get_backend('sim')         # 'sim' / '<真机名>-sim' / '<真机名>-sim-jiuding' / '<真机名>'
    job = be.run(transpile(qc, be), shots=1024)
    job.result().get_counts()

    from quafu.qiskit import sweep
    job = sweep(qc, points, 'sim')                  # 带未绑定 Parameter 的线路：本地逐点代入，作为一个任务组提交
    job.table().column('theta')

只消费 quafu.Client 与任务组句柄，不碰 HTTP 与凭证；登录与平台地址同 quafu 顶层。
线路合不合规由平台判，不合规在提交时抛 PrecheckError；比特数与 shots 超出目标 limits 的，提交前在本地就抛
（与 quafu.submit 同一套检查，上限读平台的 metadata，不在这里写数字）。导出 QASM 时只做一件规整：
末尾连续的 measure 按经典位升序排（真机要求）。
Target 从平台的后端描述装；平台还没给拓扑（coupling_map 为空）时按全连通装并 warning 一次。"""
try:
    import qiskit  # noqa: F401  缺 qiskit 时在这里给安装提示
    from qiskit.circuit.library.standard_gates import get_standard_gate_name_mapping
    from qiskit.providers import BackendV2, JobStatus, JobV1, Options
    from qiskit.result import Result
    from qiskit.transpiler import CouplingMap, Target
except ImportError:
    from .._i18n import t as _t
    raise ImportError(_t('qiskit.need_qiskit')) from None

import logging

from .._i18n import t
from .._inputs import normalize_points
from .._qasm import qiskit_to_qasm
from ..client import Client, warn_once
from ..errors import JobCancelled, JobFailed, QuafuError

log = logging.getLogger('quafu')

# 任务分发器的任务五态与任务组六态 → Qiskit JobStatus。部分完成算 ERROR（结果里失败的实验 success=False）；
# 认不出的非终态词一律当排队
STATUS_MAP = {'Queued': JobStatus.QUEUED, 'Running': JobStatus.RUNNING, 'Finished': JobStatus.DONE,
              'PartiallyFinished': JobStatus.ERROR, 'Failed': JobStatus.ERROR, 'Cancelled': JobStatus.CANCELLED}
# 理想模拟器 metadata 不列基础门（什么门都收），Target 按这组常用门装
SIM_BASIS = ['id', 'x', 'y', 'z', 'h', 's', 'sdg', 't', 'tdg', 'sx', 'rx', 'ry', 'rz', 'u',
             'cx', 'cz', 'swap', 'ccx', 'measure', 'reset']


def job_status(status):
    return STATUS_MAP.get(status, JobStatus.QUEUED)


def build_target(md):
    """由平台的后端 metadata 装 Target：n_qubits、basis_gates（加 measure）、coupling_map（空则全连通）。"""
    n = int(md.get('n_qubits') or 0)
    known = get_standard_gate_name_mapping()
    basis = [g for g in (md.get('basis_gates') or SIM_BASIS) if g in known]
    if 'measure' not in basis:
        basis.append('measure')
    edges = [tuple(e) for e in (md.get('coupling_map') or [])]
    # 九鼎模拟（noise 为 none 而 device 是一台真机）虽是模拟器，也按那台真机的连接图转译，缺拓扑同样要提示
    chip_graph = not md.get('simulator') or (md.get('noise') == 'none' and md.get('device') not in (None, 'sim'))
    if not edges and chip_graph and md.get('name') != 'sim':
        warn_once(('topology', md.get('name')), t('qiskit.no_topology'), md.get('name'))
    return Target.from_configuration(basis_gates=basis, num_qubits=n,
                                     coupling_map=CouplingMap(edges) if edges else None)


def to_qasm(qc):
    """导出 OpenQASM 2；末尾 measure 按经典位升序（真机要求），实现在 quafu._qasm。"""
    return qiskit_to_qasm(qc)


def bind(qc, points, names=None, unit='rad'):
    """把 qc 的未绑定参数逐点代入，返回 (parameters, circuits)，可直接交给
    quafu.submit(circuits, target, parameters=parameters) 或迭代式任务组的 job.append(circuits=circuits, iteration=k)。

    points 的列序 = qc.parameters 的顺序（Qiskit 按名字排序，ParameterVector 按下标）；可传 numpy 数组，
    只有一个参数时每行可以是单个数。参数名默认用 Qiskit 里的名字原样（theta、theta[0]、θ 都行）；
    names 按同样顺序另起名字，此时原名记进 symbol。unit 是所有参数的单位，门角度按定义是弧度。"""
    params = list(qc.parameters)
    if not params:
        raise ValueError(t('qiskit.no_params'))
    keys = [p.name for p in params] if names is None else [str(n) for n in names]
    if len(keys) != len(params):
        raise ValueError(t('qiskit.names_count', len(params), ', '.join(p.name for p in params)))
    circuits = []
    for i, row in enumerate(normalize_points(points)):
        if len(row) != len(params):
            raise ValueError(t('qiskit.point_len', i, len(row), len(params), ', '.join(keys)))
        circuits.append({'qasm': to_qasm(qc.assign_parameters(dict(zip(params, row)))),
                         'parameter_values': dict(zip(keys, row))})
    parameters = []
    for p, k in zip(params, keys):
        item = {'name': k, 'unit': unit}
        if k != p.name:
            item['symbol'] = p.name
        parameters.append(item)
    return parameters, circuits


def sweep(qc, points, target, shots=1024, compiler='qiskit', name=None, names=None, unit='rad', client=None):
    """Qiskit 参数化线路的扫参：bind() 逐点代入后作为一个任务组提交，返回任务组句柄（quafu.Job）。
    job.table() 按提交顺序给回每个点的参数值与计数，与 quafu.sweep（平台代入模板）同形。
    client 不给时按 quafu 顶层的默认身份与平台地址新建一个。"""
    parameters, circuits = bind(qc, points, names, unit)
    return (client or Client()).submit(circuits, target, shots=shots, compiler=compiler, name=name,
                                       parameters=parameters)


class QuafuProvider(object):
    """client：已有的 quafu.Client；不给就用 client_kwargs（api_key / base_url / ca_bundle / proxy）新建一个。"""

    def __init__(self, client=None, **client_kwargs):
        self.client = client if client is not None else Client(**client_kwargs)

    def backends(self, name=None):
        names = [d['name'] for d in self.client.devices()]
        return [QuafuBackend(self, x) for x in names if name is None or x == name]

    def get_backend(self, name):
        """取一个后端并当场拉一次 metadata：名字不认识在这里就报错。"""
        be = QuafuBackend(self, name)
        be.target
        return be

    backend = get_backend


class QuafuBackend(BackendV2):
    def __init__(self, provider, name):
        super().__init__(provider=provider, name=name)
        self.quafu = provider
        self._metadata = None
        self._target = None

    @property
    def backend_metadata(self):
        """平台给的后端描述原样（懒取一次）。"""
        if self._metadata is None:
            self._metadata = self.quafu.client.metadata(self.name)
        return self._metadata

    @property
    def target(self):
        if self._target is None:
            self._target = build_target(self.backend_metadata)
        return self._target

    @property
    def max_circuits(self):
        return None

    @classmethod
    def _default_options(cls):
        return Options(shots=1024)

    def run(self, run_input, **options):
        """提交线路，返回 QuafuJob。只认 shots，别的参数报错，不静默吞。
        全部线路作为一个任务组一次提交（一条是 single，多条是 collection，全有或全无）。"""
        shots = options.pop('shots', None) or self.options.shots
        if options:
            raise TypeError(t('qiskit.run_options', ', '.join(sorted(options))))
        circuits = list(run_input) if isinstance(run_input, (list, tuple)) else [run_input]
        qasms = [to_qasm(qc) for qc in circuits]
        job = self.quafu.client.submit(qasms[0] if len(qasms) == 1 else qasms, self.name, shots=shots)
        return QuafuJob(self, circuits, shots, job)


class QuafuJob(JobV1):
    """一次 run() 的全部线路：job_id 是任务组号，.job 是 quafu.Job。"""

    def __init__(self, backend, circuits, shots, job):
        super().__init__(backend, job.id)
        self.circuits, self.shots = list(circuits), shots
        self.job = job
        self._result = None

    def submit(self):
        """提交已在 backend.run() 里完成，这里什么都不做。"""

    def status(self):
        return job_status(self.job.status())

    def cancel(self):
        """取消任务组里还能取消的任务；已在取回结果或已结束的照常出结果。"""
        self.job.cancel()

    def result(self, timeout=None):
        """等全部线路结束并装成 Qiskit Result。部分失败时失败的实验 success=False（get_counts 对它报错）；
        一条都没成功时抛 JobFailed / JobCancelled。"""
        if self._result is None:
            outcomes = self._job_outcomes(timeout)
            ok = [o for o in outcomes if not isinstance(o, QuafuError)]
            if not ok:
                raise outcomes[0]
            failed = len(outcomes) - len(ok)
            self._result = Result.from_dict({
                'backend_name': self.backend().name, 'backend_version': self.backend().backend_version or '',
                'qobj_id': '', 'job_id': self.job_id(), 'success': not failed,
                # Qiskit 取失败实验的 counts 时会把这句拼进报错，不能是 None
                'status': t('qiskit.failed_count', failed, len(outcomes)) if failed else 'COMPLETED',
                'results': [_experiment(o, qc, self.shots) for o, qc in zip(outcomes, self.circuits)]})
        return self._result

    def _job_outcomes(self, timeout):
        from ..jobs import failure
        out = []
        results = self.job.results(timeout=timeout)
        for k in range(len(self.circuits)):
            r = results[k] if k < len(results) else None
            if r is None:
                out.append(JobFailed(t('qiskit.no_result', self.job.id, k), job_id=self.job.id))
            elif r.ok:
                out.append((r.counts, r.shots_returned, r.task_id, r.calibration_id))
            else:
                out.append(failure(r, self.job.id))
        return out


def _experiment(outcome, qc, shots):
    """一条线路的结果 → Qiskit 实验结果。平台的键是展平的比特串（最右是 c[0]），转成十六进制键，
    Qiskit 再按 creg_sizes 格式化回带寄存器空格的串。"""
    header = {'name': qc.name, 'memory_slots': qc.num_clbits, 'creg_sizes': [[c.name, c.size] for c in qc.cregs]}
    if isinstance(outcome, QuafuError):
        return {'shots': shots, 'success': False, 'status': str(outcome), 'data': {}, 'header': header}
    counts, returned, task_id, calibration_id = outcome
    header.update(task_id=task_id, calibration_id=calibration_id)
    return {'shots': returned, 'success': True, 'header': header,
            'data': {'counts': {hex(int(b, 2)): n for b, n in counts.items()}}}
