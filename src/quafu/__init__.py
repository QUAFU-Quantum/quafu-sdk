# -*- coding: utf-8 -*-
"""QUAFU 量子计算平台的 Python SDK（发行名 quafu-sdk）。

    import quafu
    job = quafu.submit(qasm, target='sim')     # 第一次用时打印登录链接，在浏览器里登录即可
    print(job.result().counts)

    quafu.login() / quafu.logout() / quafu.whoami()
    quafu.devices()                            # 能交到哪些目标
    quafu.job('任务组号')                      # 接回之前交的任务组
    quafu.sweep(template, parameters, points, target)   # 扫参：平台按参数点代入模板
    quafu.open_job(target, ...)                # 迭代式任务组：append / wait / table / close
    quafu.device('Dongling').calibration()     # 设备详情与校准数据；quafu.calibration(id)
    quafu.stats()                              # 本人用量与额度（北京时间 23:00 重置）
    quafu.publish(task_id) / quafu.unpublish(task_id)   # 把自己已完成的一条任务设为公开 / 取消公开
    quafu.public_task('公开 ID 或分享链接')    # 看别人公开的任务：结果与所有者看到的一致，.verify() 本机核对指纹
    quafu.Client(api_key='qf_…')               # 显式身份
    from quafu.qiskit import QuafuProvider, sweep   # Qiskit 后端适配与参数化线路扫参（需要 qiskit）

运行时只用标准库；Qiskit 线路作为输入时需要 pip install "quafu-sdk[qiskit]"。"""
import os as _os
import sys as _sys

from ._conflict import ConflictError, check as _check_conflict

try:
    _check_conflict(_os.path.dirname(_os.path.abspath(__file__)))
except ConflictError as _e:
    # 命令行 quafu 也要先 import 本包：那里报一句话、退出码 1，不甩 Python 栈
    if _os.path.basename(_sys.argv[0] if _sys.argv else '').lower() in ('quafu', 'quafu.exe'):
        from ._i18n import safe_streams as _safe_streams, t as _t
        _safe_streams()
        _sys.stderr.write(_t('cli.error', _e) + '\n')
        raise SystemExit(1)
    raise

__version__ = '0.2.7'

from ._i18n import get_language, set_language  # noqa: E402

from .config import DEFAULT_BASE_URL  # noqa: E402
from .errors import (QuafuError, AuthError, NotLoggedIn, LoginFailed, LoginExpired, LoginRevoked,  # noqa: E402
                     CredentialsError, BadRequest, PrecheckError, QuotaError, DeviceUnavailable, JobFailed,
                     JobCancelled, JobNotFound, JobClosed, TaskNotFound, ServerUnavailable, SubmitUncertain,
                     ProtocolError, ClientOutdated, Timeout, PublicTaskNotFound, NotPublishable)
from .jobs import Job, Result, Publication, PublicTask  # noqa: E402
from .tables import ResultTable  # noqa: E402
from .devices import Device, Calibration  # noqa: E402
from .bits import reorder_counts, counts_by_qubit, probabilities, expectation_z  # noqa: E402
from .client import (Client, login, logout, whoami, submit, sweep, open_job, job, devices, device,  # noqa: E402
                     calibration, stats, publish, unpublish, public_task)

__all__ = [
    '__version__', 'DEFAULT_BASE_URL', 'set_language', 'get_language',
    'login', 'logout', 'whoami', 'submit', 'sweep', 'open_job', 'job', 'devices', 'device', 'calibration', 'stats',
    'publish', 'unpublish', 'public_task',
    'Client', 'Job', 'Result', 'ResultTable', 'Device', 'Calibration', 'Publication', 'PublicTask',
    'reorder_counts', 'counts_by_qubit', 'probabilities', 'expectation_z',
    'QuafuError', 'AuthError', 'NotLoggedIn', 'LoginFailed', 'LoginExpired', 'LoginRevoked', 'CredentialsError',
    'BadRequest', 'PrecheckError', 'QuotaError', 'DeviceUnavailable', 'JobFailed', 'JobCancelled', 'JobNotFound', 'JobClosed',
    'TaskNotFound', 'ServerUnavailable', 'SubmitUncertain', 'ProtocolError', 'ClientOutdated', 'Timeout',
    'PublicTaskNotFound', 'NotPublishable',
    'ConflictError',
]
