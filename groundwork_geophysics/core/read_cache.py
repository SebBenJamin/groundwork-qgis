"""A model file's read result kept as an npz file, so the next read of an unchanged file
takes a fraction of a second. The cache is never needed: a file that cannot be read back is
ignored, one that cannot be written is skipped. Results with readings (pseudosections,
misfit files) are not kept: they are small, and more than arrays."""
from __future__ import annotations

import json
import os
import threading
import zipfile
from pathlib import Path

import numpy as np


def _temporary(path: Path) -> Path:
    """A temporary name beside ``path`` that no other writer (thread, process) uses."""
    return path.with_name(f"{path.name}.{os.getpid()}-{threading.get_ident()}.part")


def cacheable(result) -> bool:
    return result.mesh.readings is None


def save_result(path: Path, result) -> bool:
    """Write ``result`` to ``path`` (whole or not at all); False when not cacheable or not
    written."""
    if not cacheable(result):
        return False
    mesh = result.mesh
    meta = {"quantity": mesh.quantity, "unit": mesh.unit, "coverage_cut": mesh.coverage_cut,
            "z_kind": result.z_kind, "provenance": result.provenance}
    arrays = {"vertices": mesh.vertices, "cells": mesh.cells, "values": mesh.values,
              "meta": np.array(json.dumps(meta, default=str))}
    if mesh.coverage is not None:
        arrays["coverage"] = np.asarray(mesh.coverage, dtype=float)
    path = Path(path)
    tmp = _temporary(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(tmp, "wb") as f:
            np.savez(f, **arrays)
        os.replace(tmp, path)
        return True
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return False


def load_result(path: Path):
    """The ``ReaderResult`` kept at ``path``, or None (missing or unreadable)."""
    from ..readers.base import ReaderResult
    from .section_mesh import SectionMesh
    try:
        with np.load(path, allow_pickle=False) as data:
            meta = json.loads(str(data["meta"]))
            coverage = data["coverage"] if "coverage" in data.files else None
            mesh = SectionMesh(data["vertices"], data["cells"], data["values"],
                               meta["quantity"], meta["unit"], coverage=coverage,
                               coverage_cut=meta.get("coverage_cut"))
            return ReaderResult(mesh, meta["z_kind"], dict(meta.get("provenance") or {}))
    except (OSError, ValueError, KeyError, TypeError, EOFError, zipfile.BadZipFile):
        return None
