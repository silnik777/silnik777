"""Test dymny UI: aplikacja Streamlit renderuje się bez wyjątków."""

from streamlit.testing.v1 import AppTest


def test_main_page_renders_without_exception():
    at = AppTest.from_file("app/main.py", default_timeout=30)
    at.run()
    assert not at.exception
    assert at.title[0].value == "Ocena projektów B+R w dystrybucji gazu"


def _render_view(module_name: str) -> AppTest:
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    script = (
        f"import sys; sys.path.insert(0, {str(repo_root)!r})\n"
        f"from app.views import {module_name}\n"
        f"{module_name}.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=120)
    at.run()
    return at


def test_m01_page_renders_without_exception():
    at = _render_view("m01_gas_properties")
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value.startswith("M1")
    # Strona pokazuje metryki kaloryczne i flagi jakości dla gazu E
    assert any("Wobbego" in (s.body or "") for s in at.success)


def test_m02_page_renders_without_exception():
    at = _render_view("m02_compression")
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value.startswith("M2")


def test_m03_page_renders_without_exception():
    at = _render_view("m03_pipeline")
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value.startswith("M3")


def test_m04_page_renders_without_exception():
    at = _render_view("m04_expanders")
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value.startswith("M4")


def test_m05_page_renders_without_exception():
    at = _render_view("m05_prices")
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value.startswith("M5")


def test_m08_page_renders_without_exception():
    at = _render_view("m08_emissions")
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value.startswith("M8")


def test_m13_page_renders_without_exception():
    at = _render_view("m13_cold_reduction")
    assert not at.exception
    assert not at.error, [e.value for e in at.error]
    assert at.title[0].value.startswith("M13")
