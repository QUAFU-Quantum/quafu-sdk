# -*- coding: utf-8 -*-
"""任务组句柄与结果。

    job = quafu.submit(bell, target='sim')       # 交上去，立刻返回
    job.id                                       # 任务组号：进程崩了也能 quafu.job(号) 接回
    job.status()                                 # Queued / Running / Finished / PartiallyFinished / Failed / Cancelled
    r = job.result()                             # 只交了一条线路时：等到结束，返回 Result
    rs = job.results()                           # 交了一组时：按交的顺序对齐的 Result 列表
    job.cancel()
    job.table()                                  # 列式表格（扫参、迭代按参数点对齐），可转 pandas

    job = quafu.open_job('sim', ...)             # 迭代式任务组：看了结果再决定下一轮交什么
    job.append(points=[[0.1]], iteration=0); job.wait(); job.table(); ...; job.close()

一个任务组里每条线路是一个任务（task），任务号是「任务组号-序号」，序号从 0 起、就是交线路的顺序。"""
import logging
import time
import uuid
from urllib.parse import quote, urlencode

from . import bits
from ._i18n import t
from .errors import JobCancelled, JobFailed, Timeout, failure_note

log = logging.getLogger('quafu')

JOB_TERMINAL = ('Finished', 'PartiallyFinished', 'Failed', 'Cancelled')
TASK_TERMINAL = ('Finished', 'Failed', 'Cancelled')
POLL_FIRST, POLL_FIRST_FOR = 1.0, 60.0         # 第一分钟每秒一次：模拟器任务多在这期间完成
POLL_MID, POLL_SLOW_AFTER = 5.0, 600.0          # 之后每 5 秒；满 10 分钟后每 30 秒（真机排队以小时计）
POLL_SLOW = 30.0
REPORT_EVERY = 300.0                            # 每 5 分钟 logging.info 一次进展
DETAIL_INCLUDE = 'counts,executed'


def poll_interval(elapsed):
    if elapsed < POLL_FIRST_FOR:
        return POLL_FIRST
    if elapsed < POLL_SLOW_AFTER:
        return POLL_MID
    return POLL_SLOW


class Result(object):
    """任务组里一条线路的结果。平台没给的字段为 None，SDK 不猜。

    status              这一条的状态：Finished / Failed / Cancelled（没到终态时是 Queued / Running）
    ok                  status == 'Finished'
    counts              原始计数 {比特串: 次数}；没成功时为 None。键恰好 n_clbits 位、只含 0 和 1
    bit_order           位序声明：'c0_rightmost' = 比特串最右一位是经典位 c[0]
    n_clbits            经典位个数
    shots_requested     请求的次数；shots_returned 实际纳入的次数（= counts 之和，归一化用它）
    measurements        [{cbit, physical_qubit, virtual_qubit}]：经典位测的是哪个物理比特，解释 counts 的依据
    executed_qasm       实际上机（或上模拟器）的线路文本
    compiler            平台回显用了什么编译：{name, version, optimization_level, seed}
    calibration_id      这次运行用的校准数据标识（理想模拟为 None）
    target / backend    交的目标 / 实际执行的后端（真机是落到的那台）
    error               没成功时的原因 {category, stage, retryable, detail, vars}，成功时为 None
    parameter_values    这一条的参数值 {参数名: 值}（扫参、迭代、带参数的线路集合），没有参数为 None
    name / iteration / evaluation_index   线路名、第几轮、这一轮第几次评估（迭代式任务组用）
    task_id             任务号；raw 是平台给的这条任务的详情原样

    按比特取数：r.reorder([1, 0])、r.reorder('c0_leftmost')、r.counts_by_qubit([108, 109])、r.expectation_z([0, 1])"""

    def __init__(self, detail):
        d = detail or {}
        result = d.get('result') or {}
        circuit = d.get('circuit') or {}
        executed = circuit.get('executed') or {}
        execution = d.get('execution') or {}
        self.raw = d
        self.task_id = d.get('task_id')
        self.status = d.get('status')
        self.target = d.get('target')
        self.chip = d.get('chip')
        self.backend = self.chip if d.get('kind') == 'real' and self.chip else self.target
        finished = self.status == 'Finished'
        self.counts = dict(result['counts']) if finished and isinstance(result.get('counts'), dict) else None
        self.bit_order = result.get('bit_order')
        self.n_clbits = result.get('n_clbits')
        self.classical_registers = result.get('classical_registers')
        self.shots_requested = execution.get('shots_requested')
        returned = result.get('shots_returned', execution.get('shots_returned'))
        if returned is None and self.counts is not None:
            returned = sum(self.counts.values())
        self.shots_returned = returned
        self.measurements = circuit.get('measurements')
        self.executed_qasm = executed.get('text')
        self.compiler = execution.get('compiler')
        self.calibration_id = (d.get('calibration') or {}).get('id')
        err = d.get('error')
        self.error = err if self.status == 'Failed' and isinstance(err, dict) else None
        job = d.get('job') or {}
        self.seq = job.get('seq')
        self.parameter_values = job.get('parameter_values') or None
        self.name = d.get('name') or None
        self.iteration = d.get('iteration', job.get('iteration'))
        self.evaluation_index = job.get('evaluation_index')

    @property
    def ok(self):
        return self.status == 'Finished'

    def __repr__(self):
        if self.ok:
            return 'Result(task_id=%r, backend=%r, shots_returned=%r, counts=%r)' % (
                self.task_id, self.backend, self.shots_returned, self.counts)
        return 'Result(task_id=%r, status=%r, error=%r)' % (
            self.task_id, self.status, (self.error or {}).get('category'))

    def probabilities(self):
        """{比特串: 概率}，按实际纳入的次数归一；没成功时为 None。"""
        return bits.probabilities(self.counts)

    def _bit_order(self):
        if self.bit_order is None:
            raise ValueError(t('jobs.no_bit_order'))
        return self.bit_order

    def reorder(self, order):
        """键从左到右依次是 order 里的经典位（只列一部分即边缘分布）；也可写 'c0_leftmost' / 'c0_rightmost'。"""
        if self.counts is None:
            return None
        return bits.reorder_counts(self.counts, order, self._bit_order(), self.n_clbits)

    def counts_by_qubit(self, qubits):
        """键从左到右依次是 qubits 里各物理比特的测量值（按 measurements 找到各自的经典位）。"""
        if self.counts is None:
            return None
        if not self.measurements:
            raise ValueError(t('jobs.no_measurements'))
        return bits.counts_by_qubit(self.counts, self.measurements, qubits, self._bit_order(), self.n_clbits)

    def expectation_z(self, cbits):
        """经典位 cbits 上的 Z 串期望值 <Z…Z>，只从原始 counts 算，不给不确定度。"""
        if self.counts is None:
            return None
        return bits.expectation_z(self.counts, cbits, self._bit_order())


def failure(result, job_id):
    """一条没成功的结果 → 要抛的异常。"""
    if result.status == 'Cancelled':
        return JobCancelled(t('jobs.cancelled', result.task_id), job_id=job_id, body=result.raw)
    err = result.error or {}
    cat, detail = err.get('category'), err.get('detail')
    retry = {True: 'jobs.retry_yes', False: 'jobs.retry_no'}.get(err.get('retryable'))
    vars_ = err.get('vars') if isinstance(err.get('vars'), dict) else None
    msg = t('jobs.failed', result.task_id, cat, detail or '', failure_note(cat, vars_),
            t('errors.paren', t(retry)) if retry else '')
    return JobFailed(msg, job_id=job_id, task_id=result.task_id, category=cat, detail=detail,
                     error_stage=err.get('stage'), retryable=err.get('retryable'), vars=vars_, body=result.raw)


class Job(object):
    """平台上的一个任务组。n_tasks 是它目前有几条线路；open 为真表示是还能追加的迭代式任务组。"""

    def __init__(self, client, job_id, n_tasks=None, status=None, open=None, target=None):
        self.client = client
        self.target = target            # 提交时的目标；按任务组号取回的句柄不知道，为 None
        self.id = str(job_id)
        self.n_tasks = n_tasks
        self.open = open
        self._status = status
        self._done = {}                 # seq → 已到终态的 Result（终态不再变，取过就不再取）

    def __repr__(self):
        return 'Job(id=%r, n_tasks=%r, status=%r%s)' % (self.id, self.n_tasks, self._status,
                                                       ', open=True' if self.open else '')

    def _path(self, tail=''):
        return '/jobs/%s%s' % (quote(self.id, safe=''), tail)

    def _get(self, tail='', **kw):
        return self.client._request('GET', self._path(tail), endpoint='job', job_id=self.id, **kw)

    def _refresh(self, deadline=None):
        d = self._get('/status', deadline=deadline)
        self._status = d.get('status')
        if 'open' in d:
            self.open = bool(d.get('open'))
        total = (d.get('counts') or {}).get('total')
        if total is not None:
            self.n_tasks = total
        return d

    def status(self):
        """现查一次任务组状态：Queued / Running / Finished / PartiallyFinished（有成功、其余失败或取消）/
        Failed / Cancelled。"""
        return self._refresh().get('status')

    def wait(self, timeout=None):
        """等到任务组结束，返回最终状态；部分或全部失败不抛异常（各条的原因看 results()）。
        迭代式任务组（open）等到「当前没有排队或运行中的任务」就返回，供每一轮调用。
        timeout 秒内没结束抛 Timeout，任务组仍在平台上，可以再等。Ctrl-C 只停止等待、不取消任务组。"""
        start = time.monotonic()
        deadline = None if timeout is None else start + timeout
        next_report = start + REPORT_EVERY
        try:
            while True:
                try:
                    d = self._refresh(deadline)
                except Timeout:
                    raise self._timeout(timeout) from None
                if self._status in JOB_TERMINAL:
                    return self._status
                c = d.get('counts') or {}
                if self.open and not (c.get('queued') or 0) + (c.get('running') or 0):
                    return self._status
                now = time.monotonic()
                if deadline is not None and now >= deadline:
                    raise self._timeout(timeout)
                if now >= next_report:
                    c = d.get('counts') or {}
                    log.info(t('jobs.progress'), self.id, (now - start) // 60,
                             self._status, c.get('finished'), c.get('total'))
                    next_report += REPORT_EVERY
                interval = poll_interval(now - start)
                if deadline is not None:
                    interval = max(0.0, min(interval, deadline - now))
                time.sleep(interval)
        except KeyboardInterrupt:
            log.warning(t('jobs.stopped'), self.id, self.id)
            raise

    def _timeout(self, timeout):
        return Timeout(t('jobs.timeout', timeout, self.id, self._status or t('jobs.status_unknown')), job_id=self.id)

    def results(self, timeout=None):
        """等到任务组结束，返回 Result 列表，顺序就是交线路的顺序。没成功的那几条 counts 为 None、
        status 与 error 说明原因，不抛异常。"""
        settled = self._status in JOB_TERMINAL and not self.open and self.n_tasks is not None
        if not (settled and len(self._done) == self.n_tasks):        # 全部取过且任务组已结束：不再问平台
            self.wait(timeout)
        if self.n_tasks is None:
            self._refresh()
        out = []
        for seq in range(self.n_tasks or 0):
            r = self._done.get(seq)
            if r is None:
                d = self.client._request('GET', self._path('/tasks/%d?include=%s' % (seq, DETAIL_INCLUDE)),
                                         endpoint='task', task_id='%s-%d' % (self.id, seq), job_id=self.id)
                r = Result(d)
                if r.status in TASK_TERMINAL:
                    self._done[seq] = r
            out.append(r)
        return out

    def result(self, timeout=None):
        """只交了一条线路时用：等到结束，返回它的 Result。失败抛 JobFailed，被取消抛 JobCancelled，
        timeout 秒内没结束抛 Timeout。交了多条线路时请用 results()。"""
        if self.n_tasks is None:
            self._refresh()
        if self.n_tasks != 1:
            raise ValueError(t('jobs.result_single', self.id, self.n_tasks))
        r = self.results(timeout)[0]
        if not r.ok:
            raise failure(r, self.id)
        return r

    def table(self, timeout=None, wait=True):
        """列式结果表（ResultTable）：按提交顺序逐行对齐，参数值、计数、状态各一列，一次取一页、自动翻完。
        扫参与迭代用它最方便；可 to_pandas()。wait=True（默认）先等到结束；wait=False 立即返回当前快照，
        没到终态的行 counts 为 None——开着的迭代式任务组边跑边看就用它。"""
        from .tables import RESULT_COLUMNS, RESULT_PAGE, ResultTable
        if wait:
            self.wait(timeout)
        merged, offset = None, 0
        while True:
            page = self._get('/results?' + urlencode({'offset': offset, 'limit': RESULT_PAGE, 'fields': 'counts'}))
            n = len(page.get('seq') or [])
            cols = {col: list(page.get(col) or [None] * n) for col in RESULT_COLUMNS}
            if merged is None:
                merged = dict(page, **cols)
            else:
                for col in RESULT_COLUMNS:
                    merged[col].extend(cols[col])
            offset += n
            if n == 0 or offset >= (page.get('total') or 0):
                return ResultTable(merged)

    def append(self, circuits=None, points=None, iteration=None, evaluation_index=None):
        """向迭代式任务组追加一批任务，返回新任务的任务号列表。circuits 与 points 二选一：

        points    按任务组的模板代入的参数点（开任务组时给了 template 与 parameters 才能用）
        circuits  OpenQASM 2.0 文本、qiskit.QuantumCircuit，或 {"qasm", "shots", "name", "parameter_values",
                  "metadata"}；带 parameter_values 时开任务组要声明 parameters
        iteration 第几轮、evaluation_index 这一轮第几次评估，作用于这一批（线路项自己写了的除外）。
        自带幂等键：回应丢失时同键重放，不会重复追加。已关闭或不是迭代式时抛 JobClosed。
        由本进程开的任务组（知道目标）追加线路时，先按目标的 limits 在本地查比特数与 shots。"""
        from ._inputs import index, normalize_circuit, normalize_points
        if (circuits is None) == (points is None):
            raise TypeError(t('jobs.circuits_or_points'))
        if points is not None:
            body = {'points': normalize_points(points)}
            if iteration is not None:
                body['iteration'] = index(iteration, 'iteration')
            if evaluation_index is not None:
                body['evaluation_index'] = index(evaluation_index, 'evaluation_index')
        else:
            body = {'circuits': [normalize_circuit(c, iteration, evaluation_index) for c in circuits]}
            if self.target:
                from . import _limits
                _limits.check(self.client, self.target, circuits=body['circuits'])
        body['client_ref'] = str(uuid.uuid4())
        from .client import SUBMIT_READ_TIMEOUT
        d = self.client._request('POST', self._path('/tasks'), body=body, endpoint='job', job_id=self.id,
                                 read_timeout=SUBMIT_READ_TIMEOUT, retry='read')
        tids = list(d.get('task_ids') or [])
        seqs = [int(t.rsplit('-', 1)[1]) for t in tids if t.rsplit('-', 1)[-1].isdigit()]
        if seqs:
            self.n_tasks = max(self.n_tasks or 0, max(seqs) + 1)
        return tids

    def close(self):
        """关闭迭代式任务组：之后不能再追加，已有任务照常运行；已关闭再关无副作用。"""
        d = self.client._request('POST', self._path('/close'), endpoint='job', job_id=self.id)
        self.open, self._status = d.get('open'), d.get('status')
        return d

    def cancel(self):
        """取消任务组里还能取消的任务，返回平台的回应：cancelled_now（还在平台队列里、直接取消的条数）、
        cancel_requested（已发到设备、只能不再等的条数，额度不退）、status。正在取回结果的任务照常出结果。"""
        d = self.client._request('POST', self._path('/cancel'), endpoint='job', job_id=self.id)
        self._status = d.get('status')
        if 'open' in d:
            self.open = d.get('open')
        return d
