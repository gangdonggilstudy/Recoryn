"""Frozen runtime hook: PyAV and its GPL-codec FFmpeg are not distributed (L01 D1).

faster-whisper imports ``av`` at package import but only calls it to decode files.
Recoryn passes already decoded 16 kHz float32 arrays, so the import is satisfied by
an inert module that fails clearly if any PyAV attribute is ever used.
"""

from __future__ import annotations

import sys
import types


class _UnavailablePyAV(types.ModuleType):
    def __getattr__(self, name: str) -> object:
        raise AttributeError(f"RECORYN_PYAV_NOT_BUNDLED: av.{name}")


def install() -> None:
    if "av" in sys.modules:
        return
    module = _UnavailablePyAV("av")
    module.__dict__["__recoryn_stub__"] = True
    sys.modules["av"] = module


install()
