"""Boreholes hidden in one profile's section (round 2): a small table in the workbench file,
keyed by profile, borehole layer and borehole id. The user's borehole layer is never touched."""
from __future__ import annotations

from typing import Iterable

from osgeo import ogr

_S = ogr.OFTString
TABLE = "hidden_boreholes"
HIDDEN_FIELDS = [("profile_id", _S), ("layer_id", _S), ("borehole_id", _S)]


def _q(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


class HiddenBoreholesMixin:
    def hidden_boreholes(self, profile_id: str) -> set[tuple[str, str]]:
        with self._ds() as ds:
            lyr = ds.GetLayerByName(TABLE)
            if lyr is None:
                return set()
            return {(f["layer_id"], f["borehole_id"])
                    for f in self._select(lyr, f"profile_id = {_q(profile_id)}")}

    def set_boreholes_hidden(self, profile_id: str, keys: Iterable[tuple[str, str]],
                             hidden: bool) -> None:
        from .gpkg_store import _make_layer
        keys = list(keys)
        if not keys:
            return
        with self._tx() as ds:
            lyr = ds.GetLayerByName(TABLE) or _make_layer(ds, TABLE, HIDDEN_FIELDS)
            for layer_id, bid in keys:
                self._delete_where(lyr, f"profile_id = {_q(profile_id)} AND "
                                        f"layer_id = {_q(layer_id)} AND "
                                        f"borehole_id = {_q(bid)}")
                if hidden:
                    f = ogr.Feature(lyr.GetLayerDefn())
                    f["profile_id"], f["layer_id"], f["borehole_id"] = profile_id, layer_id, bid
                    lyr.CreateFeature(f)

    def _drop_hidden(self, ds, profile_id: str) -> None:
        lyr = ds.GetLayerByName(TABLE)
        if lyr is not None:
            self._delete_where(lyr, f"profile_id = {_q(profile_id)}")
