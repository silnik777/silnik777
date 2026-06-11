"""Punkt wejścia aplikacji Streamlit.

Uruchomienie lokalne:
    streamlit run app/main.py

Strony zaimplementowane wskazują funkcję ``render`` w rejestrze modułów;
pozostałe otrzymują automatyczną zaślepkę z opisem zakresu i etapem planu.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import streamlit as st

# Umożliwia import pakietów `core` i `app` przy starcie przez `streamlit run`.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from app.modules_registry import MODULES, ModuleInfo  # noqa: E402
from app.views import home  # noqa: E402


def _placeholder_page(module: ModuleInfo) -> Callable[[], None]:
    """Tworzy stronę-zaślepkę dla modułu, który powstanie w późniejszym etapie."""

    def page() -> None:
        st.title(module.title)
        st.info(f"Moduł w przygotowaniu — planowany w **etapie {module.stage}**.")
        st.subheader("Zakres modułu")
        st.markdown(module.description)

    page.__name__ = module.slug.replace("-", "_")
    return page


def _build_navigation() -> st.navigation:
    pages: dict[str, list[st.Page]] = {
        "Start": [st.Page(home.render, title="Strona główna", icon="🏠", url_path="start")]
    }
    for module in MODULES:
        renderer = module.render or _placeholder_page(module)
        pages.setdefault(module.section, []).append(
            st.Page(renderer, title=module.title, icon=module.icon, url_path=module.slug)
        )
    return st.navigation(pages)


st.set_page_config(
    page_title="Ocena projektów B+R — dystrybucja gazu",
    page_icon="🔬",
    layout="wide",
)

_build_navigation().run()
