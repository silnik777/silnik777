"""M8–M9 — Emisje: spalanie (stechiometria), ucieczki CH4, zakres 2."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.composition import GasComposition
from core.config import load_data_file
from core.emissions import (
    combustion_emissions,
    electricity_emissions_t_co2,
    gwp_factors,
    leak_emissions,
)
from core.prices import all_scenarios


@st.cache_data(show_spinner=False)
def _emissions_vs_h2(base_fractions: tuple[tuple[str, float], ...]) -> pd.DataFrame:
    base = GasComposition(fractions=base_fractions)
    rows = []
    for pct in range(0, 101, 5):
        e = combustion_emissions(base.blend_with_hydrogen(pct / 100.0))
        rows.append(
            {
                "H2 [% mol]": pct,
                "g CO2/kWh (Hi)": e.g_co2_per_kwh_hi,
                "kg CO2/Nm³": e.kg_co2_per_m3_ref,
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    st.title("M8–M9 · Emisje GHG")
    st.caption(
        "Spalanie: stechiometria ze składu (M1) · CH4→CO2eq: IPCC AR6 · "
        "zakres 2: emisyjność miksu ze scenariuszy M5"
    )

    col_in, col_out = st.columns([2, 3], gap="large")
    with col_in:
        st.subheader("Gaz")
        compositions = load_data_file("gas_compositions.yaml")["compositions"]
        gas_key = st.selectbox(
            "Skład", list(compositions), format_func=lambda k: compositions[k]["name_pl"]
        )
        base = GasComposition.predefined(gas_key)
        h2_pct = 0.0
        if gas_key != "wodor_99999":
            h2_pct = st.slider("Domieszka H2 [% mol]", 0.0, 100.0, 0.0, 5.0)
        composition = base.blend_with_hydrogen(h2_pct / 100.0)
        fossil = gas_key != "biometan"
        st.caption(
            f"Metan traktowany jako **{'kopalny' if fossil else 'biogeniczny'}** "
            "(GWP wg IPCC AR6)."
        )

    e = combustion_emissions(composition)
    with col_out:
        st.subheader("Spalanie (zakres 1) — stechiometrycznie ze składu")
        r1 = st.columns(4)
        r1[0].metric("na Nm³", f"{e.kg_co2_per_m3_ref:.3f} kg CO2")
        r1[1].metric("na kg paliwa", f"{e.kg_co2_per_kg:.3f} kg CO2")
        r1[2].metric("na kWh (Hi)", f"{e.g_co2_per_kwh_hi:.1f} g CO2")
        r1[3].metric(
            "na GJ (Hi)",
            f"{e.kg_co2_per_gj_hi:.2f} kg CO2",
            help="Wskaźnik referencyjny IPCC dla gazu ziemnego: 56,1 kg CO2/GJ.",
        )

        curve = _emissions_vs_h2(base.fractions)
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=curve["H2 [% mol]"],
                y=curve["g CO2/kWh (Hi)"],
                name="g CO2/kWh (Hi)",
                mode="lines",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=curve["H2 [% mol]"],
                y=curve["kg CO2/Nm³"] * 100,
                name="kg CO2/Nm³ ×100",
                mode="lines",
                line=dict(dash="dash"),
            )
        )
        fig.add_vline(x=h2_pct, line_dash="dot", annotation_text=f"{h2_pct:g}% H2")
        fig.update_layout(
            xaxis_title="Udział H2 [% mol]",
            yaxis_title="emisja CO2 ze spalania",
            height=380,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        st.caption(
            "Uwaga: redukcja emisji na kWh jest istotnie mniejsza niż udział "
            "objętościowy H2 (~3× niższa gęstość energii H2 na m³)."
        )

    st.divider()
    c1, c2 = st.columns(2, gap="large")

    with c1:
        st.subheader("Ucieczki metanu (zakres 1)")
        leaked = st.number_input(
            "Objętość wycieku [Nm³/rok]",
            0.0,
            1e7,
            10_000.0,
            100.0,
            help="Np. straty sieciowe, emisje z upustów i nieszczelności.",
        )
        leak = leak_emissions(composition, leaked, fossil=fossil)
        st.metric("Masa CH4", f"{leak.ch4_mass_kg / 1e3:.2f} t/rok")
        fig2 = go.Figure(
            go.Bar(
                x=["GWP100", "GWP20"],
                y=[leak.co2eq_gwp100_kg / 1e3, leak.co2eq_gwp20_kg / 1e3],
                marker_color=["#1f77b4", "#d62728"],
                text=[
                    f"{leak.co2eq_gwp100_kg / 1e3:.1f} t",
                    f"{leak.co2eq_gwp20_kg / 1e3:.1f} t",
                ],
            )
        )
        fig2.update_layout(yaxis_title="t CO2eq/rok", height=320, showlegend=False)
        st.plotly_chart(fig2, config={"displaylogo": False})
        gwp = gwp_factors()
        st.caption(
            f"GWP CH4 ({'kopalny' if fossil else 'biogeniczny'}): "
            f"{gwp['CH4_kopalny' if fossil else 'CH4_biogeniczny']['gwp100']} (100 lat) / "
            f"{gwp['CH4_kopalny' if fossil else 'CH4_biogeniczny']['gwp20']} (20 lat) — "
            f"{gwp['CH4_kopalny']['source']}. Pośredni efekt klimatyczny H2 — poza zakresem."
        )

    with c2:
        st.subheader("Energia elektryczna (zakres 2)")
        scenarios = all_scenarios()
        sc_key = st.selectbox(
            "Scenariusz emisyjności miksu (M5)",
            list(scenarios),
            index=list(scenarios).index("bazowy") if "bazowy" in scenarios else 0,
            format_func=lambda k: scenarios[k].name_pl,
        )
        year = st.slider("Rok", 2025, 2050, 2030)
        mwh = st.number_input("Zużycie energii [MWh/rok]", 0.0, 1e6, 1000.0, 10.0)
        sc = scenarios[sc_key]
        t_co2 = electricity_emissions_t_co2(mwh, sc, year)
        st.metric(
            f"Emisje zakresu 2 ({year})",
            f"{t_co2:,.1f} t CO2/rok",
            help=f"Wskaźnik miksu: {sc.price('emisyjnosc_miksu', year):.3f} t CO2/MWh",
        )
        years = list(range(2025, 2051))
        fig3 = go.Figure(
            go.Scatter(x=years, y=[sc.price("emisyjnosc_miksu", y) for y in years], mode="lines")
        )
        fig3.add_vline(x=year, line_dash="dot")
        fig3.update_layout(xaxis_title="Rok", yaxis_title="t CO2/MWh el.", height=300)
        st.plotly_chart(fig3, config={"displaylogo": False})

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Spalanie (zakres 1):** stechiometrycznie ze składu molowego:
`e = Σ xⱼ·nCⱼ·M(CO₂) / V_m` — pełne utlenienie węgla, CO₂ z paliwa
przechodzi do spalin; V_m rzeczywiste (GERG-2008, M1). Test porównawczy:
gaz E ±5% względem wskaźnika IPCC 56,1 kg CO₂/GJ.

**CH₄→CO₂eq:** GWP wg **IPCC AR6** (tab. 7.15): kopalny 29,8 (100 lat) /
82,5 (20 lat); biogeniczny 27,0 / 80,8. Współczynniki edytowalne w
`data/emission_factors.yaml`.

**Zakres 2:** MWh × emisyjność miksu [t CO₂/MWh] ze ścieżki scenariusza
M5 (punkt startowy wg KOBiZE, trajektoria malejąca — edytowalna).

**Poza zakresem:** pośredni efekt klimatyczny H₂ (GWP(H₂)≈11±5 wg
najnowszej literatury — bez ujęcia w AR6), emisje N₂O ze spalania
(pomijalne dla gazu), cykl życia paliw (zakres 3).
            """)
