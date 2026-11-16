"""Round 2, B1: Patterns… opened slowly - every row's list built a preview icon for every
pattern. The previews are built once and shared by all rows."""
import time


def _renderer(n):
    from qgis.core import QgsCategorizedSymbolRenderer, QgsFillSymbol, QgsRendererCategory
    return QgsCategorizedSymbolRenderer("lith", [
        QgsRendererCategory(f"c{i}", QgsFillSymbol.createSimple({"color": "200,200,200"}),
                            f"class {i}") for i in range(n)])


def test_icons_built_once(qgis_app, monkeypatch):
    from groundwork_geophysics.patterns import catalogue
    from groundwork_geophysics.ui import pattern_table
    real, built = pattern_table.QIcon, []

    def counting(*args):
        built.append(args)
        return real(*args)

    monkeypatch.setattr(pattern_table, "QIcon", counting)
    monkeypatch.setattr(pattern_table, "_MODEL", None, raising=False)    # a fresh session
    start = time.perf_counter()
    t = pattern_table.PatternTable(_renderer(30))
    print(f"\nPatternTable with 30 classes: {time.perf_counter() - start:.2f} s")
    assert len(built) <= len(catalogue()) + 1
    t.deleteLater()


def test_choices_unchanged(qgis_app):
    from groundwork_geophysics.patterns import catalogue
    from groundwork_geophysics.ui.pattern_table import NO_PATTERN, PatternTable
    t = PatternTable(_renderer(2))
    combo = t._combos["c0"]
    assert [combo.itemText(i) for i in range(combo.count())] == \
        [NO_PATTERN] + [p.label for p in catalogue()]
    sand = next(p for p in catalogue() if p.code == "607")
    t.set_pattern("c1", sand)
    assert t.pattern("c1") == sand and t.pattern("c0") is None
    assert t._combos["c0"].currentText() == NO_PATTERN        # rows share the list, not the choice
    t.deleteLater()
