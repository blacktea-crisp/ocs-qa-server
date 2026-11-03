# -*- coding: utf-8 -*-
"""Tray launcher (double-click, runs via pythonw, no console window)."""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
os.chdir(ROOT)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from scripts.tray import main

if __name__ == "__main__":
    main()
