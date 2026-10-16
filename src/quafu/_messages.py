# -*- coding: utf-8 -*-
"""Message table: every user-facing string the SDK prints or puts in an exception, in English and Chinese.

One entry per message, both languages side by side, so a new message cannot be added in only one of them.
Templates use %-formatting with positional arguments; both languages take the same arguments in the same
order (tests/unit/test_i18n.py checks this, and that every key the code uses exists here).
Wording follows UI-copy conventions: English uses
standard CLI phrasing (sentence case, "log in" / "log out"), Chinese uses 书面、中性 interface wording.
"""

MESSAGES = {
    # ── command line ─────────────────────────────────────────────────
    'cli.description': (
        'Command-line interface for the QUAFU quantum computing platform: log in, log out, show the current '
        'account, and manage settings.',
        'QUAFU 量子计算平台命令行：登录、退出登录、查看当前账号、管理设置。'),
    'cli.metavar.command': ('<command>', '<命令>'),
    'cli.usage': ('usage: ', '用法：'),
    'cli.commands': ('commands', '命令'),
    'cli.arguments': ('arguments', '参数'),
    'cli.options': ('options', '选项'),
    'cli.help.help': ('Show this help message and exit', '显示帮助并退出'),
    'cli.help.version': ('Show the version and exit', '显示版本号并退出'),
    'cli.help.base_url': ('Platform URL. Defaults to the QUAFU_BASE_URL environment variable, then the built-in '
                          'default',
                          '平台地址；不写时读环境变量 QUAFU_BASE_URL，再不写用内置默认值'),
    'cli.help.login': ('Log in (browser login by default: prints a link and tries to open your browser)',
                       '登录（默认网页登录：打印链接并尝试打开浏览器）'),
    'cli.help.api_key': ('Use - to read an API key from standard input and save it (for scripts and CI)',
                         '写 - 表示从标准输入读取 API Key 并保存（用于脚本与 CI）'),
    'cli.help.no_browser': ("Print the link only; don't open a browser", '只打印链接，不自动打开浏览器'),
    'cli.help.force': ('Log in again even if already logged in (switch accounts or renew early)',
                       '已登录时也重新登录（切换账号或提前续期）'),
    'cli.help.logout': ('Log out: remove the login saved on this machine and revoke the browser login',
                        '退出登录：删除本机保存的登录态，并撤销本次网页登录'),
    'cli.help.whoami': ('Show the current account, credential type, and expiry', '显示当前账号、凭证种类与有效期'),
    'cli.help.json': ('Output JSON', '以 JSON 格式输出'),
    'cli.help.config': ('Get or set settings saved on this machine', '查看或修改本机保存的设置'),
    'cli.help.config_get': ('Print the effective value of a setting', '显示一项设置当前生效的值'),
    'cli.help.config_set': ('Set a setting and save it on this machine', '修改一项设置并保存在本机'),
    'cli.help.config_key': ('Setting name: language', '设置项：language'),
    'cli.help.config_value': ('Value. language: en (English) or zh (Chinese)', '值。language：en（英文）或 zh（中文）'),
    'cli.kind.api_key': ('API key', 'API Key'),
    'cli.kind.oauth': ('browser login', '网页登录'),
    'cli.source.argument': ('argument', '参数'),
    'cli.source.env': ('environment variable QUAFU_API_KEY', '环境变量 QUAFU_API_KEY'),
    'cli.source.saved': ('login saved on this machine', '本机保存的登录态'),
    'cli.never_expires': ('never', '不过期'),
    'cli.stdin_empty': ('No API key was read from standard input', '未从标准输入读取到 API Key'),
    'cli.logged_in': ('Logged in as %s (%s)  %s  expires: %s', '已登录：%s（%s）  %s  有效期至 %s'),
    'cli.saved_to': ('Platform %s; login saved to %s', '平台 %s，登录态已保存至 %s'),
    'cli.whoami.account': ('Account     %s (%s)', '账号      %s（%s）'),
    'cli.whoami.platform': ('Platform    %s', '平台      %s'),
    'cli.whoami.credential': ('Credential  %s %s (from %s)', '凭证      %s %s（来自%s）'),
    'cli.whoami.expires': ('Expires     %s', '有效期至  %s'),
    'cli.config.unknown_key': ('Unknown setting %r. Available settings: %s', '未知的设置项 %r。可用的设置项：%s'),
    'cli.config.language_set': ('Display language set to English.', '显示语言已设为中文。'),
    'cli.config.env_overrides': ('Note: QUAFU_LANG=%s is set and takes precedence over the saved setting.',
                                 '注意：已设置环境变量 QUAFU_LANG=%s，它优先于本机保存的设置。'),
    'cli.config.save_failed': ('Could not save settings to %s (%s)', '无法保存设置至 %s（%s）'),
    'cli.error': ('Error: %s', '错误：%s'),
    'cli.interrupted': ('Interrupted', '已中断'),

    # ── language ─────────────────────────────────────────────────────
    'lang.invalid': ('Unsupported language %r. Use en or zh.', '不支持的语言 %r，请使用 en 或 zh。'),

    # ── browser login (oauth.py) ─────────────────────────────────────
    'oauth.html_lang': ('en', 'zh-CN'),
    'oauth.page.not_found.title': ('Page not found', '找不到页面'),
    'oauth.page.not_found.text': ('This address only receives QUAFU login callbacks.', '此地址仅用于接收 QUAFU 登录回调。'),
    'oauth.page.done.title': ('Login already completed', '登录已完成'),
    'oauth.page.done.text': ('This login is already complete. You can close this page.', '本次登录已完成，可以关闭此页面。'),
    'oauth.page.failed.title': ('Login failed', '登录失败'),
    'oauth.page.mismatch.text': ("This callback doesn't match the login in progress in your terminal. Return to the "
                                 'terminal and run quafu login again.',
                                 '回调与终端中正在进行的登录不匹配。请回到终端重新运行 quafu login。'),
    'oauth.page.denied.title': ('Authorization cancelled', '已取消授权'),
    'oauth.page.denied.text': ('QUAFU SDK was not authorized. You can close this page and return to the terminal.',
                               '未授权 QUAFU SDK。可以关闭此页面并返回终端。'),
    'oauth.page.success.title': ('Login successful', '登录成功'),
    'oauth.page.success.text': ('You can close this page and return to your terminal or notebook.',
                                '可以关闭此页面，返回终端或 notebook 继续。'),
    'oauth.page.no_code.text': ('The callback is missing the authorization code. Return to the terminal and run '
                                'quafu login again.',
                                '回调中缺少授权码。请回到终端重新运行 quafu login。'),
    'oauth.paste_incomplete': ('Incomplete authorization code. Paste the full text shown on the page (format: '
                               'code#state). Run quafu login again.',
                               '授权码不完整：请粘贴网页上显示的完整内容（格式为「授权码#校验码」）。请重新运行 quafu login'),
    'oauth.paste_mismatch': ("This authorization code doesn't match the current login and was not used. Run quafu "
                             'login again and paste the code shown on the page it opens.',
                             '授权码与本次登录不匹配，未使用。请重新运行 quafu login，并粘贴本次打开的页面上显示的授权码'),
    'oauth.code_prompt': ('Authorization code: ', '授权码：'),
    'oauth.done_in_browser': ('\nAuthorization completed in the browser.\n', '\n已在浏览器中完成授权。\n'),
    'oauth.done_in_browser_notebook': ('\nAuthorization completed in the browser. You can ignore the input box above.\n',
                                       '\n已在浏览器中完成授权，可忽略上方的输入框。\n'),
    'oauth.denied': ('Authorization was denied in the browser. You are not logged in. To log in, run quafu login '
                     'again.',
                     '已在网页上拒绝授权，未登录。如需登录，请重新运行 quafu login'),
    'oauth.failed': ('Browser login failed (%s). Run quafu login again.', '网页登录失败（%s）。请重新运行 quafu login'),
    'oauth.timeout': ('Browser login timed out (%d minutes). Run quafu login again. On servers, CI, and other '
                      'environments without a browser, create an API key on the website account page and set the '
                      'QUAFU_API_KEY environment variable.',
                      '网页登录超时（%d 分钟）。请重新运行 quafu login。在服务器、CI 等没有浏览器的环境中，建议在网站账户页'
                      '创建 API Key，并设置环境变量 QUAFU_API_KEY'),
    'oauth.open_link': ('Open this link in your browser to log in to QUAFU:\n  %s\n',
                        '请在浏览器中打开以下链接登录 QUAFU：\n  %s\n'),
    'oauth.paste_hint': ('(If the page shows an authorization code after you approve, paste it below and press '
                         'Enter.)\n',
                         '（如果授权后页面显示授权码，请将其粘贴到下方并按回车）\n'),
    'oauth.paste_hint_opened': ('(Browser opened. If the page shows an authorization code after you approve, paste '
                                'it below and press Enter.)\n',
                                '（已尝试自动打开浏览器。如果授权后页面显示授权码，请将其粘贴到下方并按回车）\n'),
    'oauth.open_link_local': ('Open this link in a browser on this machine to log in to QUAFU (valid for %d '
                              'minutes):\n  %s\n',
                              '请在本机浏览器中打开以下链接登录 QUAFU（%d 分钟内有效）：\n  %s\n'),
    # Deliberately written in the *other* language: it is the way out for someone who can't read this one.
    'oauth.lang_hint': ('使用中文请按 Z 并回车。\n', 'Press E then Enter to set English as display language.\n'),
    'oauth.lang_save_failed': ('Could not save the language setting (%s); it applies to this session only.\n',
                               '无法保存语言设置（%s），仅对本次运行生效。\n'),

    # ── client.py ────────────────────────────────────────────────────
    'client.login_expired': ('Your QUAFU browser login expired on %s (browser logins are valid for 90 days and are '
                             'not renewed). Run quafu login to log in again. For long-running scripts, use an API key '
                             'instead (create one on the website account page and set the QUAFU_API_KEY environment '
                             'variable).',
                             'QUAFU 网页登录已于 %s 过期（网页登录有效期 90 天，不续期）。请运行 quafu login 重新登录。'
                             '长期运行的脚本建议改用 API Key（在网站账户页创建，并设置环境变量 QUAFU_API_KEY）'),
    'client.not_logged_in_log': ('Not logged in to QUAFU (%s); not interactive, so no browser login was started',
                                 '未登录 QUAFU（%s）；当前无法交互，未发起网页登录'),
    'client.not_logged_in': ('Not logged in to QUAFU (%s). This environment is not interactive, so a browser login '
                             "can't start. Do one of the following:\n"
                             '  · Run quafu login in a terminal (or quafu.login() in a notebook) and log in in your '
                             'browser\n'
                             '  · Create an API key on the website account page and set the %s environment variable',
                             '未登录 QUAFU（%s）。当前环境无法交互，不能发起网页登录。请任选一种方式：\n'
                             '  · 在终端运行 quafu login（或在 notebook 中执行 quafu.login()），按提示在浏览器中登录\n'
                             '  · 在网站账户页创建 API Key，并设置环境变量 %s'),
    'client.relogin': ('\nLogging in again.\n', '\n正在重新登录。\n'),
    'client.nan_body': ("The request body contains NaN or infinity, which JSON can't represent",
                        '请求体里有 NaN 或无穷，JSON 表示不了'),
    'client.deadline': ('Deadline reached', '等到时限'),
    'client.submit_uncertain': ('The submit request may have reached the platform, but no response was received '
                                '(%s). It was not retried, to avoid a duplicate submission. Check your jobs on the '
                                'website to see whether the job was created.',
                                '提交请求可能已到达平台，但未收到响应（%s）。为避免重复提交，未自动重试。'
                                '请在网站「我的任务」中确认该任务组是否已创建'),
    'client.not_json': ('The platform returned a non-JSON response (HTTP %d): %s', '平台返回的不是 JSON（HTTP %d）：%s'),
    'client.json_not_object': ('The platform returned JSON that is not an object (HTTP %d): %s',
                               '平台返回的 JSON 不是对象（HTTP %d）：%s'),
    'client.redirect': ("The platform returned a redirect (HTTP %d → %s). The SDK doesn't follow redirects. Check "
                        'the platform URL (QUAFU_BASE_URL).',
                        '平台返回了跳转（HTTP %d → %s），SDK 不跟随跳转。请检查平台地址（QUAFU_BASE_URL）'),
    'client.who_not_logged_in': ('not logged in', '未登录'),
    'client.oauth_revoked': ('Your browser login is no longer valid; it may have been revoked on the website (%s). '
                             'Run quafu login to log in again.',
                             '网页登录已失效，可能已在网站上撤销（%s）。请运行 quafu login 重新登录'),
    'client.empty_circuits': ('The circuit list is empty', '线路列表为空'),
    'client.where_circuit': ('Circuit', '线路'),
    'client.where_circuit_n': ('Circuit %d', '第 %d 条线路'),
    'client.template_type': ('template must be an OpenQASM 2.0 template string, with {{name}} at each parameter '
                             'position',
                             'template 应为 OpenQASM 2.0 模板文本，参数位置写 {{参数名}}'),
    'client.target_required': ('Specify a target, such as sim, Dongling, or Dongling-sim. See quafu.devices() for '
                               'available names.',
                               '请指定 target，例如 sim、Dongling、Dongling-sim。可用的名称见 quafu.devices()'),
    'client.compiler_invalid': ('compiler must be %s; got %r', 'compiler 只能是 %s，当前为 %r'),
    'client.missing_job_id': ('Submit succeeded, but the response has no job ID: %s', '提交成功，但响应中缺少任务组号：%s'),
    'client.job_id_type': ('The job ID must be a string, such as job.id returned by submit()',
                           '任务组号应为字符串，例如 submit() 返回的 job.id'),
    'client.expiring': ('Your QUAFU login expires on %s. Run quafu login to log in again.\n',
                        'QUAFU 登录将于 %s 过期，运行 quafu login 可重新登录\n'),
    'client.invalid_grant': ('The authorization code is invalid, already used, or expired (codes are valid for 5 '
                             'minutes). Run quafu login again.',
                             '授权码无效、已使用或已过期（5 分钟内有效）。请重新运行 quafu login'),
    'client.token_failed': ('Could not get a login token (HTTP %s, %s). Run quafu login again.',
                            '获取登录令牌失败（HTTP %s，%s）。请重新运行 quafu login'),
    'client.unknown_error': ('unknown error', '未知错误'),
    'client.token_bad_format': ('Unrecognized token response from the platform (access_token is missing or the '
                                'token type is not Bearer)',
                                '平台返回的令牌格式无法识别（缺少 access_token 或类型不是 Bearer）'),
    'client.token_no_expiry': ('The token returned by the platform has no expiry', '平台返回的令牌缺少有效期'),
    'client.web_logged_in': ('Logged in as %s (%s); expires %s\n', '已登录：%s（%s），有效期至 %s\n'),
    'client.revoke_failed_log': ('Could not revoke the old browser login token (%s)', '撤销旧的网页登录令牌没有成功（%s）'),
    'client.env_key_set': ('Note: the %s environment variable is set and takes precedence over the saved login\n',
                           '注意：已设置环境变量 %s，它优先于本机保存的登录态\n'),
    'client.logout_none': ('No login is saved on this machine for %s.', '本机未保存 %s 的登录态。'),
    'client.logout_oauth': ('Logged out. The login saved on this machine was removed. %s',
                            '已退出登录，本机登录态已删除。%s'),
    'client.logout_revoked': ('The login was revoked on the platform.', '平台上的本次登录已撤销。'),
    'client.logout_revoke_failed': ("Couldn't reach the platform to revoke this login. Revoke it under signed-in "
                                    'devices on the website.',
                                    '无法连接平台撤销本次登录，请在网站「已登录的设备」中撤销。'),
    'client.logout_api_key': ('Removed the API key saved on this machine. The key is still valid; to invalidate it, '
                              'disable or delete it on the website account page.',
                              '已删除本机保存的 API Key。该 Key 仍然有效，如需作废，请在网站账户页停用或删除。'),
    'client.logout_env_note': ('\nNote: the %s environment variable is still set, and the SDK will keep using it.',
                               '\n注意：环境变量 %s 仍已设置，SDK 将继续使用它。'),

    # ── errors.py ────────────────────────────────────────────────────
    'errors.auth.invalid_api_key': ('Invalid credential (%s): the API key may have been disabled or deleted, or the '
                                    'browser login revoked. Run quafu login to log in again, or check the '
                                    'QUAFU_API_KEY environment variable.',
                                    '凭证无效（%s）：API Key 可能已停用或删除，网页登录可能已撤销。'
                                    '请运行 quafu login 重新登录，或检查环境变量 QUAFU_API_KEY'),
    'errors.auth.session_required': ("This action requires logging in on the website; the SDK doesn't support it "
                                     '(%s)',
                                     '该操作只能在网站上登录后进行，SDK 不支持（%s）'),
    'errors.auth.unauthenticated': ('Invalid credential (%s). Check that the platform URL (QUAFU_BASE_URL) is '
                                    'correct, or run quafu login to log in again.',
                                    '凭证无效（%s）。请检查平台地址（QUAFU_BASE_URL）是否正确，或运行 quafu login 重新登录'),
    'errors.auth.generic': ('Authentication failed (%s): %s', '未通过鉴权（%s）：%s'),
    'errors.job.closed': ('Job %s is closed and cannot accept more tasks. Create a new job.',
                          '任务组 %s 已关闭，不能再追加；新建一个任务组'),
    'errors.job.not_iterative': ('Job %s is not iterative and cannot accept more tasks', '任务组 %s 不是迭代式，不能追加'),
    'errors.job.no_template': ('Job %s has no template; append circuits instead', '任务组 %s 没有模板，只能按 circuits 追加'),
    'errors.not_cancellable.collecting': ('results are being collected; wait for the result', '正在取回结果，等它出结果即可'),
    'errors.not_cancellable.finished': ('it has already finished', '已经完成'),
    'errors.not_cancellable.failed': ('it has already failed', '已经失败'),
    'errors.not_cancellable.other': ('results are being collected, or it has already finished or failed',
                                     '已在取回结果，或已完成 / 已失败'),
    'errors.not_cancellable': ('Task %s can no longer be cancelled: %s (%s)', '任务 %s 已无法取消：%s（%s）'),
    'errors.too_large_hint': ("The SDK doesn't split requests automatically. Reduce the number or size of circuits "
                              'and submit them as several jobs.',
                              'SDK 不会自动拆分，请减少线路数或线路大小后分成几个作业提交'),
    'errors.limit.sim_timeout': ('the simulation exceeded the wall-clock limit of %s seconds', '模拟超过墙钟上限 %s 秒'),
    'errors.limit.sim_memory': ('the simulation exceeded the memory limit of %s MB', '模拟超过内存上限 %s MB'),
    'errors.paren': (' (%s)', '（%s）'),
    'errors.payload_413': ('The request body exceeds the platform limit (HTTP 413). %s',
                           '请求体超过平台的上限（HTTP 413）；%s'),
    'errors.unavailable': ('The platform is temporarily unavailable (HTTP %d): %s', '平台暂时不可用（HTTP %d）：%s'),
    'errors.unrecognized': ('Unrecognized response from the platform (HTTP %d): %s', '无法识别平台的响应（HTTP %d）：%s'),
    'errors.outdated': ('The platform requires a newer SDK: pip install -U quafu-sdk (%s)',
                        '平台要求更新 SDK：pip install -U quafu-sdk（%s）'),
    'errors.task_cancelled': ('Task %s was cancelled and has no result', '任务 %s 已取消，没有结果'),
    'errors.not_ready': ('Task %s is not finished yet (%s)', '任务 %s 还没完成（%s）'),
    'errors.not_terminal': ('not in a final state', '未到终态'),
    'errors.task_failed': ('Task %s failed [%s]: %s%s', '任务 %s 失败 [%s]：%s%s'),
    'errors.task_not_found': ("Task %s doesn't exist or doesn't belong to the current account (key %s)",
                              '任务 %s 不存在，或不属于当前账号（key %s）'),
    'errors.job_not_found': ("Job %s doesn't exist or doesn't belong to the current account (key %s)",
                             '任务组 %s 不存在，或不属于当前账号（key %s）'),
    'errors.no_such_object': ('object not found', '没有这个对象'),
    'errors.no_endpoint': ('The platform has no such endpoint (HTTP 404). Check that the platform URL '
                           '(QUAFU_BASE_URL) is correct.',
                           '平台上没有这个端点（HTTP 404）；检查平台地址（QUAFU_BASE_URL）是否指对了'),
    'errors.quota': ('Quota or limit exceeded [%s]: %s%s', '超出额度或上限 [%s]：%s%s'),
    'errors.quota.limit_tail': (' (limit %s). %s', '（上限 %s）；%s'),
    'errors.quota.see_docs': ('see the platform documentation', '见平台说明'),
    'errors.quota.too_many_jobs_tail': (" (%s created today; daily limit %s). The SDK doesn't retry automatically; "
                                        'combine circuits into fewer jobs.',
                                        '（今天已建 %s 个，每天上限 %s）；SDK 不会自动重试，把线路合进更少的任务组'),
    'errors.quota.retry_tail': ('; retry in about %d seconds', '，约 %d 秒后可重试'),
    'errors.quota.daily_cap': ('daily hard cap reached: %s tasks submitted today, the cap is %s (normal quota %s; '
                               'tasks beyond the normal quota are still accepted, at the lowest priority). '
                               'The count resets at %s Beijing time',
                               '今日已交 %s 条，达到每日硬上限 %s 条（正常额度 %s 条，超出的部分照常接收、排在最低优先级）。'
                               '北京时间 %s 重置'),
    'errors.quota.reset_in': (' (in about %s).', '，约 %s后可再提交。'),
    'errors.quota.end': ('.', '。'),
    'errors.quota.too_many_at_once': ('this request has %s tasks, more than the daily hard cap of %s. '
                                      'Split it into smaller submissions.',
                                      '本次要交 %s 条，超过每日硬上限 %s 条，请拆小再交。'),
    'errors.quota.paused': ('this backend is not accepting tasks right now; try again later.',
                            '这种后端暂停收单，请稍后再试。'),
    'errors.quota.wait_s': ('%d seconds', '%d 秒'),
    'errors.quota.wait_min': ('%d minutes', '%d 分钟'),
    'errors.quota.wait_h': ('%s hours', '%s 小时'),
    'errors.precheck': ('Precheck failed [%s]: %s%s', '预检未通过 [%s]：%s%s'),
    'errors.precheck.sep': ('; ', '；'),
    'errors.precheck.reason': ('reason: %s', '原因：%s'),
    'errors.precheck.unmeasured': ('real devices require every classical bit to be written once by measure; classical '
                                   'bits not written: %s (simulators are exempt)',
                                   '真机要求每个经典位都被 measure 写入一次，没写入的经典位：%s（模拟器不受此限）'),
    'errors.precheck.see_cbits': ('see vars.cbits', '见 vars.cbits'),
    'errors.precheck.measurement_order': ('real devices require measure statements in ascending classical-bit order '
                                          '(simulators are exempt)',
                                          '真机要求 measure 语句按经典位下标升序出现（模拟器不受此限）'),
    'errors.precheck.sim_estimate': ('%s active qubits; the %s method needs an estimated %s MB; limit %s MB',
                                     '活跃比特 %s，按 %s 估算要 %s MB，上限 %s MB'),
    'errors.precheck.qubits': ('%s qubits; limit %s', '比特数 %s，上限 %s'),
    'errors.precheck.limits_url': ('limits: GET %s', '各项上限见 GET %s 的 limits'),
    'errors.precheck.missing_params': ('the job declares no parameters; declare parameter names and units before '
                                       'submitting circuits with parameter values',
                                       '任务组没有声明 parameters，带参数值的线路要先声明参数与单位'),
    'errors.precheck.undeclared': ('undeclared parameters: %s', '未声明的参数：%s'),
    'errors.forbidden': ('Permission denied [%s]: %s', '没有权限 [%s]：%s'),
    'errors.device_unavailable': ('Device unavailable: %s', '设备暂不可用：%s'),
    'errors.device_unavailable.jiuding_sim': ('the Jiuding simulator %s has no simulator ready right now; '
                                              'try again in a few minutes',
                                              '九鼎模拟 %s 此刻没有就绪的模拟器，请过几分钟再试'),
    'errors.field': (' (field %s)', '（字段 %s）'),
    'errors.bad_request': ('Invalid request [%s]: %s%s', '请求不合法 [%s]：%s%s'),
    'errors.server': ('Platform error (HTTP %d) [%s]: %s', '平台出错（HTTP %d）[%s]：%s'),

    # ── local limit check (_limits.py) ───────────────────────────────
    'limits.where_n': ('circuit #%d: ', '第 %d 条线路：'),
    'limits.how_declared': ('counted as the declared width', '按线路声明的宽度数'),
    'limits.how_active': ('counted as the qubits touched by gates', '按被门碰过的比特数'),
    'limits.qubits': ('%starget %s allows at most %s qubits (%s); this circuit has %s. Not submitted. '
                      'Limits: GET %s (limits)',
                      '%s目标 %s 最多 %s 个比特（%s），这条线路有 %s 个，未提交。各项上限以 GET %s 的 limits 为准'),
    'limits.shots_range': ('%sshots for target %s must be between %s and %s; got %s. Not submitted. '
                           'Limits: GET %s (limits)',
                           '%s目标 %s 的 shots 须在 %s 到 %s 之间，收到 %s，未提交。各项上限以 GET %s 的 limits 为准'),
    'limits.shots_step': ('%sshots for target %s must be a multiple of %s; got %s. Not submitted. '
                          'Limits: GET %s (limits)',
                          '%s目标 %s 的 shots 须是 %s 的整数倍，收到 %s，未提交。各项上限以 GET %s 的 limits 为准'),

    # ── credentials.py ───────────────────────────────────────────────
    'cred.what.api_key': ('API key', 'API Key'),
    'cred.what.oauth': ('Browser login token', '网页登录令牌'),
    'cred.not_str': ('%s must be a string', '%s 应为字符串'),
    'cred.empty': ('%s is empty', '%s 为空'),
    'cred.prefix': ('%s must start with %s. Copy the full value from the website account page.',
                    '%s 应以 %s 开头，请从网站账户页复制完整内容'),
    'cred.charset': ('%s may contain only letters and digits after %s. Check for extra spaces, quotes, or line breaks.',
                     '%s 在 %s 之后只能包含字母和数字，请检查是否多复制了空格、引号或换行'),
    'cred.unknown_kind': ('Unknown credential kind %r', '凭证种类 %r 不认识'),
    'cred.dir_outside_home': ('Credentials directory %s is outside your home directory; make sure other users '
                              "can't read it",
                              '凭证目录 %s 在用户主目录之外，确认它不是多人可读的位置'),
    'cred.hint': ('Credentials file %s %s. Delete the file and run quafu login again, or set %s to use a different '
                  'directory.',
                  '凭证文件 %s %s。请删除该文件后重新运行 quafu login，或设置 %s 改用其他目录'),
    'cred.symlink_read': ("is a symbolic link; the SDK doesn't read credentials from symbolic links",
                          '是符号链接，SDK 不从符号链接读取凭证'),
    'cred.symlink_write': ("is a symbolic link; the SDK doesn't write credentials to symbolic links",
                           '是符号链接，SDK 不向符号链接写入凭证'),
    'cred.unreadable': ("can't be read (%s)", '无法读取（%s）'),
    'cred.unwritable': ("can't be written (%s)", '无法写入（%s）'),
    'cred.bad_format': ('has an unrecognized format', '格式无法识别'),
    'cred.bad_version': ('has an unrecognized version %r (this SDK supports %d); it may have been written by a newer '
                         'SDK',
                         '的版本 %r 无法识别（本 SDK 支持 %d），可能由更新版本的 SDK 写入'),
    'cred.entry_incomplete': ('has an incomplete entry for %s', '中 %s 的条目不完整'),
    'cred.entry_bad': ('has a malformed entry for %s', '中 %s 的条目格式不正确'),
    'env_var': ('Environment variable %s: %s', '环境变量 %s：%s'),

    # ── config.py ────────────────────────────────────────────────────
    'config.empty': ('The platform URL is empty', '平台地址为空'),
    'config.bad_format': ('Invalid platform URL: %s', '平台地址格式不正确：%s'),
    'config.need_host': ('The platform URL must look like https://hostname; got %s', '平台地址应为 https://主机名 的形式，当前为 %s'),
    'config.https_required': ('The platform URL must use https (except loopback addresses); got %s. Plain http would '
                              'expose login credentials on the network.',
                              '平台地址必须使用 https（本机回环地址除外），当前为 %s。明文 http 会在网络上暴露登录凭证'),
    'config.no_path': ('The platform URL must contain only the host, with no path, for example %s; got %s',
                       '平台地址只写到主机名，不带路径，例如 %s；当前为 %s'),
    'config.no_userinfo': ('The platform URL must not contain a username or password', '平台地址中不能包含用户名或密码'),

    # ── transport.py ─────────────────────────────────────────────────
    'transport.proxy_http_only': ('Only HTTP proxies are supported; write host:port: %s', '代理只支持 HTTP 代理，写成 host:port：%s'),
    'transport.proxy_port': ('Invalid proxy port: %s', '代理端口不对：%s'),
    'transport.ca_unreadable': ("Can't read the CA certificate file %s (%s)", '读不了 CA 证书文件 %s（%s）'),
    'transport.via_proxy': ('via proxy %s:%d', '经代理 %s:%d'),
    'transport.no_proxy': ('no proxy', '未经代理'),
    'transport.cert_failed': ('Certificate verification failed for platform %s (%s). For a self-signed certificate, '
                              'pass Client(ca_bundle=...) or set QUAFU_CA_BUNDLE to the PEM file. The SDK has no '
                              'option to turn off verification.',
                              '平台 %s 的证书校验失败（%s）。自签证书请用 Client(ca_bundle=...) '
                              '或环境变量 QUAFU_CA_BUNDLE 指向那份 PEM；SDK 不提供关闭校验的开关'),
    'transport.no_response': ('did not respond within %g seconds', '在 %g 秒内没有应答'),
    'transport.connect_timeout': ("couldn't be reached within %g seconds", '%g 秒内连不上'),
    'transport.timeout': ('Platform %s %s (%s)', '平台 %s %s（%s）'),
    'transport.connect_failed': ("Can't connect to platform %s (%s, %s)", '连不上平台 %s（%s，%s）'),
    'transport.proxy_hint': ('. If you need a proxy, set QUAFU_PROXY=host:port', '。如需经代理访问，请设置环境变量 QUAFU_PROXY=主机:端口'),
    'transport.bad_http': ('Platform %s disconnected or sent a malformed HTTP response (%s, %s)',
                           '平台 %s 中途断开或回了坏的 HTTP（%s，%s）'),
    'transport.comm_error': ('Error communicating with platform %s (%s)', '与平台 %s 通信出错（%s）'),

    # ── jobs.py / tables.py ──────────────────────────────────────────
    'jobs.no_bit_order': ("The platform didn't declare the bit order (bit_order) of this result, so bits can't be "
                          'reordered',
                          '平台未声明这份结果的位序（bit_order），无法按比特重排'),
    'jobs.no_measurements': ("This result has no measurements (classical bit → physical qubit), so counts can't be "
                             'selected by physical qubit',
                             '这份结果没有 measurements（经典位 → 物理比特），无法按物理比特取数'),
    'jobs.cancelled': ('Task %s was cancelled and has no result', '任务 %s 已取消，无结果'),
    'jobs.retry_yes': ('can be resubmitted as is', '可原样重新提交'),
    'jobs.retry_no': ("resubmitting as is won't succeed; change the circuit or parameters",
                      '原样重新提交不会成功，请修改线路或参数'),
    'jobs.failed': ('Task %s failed [%s]: %s%s%s', '任务 %s 失败 [%s]：%s%s%s'),
    'jobs.progress': ('Job %s has been waiting for %d minutes: %s, %s / %s finished', '任务组 %s 已等 %d 分钟：%s，完成 %s / %s'),
    'jobs.stopped': ('Stopped waiting; job %s is still on the platform. Use quafu.job(%r) to resume.',
                     '已停止等待；任务组 %s 仍在平台上，quafu.job(%r) 可以接回'),
    'jobs.timeout': ('After waiting %g seconds, job %s is still not finished (%s). It is still running on the '
                     'platform; call result() or wait() again to keep waiting.',
                     '等待 %g 秒后任务组 %s 仍未结束（%s）。任务组仍在平台上运行，可再次调用 result() 或 wait() 继续等待'),
    'jobs.status_unknown': ('status unknown', '状态未知'),
    'jobs.result_single': ('Job %s has %s circuits; result() only works for single-circuit jobs. Use results().',
                           '任务组 %s 包含 %s 条线路，result() 仅适用于单条线路的任务组，请使用 results()'),
    'jobs.circuits_or_points': ('Give exactly one of circuits and points', 'circuits 与 points 只能给一个'),
    'tables.no_bit_order': ("The platform didn't declare the bit order (bit_order), so bits can't be reordered",
                            '平台未声明位序（bit_order），无法按比特重排'),
    'tables.need_pandas': ('to_pandas requires pandas. Install it with pip install pandas, or use to_dict().',
                           'to_pandas 需要 pandas，请先安装：pip install pandas（或改用 to_dict()）'),

    # ── bits.py ──────────────────────────────────────────────────────
    'bits.bad_key': ('Invalid counts key %r: it must be a bit string of 0s and 1s with no spaces',
                     'counts 的键 %r 不合规范：应是只含 0 和 1、不含空格的比特串'),
    'bits.key_length': ('Key %r has length %d, but n_clbits=%d', '键 %r 的长度 %d 与 n_clbits=%d 不符'),
    'bits.unknown_order': ('Unknown bit order %r (this SDK supports %s). Upgrade quafu-sdk.',
                           '不认识的位序 %r（本 SDK 认 %s），请升级 quafu-sdk'),
    'bits.cbit_range': ('Classical bit %d is out of range (this result has %d bits)', '经典位 %d 超出范围（这份结果只有 %d 位）'),
    'bits.order_type': ('order must be a list of classical bit indices or one of %s', 'order 写经典位下标列表，或 %s 之一'),
    'bits.not_measured': ('Physical qubits %s were not measured (not in measurements)',
                          '物理比特 %s 没有被测量（measurements 里没有它）'),
    'bits.zero_total_norm': ("The total of counts is 0, so it can't be normalized", 'counts 总数为 0，不能归一化'),
    'bits.zero_total_exp': ("The total of counts is 0, so the expectation value can't be computed",
                            'counts 总数为 0，不能算期望值'),

    # ── _inputs.py / _qasm.py ────────────────────────────────────────
    'inputs.not_number': ('%s must be a number; got %r', '%s 应为数值，当前为 %r'),
    'inputs.overflow': ('%s is out of double-precision range', '%s 超出双精度范围'),
    'inputs.not_finite': ('%s must not be NaN or infinity', '%s 不能为 NaN 或无穷'),
    'inputs.index_range': ('%s must be between 0 and %d; got %d', '%s 应在 0..%d 之间，当前为 %d'),
    'inputs.param_unknown_fields': ('Unrecognized fields in a parameter declaration: %s', '参数声明中有无法识别的字段：%s'),
    'inputs.param_shape': ('Each item in parameters must be {"name": ..., "unit": ...} or (name, unit); unit is '
                           'required (use "1" for dimensionless)',
                           'parameters 每项应为 {"name": ..., "unit": ...} 或 (name, unit)；unit 必填，无量纲写 "1"'),
    'inputs.param_required': ('A parameter declaration needs name and unit (use "1" for dimensionless): %r',
                              '参数声明须包含 name 与 unit（无量纲写 "1"）：%r'),
    'inputs.circuit_type': ('A circuit item must be OpenQASM 2.0 text, a qiskit.QuantumCircuit, or {"qasm": ...}; '
                            'for parameterized Qiskit circuits, use quafu.qiskit.sweep',
                            '线路项应为 OpenQASM 2.0 文本、qiskit.QuantumCircuit 或 {"qasm": ...}；'
                            'Qiskit 参数化线路请用 quafu.qiskit.sweep'),
    'inputs.circuit_unknown_fields': ('Unrecognized fields in a circuit item: %s', '线路项中有无法识别的字段：%s'),
    'inputs.qasm_type': ('The qasm of a circuit item must be OpenQASM 2.0 text', '线路项的 qasm 应为 OpenQASM 2.0 文本'),
    'qasm.empty': ('%s is an empty string', '%s为空字符串'),
    'qasm.type': ('%s must be OpenQASM 2.0 text (str) or a qiskit.QuantumCircuit; got %s. To use Qiskit circuits, '
                  'install: %s',
                  '%s应为 OpenQASM 2.0 文本（str）或 qiskit.QuantumCircuit，当前为 %s。使用 Qiskit 线路需先安装：%s'),

    # ── quafu.qiskit ─────────────────────────────────────────────────
    'qiskit.need_qiskit': ('The Qiskit adapter requires qiskit. Install it with: pip install "quafu-sdk[qiskit]"',
                           'Qiskit 适配需要 qiskit，请先安装：pip install "quafu-sdk[qiskit]"'),
    'qiskit.no_topology': ("The platform hasn't provided the topology of %s (coupling_map is empty), so the Target "
                           "is fully connected: local transpile won't route for the chip's connectivity",
                           '平台还没给 %s 的拓扑（coupling_map 为空），Target 按全连通装：本地 transpile 不会按芯片连通性布线'),
    'qiskit.no_params': ('The circuit has no unbound parameters; submit circuits without parameters with quafu.submit',
                         '线路中没有未绑定的参数；不带参数的线路请直接用 quafu.submit'),
    'qiskit.names_count': ('names must give %d names in the order of qc.parameters (%s)',
                           'names 应按 qc.parameters 的顺序给出 %d 个名字（%s）'),
    'qiskit.point_len': ('points[%d] has %d values, but the circuit has %d parameters (%s)',
                         'points[%d] 有 %d 个值，而线路有 %d 个参数（%s）'),
    'qiskit.run_options': ("QuafuBackend.run doesn't support these options: %s", 'QuafuBackend.run 不支持以下参数：%s'),
    'qiskit.failed_count': ('%d / %d circuits failed', '%d / %d 条线路失败'),
    'qiskit.no_result': ('Job %s has no result for circuit %d', '任务组 %s 的第 %d 条线路没有结果'),

    # ── _conflict.py ─────────────────────────────────────────────────
    'conflict.list_sep': (', ', '、'),
    'conflict.foreign_files': ('files in the quafu directory that do not belong to quafu-sdk: %s',
                               'quafu 目录中有不属于 quafu-sdk 的文件：%s'),
    'conflict.message': ('Another package that uses the name quafu is installed in this Python environment (%s). '
                         "The two packages overwrite each other's files, so QUAFU SDK can't work reliably. Create a "
                         'clean virtual environment with uv (https://docs.astral.sh/uv/) and install again:\n%s',
                         '检测到当前 Python 环境里还装了另一个占用 quafu 名字的包（%s），两者会互相覆盖文件，'
                         'QUAFU SDK 无法可靠工作。请用 uv（https://docs.astral.sh/uv/）新建一个干净的虚拟环境再安装：\n%s'),
}
