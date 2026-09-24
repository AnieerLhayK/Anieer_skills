#!/usr/bin/env python3
"""Compatibility CLI facade for the bounded, read-only disk scan engine.

Public functions remain importable here for existing callers and tests.
Implementation lives in focused internal modules.
"""

from __future__ import annotations

import time

try:
    from scripts import disk_scan_engine as _engine
    from scripts.disk_scan_engine import *  # noqa: F401,F403 - compatibility surface
except ImportError:
    import disk_scan_engine as _engine
    from disk_scan_engine import *  # noqa: F401,F403 - compatibility surface

_scan_root_impl = _engine.scan_root
_run_scan_impl = _engine.run_scan
_run_two_stage_scan_impl = _engine.run_two_stage_scan


def scan_root(*args, **kwargs):
    """Delegate through this facade so legacy monkeypatches remain effective."""
    _engine.time = time
    return _scan_root_impl(*args, **kwargs)


def run_scan(config_path, output, max_depth=None):
    """Run with the facade scan hook for legacy scan_root patches."""
    _engine.time = time
    _engine.scan_root = scan_root
    return _run_scan_impl(config_path, output, max_depth)


def run_two_stage_scan(config_path, config, audit_policy):
    _engine.time = time
    _engine.scan_root = scan_root
    return _run_two_stage_scan_impl(config_path, config, audit_policy)


def main():
    _engine.run_scan = run_scan
    return _engine.main()


if __name__ == "__main__":
    raise SystemExit(main())
