# -*- coding: utf-8 -*-
"""Ising problems: QUBO or Ising models solved on the platform's Ising machines (no quantum circuits).

    import quafu
    job = quafu.solve_qubo({(0, 1): 2.0, (0, 0): -1.0, (1, 1): -1.0}, target='<Ising machine>')
    r = job.result()                     # Samples
    r.best.values, r.best.energy         # lowest-energy solution vector and its energy

    p = quafu.Problem.from_ising(J, h)   # build locally, check, compute energies
    p.energy([1, -1, 1])
    job = quafu.submit_problems([p, q], target='<Ising machine>')   # several problems in one job

Energy, as the platform defines it for every Ising machine (the goal is to minimize it):

    E(v) = offset + sum over linear (i, w) of w * v[i] + sum over quadratic (i, j, w) of w * v[i] * v[j]

with v[i] in {-1, +1} for type 'ising' and v[i] in {0, 1} for type 'qubo'. Every term counts once; repeated
pairs add up and (i, j) is the same term as (j, i). A dense matrix M therefore means E = v^T M v (both triangles
and the diagonal count). Diagonal terms fold exactly: x*x = x in QUBO (a linear term), s*s = 1 in Ising (a constant).

Problems are canonicalized locally before they are sent: (j, i) merges into (i, j) with i < j, repeats add up,
diagonal terms fold as above, and zero terms are dropped. The payload is sparse ([i, j, w] triples and [i, w]
pairs) and identical whichever input shape produced it.

Ising machines are the rows of quafu.devices() whose paradigm is 'ising'. Their resource limits come only from
GET {BASE_URL}/api/v1/backends/<target>/metadata (limits.max_variables, max_terms, max_problems_per_job); the SDK
checks them before sending and leaves the final word to the platform."""
import collections
import math
import operator
import re
import threading
import time

from . import _limits
from ._i18n import t
from ._inputs import number
from .errors import BadRequest, PrecheckError, ProtocolError, QuotaError, ServerUnavailable

TYPES = ('ising', 'qubo')
DOMAINS = {'ising': (-1, 1), 'qubo': (0, 1)}
CONTRACT_MIN = (0, 3, 0)          # the platform contract that accepts problems[] in POST /jobs
CACHE_S = 600.0                   # a platform that supports problems keeps supporting them
RECHECK_S = 30.0                  # an older platform may be upgraded while this process runs

_contract = {}
_lock = threading.Lock()


# ── input parsing ────────────────────────────────────────────────────

def _weight(v, where):
    if isinstance(v, (str, bytes, bool)):
        raise TypeError(t('inputs.not_number', where, v))
    return number(v, where)


def _index(v, where):
    if isinstance(v, bool):
        raise TypeError(t('ising.index_type', where, v))
    if isinstance(v, float) and v.is_integer():
        return int(v)
    try:
        return operator.index(v)
    except TypeError:
        raise TypeError(t('ising.index_type', where, v)) from None


def _as_list(x):
    return x.tolist() if hasattr(x, 'tolist') else x


def _matrix(m, what):
    """Q / J → (dense size or None, [(i, j, w)]). Accepts {(i, j): w}, a square nested list, or anything with
    tolist()."""
    if isinstance(m, dict):
        terms = []
        for key, w in m.items():
            if not (isinstance(key, tuple) and len(key) == 2):
                raise TypeError(t('ising.key_shape', what, key))
            where = '%s[%r]' % (what, key)
            terms.append((_index(key[0], where), _index(key[1], where), _weight(w, where)))
        return None, terms
    m = _as_list(m)
    if not isinstance(m, (list, tuple)):
        raise TypeError(t('ising.matrix_type', what, type(m).__name__))
    n, terms = len(m), []
    for r, row in enumerate(m):
        row = _as_list(row)
        if not isinstance(row, (list, tuple)):
            raise TypeError(t('ising.row_type', what, r, type(row).__name__))
        if len(row) != n:
            raise ValueError(t('ising.not_square', what, n, r, len(row)))
        for c, w in enumerate(row):
            w = _weight(w, '%s[%d][%d]' % (what, r, c))
            if w:
                terms.append((r, c, w))
    return n, terms


def _pairs(x):
    return all(isinstance(_as_list(e), (list, tuple)) and len(_as_list(e)) == 2 for e in x)


def _linear(h, what):
    """h / linear → (dense size or None, [(i, w)]). Accepts a list of weights, a list of (i, w) pairs, {i: w}, or
    anything with tolist()."""
    if h is None:
        return None, []
    if isinstance(h, dict):
        return None, [(_index(i, '%s[%r]' % (what, i)), _weight(w, '%s[%r]' % (what, i))) for i, w in h.items()]
    h = _as_list(h)
    if not isinstance(h, (list, tuple)):
        raise TypeError(t('ising.linear_type', what, type(h).__name__))
    if not h:
        return None, []
    if _pairs(h):
        out = []
        for k, e in enumerate(h):
            i, w = _as_list(e)
            out.append((_index(i, '%s[%d]' % (what, k)), _weight(w, '%s[%d]' % (what, k))))
        return None, out
    return len(h), [(i, w) for i, w in ((i, _weight(w, '%s[%d]' % (what, i))) for i, w in enumerate(h)) if w]


def _triples(quadratic, what):
    """from_terms' quadratic → [(i, j, w)]: a list of (i, j, w) triples, or {(i, j): w}."""
    if isinstance(quadratic, dict):
        return _matrix(quadratic, what)[1]
    quadratic = _as_list(quadratic)
    if not isinstance(quadratic, (list, tuple)):
        raise TypeError(t('ising.terms_type', what, type(quadratic).__name__))
    out = []
    for k, e in enumerate(quadratic):
        e = _as_list(e)
        if not (isinstance(e, (list, tuple)) and len(e) == 3):
            raise TypeError(t('ising.term_shape', what, k, e))
        where = '%s[%d]' % (what, k)
        out.append((_index(e[0], where), _index(e[1], where), _weight(e[2], where)))
    return out


def _type(v):
    if v not in TYPES:
        raise ValueError(t('ising.type_invalid', ' / '.join(repr(x) for x in TYPES), v))
    return v


def _size(num_variables, dense, quad, lin):
    """Number of variables: explicit, else the dense dimension (all dense inputs must agree), else max index + 1."""
    if num_variables is not None:
        if isinstance(num_variables, bool):
            raise TypeError(t('ising.num_variables', num_variables))
        try:
            n = operator.index(num_variables)
        except TypeError:
            raise TypeError(t('ising.num_variables', num_variables)) from None
    else:
        sizes = sorted(set(d for _, d in dense if d is not None))
        if len(sizes) > 1:
            raise ValueError(t('ising.size_mismatch', ', '.join('%s: %d' % (w, d) for w, d in dense if d is not None)))
        if sizes:
            n = sizes[0]
        else:
            n = 1 + max([max(i, j) for i, j, _ in quad] + [i for i, _ in lin] + [-1])
    if n < 1:
        raise ValueError(t('ising.num_variables', n))
    return n


# ── Problem ──────────────────────────────────────────────────────────

class Problem(object):
    """One Ising or QUBO problem, canonicalized and checked locally (nothing is sent until you submit it).

    type            'ising' (variables are spins -1 / +1) or 'qubo' (variables are 0 / 1)
    num_variables   number of variables N; indices run 0..N-1
    quadratic       [(i, j, w)] with i < j, merged, non-zero, sorted
    linear          [(i, w)], merged, non-zero, sorted
    offset          constant term
    name            optional name of this problem, shown with its task
    num_terms       len(quadratic) + len(linear): what the platform's max_terms counts

    Build with Problem.from_qubo(Q), Problem.from_ising(J, h) or Problem.from_terms(type, N, quadratic, linear);
    the constructor takes the same arguments as from_terms."""

    def __init__(self, type, num_variables, quadratic=(), linear=None, offset=0, name=None):
        quad = _triples(quadratic, 'quadratic')
        nl, lin = _linear(linear, 'linear')
        self._build(type, num_variables, quad, [('linear', nl)], lin, offset, name)

    def _build(self, type_, num_variables, quad, dense, lin, offset, name):
        self.type = _type(type_)
        n = _size(num_variables, dense, quad, lin)
        off = _weight(offset, 'offset')
        q, h = collections.defaultdict(float), collections.defaultdict(float)
        for i, j, w in quad:
            for k in (i, j):
                if not 0 <= k < n:
                    raise ValueError(t('ising.index_range', 'quadratic', k, n - 1))
            if i == j:
                if self.type == 'qubo':
                    h[i] += w              # x * x = x
                else:
                    off += w               # s * s = 1
            else:
                q[(min(i, j), max(i, j))] += w
        for i, w in lin:
            if not 0 <= i < n:
                raise ValueError(t('ising.index_range', 'linear', i, n - 1))
            h[i] += w
        if name is not None and not isinstance(name, str):
            raise TypeError(t('ising.name_type', name))
        self.num_variables = n
        self.quadratic = [(i, j, w) for (i, j), w in sorted(q.items()) if w]
        self.linear = [(i, w) for i, w in sorted(h.items()) if w]
        self.offset = off
        self.name = name or None

    @classmethod
    def _make(cls, type_, num_variables, quad, dense, lin, offset, name):
        p = cls.__new__(cls)
        p._build(type_, num_variables, quad, dense, lin, offset, name)
        return p

    @classmethod
    def from_qubo(cls, Q, offset=0, num_variables=None, name=None):
        """A QUBO problem: minimize offset + x^T Q x over x in {0, 1}^N.

        Q is {(i, j): w}, a square nested list, or an array (anything with tolist(), e.g. numpy). Every non-zero
        entry is a term, so Q need not be symmetric or triangular; the diagonal holds the linear terms.
        num_variables is needed only when the last variables appear in no term of a dict."""
        n, quad = _matrix(Q, 'Q')
        return cls._make('qubo', num_variables, quad, [('Q', n)], [], offset, name)

    @classmethod
    def from_ising(cls, J, h=None, offset=0, num_variables=None, name=None):
        """An Ising problem: minimize offset + h.s + s^T J s over s in {-1, +1}^N.

        J is {(i, j): w}, a square nested list, or an array; h is a list (or array) of N fields, a list of (i, w)
        pairs, or {i: w}. Diagonal entries of J are constants (s * s = 1) and fold into the offset."""
        n, quad = _matrix(J, 'J')
        nh, lin = _linear(h, 'h')
        return cls._make('ising', num_variables, quad, [('J', n), ('h', nh)], lin, offset, name)

    @classmethod
    def from_terms(cls, type, num_variables, quadratic, linear=None, offset=0, name=None):
        """A problem in the platform's own shape: type 'ising' or 'qubo', N variables, quadratic as (i, j, w)
        triples (or {(i, j): w}), linear as (i, w) pairs, a list of N weights, or {i: w}."""
        return cls(type, num_variables, quadratic, linear, offset, name)

    @property
    def num_terms(self):
        return len(self.quadratic) + len(self.linear)

    def __repr__(self):
        return 'Problem(type=%r, num_variables=%d, num_terms=%d%s)' % (
            self.type, self.num_variables, self.num_terms, ', name=%r' % self.name if self.name else '')

    def to_payload(self):
        """The problems[] item of POST /jobs: sparse triples and pairs, non-zero terms only."""
        d = {'type': self.type, 'num_variables': self.num_variables,
             'quadratic': [[i, j, w] for i, j, w in self.quadratic], 'linear': [[i, w] for i, w in self.linear],
             'offset': self.offset}
        if self.name:
            d['name'] = self.name
        return d

    def energy(self, values):
        """E(values) by the platform's definition (see the module docstring). values has N entries: -1 / +1 for an
        Ising problem, 0 / 1 for QUBO (e.g. Samples.best.values)."""
        v = list(_as_list(values))
        if len(v) != self.num_variables:
            raise ValueError(t('ising.values_length', len(v), self.num_variables))
        domain = DOMAINS[self.type]
        for k, x in enumerate(v):
            if isinstance(x, (str, bytes)) or x not in domain:
                raise ValueError(t('ising.values_domain', k, x, self.type, ' / '.join(map(str, domain))))
        return math.fsum([self.offset] + [w * v[i] for i, w in self.linear]
                         + [w * v[i] * v[j] for i, j, w in self.quadratic])


# ── results ──────────────────────────────────────────────────────────

Sample = collections.namedtuple('Sample', 'values energy occurrences')
Sample.__doc__ = """One distinct solution: values (-1 / +1 or 0 / 1 each), energy (platform definition), occurrences."""


def is_samples(detail):
    """Whether a task detail is an Ising task: result.type is 'samples', or program.paradigm is 'ising' (a failed or
    unfinished Ising task has no result yet)."""
    d = detail if isinstance(detail, dict) else {}
    result = d.get('result') if isinstance(d.get('result'), dict) else {}
    program = d.get('program') if isinstance(d.get('program'), dict) else {}
    return result.get('type') == 'samples' or program.get('paradigm') == 'ising'


def _sample(row):
    values = [int(x) if isinstance(x, float) and x.is_integer() else x for x in row.get('values') or []]
    occ = row.get('occurrences')
    return Sample(values, row.get('energy'), 1 if occ is None else occ)


class Samples(object):
    """The result of one Ising problem. Fields the platform did not give are None; the SDK does not guess.

    status              Finished / Failed / Cancelled (Queued / Running before that); ok is status == 'Finished'
    samples             distinct solutions [Sample(values, energy, occurrences)], lowest energy first; None unless
                        finished
    best                the lowest-energy Sample (best.values, best.energy); None unless finished
    energies            [sample.energy, ...] in the order of samples
    problem_type        'ising' (values are -1 / +1) or 'qubo' (values are 0 / 1)
    energy_trace        the machine's energy during the run, converted to the platform's energy definition; None
                        when the machine gives none or it could not be converted
    device_time_us      compute time reported by the machine, in microseconds
    num_variables       from the task's program section
    error               why it failed {category, stage, retryable, detail, vars}; None on success
    name / seq / task_id / target / raw   problem name, position in the job, task ID, target, the task detail as is

    Energies are recomputed by the platform with its own definition, so Problem.energy(sample.values) agrees."""

    def __init__(self, detail):
        d = detail or {}
        result = d.get('result') or {}
        program = d.get('program') or {}
        self.raw = d
        self.task_id = d.get('task_id')
        self.status = d.get('status')
        self.target = d.get('target')
        self.backend = d.get('chip') or self.target
        self.name = d.get('name') or None
        self.seq = (d.get('job') or {}).get('seq')
        self.problem_type = result.get('problem_type') or program.get('type')
        self.num_variables = program.get('num_variables')
        finished = self.status == 'Finished'
        rows = result.get('samples') if finished and isinstance(result.get('samples'), list) else None
        self.samples = None if rows is None else [_sample(r) for r in rows if isinstance(r, dict)]
        self.energy_trace = result.get('energy_trace') if finished else None
        self.device_time_us = result.get('device_time_us') if finished else None
        err = d.get('error')
        self.error = err if self.status == 'Failed' and isinstance(err, dict) else None

    @property
    def ok(self):
        return self.status == 'Finished'

    @property
    def best(self):
        if not self.samples:
            return None
        return min(self.samples, key=lambda s: s.energy if isinstance(s.energy, (int, float)) else math.inf)

    @property
    def energies(self):
        return None if self.samples is None else [s.energy for s in self.samples]

    def __repr__(self):
        if self.ok:
            best = self.best
            return 'Samples(task_id=%r, best_energy=%r, n_samples=%d)' % (
                self.task_id, best.energy if best else None, len(self.samples or ()))
        return 'Samples(task_id=%r, status=%r, error=%r)' % (self.task_id, self.status,
                                                             (self.error or {}).get('category'))


# ── devices ──────────────────────────────────────────────────────────

def device_rows(payload):
    """GET /devices' ising_devices → rows for quafu.devices(): kind 'ising', paradigm 'ising'; n_qubits is None."""
    out = []
    for row in payload.get('ising_devices') or []:
        if isinstance(row, dict) and row.get('name'):
            out.append({'name': row['name'], 'kind': 'ising', 'paradigm': row.get('paradigm') or 'ising',
                        'status': row.get('status'), 'n_qubits': None, 'queue': row.get('queue'),
                        'limits': row.get('limits'), 'technology': row.get('technology'),
                        'max_variables': row.get('max_variables'), 'problem_types': row.get('problem_types')})
    return out


# ── platform checks ──────────────────────────────────────────────────

def _version(v):
    m = re.match(r'\s*(\d+)\.(\d+)(?:\.(\d+))?', v) if isinstance(v, str) else None
    return tuple(int(x or 0) for x in m.groups()) if m else None


def contract_version(client):
    """The platform's contract_version from the public GET /healthz (None if it reports none). Cached per platform."""
    key, now = client.api, time.monotonic()
    with _lock:
        hit = _contract.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        v = client._request('GET', '/healthz', auth=False).get('contract_version')
    except (ProtocolError, BadRequest):          # no such endpoint: a platform older than any contract version
        v = None
    v = v if isinstance(v, str) else None
    ok = (_version(v) or ()) >= CONTRACT_MIN
    with _lock:
        _contract[key] = (now + (CACHE_S if ok else RECHECK_S), v)
    return v


def clear_cache():
    with _lock:
        _contract.clear()


def require_contract(client):
    """Raise ServerUnavailable (sent=False) if the platform's contract predates Ising problems; nothing is sent."""
    v = contract_version(client)
    if (_version(v) or ()) < CONTRACT_MIN:
        raise ServerUnavailable(t('ising.platform_too_old', client.base_url, v or t('ising.version_unknown'),
                                  '.'.join(map(str, CONTRACT_MIN))), sent=False)


def _count(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def check_limits(client, target, problems):
    """Check problems against the target's limits without sending, with the platform's own error for each
    (vars['local'] True): too many problems → QuotaError job_too_large, too many variables → PrecheckError
    precheck.problemInvalid (field num_variables), too many terms → PrecheckError precheck.problemTooLarge.
    Skipped when the limits cannot be read, as for circuits."""
    lim = _limits.fetch(client, target)
    if not lim:
        return
    url = _limits.metadata_url(client.api, target)
    most = _count(lim.get('max_problems_per_job'))
    if most is not None and len(problems) > most:
        raise QuotaError(t('ising.too_many_problems', target, most, len(problems), url), code='job_too_large',
                         vars={'requested': len(problems), 'existing': 0, 'max': most, 'limits_url': url,
                               'local': True})
    max_vars, max_terms = _count(lim.get('max_variables')), _count(lim.get('max_terms'))
    many = len(problems) > 1
    for i, p in enumerate(problems):
        where = t('ising.where_n', i) if many else ''
        if max_vars is not None and p.num_variables > max_vars:
            raise PrecheckError(t('ising.too_many_variables', where, target, max_vars, p.num_variables, url),
                                category='precheck.problemInvalid',
                                vars={'task_index': i, 'field': 'num_variables', 'num_variables': p.num_variables,
                                      'max_variables': max_vars, 'limits_url': url, 'local': True})
        if max_terms is not None and p.num_terms > max_terms:
            raise PrecheckError(t('ising.too_many_terms', where, target, max_terms, p.num_terms, url),
                                category='precheck.problemTooLarge',
                                vars={'task_index': i, 'num_terms': p.num_terms, 'max_terms': max_terms,
                                      'limits_url': url, 'local': True})


# ── submitting ───────────────────────────────────────────────────────

class IsingMethods(object):
    """Client methods for Ising problems (mixed into quafu.Client)."""

    def solve_qubo(self, Q, target, *, offset=0, num_variables=None, name=None):
        """Submit one QUBO problem (see Problem.from_qubo) to an Ising machine; returns a Job without waiting.
        job.result() returns Samples. name is the job name, shown under "My jobs" on the website."""
        return self.submit_problems(Problem.from_qubo(Q, offset=offset, num_variables=num_variables), target,
                                    name=name)

    def solve_ising(self, J, h=None, target=None, *, offset=0, num_variables=None, name=None):
        """Submit one Ising problem (see Problem.from_ising) to an Ising machine; returns a Job without waiting.
        target is required; job.result() returns Samples."""
        return self.submit_problems(Problem.from_ising(J, h, offset=offset, num_variables=num_variables), target,
                                    name=name)

    def submit_problems(self, problems, target, *, name=None):
        """Submit one Problem, or a list of them as one job (one task per problem, in order); returns a Job.

        Before sending: checks that the platform supports Ising problems (contract 0.3.0 or later, else
        ServerUnavailable) and the target's limits (see check_limits; vars['local'] True). Ising problems take
        no shots and no compiler, and cannot be appended to a job later. job.results() returns one Samples per
        problem, in submission order.

        The platform rejects with PrecheckError: precheck.paradigmMismatch (the target is not an Ising machine),
        precheck.unknownDevice, precheck.problemInvalid (vars task_index, field; field 'precision' means the
        machine cannot represent the weights at its precision), precheck.problemTooLarge; QuotaError
        job_too_large for too many problems; DeviceUnavailable when the machine is not online."""
        single = isinstance(problems, Problem)
        items = [problems] if single else list(problems)
        if not items:
            raise ValueError(t('ising.empty_problems'))
        for i, p in enumerate(items):
            if not isinstance(p, Problem):
                raise TypeError(t('ising.problem_type', i, type(p).__name__))
        if not isinstance(target, str) or not target.strip():
            raise BadRequest(t('ising.target_required'))
        target = target.strip()
        self._require_creds()            # not logged in is reported before any network request
        require_contract(self)
        check_limits(self, target, items)
        body = {'mode': 'single' if single else 'collection', 'target': target,
                'problems': [p.to_payload() for p in items]}
        job = self._create_job(body, name, len(items))
        job.paradigm = 'ising'
        return job


def solve_qubo(Q, target, *, offset=0, num_variables=None, name=None):
    """Submit one QUBO problem to an Ising machine; see Client.solve_qubo()."""
    from .client import Client
    return Client().solve_qubo(Q, target, offset=offset, num_variables=num_variables, name=name)


def solve_ising(J, h=None, target=None, *, offset=0, num_variables=None, name=None):
    """Submit one Ising problem to an Ising machine; see Client.solve_ising()."""
    from .client import Client
    return Client().solve_ising(J, h, target, offset=offset, num_variables=num_variables, name=name)


def submit_problems(problems, target, *, name=None):
    """Submit one Problem or a list of them as one job; see Client.submit_problems()."""
    from .client import Client
    return Client().submit_problems(problems, target, name=name)
