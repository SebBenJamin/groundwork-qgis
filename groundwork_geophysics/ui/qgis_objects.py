"""Handing QGIS objects to QGIS, and telling their kind, without stale Python wrappers.

A renderer or symbol QGIS made (a ``clone()``, a ``load()``) and the plugin then gives to a
setter that keeps it (``setRenderer``, ``setRenderer3D``, ...) stays wrapped in Python for
as long as the layer's wrapper lives: the binding makes it the layer's child. QGIS deletes
the object when the layer gets another renderer, but the wrapper stays known at that
address, and a new object QGIS makes there later comes back to Python as the old wrapper,
of the wrong class (a graduated renderer seen as categorized; using it crashes QGIS).
``handed_over`` lets go of the wrapper; ``as_kind`` asks QGIS for the kind (the virtual
``type()``) instead of trusting the Python class.
"""
from __future__ import annotations


def handed_over(obj) -> None:
    """``obj`` was just given to a QGIS setter that keeps it: when QGIS made it, drop
    Python's hold, so its wrapper goes with Python's last reference. An object made in
    Python is left as it is (QGIS tells the binding when it deletes one of those)."""
    from qgis.PyQt import sip
    if obj is None:
        return
    try:
        if not sip.ispycreated(obj):
            sip.transferto(obj, None)
    except (TypeError, RuntimeError):            # not a wrapped QGIS object, or gone
        pass


def as_kind(obj, kind: str, base, cls):
    """``obj`` as ``cls`` when QGIS says it is of ``kind`` (its ``type()``), else None.
    Cast through ``base`` (a common base class), as the Python class may be a stale one."""
    from qgis.PyQt import sip
    if obj is None or obj.type() != kind:
        return None
    return sip.cast(sip.cast(obj, base), cls)
