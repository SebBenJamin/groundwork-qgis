"""What a context source gathers per profile, cached, with the last error per profile.

QGIS-free. A failing source never breaks the section: the profile gets empty items, and
the error text is kept (and reported) so the plugin can log it."""
from __future__ import annotations

from typing import Callable

from ..core.context import ContextItems
from ..core.model import Profile


class GatheredContext:
    def __init__(self):
        self.source: Callable[[Profile], ContextItems] | None = None
        #: profile id -> "ExceptionType: message" of the source's last failure
        self.errors: dict[str, str] = {}
        self._items: dict[str, ContextItems] = {}

    def clear(self) -> None:
        self._items.clear()

    def set_borehole_views(self, views: dict) -> None:
        for items in self._items.values():
            items.borehole_views = dict(views)

    def items(self, profile: Profile,
              on_error: Callable[[str, str], None] | None = None) -> ContextItems:
        """The source's items for ``profile`` (no ties), cached until ``clear()``: the
        gatherer samples the DEM on every call. A failure is cached as empty items, kept
        in ``errors`` and passed to ``on_error(profile_id, message)``; success clears it."""
        items = self._items.get(profile.id)
        if items is None:
            items = ContextItems()
            if self.source is not None:
                try:
                    items = self.source(profile)
                    self.errors.pop(profile.id, None)
                except Exception as exc:        # a broken source must not break the section
                    message = self.errors[profile.id] = f"{type(exc).__name__}: {exc}"
                    if on_error is not None:
                        on_error(profile.id, message)
            self._items[profile.id] = items
        return items
