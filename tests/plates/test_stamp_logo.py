"""The plate logo: kept as the project variable ``wb_logo``, relative inside the project
folder, and resolved by the logo picture's expression (empty when the file is missing)."""
import pytest


@pytest.fixture
def prj(qgis_app, tmp_path):
    from qgis.core import QgsProject
    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(tmp_path / "p.qgz"))
    yield project
    project.clear()


def _image(path):
    from qgis.PyQt.QtGui import QImage
    path.parent.mkdir(parents=True, exist_ok=True)
    img = QImage(4, 4, QImage.Format.Format_RGB32)
    img.fill(0)
    assert img.save(str(path))
    return path


def _evaluate(project, expression):
    from qgis.core import QgsExpression, QgsExpressionContext, QgsExpressionContextUtils
    ctx = QgsExpressionContext()
    ctx.appendScope(QgsExpressionContextUtils.globalScope())
    ctx.appendScope(QgsExpressionContextUtils.projectScope(project))
    expr = QgsExpression(expression)
    value = expr.evaluate(ctx)
    assert not expr.hasEvalError(), expr.evalErrorString()
    return value


def test_set_plate_logo_relative_inside_project(prj, tmp_path):
    from groundwork_geophysics.plates.build import plate_logo, set_plate_logo
    set_plate_logo(prj, str(tmp_path / "img" / "logo.png"))
    assert plate_logo(prj) == "img/logo.png"


def test_set_plate_logo_absolute_outside(prj, tmp_path_factory):
    from pathlib import Path

    from groundwork_geophysics.plates.build import plate_logo, set_plate_logo
    other = tmp_path_factory.mktemp("elsewhere") / "logo.png"
    set_plate_logo(prj, str(other))
    assert Path(plate_logo(prj)) == other


def test_set_plate_logo_clear(prj, tmp_path):
    from groundwork_geophysics.plates.build import plate_logo, set_plate_logo
    set_plate_logo(prj, str(tmp_path / "logo.png"))
    set_plate_logo(prj, "")
    assert plate_logo(prj) == ""


def test_logo_expression_resolves(prj, tmp_path):
    from pathlib import Path

    from groundwork_geophysics.plates.build import set_plate_logo
    from groundwork_geophysics.plates.stamp import LOGO_EXPRESSION
    logo = _image(tmp_path / "img" / "logo.png")
    set_plate_logo(prj, str(logo))
    assert Path(_evaluate(prj, LOGO_EXPRESSION)) == logo


def test_logo_expression_missing_file_is_empty(prj, tmp_path):
    from groundwork_geophysics.plates.build import set_plate_logo
    from groundwork_geophysics.plates.stamp import LOGO_EXPRESSION
    set_plate_logo(prj, str(tmp_path / "gone.png"))
    assert _evaluate(prj, LOGO_EXPRESSION) in ("", None)
    set_plate_logo(prj, "")
    assert _evaluate(prj, LOGO_EXPRESSION) in ("", None)
