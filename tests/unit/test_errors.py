# -*- coding: utf-8 -*-
"""错误映射表：任务分发器三种错误体形状、非 JSON 的 500 / 413 与 nginx 502 页面、同码不同端点、契约 §3.11 的新码。"""
import pytest

from quafu import errors as E

from ..helpers import dispatcher_error

pytestmark = pytest.mark.usefixtures('zh')          # 断言的是中文文案；英文见 test_i18n.py

WHO = 'qf_abcdefgh...'

CASES = [
    # (端点, HTTP 码, 响应体, 期望异常, 期望 code)
    ('other', 401, {'error': '未登录', 'code': 'unauthenticated'}, E.LoginRevoked, 'unauthenticated'),
    ('other', 401, {'error': 'x', 'code': 'invalid_api_key'}, E.LoginRevoked, 'invalid_api_key'),
    ('other', 401, {'error': 'x', 'code': 'session_required'}, E.AuthError, 'session_required'),
    ('submit', 403, dispatcher_error('precheck.guestDemoOnly', '游客只能跑演示线路'), E.PrecheckError,
     'precheck.guestDemoOnly'),
    ('job', 403, {'error': '游客不能建任务组', 'code': 'guest_not_allowed'}, E.AuthError, 'guest_not_allowed'),
    ('submit', 422, dispatcher_error('precheck.shotsOutOfRange', shots=99999), E.PrecheckError,
     'precheck.shotsOutOfRange'),
    ('submit', 422, dispatcher_error('precheck.shotsGranularity', '真机 shots 只收 1024 的整数倍', shots=1000,
                                  allowed=[1024, 2048]), E.PrecheckError, 'precheck.shotsGranularity'),
    ('job', 422, dispatcher_error('precheck.badTemplate', '未声明的占位符', placeholder='phi'), E.PrecheckError,
     'precheck.badTemplate'),
    ('submit', 422, dispatcher_error('precheck.unknownDemo', demo='x.qasm'), E.PrecheckError, 'precheck.unknownDemo'),
    ('submit', 422, dispatcher_error('precheck.unknownDevice', '未知设备 X', device='X'), E.PrecheckError,
     'precheck.unknownDevice'),
    ('submit', 422, {'error': '请求体不合法', 'code': 'invalid_body',
                     'detail': [{'loc': ['body', 'qasm'], 'msg': 'Field required'}]}, E.BadRequest, 'invalid_body'),
    ('submit', 429, dispatcher_error('runtime.quotaExhausted', days=1), E.QuotaError, 'runtime.quotaExhausted'),
    ('job', 422, {'error': '任务数超上限', 'code': 'job_too_large', 'vars': {'requested': 600, 'existing': 0, 'max': 500}},
     E.QuotaError, 'job_too_large'),
    ('job', 413, {'error': '请求体太大', 'code': 'payload_too_large', 'vars': {'bytes': 20000000, 'max': 16777216}},
     E.QuotaError, 'payload_too_large'),
    ('job', 429, {'error': '开着的迭代任务组太多', 'code': 'too_many_open_jobs'}, E.QuotaError, 'too_many_open_jobs'),
    ('submit', 503, dispatcher_error('runtime.deviceUnavailable', '设备 X 当前不可用', device='X'),
     E.DeviceUnavailable, 'runtime.deviceUnavailable'),
    ('result', 409, {'task_id': 'T1', 'status': 'Cancelled'}, E.TaskCancelled, None),
    ('result', 409, {'task_id': 'T1', 'status': 'Running', 'stage': 'executing'}, E.NotReady, None),
    ('result', 409, {'error': '任务还没完成', 'code': 'task_not_finished', 'status': 'Running', 'stage': 'executing'},
     E.NotReady, 'task_not_finished'),
    ('result', 409, {'error': '任务已取消', 'code': 'task_cancelled'}, E.TaskCancelled, 'task_cancelled'),
    ('result', 422, dispatcher_error('runtime.rejected', '设备拒绝', status='Failed'), E.TaskFailed, 'runtime.rejected'),
    ('result', 422, dispatcher_error('runtime.emptyResult', '设备跑完没结果', status='Failed'), E.TaskFailed,
     'runtime.emptyResult'),
    ('result', 422, dispatcher_error('runtime.simTimeout', '模拟超时', status='Failed', limit_s=60), E.TaskFailed,
     'runtime.simTimeout'),
    ('result', 422, dispatcher_error('runtime.simResourceExceeded', '模拟超内存', status='Failed', limit_mb=512),
     E.TaskFailed, 'runtime.simResourceExceeded'),
    ('task', 404, {'error': 'not found', 'code': 'not_found'}, E.TaskNotFound, 'not_found'),
    ('result', 404, {'error': 'not found', 'code': 'not_found'}, E.TaskNotFound, 'not_found'),
    ('job', 404, {'error': 'not found', 'code': 'not_found'}, E.JobNotFound, 'not_found'),
    ('job', 409, {'error': 'x', 'code': 'job_closed'}, E.JobClosed, 'job_closed'),
    ('job', 409, {'error': 'x', 'code': 'job_not_iterative'}, E.JobClosed, 'job_not_iterative'),
    ('job', 409, {'error': 'x', 'code': 'job_has_no_template'}, E.JobClosed, 'job_has_no_template'),
    ('task', 409, {'error': '任务已无法取消', 'code': 'not_cancellable'}, E.NotCancellable, 'not_cancellable'),
    ('job', 429, {'error': '今天建任务组太多', 'code': 'too_many_jobs', 'vars': {'limit': 1000, 'used': 1000}},
     E.QuotaError, 'too_many_jobs'),
    ('other', 404, {'detail': 'Not Found'}, E.ProtocolError, None),
    ('other', 404, {'error': 'unknown device', 'code': 'unknown_device'}, E.BadRequest, 'unknown_device'),
    ('other', 400, {'error': 'status 不是合法状态词', 'code': 'bad_status'}, E.BadRequest, 'bad_status'),
    ('other', 426, {'error': '请升级', 'code': 'client_outdated'}, E.ClientOutdated, 'client_outdated'),
    ('other', 500, {'error': 'boom', 'code': 'runtime.internal'}, E.ServerUnavailable, 'runtime.internal'),
    ('other', 418, {'weird': 1}, E.ProtocolError, None),
    ('other', 400, {'code': 123, 'error': ['not', 'a', 'string']}, E.BadRequest, None),
]


@pytest.mark.parametrize('endpoint,status,body,exc,code', CASES)
def test_mapping_table(endpoint, status, body, exc, code):
    e = E.from_response(endpoint, status, body, {}, b'', task_id='T1', who=WHO, job_id='j1')
    assert type(e) is exc
    assert isinstance(e, E.QuafuError) and e.status == status and e.code == code and e.body is body
    assert str(e)


def test_precheck_carries_category_detail_vars():
    e = E.from_response('submit', 422, dispatcher_error('precheck.qubitUnavailable', '比特 3 不可用', qubit=3), {})
    assert (e.category, e.detail, e.vars) == ('precheck.qubitUnavailable', '比特 3 不可用', {'qubit': 3})
    assert '比特 3 不可用' in str(e)


def test_shots_error_without_detail_still_says_something():
    e = E.from_response('submit', 422, dispatcher_error('precheck.shotsOutOfRange', shots=99999), {})
    assert '99999' in str(e)


@pytest.mark.parametrize('reason', ['duplicate_measurement', 'mid_circuit_measurement', 'reset'])
def test_bad_circuit_reason_is_in_the_message(reason):
    e = E.from_response('submit', 422, dispatcher_error('precheck.badCircuit', '末端测量检查未通过', reason=reason,
                                                     task_index=0), {})
    assert type(e) is E.PrecheckError and reason in str(e) and e.vars['reason'] == reason


def test_real_device_measurement_rules_are_explained():
    e = E.from_response('submit', 422, dispatcher_error('precheck.badCircuit', '经典位没写入', reason='unmeasured_clbit',
                                                     cbits=[1, 3]), {})
    assert type(e) is E.PrecheckError and e.vars['cbits'] == [1, 3]
    assert 'unmeasured_clbit' in str(e) and '1, 3' in str(e) and '模拟器不受此限' in str(e)
    e = E.from_response('submit', 422, dispatcher_error('precheck.badCircuit', '测量顺序', reason='measurement_order'), {})
    assert '升序' in str(e)


def test_undeclared_parameter_values_say_what_is_missing():
    e = E.from_response('job', 422, dispatcher_error('precheck.badTemplate', '参数值需要声明', task_index=0,
                                                  missing=True, undeclared=['theta']), {})
    assert type(e) is E.PrecheckError and '没有声明 parameters' in str(e) and 'theta' in str(e)
    e = E.from_response('job', 422, dispatcher_error('precheck.badTemplate', '参数值需要声明', task_index=2,
                                                  missing=False, undeclared=['phi', 'psi']), {})
    assert '没有声明' not in str(e) and 'phi, psi' in str(e)


def test_multiple_classical_registers_is_a_precheck_error():
    e = E.from_response('job', 422, dispatcher_error('precheck.multipleClassicalRegisters', '只收单个经典寄存器',
                                                  n_cregs=2, task_index=3), {})
    assert type(e) is E.PrecheckError and e.category == 'precheck.multipleClassicalRegisters'
    assert e.vars == {'n_cregs': 2, 'task_index': 3}


def test_sim_too_large_says_the_estimate_when_there_is_one():
    e = E.from_response('submit', 422, dispatcher_error('precheck.simTooLarge', '模拟规模超限', n_qubits=26,
                                                     method='statevector', estimate_mb=1024, limit_mb=512), {})
    assert type(e) is E.PrecheckError and '活跃比特 26' in str(e) and 'statevector' in str(e)
    assert '1024 MB' in str(e) and '上限 512 MB' in str(e)
    e = E.from_response('submit', 422, dispatcher_error('precheck.simTooLarge', '带噪模拟比特过多', n=20, limit=16), {})
    assert '比特数 20，上限 16' in str(e)
    e = E.from_response('submit', 422, dispatcher_error('precheck.simTooLarge', '理想模拟比特过多', n_qubits=26,
                                                     limit_qubits=24), {})
    assert '比特数 26，上限 24' in str(e)
    e = E.from_response('submit', 422, dispatcher_error('precheck.simTooLarge', '模拟规模超限'), {})
    assert type(e) is E.PrecheckError and str(e)


def test_review_limits_say_what_happened():
    e = E.from_response('job', 429, {'error': '今天建任务组太多', 'code': 'too_many_jobs',
                                     'vars': {'limit': 1000, 'used': 1000}}, {})
    assert e.vars == {'limit': 1000, 'used': 1000} and '上限 1000' in str(e) and '不会自动重试' in str(e)
    e = E.from_response('submit', 422, {'error': '字段超长', 'code': 'invalid_body', 'vars': {'field': 'name'}}, {})
    assert type(e) is E.BadRequest and '字段 name' in str(e)
    e = E.from_response('task', 409, {'error': '不可取消', 'code': 'not_cancellable'}, {}, task_id='T9')
    assert e.task_id == 'T9' and '已无法取消' in str(e) and not isinstance(e, E.ServerUnavailable)


def test_not_cancellable_says_which_stage():
    body = {'error': '不可取消', 'code': 'not_cancellable', 'vars': {'stage': 'collecting'}}
    e = E.from_response('task', 409, body, {}, task_id='T9')
    assert type(e) is E.NotCancellable and e.stage == 'collecting' and '正在取回结果' in str(e)
    e = E.from_response('task', 409, dict(body, vars={'stage': 'finished'}), {}, task_id='T9')
    assert e.stage == 'finished' and '已经完成' in str(e)
    e = E.from_response('task', 409, {'error': '不可取消', 'code': 'not_cancellable'}, {}, task_id='T9')
    assert e.stage is None and '已无法取消' in str(e)


def test_failure_limits_are_spelled_out_when_the_dispatcher_sends_vars():
    e = E.from_response('result', 422, dispatcher_error('runtime.simTimeout', '模拟超时', status='Failed', limit_s=60),
                        {}, task_id='T1')
    assert type(e) is E.TaskFailed and e.vars['limit_s'] == 60 and '墙钟上限 60 秒' in str(e)
    assert E.failure_note('runtime.simResourceExceeded', {'limit_mb': 512}) == '（模拟超过内存上限 512 MB）'
    assert E.failure_note('runtime.simTimeout', None) == '' and E.failure_note('runtime.rejected', {'x': 1}) == ''
    e = E.from_response('result', 422, {'error': '模拟超时', 'error_category': 'runtime.simTimeout'}, {}, task_id='T1')
    assert e.vars is None and '墙钟' not in str(e)


def test_pydantic_detail_list_is_rendered_as_json():
    body = {'error': '', 'code': 'invalid_body', 'detail': [{'loc': ['body', 'qasm'], 'msg': 'Field required'}]}
    assert 'Field required' in str(E.from_response('submit', 422, body, {}))


@pytest.mark.parametrize('headers,body,expected', [
    ({'retry-after': '30'}, {}, 30),
    ({}, {'retry_after': 12}, 12),
    ({'retry-after': 'soon'}, {}, None),
    ({}, {}, None),
])
def test_quota_retry_after(headers, body, expected):
    b = dict(dispatcher_error('runtime.quotaExhausted', days=1), **body)
    assert E.from_response('submit', 429, b, headers).retry_after == expected


CAP = dict(limit=500, hard_limit=5000, used=5000, remaining=0, requested=1,
           resets_at='2026-10-10T23:00:00+08:00', wait_s=7200)


def test_daily_hard_cap_says_used_cap_normal_quota_and_reset_time():
    b = dict(dispatcher_error('runtime.quotaExhausted', '平台原文', **CAP), retry_after=7200)
    e = E.from_response('submit', 429, b, {})
    assert type(e) is E.QuotaError and e.code == 'runtime.quotaExhausted'
    assert e.retry_after == 7200 and e.resets_at == CAP['resets_at'] and e.vars['hard_limit'] == 5000
    msg = str(e)
    assert '今日已交 5000 条' in msg and '硬上限 5000 条' in msg and '正常额度 500 条' in msg
    assert '23:00 重置' in msg and '2.0 小时' in msg and '最低优先级' in msg and '平台原文' not in msg


def test_daily_hard_cap_too_many_at_once_and_paused():
    big = dict(CAP, used=0, requested=6000, wait_s=None)
    e = E.from_response('submit', 429, dispatcher_error('runtime.quotaExhausted', **big), {})
    assert '6000' in str(e) and '拆小' in str(e) and e.retry_after is None
    paused = dict(CAP, limit=0, hard_limit=0, used=0)
    assert '暂停收单' in str(E.from_response('submit', 429, dispatcher_error('runtime.quotaExhausted', **paused), {}))


def test_daily_hard_cap_in_english(monkeypatch):
    from quafu import set_language
    set_language('en')
    e = E.from_response('submit', 429, dict(dispatcher_error('runtime.quotaExhausted', **CAP), retry_after=7200), {})
    msg = str(e)
    assert 'daily hard cap' in msg and 'normal quota 500' in msg and '23:00 Beijing time' in msg
    assert 'lowest priority' in msg and '2.0 hours' in msg


def test_too_large_says_the_limit_and_that_nothing_is_split():
    e = E.from_response('job', 422, {'error': '任务数超上限', 'code': 'job_too_large',
                                     'vars': {'requested': 600, 'existing': 0, 'max': 500}}, {}, job_id='j1')
    assert '500' in str(e) and '不会自动拆分' in str(e) and e.vars['max'] == 500
    page = b'<html><head><title>413 Request Entity Too Large</title></head></html>'
    e = E.from_response('job', 413, None, {}, page)
    assert type(e) is E.QuotaError and e.code == 'payload_too_large' and '不会自动拆分' in str(e)


def test_task_and_job_errors_carry_ids_and_who():
    nf = E.from_response('task', 404, {'error': 'not found', 'code': 'not_found'}, {}, task_id='T9', who=WHO)
    assert nf.task_id == 'T9' and 'T9' in str(nf) and WHO in str(nf)
    tf = E.from_response('result', 422, dispatcher_error('runtime.rejected', '设备拒绝'), {}, task_id='T9')
    assert (tf.task_id, tf.category, tf.detail) == ('T9', 'runtime.rejected', '设备拒绝')
    nr = E.from_response('result', 409, {'task_id': 'T9', 'status': 'Running'}, {}, task_id='T9')
    assert nr.task_status == 'Running'
    jc = E.from_response('job', 409, {'error': 'x', 'code': 'job_closed'}, {}, job_id='j9')
    assert jc.job_id == 'j9' and 'j9' in str(jc) and '新建' in str(jc)


def test_non_json_500_and_nginx_502_page():
    e = E.from_response('other', 500, None, {}, b'Internal Server Error')
    assert type(e) is E.ServerUnavailable and 'Internal Server Error' in str(e)
    page = b'<html>\r\n<head><title>502 Bad Dispatcher</title></head>\r\n<body>' + b'x' * 500 + b'</body></html>'
    e = E.from_response('other', 502, None, {}, page)
    assert type(e) is E.ServerUnavailable and '502 Bad Dispatcher' in str(e)
    assert '\n' not in str(e) and len(str(e)) < 260


def test_non_json_4xx_is_protocol_error():
    e = E.from_response('other', 418, None, {}, b'\xff\xfe teapot')
    assert type(e) is E.ProtocolError and 'teapot' in str(e)


def test_hierarchy():
    assert issubclass(E.SubmitUncertain, E.ServerUnavailable) and E.SubmitUncertain.maybe_submitted
    assert issubclass(E.NotLoggedIn, E.AuthError) and issubclass(E.CredentialsError, E.AuthError)
    assert not issubclass(E.Timeout, TimeoutError)
    for cls in (E.LoginFailed, E.LoginExpired, E.LoginRevoked):
        assert issubclass(cls, E.AuthError)
    for cls in (E.AuthError, E.JobFailed, E.JobCancelled, E.BadRequest, E.PrecheckError, E.QuotaError, E.DeviceUnavailable,
                E.TaskFailed, E.TaskCancelled, E.TaskNotFound, E.NotReady, E.ServerUnavailable, E.ProtocolError,
                E.ClientOutdated, E.Timeout, E.JobClosed, E.JobNotFound, E.NotCancellable):
        assert issubclass(cls, E.QuafuError)
