"""Test dymny UI: aplikacja Streamlit renderuje się bez wyjątków."""

from streamlit.testing.v1 import AppTest


def test_main_page_renders_without_exception():
    at = AppTest.from_file("app/main.py", default_timeout=30)
    at.run()
    assert not at.exception
    assert at.title[0].value == "Ocena projektów B+R w dystrybucji gazu"
