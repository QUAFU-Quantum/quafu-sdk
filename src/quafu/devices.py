# -*- coding: utf-8 -*-
"""设备与校准快照（公开数据，不需要登录）。

    d = quafu.device('Dongling')                   # 一台设备的详情
    cal = d.calibration()                          # 该设备当前的校准数据
    cal.qubit(5)['t1_us'], cal.coupler(5, 6)['cz_fidelity']
    cal.measured_qubit(5), cal.grid                # 平台实测覆盖层、版图格子
    quafu.calibration(r.calibration_id)            # 某次运行用的那份（不可变，永久可取）

校准快照是平台自己的 schema：时间量字段名带单位（t1_us），保真度是 0..1 的小数，
未测或未填一律 None，0 只表示测得为零。qubits / couplers 只放硬件方公开值；我方实测（读出、逐对普查）
在 measured 覆盖层，值在哪一层就说明是谁测的。"""


def _by_index(items, index):
    return next((q for q in items if q.get('index') == index), None)


def _by_pair(items, a, b):
    pair = sorted((a, b))
    return next((c for c in items if sorted(c.get('qubits') or []) == pair), None)


class Device(object):
    """设备列表的一行。常用字段做成属性，其余 d['字段'] 或 d.raw 取。"""

    def __init__(self, client, row):
        self.client = client
        self.raw = dict(row)
        self.name = self.raw.get('name')
        self.status = self.raw.get('status')
        self.n_qubits = self.raw.get('n_qubits')
        self.queue = self.raw.get('queue')
        self.calibration_id = self.raw.get('calibration_id')
        self.calibration_source = self.raw.get('calibration_source')

    def __getitem__(self, key):
        return self.raw[key]

    def get(self, key, default=None):
        return self.raw.get(key, default)

    def __repr__(self):
        return 'Device(name=%r, status=%r, n_qubits=%r, calibration_id=%r)' % (
            self.name, self.status, self.n_qubits, self.calibration_id)

    def calibration(self):
        """该设备当前的校准快照（Calibration）。"""
        return self.client.device_calibration(self.name)


class Calibration(object):
    """一份校准快照。

    qubits / couplers   硬件方公开值的全芯片列表；qubit(i) / coupler(a, b) 按物理编号取一项
    measured            我方实测覆盖层原样（census_date、readout_date、qubits[]{readout_status, readout_fidelity_0/1}、
                        couplers[]{census}），没有时为 None；measured_qubit(i) / measured_coupler(a, b) 取一项
    grid                版图格子 {rows, cols}（服务端从坐标推出）
    raw                 响应原样"""

    def __init__(self, payload):
        self.raw = payload
        self.id = payload.get('id')
        self.chip = payload.get('chip')
        self.calibrated_at = payload.get('calibrated_at')
        self.source = payload.get('source')
        self.basis_gates = payload.get('basis_gates')
        self.grid = payload.get('grid')
        self.qubits = list(payload.get('qubits') or [])
        self.couplers = list(payload.get('couplers') or [])
        self.measured = payload.get('measured')

    def __repr__(self):
        return 'Calibration(id=%r, chip=%r, calibrated_at=%r, qubits=%d, couplers=%d, measured=%s)' % (
            self.id, self.chip, self.calibrated_at, len(self.qubits), len(self.couplers), self.measured is not None)

    def qubit(self, index):
        """物理比特 index 的硬件方公开值，没有返回 None。"""
        return _by_index(self.qubits, index)

    def coupler(self, a, b):
        """连接物理比特 a、b 的耦合器的硬件方公开值（不分先后），没有返回 None。"""
        return _by_pair(self.couplers, a, b)

    def measured_qubit(self, index):
        """物理比特 index 的我方实测（读出状态与读出保真度），没有返回 None。"""
        return _by_index((self.measured or {}).get('qubits') or [], index)

    def measured_coupler(self, a, b):
        """比特 a、b 之间耦合器的我方逐对普查结果，没有返回 None。"""
        return _by_pair((self.measured or {}).get('couplers') or [], a, b)
