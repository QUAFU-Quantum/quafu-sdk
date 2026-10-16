# -*- coding: utf-8 -*-
"""任务组结果的列式表格：扫参、迭代这类「一组线路按参数点对齐」的场合用它，可直接转 pandas。

    t = job.table()
    t.column('theta'), t.counts, t.status, t.to_pandas()

平台按 seq（提交顺序）逐行对齐，含任务组内全部任务；没到终态或没成功的行 counts 为 None。"""
from . import bits
from ._i18n import t
from .jobs import TASK_TERMINAL as TERMINAL

RESULT_PAGE = 200                  # 平台每页上限
RESULT_COLUMNS = ('n_clbits', 'seq', 'replicate_index', 'evaluation_index', 'task_ids', 'points', 'names',
                  'iterations', 'status', 'shots_returned', 'counts', 'errors')


class ResultTable(object):
    """任务组的列式结果：下列列表按 seq 逐行对齐，含任务组内全部任务；没到终态或没成功的点 counts / shots_returned
    为 None、status 如实（曲线的 x 轴不塌）。

    seq、task_ids、points（每行按 parameters 的顺序，没有参数值为 None）、status、shots_returned、counts、
    n_clbits（逐行，collection 里各条线路可以不同宽）、names、iterations、evaluation_index、replicate_index、errors
    bit_order 全任务组一致放顶层；parameters 是参数声明（name、unit、symbol）。complete 为全部任务都已到终态。

    转 pandas：res.to_pandas() 或 pandas.DataFrame(res.to_dict())；转 numpy：numpy.array(res.column('theta'), dtype=float)。
    本对象不依赖这两个库。"""

    def __init__(self, payload):
        self.raw = payload
        self.job_id = payload.get('job_id')
        self.schema_version = payload.get('schema_version')
        self.parameters = list(payload.get('parameters') or [])
        self.bit_order = payload.get('bit_order')
        n = len(payload.get('seq') or [])
        for col in RESULT_COLUMNS:
            setattr(self, col, list(payload.get(col) or [None] * n))

    def __len__(self):
        return len(self.seq)

    def __repr__(self):
        return 'ResultTable(job_id=%r, rows=%d, parameters=%r)' % (self.job_id, len(self), self.parameter_names)

    @property
    def parameter_names(self):
        return [p.get('name') for p in self.parameters]

    @property
    def ok(self):
        """逐行是否成功。"""
        return [s == 'Finished' for s in self.status]

    @property
    def complete(self):
        """全部任务都已到终态（完成、失败或取消）。"""
        return all(s in TERMINAL for s in self.status)

    def parameter_values(self, i):
        point = self.points[i]
        return None if point is None else dict(zip(self.parameter_names, point))

    def column(self, name):
        """按名字取一列：参数名取该参数的值（没有参数值的行为 None），其余同属性名。"""
        names = self.parameter_names
        if name in names:
            j = names.index(name)
            return [None if p is None else p[j] for p in self.points]
        alias = {'task_id': 'task_ids', 'name': 'names', 'iteration': 'iterations', 'error': 'errors'}
        return list(getattr(self, alias.get(name, name)))

    def rows(self):
        """逐行 dict：seq、task_id、parameter_values、status、shots_returned、counts、n_clbits、name、iteration、
        evaluation_index、replicate_index、error。"""
        return [{'seq': self.seq[i], 'task_id': self.task_ids[i], 'parameter_values': self.parameter_values(i),
                 'status': self.status[i], 'shots_returned': self.shots_returned[i], 'counts': self.counts[i],
                 'n_clbits': self.n_clbits[i], 'name': self.names[i], 'iteration': self.iterations[i],
                 'evaluation_index': self.evaluation_index[i], 'replicate_index': self.replicate_index[i],
                 'error': self.errors[i]} for i in range(len(self))]

    def __iter__(self):
        return iter(self.rows())

    def _bit_order(self):
        if self.bit_order is None:
            raise ValueError(t('tables.no_bit_order'))
        return self.bit_order

    def probabilities(self):
        return [bits.probabilities(c) for c in self.counts]

    def reordered(self, order):
        """逐行按 order 重排 counts（各行按自己的 n_clbits 核对），没有 counts 的行保持 None。"""
        return [bits.reorder_counts(c, order, self._bit_order(), n) for c, n in zip(self.counts, self.n_clbits)]

    def expectation_z(self, cbits):
        """逐行的 Z 串期望值（只从原始 counts 算），没有 counts 的行为 None。"""
        return [bits.expectation_z(c, cbits, self._bit_order()) for c in self.counts]

    def to_dict(self):
        """{列名: 列表}，每个参数一列；可直接给 pandas.DataFrame。参数名与固定列重名时参数列加前缀 param:。"""
        fixed = {'seq': self.seq, 'task_id': self.task_ids, 'status': self.status,
                 'shots_returned': self.shots_returned, 'counts': self.counts, 'n_clbits': self.n_clbits,
                 'name': self.names, 'iteration': self.iterations, 'evaluation_index': self.evaluation_index,
                 'replicate_index': self.replicate_index,
                 'error_category': [(e or {}).get('category') for e in self.errors]}
        out = {'seq': fixed.pop('seq'), 'task_id': fixed.pop('task_id')}
        for name in self.parameter_names:
            out[name if name not in fixed and name not in out else 'param:' + name] = self.column(name)
        out.update(fixed)
        return out

    def to_pandas(self):
        try:
            import pandas
        except ImportError:
            raise ImportError(t('tables.need_pandas')) from None
        return pandas.DataFrame(self.to_dict())
