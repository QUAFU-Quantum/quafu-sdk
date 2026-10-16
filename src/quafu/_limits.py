# -*- coding: utf-8 -*-
"""提交前的本地上限检查：比特数与 shots 按平台公开的 limits 判，不在包里另写数字。

每个提交目标（target）的上限只有一处来源：GET {BASE_URL}/api/v1/backends/<target>/metadata 的 limits（公开，免登录）。
这里第一次用到某个 target 时取一次、进程内缓存一段时间；取不到（离线、平台还没给 limits、target 不认识）就跳过本地检查，
照常交给平台判——本地检查只是让明显超限的提交不必跑一趟网络就得到清楚的报错，平台的检查始终是最终口径。

比特数怎么数看 limits.qubit_count：
  declared  线路声明的宽度（全部 qreg 的大小之和）
  active    被门碰过的比特（barrier 不算）。平台对九鼎模拟还会把转译后路由经过的比特算进去，本地看不到转译结果，
            所以本地只按线路本身数——数出来不会比平台多，不会误拒。
只认得出的 OpenQASM 2 才数；qiskit 线路先导出成 QASM 再数。数不出来（语法超出这里的简单解析）就不查比特数。"""
import re
import threading
import time
from urllib.parse import quote

from ._i18n import t
from .errors import PrecheckError, QuafuError

CACHE_S = 600.0                    # 平台的上限可以随配置调整，缓存不宜太久
FAIL_CACHE_S = 30.0                # 取不到时短暂记住，免得一组提交里每条都再等一次
_cache = {}
_lock = threading.Lock()


def metadata_url(api, target):
    return '%s/backends/%s/metadata' % (api, quote(target, safe=''))


def fetch(client, target):
    """这个 target 的 limits（dict），取不到为 None。按 (平台入口, target) 进程内缓存。"""
    key = (client.api, target)
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            return hit[1]
    try:
        md = client._request('GET', '/backends/%s/metadata' % quote(target, safe=''), auth=False, retry='none')
        lim = md.get('limits')
        lim = lim if isinstance(lim, dict) else None
    except (QuafuError, OSError, ValueError):
        lim = None
    with _lock:
        _cache[key] = (now + (CACHE_S if lim is not None else FAIL_CACHE_S), lim)
    return lim


def clear_cache():
    with _lock:
        _cache.clear()


# ── OpenQASM 2 的比特计数（只为本地检查，不做语法校验） ──────────────────────

_COMMENT = re.compile(r'//[^\n]*')
_GATE_DEF = re.compile(r'\b(?:gate|opaque)\b[^{;]*(\{[^}]*\})?', re.S)
_QREG = re.compile(r'^\s*qreg\s+([A-Za-z_]\w*)\s*\[\s*(\d+)\s*\]\s*$')
_SKIP = re.compile(r'^\s*(OPENQASM|include|creg|barrier)\b')
_ARG = re.compile(r'([A-Za-z_]\w*)\s*(?:\[\s*(\d+)\s*\])?')


def count_qubits(qasm):
    """(declared, active)；认不出时为 None。"""
    if not isinstance(qasm, str):
        return None
    text = _GATE_DEF.sub(';', _COMMENT.sub('', qasm))
    regs, used = {}, set()
    for stmt in text.split(';'):
        stmt = stmt.strip()
        if not stmt or _SKIP.match(stmt):
            continue
        m = _QREG.match(stmt)
        if m:
            regs[m.group(1)] = int(m.group(2))
            continue
        stmt = re.sub(r'^if\s*\([^)]*\)\s*', '', stmt)
        stmt = stmt.split('->', 1)[0]                     # measure q[0] -> c[0]：只看左边
        stmt = re.sub(r'\([^()]*(\([^()]*\)[^()]*)*\)', ' ', stmt)    # 去掉门参数（含一层嵌套括号）
        parts = stmt.split(None, 1)
        if len(parts) < 2:
            return None
        for arg in parts[1].split(','):
            m = _ARG.fullmatch(arg.strip())
            if not m or m.group(1) not in regs:
                return None
            name, idx = m.group(1), m.group(2)
            if idx is None:
                used.update((name, i) for i in range(regs[name]))
            elif int(idx) < regs[name]:
                used.add((name, int(idx)))
            else:
                return None
    if not regs:
        return None
    return sum(regs.values()), len(used)


# ── 检查 ─────────────────────────────────────────────────────────────

def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def check_shots(lim, shots, target, url, where=''):
    lo, hi, step = _int(lim.get('min_shots')), _int(lim.get('max_shots')), _int(lim.get('shots_step'))
    if lo is not None and hi is not None and not lo <= shots <= hi:
        raise PrecheckError(t('limits.shots_range', where, target, lo, hi, shots, url),
                            category='precheck.shotsOutOfRange',
                            vars={'shots': shots, 'min_shots': lo, 'max_shots': hi, 'limits_url': url, 'local': True})
    if step and step > 1 and shots % step:
        raise PrecheckError(t('limits.shots_step', where, target, step, shots, url),
                            category='precheck.shotsGranularity',
                            vars={'shots': shots, 'shots_step': step, 'limits_url': url, 'local': True})


def check_qubits(lim, qasm, target, url, where=''):
    limit = _int(lim.get('max_qubits'))
    counted = count_qubits(qasm) if limit is not None else None
    if counted is None:
        return
    active = lim.get('qubit_count') == 'active'
    n = counted[1] if active else counted[0]
    if n > limit:
        how = t('limits.how_active') if active else t('limits.how_declared')
        raise PrecheckError(t('limits.qubits', where, target, limit, how, n, url),
                            category='precheck.simTooLarge',
                            vars={'n_qubits': n, 'limit_qubits': limit, 'qubit_count': lim.get('qubit_count'),
                                  'limits_url': url, 'local': True})


def check(client, target, shots=None, circuits=(), template=None):
    """按这个 target 的 limits 检查 shots 与每条线路的比特数；超限抛 PrecheckError（vars['local'] 为 True），
    取不到 limits 时什么也不做。circuits 是已规整好的线路项（{'qasm', 'shots', …}）。"""
    lim = fetch(client, target)
    if not lim:
        return
    url = metadata_url(client.api, target)
    if shots is not None:
        check_shots(lim, shots, target, url)
    many = len(circuits) > 1
    for i, c in enumerate(circuits):
        where = t('limits.where_n', i) if many else ''
        if c.get('shots') is not None:
            check_shots(lim, c['shots'], target, url, where)
        check_qubits(lim, c.get('qasm'), target, url, where)
    if template is not None:
        check_qubits(lim, template, target, url)
