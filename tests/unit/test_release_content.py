# -*- coding: utf-8 -*-
"""发到 PyPI 的东西只客观描述功能：不出现任何人的名字或 GitHub 账号，也不出现内部 Issue 号。

查的是会打进安装包的文件（src/ 下全部、README、pyproject.toml、LICENSE）。改动的动机、谁提的，写在仓库里的
CHANGELOG.md、PR 与 Issue 里——CHANGELOG 不打进包。名单是固定几项，另可用环境变量 QUAFU_PEOPLE_MD
指向一份协作者名单（Markdown 表格，每行「| 人名 | `GitHub 账号` |」开头）一并核对；名单本身不进本仓库。"""
import os
import pathlib
import re

SDK_DIR = pathlib.Path(__file__).resolve().parents[2]
PEOPLE = pathlib.Path(os.environ.get('QUAFU_PEOPLE_MD') or SDK_DIR / '.people.md')
ALWAYS = ('Neo', 'NeoFantom', 'FlagQuantum')
ISSUE_REF = re.compile(r'(?<![\w&/])#\d{2,}\b')


def shipped_files():
    files = [p for p in (SDK_DIR / 'src').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    files += [SDK_DIR / n for n in ('README.md', 'pyproject.toml', 'LICENSE')]
    return [p for p in files if p.exists()]


def names():
    out = set(ALWAYS)
    if PEOPLE.exists():
        for row in PEOPLE.read_text(encoding='utf-8').splitlines():
            m = re.match(r'\|\s*([^|（(]+?)\s*(?:[（(][^)）]*[)）])?\s*\|\s*`([^`]+)`', row)
            if m:
                out.update({m.group(1), m.group(2)})
    return sorted(n for n in out if n)


def test_shipped_files_name_no_people_and_no_issue_numbers():
    who = names()
    pattern = re.compile('|'.join(r'(?<![\w-])%s(?![\w-])' % re.escape(n) if n.isascii() else re.escape(n)
                                  for n in who))
    hits = []
    for p in shipped_files():
        try:
            text = p.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            for m in (*pattern.finditer(line), *ISSUE_REF.finditer(line)):
                hits.append('%s:%d: %s' % (p.relative_to(SDK_DIR), i, m.group(0)))
    assert not hits, '发布内容里不能有人名或 Issue 号：\n' + '\n'.join(hits)


def test_people_list_is_read():
    who = names()
    if PEOPLE.exists():
        assert len(who) > len(ALWAYS)
