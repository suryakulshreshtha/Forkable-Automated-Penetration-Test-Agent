#!/usr/bin/env python3
"""Standalone entrypoint for the offline demo: `python demo/run_demo.py`."""

import sys
from pathlib import Path

# allow running from a source checkout without installing
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fapta.demo_runner import run_demo  # noqa: E402

if __name__ == "__main__":
    run_demo()
