# -*- coding: utf-8 -*-
"""命令行 quafu：login / logout / whoami / config。

界面语言（英文默认 / 中文）见 _i18n；quafu config get|set language 读写本机设置。

退出码：0 成功；1 SDK 报的错（含同名包冲突）；2 用法错误；130 Ctrl-C。
不能交互又没登录（NotLoggedIn / LoginExpired）时，说明打到 stdout 而不是 stderr，退出码 1。

本模块顶层只 import 标准库、_conflict 与 _i18n（两者也只用标准库）：别的包后装、盖掉了本包的 __init__ 时，命令行仍能走到冲突检查、
报清楚的错，而不是在 import 别的模块时甩出 Python 栈。其余模块都在 main() 里检查过之后再 import。"""
import argparse
import json
import os
import sys

from ._conflict import ConflictError, check as check_conflict
from ._i18n import safe_streams, t

VERSION = '0.2.7'                   # 与 quafu.__version__ 同值（测试核对）；这里不 import quafu 取它，理由见上

# 测试注入传输层用；正常运行恒为 None（走真实网络）
_transport = None

# quafu config 认的设置项。目前只有 language；照 gh / npm / git 的 config get|set 写法，以后加设置项不用加顶层命令
SETTINGS = ('language',)


def _kind(kind):
    return t('cli.kind.' + kind) if kind in ('api_key', 'oauth') else kind


def _source(source):
    return t('cli.source.' + source) if source in ('argument', 'env', 'saved') else source


def _when(iso):
    from .client import _date
    return _date(iso) if iso else t('cli.never_expires')


def _quafu_error():
    from .errors import QuafuError
    return QuafuError


def cmd_login(args):
    from .client import login
    from .errors import QuafuError
    key = None
    if args.api_key == '-':
        key = sys.stdin.readline()
        if not key.strip():
            raise QuafuError(t('cli.stdin_empty'))
    info = login(key, force=args.force, open_browser=not args.no_browser, base_url=args.base_url,
                 _transport=_transport, _announce=False)
    print(t('cli.logged_in', info.get('name') or '', info.get('public_id') or '', _kind(info['kind']),
            _when(info.get('expires_at'))))
    print(t('cli.saved_to', info['base_url'], info['saved_to']))


def cmd_logout(args):
    from .client import logout
    print(logout(base_url=args.base_url, _transport=_transport)['message'])


def cmd_whoami(args):
    from .client import Client
    info = Client(base_url=args.base_url, _transport=_transport).whoami()
    if args.json:
        print(json.dumps(info, ensure_ascii=False, indent=2))
        return
    print(t('cli.whoami.account', info.get('name') or '', info.get('public_id') or ''))
    print(t('cli.whoami.platform', info['base_url']))
    print(t('cli.whoami.credential', _kind(info['kind']), info['credential'], _source(info['source'])))
    print(t('cli.whoami.expires', _when(info.get('expires_at'))))


def _check_setting(key):
    from .errors import QuafuError
    if key not in SETTINGS:
        raise QuafuError(t('cli.config.unknown_key', key, ', '.join(SETTINGS)))


def _env_note(saved):
    """QUAFU_LANG 盖过本机保存的设置时提示一句（stderr，不进 stdout，方便脚本取值）。"""
    from . import _i18n
    lang, source = _i18n.resolve()
    if source == 'env' and lang != saved:
        sys.stderr.write(t('cli.config.env_overrides', os.environ.get(_i18n.ENV_LANG)) + '\n')


def cmd_config_get(args):
    """打印当前生效的值（en / zh），与 git / gh / npm 的 config get 一样只输出值本身。"""
    from . import _i18n
    _check_setting(args.key)
    print(_i18n.get_language())
    _env_note(_i18n.saved_language())


def cmd_config_set(args):
    from . import _i18n
    from .errors import QuafuError
    _check_setting(args.key)
    code = _i18n.normalize(args.value)
    if code is None:
        raise QuafuError(t('lang.invalid', args.value))
    try:
        _i18n.save_language(code)
    except OSError as e:
        raise QuafuError(t('cli.config.save_failed', _i18n.settings_path(), type(e).__name__)) from None
    if _i18n.resolve()[1] != 'env':
        print(t('cli.config.language_set'))
    else:                       # 环境变量仍盖着：确认句用将来生效的语言说不准，改为说明原因
        _env_note(code)


class _Formatter(argparse.HelpFormatter):
    """帮助里 argparse 自带的「usage:」也跟界面语言走。"""

    def add_usage(self, usage, actions, groups, prefix=None):
        # prefix='' 是 argparse 自己在算子命令的 prog，不能动
        return super().add_usage(usage, actions, groups, t('cli.usage') if prefix is None else prefix)


def _parser(factory, positionals_key, **kw):
    """建一个 parser：-h 的说明、两个参数分组的标题都用消息表里的文案（argparse 自带的是英文）。"""
    p = factory(add_help=False, formatter_class=_Formatter, **kw)
    p._positionals.title = t(positionals_key)
    p._optionals.title = t('cli.options')
    p.add_argument('-h', '--help', action='help', help=t('cli.help.help'))
    return p


def build_parser():
    p = _parser(argparse.ArgumentParser, 'cli.commands', prog='quafu', description=t('cli.description'))
    p.add_argument('--version', action='version', version='quafu-sdk %s' % VERSION, help=t('cli.help.version'))
    p.add_argument('--base-url', metavar='URL', default=None, help=t('cli.help.base_url'))
    sub = p.add_subparsers(dest='cmd', metavar=t('cli.metavar.command'))

    def add(name, help_key):
        return _parser(sub.add_parser, 'cli.arguments', name=name, help=t(help_key), description=t(help_key))

    s = add('login', 'cli.help.login')
    s.add_argument('--api-key', choices=['-'], help=t('cli.help.api_key'))
    s.add_argument('--no-browser', action='store_true', help=t('cli.help.no_browser'))
    s.add_argument('--force', action='store_true', help=t('cli.help.force'))
    s.set_defaults(func=cmd_login)

    s = add('logout', 'cli.help.logout')
    s.set_defaults(func=cmd_logout)

    s = add('whoami', 'cli.help.whoami')
    s.add_argument('--json', action='store_true', help=t('cli.help.json'))
    s.set_defaults(func=cmd_whoami)

    s = add('config', 'cli.help.config')
    s._positionals.title = t('cli.commands')
    csub = s.add_subparsers(dest='config_cmd', metavar=t('cli.metavar.command'))
    s.set_defaults(func=lambda args, cp=s: cp.print_help() or 2)
    for name, help_key, func in (('get', 'cli.help.config_get', cmd_config_get),
                                 ('set', 'cli.help.config_set', cmd_config_set)):
        c = _parser(csub.add_parser, 'cli.arguments', name=name, help=t(help_key), description=t(help_key))
        c.add_argument('key', metavar='KEY', help=t('cli.help.config_key'))
        if name == 'set':
            c.add_argument('value', metavar='VALUE', help=t('cli.help.config_value'))
        c.set_defaults(func=func)
    return p


def main(argv=None):
    safe_streams()              # 重定向到 cp1252 这类写不出中文的编码时换成「?」，不崩
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, 'func', None):
        parser.print_help()
        return 2
    try:
        check_conflict(os.path.dirname(os.path.abspath(__file__)))
    except ConflictError as e:
        sys.stderr.write(t('cli.error', e) + '\n')
        return 1
    QuafuError = _quafu_error()
    from .errors import LoginExpired, NotLoggedIn
    try:
        return args.func(args) or 0
    except (NotLoggedIn, LoginExpired) as e:
        # 不能交互又没登录：说明打到 stdout（计划任务、后台脚本常常只收 stdout），同时 SDK 已记了一条 WARNING 日志
        print(t('cli.error', e))
        return 1
    except QuafuError as e:
        sys.stderr.write(t('cli.error', e) + '\n')
        return 1
    except KeyboardInterrupt:
        sys.stderr.write('\n' + t('cli.interrupted') + '\n')
        return 130


if __name__ == '__main__':
    sys.exit(main())
