"""M14 — Karta projektu B+R: formularz, porównanie, ranking, eksport."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.export import export_csv, export_xlsx, projects_dataframe, ranking_dataframe
from core.project_card import (
    ProjectCard,
    compare_projects,
    criteria_registry,
    delete_project,
    load_projects,
    save_project,
)

_CATEGORY_ICONS = {"techniczne": "⚙️", "ekonomiczne": "💰", "ekologiczne": "🌍"}


def _project_form() -> None:
    registry = criteria_registry()
    existing = load_projects()
    edit_slug = st.selectbox(
        "Edytuj zapisany projekt (albo zostaw puste — nowy)",
        ["— nowy projekt —"] + list(existing),
        format_func=lambda k: existing[k].name if k in existing else k,
    )
    base = existing.get(edit_slug)

    with st.form("project_form"):
        name = st.text_input(
            "Nazwa projektu *",
            value=base.name if base else "",
            help="Np. 'Turboekspander — stacja Wola', 'Elektrolizer PEM 1 MW'.",
        )
        description = st.text_area(
            "Krótki opis",
            value=base.description if base else "",
            help="Czego dotyczy projekt, lokalizacja, skala.",
        )

        st.markdown(
            "**Wskaźniki** — wypełnij te, które masz policzone (pozostałe "
            "zostaw puste; przy każdym jest podpowiedź, w którym module "
            "narzędzia wyznaczysz wartość):"
        )
        values: dict[str, float] = {}
        for category in ("techniczne", "ekonomiczne", "ekologiczne"):
            st.markdown(f"{_CATEGORY_ICONS[category]} **{category.capitalize()}**")
            cols = st.columns(3)
            crits = [c for c in registry.values() if c.category == category]
            for i, crit in enumerate(crits):
                default = (
                    str(base.indicators[crit.key]) if base and crit.key in base.indicators else ""
                )
                raw = cols[i % 3].text_input(
                    f"{crit.name_pl} [{crit.unit}]",
                    value=default,
                    help=f"Gdzie policzyć: {crit.gdzie_policzyc}",
                    key=f"crit_{crit.key}",
                )
                if raw.strip():
                    try:
                        values[crit.key] = float(raw.replace(",", "."))
                    except ValueError:
                        st.error(
                            f"'{crit.name_pl}': wpisz liczbę (np. 12,5) — " f"otrzymano '{raw}'."
                        )

        notes = st.text_area("Uwagi / założenia", value=base.notes if base else "")
        submitted = st.form_submit_button("💾 Zapisz projekt", type="primary")

    if submitted:
        if not name.strip():
            st.error("Podaj nazwę projektu.")
            return
        try:
            path = save_project(
                ProjectCard(
                    name=name.strip(),
                    description=description,
                    indicators=values,
                    notes=notes,
                )
            )
            st.success(f"Zapisano projekt „{name}” ({len(values)} wskaźników) → {path.name}")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))


def _comparison_tab() -> None:
    projects = load_projects()
    if len(projects) < 2:
        st.info(
            "📌 Aby porównać projekty, zapisz co najmniej dwa w zakładce "
            "„Nowy / edycja projektu»."
        )
        return
    selected = st.multiselect(
        "Projekty do porównania (min. 2)",
        list(projects),
        default=list(projects)[:3],
        format_func=lambda k: projects[k].name,
    )
    if len(selected) < 2:
        st.info("Wybierz co najmniej dwa projekty.")
        return

    registry = criteria_registry()
    with st.expander("⚖️ Wagi kryteriów (domyślnie równe)", expanded=False):
        weights = {}
        cols = st.columns(3)
        for i, (key, crit) in enumerate(registry.items()):
            weights[key] = cols[i % 3].slider(
                f"{crit.name_pl}", 0.0, 2.0, crit.default_weight, 0.1, key=f"w_{key}"
            )

    cards = [projects[k] for k in selected]
    try:
        result = compare_projects(cards, weights)
    except ValueError as exc:
        st.error(str(exc))
        return

    if result.skipped_criteria:
        skipped_names = ", ".join(
            registry[k].name_pl for k in result.skipped_criteria if weights.get(k, 1) > 0
        )
        if skipped_names:
            st.warning(
                f"Pominięte kryteria (brak wartości w którymś projekcie): {skipped_names}. "
                "Uzupełnij wskaźniki, aby je uwzględnić."
            )

    st.subheader("🏆 Ranking")
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}
    rank_df = pd.DataFrame(
        {
            "Miejsce": [f"{medal.get(i, i)}" for i in range(1, len(result.ranked) + 1)],
            "Projekt": [r.card.name for r in result.ranked],
            "Wynik [0–1]": [round(r.score, 3) for r in result.ranked],
        }
    )
    c_l, c_r = st.columns([2, 3], gap="large")
    with c_l:
        st.dataframe(rank_df, hide_index=True, width="stretch")
    with c_r:
        categories = [registry[k].name_pl for k in result.used_criteria]
        fig = go.Figure()
        for r in result.ranked:
            fig.add_trace(
                go.Scatterpolar(
                    r=[r.criterion_scores[k] for k in result.used_criteria]
                    + [r.criterion_scores[result.used_criteria[0]]],
                    theta=categories + [categories[0]],
                    name=r.card.name,
                    fill="toself",
                    opacity=0.55,
                )
            )
        fig.update_layout(
            polar=dict(radialaxis=dict(range=[0, 1])),
            height=420,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        st.caption("Wykres radarowy: oceny znormalizowane 0–1 (1 = najlepszy w zbiorze).")

    st.subheader("Wskaźniki źródłowe")
    st.dataframe(projects_dataframe(cards), hide_index=True, width="stretch")

    st.subheader("📤 Eksport")
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "⬇️ XLSX (Projekty + Ranking + Kryteria)",
        data=export_xlsx(cards, result, weights),
        file_name="ocena_projektow_BR.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    c2.download_button(
        "⬇️ CSV (pod Power BI / Excel)",
        data=export_csv(cards),
        file_name="projekty_BR.csv",
        mime="text/csv",
    )
    c3.download_button(
        "⬇️ Ranking (CSV)",
        data=ranking_dataframe(result).to_csv(index=False, sep=";").encode("utf-8-sig"),
        file_name="ranking_BR.csv",
        mime="text/csv",
    )


def _manage_tab() -> None:
    projects = load_projects()
    if not projects:
        st.info("Brak zapisanych projektów.")
        return
    st.dataframe(projects_dataframe(list(projects.values())), hide_index=True, width="stretch")
    del_slug = st.selectbox("Usuń projekt", list(projects), format_func=lambda k: projects[k].name)
    if st.button("🗑️ Usuń wybrany projekt"):
        delete_project(del_slug)
        st.rerun()


def render() -> None:
    st.title("M14 · Karta projektu B+R")
    st.caption(
        "Zbierz wskaźniki z modułów M1–M13 → zapisz kartę projektu → "
        "porównaj projekty rankingiem z własnymi wagami → wyeksportuj XLSX/CSV"
    )

    tab_form, tab_compare, tab_manage = st.tabs(
        ["📝 Nowy / edycja projektu", "📊 Porównanie i ranking", "🗂️ Zarządzanie"]
    )
    with tab_form:
        _project_form()
    with tab_compare:
        _comparison_tab()
    with tab_manage:
        _manage_tab()

    with st.expander("📖 Założenia i metodyka"):
        st.markdown("""
**Przepływ pracy:** wartości wskaźników wyznaczasz w modułach narzędzia
(każde pole formularza podpowiada, w którym), wpisujesz do karty i zapisujesz
— projekty trafiają do `data/projects/*.json` (można je przenosić między
komputerami).

**Ocena wielokryterialna:** jak w M11 — normalizacja min–max w obrębie
porównywanych projektów (1 = najlepszy w zbiorze dla danego kryterium,
z uwzględnieniem kierunku „niższe lepsze"), suma ważona wagami użytkownika.
Kryterium bez wartości w którymkolwiek projekcie jest pomijane (ostrzeżenie).

**Eksport:** XLSX (arkusze Projekty/Ranking/Kryteria) i CSV z separatorem
„;" w UTF-8 BOM — otwiera się poprawnie w polskim Excelu i Power BI.
            """)
