"""M11 — Benchmarking technologii: ranking wielokryterialny z wagami."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.benchmarking import build_benchmark_entries, rank_technologies
from core.prices import all_scenarios


@st.cache_data(show_spinner="Liczenie LCOE/LCOS dla technologii…")
def _entries(sc_key: str, year: int, wacc: float):
    return build_benchmark_entries(all_scenarios()[sc_key], year, wacc)


def render() -> None:
    st.title("M11 · Benchmarking technologii")
    st.caption(
        "PV · wiatr · CCGT · kogeneracja · ogniwa H2 · magazyn bateryjny — "
        "wspólne wskaźniki (LCOE/LCOS z M10, emisje M7/M8, dyspozycyjność, TRL)"
    )

    scenarios = all_scenarios()
    c1, c2, c3 = st.columns(3)
    sc_key = c1.selectbox(
        "Scenariusz M5",
        list(scenarios),
        index=list(scenarios).index("bazowy") if "bazowy" in scenarios else 0,
        format_func=lambda k: scenarios[k].name_pl,
    )
    year = c2.slider("Rok", 2025, 2050, 2030)
    wacc = c3.number_input("WACC", 0.01, 0.20, 0.07, 0.005, format="%.3f")

    st.subheader("Wagi kryteriów (domyślnie równe)")
    w1, w2, w3, w4 = st.columns(4)
    weights = {
        "koszt": w1.slider("koszt (LCOE/LCOS)", 0.0, 1.0, 0.25, 0.05),
        "emisje": w2.slider("emisje CO2eq", 0.0, 1.0, 0.25, 0.05),
        "dyspozycyjnosc": w3.slider("dyspozycyjność", 0.0, 1.0, 0.25, 0.05),
        "trl": w4.slider("TRL (dojrzałość)", 0.0, 1.0, 0.25, 0.05),
    }
    if sum(weights.values()) <= 0:
        st.error("Suma wag musi być dodatnia.")
        st.stop()

    entries = _entries(sc_key, year, wacc)
    ranked = rank_technologies(entries, weights)

    df = pd.DataFrame(
        {
            "Miejsce": range(1, len(ranked) + 1),
            "Technologia": [r.entry.name_pl for r in ranked],
            "Wynik [0–1]": [r.score for r in ranked],
            "LCOE/LCOS [PLN/MWh]": [r.entry.lcox_pln_per_mwh for r in ranked],
            "g CO2eq/kWh": [r.entry.co2_g_per_kwh for r in ranked],
            "Dyspozycyjność": [r.entry.dispatchability for r in ranked],
            "TRL": [r.entry.trl for r in ranked],
        }
    )
    c_l, c_r = st.columns([3, 2], gap="large")
    with c_l:
        fig = go.Figure()
        criteria_labels = {
            "koszt": "koszt",
            "emisje": "emisje",
            "dyspozycyjnosc": "dyspozycyjność",
            "trl": "TRL",
        }
        total_w = sum(weights.values())
        for crit, label in criteria_labels.items():
            fig.add_trace(
                go.Bar(
                    x=[r.entry.name_pl for r in ranked],
                    y=[r.criterion_scores[crit] * weights[crit] / total_w for r in ranked],
                    name=label,
                )
            )
        fig.update_layout(
            barmode="stack",
            yaxis_title="wynik ważony [0–1]",
            height=440,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, config={"displaylogo": False})
    with c_r:
        st.dataframe(df.round(3), hide_index=True, width="stretch")

    st.subheader("Mapa: koszt vs emisje (rozmiar = dyspozycyjność)")
    fig2 = go.Figure(
        go.Scatter(
            x=[e.lcox_pln_per_mwh for e in entries],
            y=[e.co2_g_per_kwh for e in entries],
            text=[e.name_pl for e in entries],
            mode="markers+text",
            textposition="top center",
            marker=dict(
                size=[10 + 25 * e.dispatchability for e in entries],
                color=[e.trl for e in entries],
                colorscale="Viridis",
                colorbar=dict(title="TRL"),
            ),
        )
    )
    fig2.update_layout(
        xaxis_title="LCOE/LCOS [PLN/MWh]",
        yaxis_title=f"g CO2eq/kWh ({year}, miks: {scenarios[sc_key].name_pl})",
        height=480,
    )
    st.plotly_chart(fig2, config={"displaylogo": False})

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Wskaźniki:** LCOE z silnika M10 (ceny M5, WACC, 20 lat); magazyn:
LCOS = (CAPEX·CRF + OPEX + koszt ładowania)/energia oddana — ładowanie
z sieci po cenie energii, emisje = miks/η_RT (konserwatywnie; ładowanie
z nadwyżek OZE → niżej). Dyspozycyjność: ocena ekspercka 0–1
(`data/benchmark_extras.yaml`, edytowalna).

**Ranking:** normalizacja min–max do 0–1 (koszt i emisje: niższe = lepsze),
suma ważona wagami; wagi domyślnie równe — uzgodnione. Wynik zależy od
zbioru porównywanych technologii (cecha normalizacji min–max).

**Uwaga interpretacyjna:** LCOE nie ujmuje wartości systemowej
(dyspozycyjność łapie to częściowo); porównanie magazynu (przesuwa
energię) z wytwarzaniem ma charakter poglądowy.
            """)
