"""Runtime loading helpers for libvterm."""

from __future__ import annotations

from functools import lru_cache
import importlib
from typing import Any


@lru_cache(maxsize=1)
def load_libvterm() -> tuple[Any, Any]:
    """Load the compiled libvterm cffi module."""
    module = importlib.import_module("cockpit.terminal.bindings._libvterm")
    return module.ffi, module.lib


def libvterm_available() -> bool:
    """Return true when the compiled libvterm extension is importable."""
    try:
        load_libvterm()
    except Exception:
        return False
    return True
