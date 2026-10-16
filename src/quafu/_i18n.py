# -*- coding: utf-8 -*-
"""Display language: English (default) or Chinese, for CLI output, login prompts and exception messages.

Which language, first match wins:
  1. quafu.set_language('zh')       this process only, not saved (an explicit call in code, like an argument)
  2. environment variable QUAFU_LANG  en / zh; also en_US, zh_CN, zh-CN, zh_CN.UTF-8 …; anything else is ignored
  3. saved setting                    ~/.quafu-sdk/config.json (QUAFU_CONFIG_DIR moves the directory), written by
                                      `quafu config set language zh` or by pressing Z / E during a browser login;
                                      kept apart from credentials.json and not split by BASE_URL
  4. default                          en. The system locale is never consulted: English is the default.

Standard library only, and no imports from the rest of the package: _conflict uses it before anything else loads.
Message text lives in _messages.py."""
import json
import os

from ._messages import MESSAGES

LANGUAGES = ('en', 'zh')
DEFAULT = 'en'
ENV_LANG = 'QUAFU_LANG'
ENV_CONFIG_DIR = 'QUAFU_CONFIG_DIR'
DIR_NAME = '.quafu-sdk'
SETTINGS_FILE = 'config.json'
SETTINGS_VERSION = 1
_INDEX = {'en': 0, 'zh': 1}

_override = None                # set_language() in this process
_cache = [None, None, None]     # [path, mtime_ns, language]: one stat per lookup instead of reading the file


def normalize(value):
    """'zh' / 'zh_CN' / 'zh-CN' / 'zh_CN.UTF-8' / 'ZH' → 'zh'; same for en. Anything else → None."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower().split('.')[0].split('@')[0].replace('_', '-')
    base = v.split('-')[0]
    return base if base in LANGUAGES else None


def config_root():
    """The SDK's directory on this machine: QUAFU_CONFIG_DIR, else ~/.quafu-sdk. Credentials and settings both live here."""
    d = os.environ.get(ENV_CONFIG_DIR)
    if d:
        return os.path.abspath(os.path.expanduser(d))
    return os.path.join(os.path.abspath(os.path.expanduser('~')), DIR_NAME)


def settings_path():
    return os.path.join(config_root(), SETTINGS_FILE)


def load_settings(path=None):
    """The settings file as a dict; missing, unreadable or malformed → {} (a broken settings file must not stop the SDK)."""
    path = path or settings_path()
    try:
        with open(path, encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def saved_language():
    """The language saved in the settings file, or None."""
    path = settings_path()
    try:
        mtime = os.stat(path).st_mtime_ns
    except OSError:
        return None
    if _cache[0] == path and _cache[1] == mtime:
        return _cache[2]
    lang = normalize(load_settings(path).get('language'))
    _cache[:] = [path, mtime, lang]
    return lang


def save_language(lang):
    """Save the language in the settings file (other keys kept) and return the path. Raises ValueError for an
    unsupported language and OSError if the file can't be written. Written atomically, like credentials."""
    code = normalize(lang)
    if code is None:
        raise ValueError(t('lang.invalid', lang))
    path = settings_path()
    data = load_settings(path)
    data.update(version=SETTINGS_VERSION, language=code)
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = '%s.%d.tmp' % (path, os.getpid())
    try:
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    _cache[:] = [None, None, None]
    return path


def resolve():
    """(language, source); source is 'process', 'env', 'saved' or 'default'."""
    if _override is not None:
        return _override, 'process'
    env = normalize(os.environ.get(ENV_LANG))
    if env is not None:
        return env, 'env'
    saved = saved_language()
    if saved is not None:
        return saved, 'saved'
    return DEFAULT, 'default'


def get_language():
    """The display language in effect: 'en' or 'zh'."""
    return resolve()[0]


def set_language(lang):
    """Set the display language for this process only ('en' or 'zh'; zh_CN-style forms are accepted). It takes
    precedence over QUAFU_LANG and the saved setting and is not saved; set_language(None) removes it.
    To save a choice for every run, use `quafu config set language zh` on the command line."""
    global _override
    if lang is None:
        _override = None
        return None
    code = normalize(lang)
    if code is None:
        raise ValueError(t('lang.invalid', lang))
    _override = code
    return code


def t(key, *args):
    """The message `key` in the current language, %-formatted with args."""
    text = MESSAGES[key][_INDEX[get_language()]]
    return text % args if args else text


def safe_streams():
    """Command line only: make stdout / stderr replace characters they can't encode instead of raising.

    Redirected to a file or a pipe, Python encodes output with the locale's code page; on English Windows that is
    cp1252, which can't encode Chinese, so `quafu --help > f.txt` with the Chinese UI crashed with
    UnicodeEncodeError and a traceback. The terminal itself is unaffected (Windows writes the console in
    UTF-16). Only the error handler changes, never the encoding: a file or pipe gets what its reader expects, with
    '?' for what can't be written. Streams without reconfigure() (replaced by tests or an embedding host) are left
    alone; this must never raise."""
    import sys
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors='replace')
        except Exception:
            pass
