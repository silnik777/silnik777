"""M7 — Charakterystyki wytwarzania: benchmark technologii ciepła i energii."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.generation import generation_technologies, technology_indicators
from core.prices import all_scenarios

_CLASS_COLORS = {
    "kopalne": "#555555",
    "alternatywne": "#bcbd22",
    "niskoemisyjne": "#1f77b4",
    "bezemisyjne": "#2ca02c",
}


def render() -> None:
    st.title("M7 · Charakterystyki wytwarzania")
    st.caption(
        "Benchmark technologii ciepła i energii elektrycznej: od kopalnych po "
        "bezemisyjne · katalogi DEA/IEA (data/generation_technologies.yaml) · "
        "technologie cieplne zasilają źródła podgrzewu w M13"
    )

    techs = generation_technologies()
    scenarios = all_scenarios()

    c1, c2, c3, c4 = st.columns(4)
    categories = c1.multiselect(
        "Kategoria",
        ["cieplo", "energia_elektryczna", "kogeneracja"],
        default=["cieplo", "energia_elektryczna", "kogeneracja"],
        format_func=lambda c: {
            "cieplo": "ciepło",
            "energia_elektryczna": "en. elektryczna",
            "kogeneracja": "kogeneracja",
        }[c],
    )
    classes = c2.multiselect(
        "Klasa emisyjna",
        list(_CLASS_COLORS),
        default=list(_CLASS_COLORS),
    )
    sc_key = c3.selectbox(
        "Scenariusz M5",
        list(scenarios),
        index=list(scenarios).index("bazowy") if "bazowy" in scenarios else 0,
        format_func=lambda k: scenarios[k].name_pl,
    )
    year = c4.slider("Rok", 2025, 2050, 2030)
    sc = scenarios[sc_key]

    selected = [
        t for t in techs.values() if t.category in categories and t.emission_class in classes
    ]
    if not selected:
        st.info("Wybierz co najmniej jedną kategorię i klasę emisyjną.")
        st.stop()

    rows = []
    for t in selected:
        ind = technology_indicators(t, sc, year)
        rows.append(
            {
                "Technologia": t.name_pl,
                "Kategoria": t.category,
                "Klasa": t.emission_class,
                "Paliwo": t.fuel,
                "η el. [-]": t.eta_el,
                "η ciepła / COP [-]": t.eta_heat,
                "T zasilania [°C]": t.supply_temp_c,
                "g CO2/kWh el.": ind.g_co2_per_kwh_el,
                "g CO2/kWh ciepła": ind.g_co2_per_kwh_heat,
                "Koszt paliwowy ciepła [PLN/MWh]": ind.fuel_cost_pln_per_mwh_heat,
                "Koszt paliwowy en. el. [PLN/MWh]": ind.fuel_cost_pln_per_mwh_el,
                "CAPEX [€/kW]": t.capex_eur_per_kw,
                "Skala [kW]": f"{t.scale_range_kw[0]:g}–{t.scale_range_kw[1]:g}",
                "TRL": t.trl,
            }
        )
    df = pd.DataFrame(rows)
    st.dataframe(df.round(2), hide_index=True, width="stretch")

    tab1, tab2 = st.tabs(["Emisje jednostkowe", "Koszt paliwowy vs emisje"])
    with tab1:
        heat_df = df[df["g CO2/kWh ciepła"].notna()].sort_values("g CO2/kWh ciepła")
        fig = go.Figure(
            go.Bar(
                x=heat_df["Technologia"],
                y=heat_df["g CO2/kWh ciepła"],
                marker_color=[_CLASS_COLORS[c] for c in heat_df["Klasa"]],
            )
        )
        fig.update_layout(
            yaxis_title=f"g CO2/kWh ciepła ({year}, miks: {sc.name_pl})",
            height=420,
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        st.caption(
            "Kolory: ⬛ kopalne · 🟡 alternatywne · 🔵 niskoemisyjne (wg miksu) · "
            "🟢 bezemisyjne. Pompy ciepła/kotły elektryczne podążają za "
            "dekarbonizacją miksu (suwak roku)."
        )
    with tab2:
        plot_df = df[df["g CO2/kWh ciepła"].notna() & df["Koszt paliwowy ciepła [PLN/MWh]"].notna()]
        fig2 = go.Figure()
        for cls in plot_df["Klasa"].unique():
            sub = plot_df[plot_df["Klasa"] == cls]
            fig2.add_trace(
                go.Scatter(
                    x=sub["Koszt paliwowy ciepła [PLN/MWh]"],
                    y=sub["g CO2/kWh ciepła"],
                    text=sub["Technologia"],
                    name=cls,
                    mode="markers+text",
                    textposition="top center",
                    marker=dict(size=12, color=_CLASS_COLORS[cls]),
                )
            )
        fig2.update_layout(
            xaxis_title="koszt paliwowy ciepła [PLN/MWh]",
            yaxis_title="g CO2/kWh ciepła",
            height=480,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig2, config={"displaylogo": False})

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Dane:** katalogi technologiczne Danish Energy Agency (2023/24), IEA WEO —
wartości orientacyjne (min/typ/max) w `data/generation_technologies.yaml`.

**Sprawności wg Hi**; kocioł kondensacyjny > 1 (kondensacja spalin);
pompy ciepła: COP sezonowy; PV/wiatr: współczynnik wykorzystania mocy PL.

**Emisje:** gaz — stechiometrycznie ze składu gazu E (M8); węgiel — IPCC
94,7 kg/GJ; biomasa — 0 (CO2 biogeniczny, nota); prąd — emisyjność miksu
(M5, zakres 2); H2/słońce/wiatr — 0 w miejscu wytwarzania (emisje źródła
H2: moduł M6). **Kogeneracja:** podział nakładu paliwa metodą energetyczną
(uproszczenie — alternatywnie metoda elektrowni zastępczej).

**Koszt paliwowy** = cena nośnika (M5) / sprawność — bez CAPEX/OPEX
(pełne LCOE/LCOH: moduł M10).

**Integracja M13:** technologie cieplne tej biblioteki są dostępne jako
źródła podgrzewu gazu w module M13 (z temperaturą zasilania i sprawnością).
            """)
