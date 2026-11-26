"""Model readers: registry and auto-detection (no QGIS/Qt)."""
from __future__ import annotations

from pathlib import Path

from .base import Reader, ReaderResult

_REGISTRY: dict[str, Reader] = {}
#: the reader for a file no fixed format fits: a text table read with assigned columns
FALLBACK = "text_columns"


def register(reader: Reader) -> None:
    """Register a reader. Registration order is the detection priority (most specific first)."""
    _REGISTRY[reader.name] = reader


def get(name: str) -> Reader:
    try:
        return _REGISTRY[name]
    except KeyError:
        raise ValueError(f"Unknown reader {name!r}; available: {', '.join(_REGISTRY)}") from None


def names() -> list[str]:
    return list(_REGISTRY)


def detect(path) -> list[str]:
    """Names of all readers whose sniff accepts the file, most specific first."""
    path = Path(path)
    out = []
    for name, reader in _REGISTRY.items():
        try:
            if reader.sniff(path):
                out.append(name)
        except Exception:                      # sniff must not break detection
            continue
    return out


def read(path, reader: str | None = None, **options) -> ReaderResult:
    path = Path(path)
    if reader is None:
        found = detect(path)
        if not found:
            raise ValueError(f"{path.name}: could not recognise the file format "
                             f"(readers: {', '.join(_REGISTRY)})")
        reader = found[0]
    return get(reader).read(path, **options)


def _register_builtins() -> None:
    from .bert_data import BertDataReader
    from .gssi_dzt import GssiDztReader
    from .pulseekko import PulseEkkoReader
    from .r2_err import R2ErrReader
    from .r2_res import R2ResReader
    from .refrapy_xzv import RefrapyXzvReader
    from .segy import SegyReader
    from .text_columns import TextColumnsReader
    from .vtk_legacy import VtkLegacyReader
    from .zondres import ZondResReader
    # most specific first
    for cls in (SegyReader, GssiDztReader, PulseEkkoReader, RefrapyXzvReader, BertDataReader, R2ErrReader, R2ResReader,
                VtkLegacyReader, ZondResReader):
        register(cls())
    register(TextColumnsReader())          # never detected; chosen by the user, so last


_register_builtins()
