"""Round 2, B4: a tie strip keeps the model's colours whichever data layers are switched on
(the measured layer on top used to lend the strip its scale)."""
from types import SimpleNamespace as NS


def _layer(kind, scale, visible=True):
    return NS(style=NS(visible=visible, scale=scale), mesh=object(),
              dataset=NS(kind=kind, quantity="resistivity"))


def _col():
    return NS(quantity="resistivity", scale="column")


def test_measured_on_top_is_ignored():
    from geophysics_workbench.section.context_render import strip_scale
    layers = [_layer("ert_model", "model"), _layer("ert_measured", "measured")]
    assert strip_scale(_col(), layers) == "model"


def test_hidden_model_still_used():
    from geophysics_workbench.section.context_render import strip_scale
    layers = [_layer("ert_model", "model", visible=False), _layer("ert_measured", "measured")]
    assert strip_scale(_col(), layers) == "model"


def test_no_model_uses_column_scale():
    from geophysics_workbench.section.context_render import strip_scale
    assert strip_scale(_col(), [_layer("ert_measured", "measured")]) == "column"
