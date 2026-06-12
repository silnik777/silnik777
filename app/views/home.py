"""Strona główna — przewodnik użytkownika, status modułów."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from app.modules_registry import MODULES
from core import __version__
from core.config import data_dir


def render() -> None:
    st.title("Ocena projektów B+R w dystrybucji gazu")
    st.caption(f"Wersja silnika obliczeniowego: {__version__}")

    tab_guide, tab_workflows, tab_modules, tab_about = st.tabs(
        ["🚀 Jak zacząć", "🧭 Typowe analizy", "🧩 Moduły", "ℹ️ O narzędziu"]
    )

    with tab_guide:
        st.markdown("""
### Trzy kroki do oceny projektu

**1. Policz wskaźniki w modułach tematycznych** (menu po lewej) — np.
moc odzyskaną ekspandera w **M4**, koszt produkcji wodoru w **M10**,
redukcję emisji w **M8–M9**. Każda strona ma sekcję **„📖 Założenia
i wzory"** — tam znajdziesz metodykę i źródła.

**2. Zapisz kartę projektu w M14** — wpisz policzone wskaźniki do
formularza (każde pole podpowiada, w którym module je wyznaczysz).

**3. Porównaj projekty i wyeksportuj wyniki** — ranking z własnymi
wagami, eksport do Excela (XLSX/CSV) — gotowe do prezentacji i Power BI.

---

### Dobre nawyki

- 🟡 **Żółte ostrzeżenia** to ważne informacje merytoryczne (np. ryzyko
  hydratów, punkt pracy poza zakresem) — czytaj je, nie blokują obliczeń.
- ⚠️ Wartości z dopiskiem **„orientacyjna — do weryfikacji"** pochodzą
  z literatury; przed decyzją inwestycyjną podmień je na dane z ofert.
- 💾 Scenariusze cenowe (M5) i karty projektów (M14) zapisują się na dysku
  — przetrwają zamknięcie aplikacji i można je przekazać współpracownikom.
- ✏️ Wszystkie dane domyślne (składy gazów, sprawności, ceny) są w plikach
  tekstowych w katalogu `data/` — edytowalnych w Notatniku, bez programisty.
        """)

    with tab_workflows:
        st.markdown("""
### Przykładowe ścieżki analizy

**🔵 „Czy domieszka wodoru zmieści się w parametrach sieci?"**
1. **M1** — ustaw skład gazu i suwak %H₂: sprawdź liczbę Wobbego i flagi
   jakości; 2. **M3** — porównaj przepustowość energetyczną rury;
3. **M8–M9** — zobacz realną redukcję emisji na kWh.

**🟢 „Czy ekspander na stacji redukcyjnej się opłaci?"**
1. **M13** — wybierz wariant stacji (np. 5,5→1,7 MPa), porównaj JT /
   ekspander / zimną redukcję i dobierz źródło podgrzewu;
2. **M4** — macierz doboru technologii (moc, CAPEX, TRL);
3. **M10** — NPV/IRR przy cenach ze scenariusza; 4. **M14** — karta projektu.

**🟣 „Ile kosztuje zielony wodór z naszej instalacji?"**
1. **M6** — technologia elektrolizy i zapotrzebowanie (moc, woda, emisje);
2. **M5** — wybierz/edytuj scenariusz cen energii; 3. **M10** — LCOH
   z dekompozycją i tornado; 4. **M11** — pozycja na tle innych technologii.

**🟠 „Który kierunek B+R rekomendować zarządowi?"**
1. Policz wskaźniki dla 2–5 projektów (ścieżki wyżej); 2. **M14** —
   zapisz karty, ustaw wagi (technika/ekonomia/ekologia), pokaż ranking
   i wykres radarowy; 3. eksport XLSX → prezentacja/Power BI.
        """)

    with tab_modules:
        df = pd.DataFrame(
            {
                "Moduł": [m.title for m in MODULES],
                "Do czego służy": [m.description.split(".")[0] + "." for m in MODULES],
                "Status": ["✅" if m.render else "🔜" for m in MODULES],
            }
        )
        st.dataframe(df, hide_index=True, width="stretch")

    with tab_about:
        st.markdown(f"""
**Architektura:** logika obliczeniowa w pakiecie `core/` (czysta biblioteka
Pythona), interfejs w `app/` — ten sam silnik obsłuży REST API i Power BI.

**Termodynamika:** wyłącznie walidowane biblioteki (CoolProp —
GERG-2008/HEOS) i udokumentowane korelacje normowe (ISO 6976). **Testy:**
260+ testów automatycznych, w tym walidacja z wartościami referencyjnymi
(ISO, NIST, literatura).

**Dane:** katalog `{data_dir()}` — współczynniki i progi edytowalne bez
zmian w kodzie; każdy plik ma pola `source` i `updated`.

**Instrukcja użytkownika:** plik `INSTRUKCJA.md` w katalogu narzędzia
(otwiera się w przeglądarce/Notatniku).
        """)
