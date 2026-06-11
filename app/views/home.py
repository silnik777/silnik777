"""Strona główna — opis narzędzia, status realizacji modułów."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.modules_registry import MODULES
from core import __version__
from core.config import data_dir, load_data_file


def render() -> None:
    st.title("Ocena projektów B+R w dystrybucji gazu")
    st.caption(f"Wersja silnika obliczeniowego: {__version__}")

    st.markdown("""
Narzędzie obliczeniowo-analityczne do **oceny technicznej, ekonomicznej
i ekologicznej projektów B+R** oraz **benchmarkingu technologii** (wodór,
mieszaniny H₂/gaz ziemny, OZE) dla operatora dystrybucji gazu.

**Architektura:** cała logika obliczeniowa znajduje się w pakiecie `core/`
(czysta biblioteka Pythona), a ten interfejs korzysta wyłącznie z jej API —
ten sam silnik obsłuży w przyszłości REST API (FastAPI) i Power BI.

**Termodynamika:** wyłącznie walidowane biblioteki (CoolProp — GERG-2008/HEOS)
oraz udokumentowane korelacje normowe (ISO 6976). Każdy wynik ma sekcję
„Założenia i wzory" ze źródłem.
        """)

    st.subheader("Status modułów")
    df = pd.DataFrame(
        {
            "Moduł": [m.title for m in MODULES],
            "Etap planu": [m.stage for m in MODULES],
            "Status": ["✅ dostępny" if m.render else "🔜 w przygotowaniu" for m in MODULES],
        }
    ).sort_values("Etap planu", kind="stable")
    st.dataframe(df, hide_index=True, width="stretch")

    with st.expander("Dane konfiguracyjne (katalog data/)"):
        st.markdown(
            f"Katalog danych: `{data_dir()}` — współczynniki i progi są edytowalne "
            "bez zmian w kodzie; każdy plik ma pola `source` i `updated`."
        )
        limits = load_data_file("quality_limits.yaml")
        wobbe = limits["wobbe_index_group_E"]
        st.markdown(
            f"**Przykład — liczba Wobbego, gaz grupy E:** "
            f"{wobbe['min_mj_per_m3']}–{wobbe['max_mj_per_m3']} MJ/m³ "
            f"(nominalna {wobbe['nominal_mj_per_m3']} MJ/m³)."
        )
        st.caption(f"Źródło: {wobbe['source'].strip()}")
        if wobbe.get("note"):
            st.warning(wobbe["note"])
