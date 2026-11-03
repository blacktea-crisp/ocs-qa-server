# -*- coding: utf-8 -*-
"""双击启动托盘程序（.pyw 由 pythonw 运行，无控制台窗口）。"""
import os
import sys

# 保证以项目根为工作目录并加入 sys.path
ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.tray import main

if __name__ == "__main__":
    main()
