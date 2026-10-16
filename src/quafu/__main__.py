# -*- coding: utf-8 -*-
"""python -m quafu 等同于命令行 quafu。"""
import sys

from .cli import main

sys.exit(main())
