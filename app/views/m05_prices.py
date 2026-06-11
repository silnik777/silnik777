"""M5 — Ścieżki cenowe: scenariusze, edycja i zapis scenariuszy użytkownika."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.config import load_data_file
from core.prices import (
    all_scenarios,
    carriers,
    delete_user_scenario,
    eur_pln_rate,
    save_user_scenario,
)

_EDIT_YEARS = [2025, 2030, 2035, 2040, 2045, 2050]


def render() -> None:
    st.title("M5 · Ścieżki cenowe do 2050")
    meta = load_data_file("price_scenarios.yaml")["meta"]
    st.caption(
        "Scenariusze niski/bazowy/wysoki + scenariusze użytkownika (JSON) · "
        f"kurs roboczy {eur_pln_rate():.2f} PLN/EUR"
    )
    st.warning(f"⚠️ {meta['note']}")

    scenarios = all_scenarios()
    carrier_info = carriers()

    col_l, col_r = st.columns([2, 3], gap="large")
    with col_l:
        sel_scenarios = st.multiselect(
            "Scenariusze do porównania",
            list(scenarios),
            default=[k for k in ("niski", "bazowy", "wysoki") if k in scenarios],
            format_func=lambda k: scenarios[k].name_pl,
        )
        sel_carrier = st.selectbox(
            "Nośnik / wskaźnik",
            list(carrier_info),
            format_func=lambda k: f"{carrier_info[k]['name_pl']} [{carrier_info[k]['unit']}]",
        )

    with col_r:
        fig = go.Figure()
        years = list(range(2025, 2051))
        for key in sel_scenarios:
            sc = scenarios[key]
            if sel_carrier not in sc.paths:
                continue
            fig.add_trace(
                go.Scatter(
                    x=years,
                    y=[sc.price(sel_carrier, y) for y in years],
                    name=sc.name_pl + (" (użytk.)" if sc.is_user_defined else ""),
                    mode="lines",
                )
            )
        fig.update_layout(
            xaxis_title="Rok",
            yaxis_title=f"{carrier_info[sel_carrier]['name_pl']} "
            f"[{carrier_info[sel_carrier]['unit']}]",
            height=420,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, config={"displaylogo": False})

    st.divider()
    st.subheader("Edycja i zapis scenariusza użytkownika")
    base_key = st.selectbox(
        "Scenariusz bazowy do edycji",
        list(scenarios),
        index=list(scenarios).index("bazowy") if "bazowy" in scenarios else 0,
        format_func=lambda k: scenarios[k].name_pl,
    )
    base_sc = scenarios[base_key]
    df = pd.DataFrame(
        {
            f"{carrier_info[c]['name_pl']} [{carrier_info[c]['unit']}]": [
                round(base_sc.price(c, y), 3) for y in _EDIT_YEARS
            ]
            for c in carrier_info
            if c in base_sc.paths
        },
        index=pd.Index(_EDIT_YEARS, name="Rok"),
    )
    edited = st.data_editor(df, key=f"price_editor_{base_key}", width="stretch")

    c1, c2 = st.columns([2, 1])
    name = c1.text_input("Nazwa nowego scenariusza (litery/cyfry/_/-)", value="moj_scenariusz")
    if c2.button("💾 Zapisz scenariusz użytkownika", type="primary"):
        try:
            label_to_key = {
                f"{carrier_info[c]['name_pl']} [{carrier_info[c]['unit']}]": c for c in carrier_info
            }
            paths = {
                label_to_key[col]: {int(y): float(edited.loc[y, col]) for y in _EDIT_YEARS}
                for col in edited.columns
            }
            path = save_user_scenario(name, paths)
            st.success(f"Zapisano scenariusz '{name}' → {path}")
            st.rerun()
        except ValueError as exc:
            st.error(str(exc))

    user_keys = [k for k, sc in scenarios.items() if sc.is_user_defined]
    if user_keys:
        st.subheader("Scenariusze użytkownika")
        del_key = st.selectbox("Usuń scenariusz", user_keys)
        if st.button("🗑️ Usuń"):
            delete_user_scenario(del_key)
            st.rerun()

    with st.expander("📖 Założenia i źródła"):
        st.markdown(f"""
**Metoda:** punkty kotwiczne (np. 2025/2030/2040/2050) interpolowane
liniowo; poza zakresem — wartość stała. Jednostki: nośniki energii
**PLN/MWh (wg Hi)**, uprawnienia **EUR/t CO₂** (kurs roboczy
{eur_pln_rate():.2f}), emisyjność miksu **t CO₂/MWh**.

**Źródła wartości domyślnych (orientacyjne):** {meta["source"].strip()}

**ETS2** od 2027 r. (budynki/transport) — przed startem wartość 0.

**Emisyjność miksu PL:** punkt startowy wg KOBiZE (~0,6–0,7 t CO₂/MWh),
trajektoria malejąca do 2050 — używana w M8–M9 (zakres 2) i w M10.

**Scenariusze użytkownika:** JSON w `data/user_scenarios/` — pełna edycja
bez zmian w kodzie; walidacja przed zapisem.
            """)
