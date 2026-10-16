# -*- coding: utf-8 -*-
"""tests/windows/ 共用的小件：在子进程里跑命令行、问子进程的管道编码。

子进程的环境取当时的 os.environ：公共夹具已把 HOME / USERPROFILE 换成临时目录、清掉 QUAFU_*、平台地址指向
https://quafu.test（连不上），所以这里的命令行不会碰到本机的真凭证，也不会访问真平台。"""
import os
import subprocess
import sys

# 不装 console script 也能跑命令行：与 quafu.exe 调的是同一个入口 quafu.cli:main
CLI = 'import sys; from quafu.cli import main; sys.exit(main())'


def child_env(**extra):
    env = dict(os.environ)
    env.update(extra)
    return env


def run_cli(*args, cwd, **extra):
    """在子进程里跑 quafu 命令行，stdout / stderr 是管道（与重定向到文件、接 more 时相同），返回 bytes 结果。
    标准输入用已关闭的空管道：Windows 的 NUL 会被 isatty() 判为终端，不能用 DEVNULL 代替。
    没凭证时不会发起网页登录。"""
    return subprocess.run([sys.executable, '-c', CLI] + list(args), cwd=str(cwd), env=child_env(**extra),
                          input=b'', capture_output=True, timeout=120)


def pipe_encoding(cwd, **extra):
    """同样环境下子进程往管道写用的编码（中文版 Windows 一般是 cp936，英文版是 cp1252；设了 PYTHONUTF8 就是 utf-8）。"""
    r = subprocess.run([sys.executable, '-c', 'import sys; print(sys.stdout.encoding)'], cwd=str(cwd),
                       env=child_env(**extra), capture_output=True, text=True, timeout=60)
    return r.stdout.strip()
