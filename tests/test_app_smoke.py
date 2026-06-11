"""Test dymny UI: aplikacja Streamlit renderuje się bez wyjątków."""

from streamlit.testing.v1 import AppTest


def test_main_page_renders_without_exception():
    at = AppTest.from_file("app/main.py", default_timeout=30)
    at.run()
    assert not at.exception
    assert at.title[0].value == "Ocena projektów B+R w dystrybucji gazu"


def test_m01_page_renders_without_exception():
    from pathlib import Path

    repo_root = Path(__file__).resolve().parent.parent
    script = (
        f"import sys; sys.path.insert(0, {str(repo_root)!r})\n"
        "from app.views import m01_gas_properties\n"
        "m01_gas_properties.render()\n"
    )
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    assert not at.exception
    assert at.title[0].value.startswith("M1")
    # Strona pokazuje metryki kaloryczne i flagi jakości dla gazu E
    assert any("Wobbego" in (s.body or "") for s in at.success)
