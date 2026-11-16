"""Size rule of dialogs with a scroll area: open at the content's size hint (capped to the
screen), grow when the content grows, never shrink."""
from __future__ import annotations

from qgis.PyQt.QtCore import QSize

MAX_HEIGHT = 580            # taller content scrolls (QGIS dialogs stay under this)


def content_size(dialog, scroll, buttons) -> QSize:
    """The dialog size that shows ``scroll``'s page whole, capped to the screen."""
    page = scroll.widget()
    if page.layout() is not None:
        page.layout().activate()
    margins = dialog.layout().contentsMargins()
    frame = 2 * scroll.frameWidth()
    want = page.sizeHint() + QSize(
        scroll.verticalScrollBar().sizeHint().width() + frame + margins.left() + margins.right(),
        frame + buttons.sizeHint().height() + dialog.layout().spacing() + margins.top()
        + margins.bottom())
    screen = dialog.screen().availableGeometry()
    return QSize(min(want.width(), screen.width() - 40),
                 min(want.height(), screen.height() - 80, MAX_HEIGHT))


def fit_to_content(dialog, scroll, buttons) -> None:
    """Resize to ``content_size``, but never smaller than the dialog is now."""
    want = content_size(dialog, scroll, buttons)
    dialog.resize(max(dialog.width(), want.width()), max(dialog.height(), want.height()))
