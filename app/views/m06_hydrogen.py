"""M6 — Produkcja wodoru: biblioteka technologii i kalkulator zapotrzebowania."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.hydrogen import (
    energy_cost_pln_per_kg,
    h2_lhv_kwh_per_kg,
    hydrogen_demand,
    hydrogen_technologies,
)
from core.prices import all_scenarios


def render() -> None:
    st.title("M6 · Produkcja wodoru")
    st.caption(
        "AEL · PEM · SOEC · AEM · SMR+CCS · piroliza — parametry orientacyjne "
        "wg IEA Global Hydrogen Review 2023/2024 (data/hydrogen_production.yaml)"
    )

    techs = hydrogen_technologies()
    scenarios = all_scenarios()

    col_in, col_out = st.columns([2, 3], gap="large")
    with col_in:
        st.subheader("Technologia i produkcja")
        tech_key = st.selectbox("Technologia", list(techs), format_func=lambda k: techs[k].name_pl)
        tech = techs[tech_key]
        st.caption(
            f"Energia el.: {tech.electricity_range[0]:g}–{tech.electricity_range[1]:g} "
            f"kWh/kg (typ. {tech.electricity_kwh_per_kg:g}) · TRL {tech.trl} · "
            f"czystość {tech.purity_pct:g}% · p wyj. {tech.pressure_out_bar:g} bar · "
            f"CAPEX {tech.capex_eur_per_kw:g} €/{tech.capex_basis} · {tech.source}"
        )
        for note in tech.notes:
            st.caption(f"ℹ️ {note}")

        production = st.number_input("Produkcja H2 [kg/h]", 1.0, 50000.0, 100.0, 10.0)
        cf = st.slider("Współczynnik wykorzystania", 0.1, 1.0, 0.9, 0.05)
        age = st.slider(
            "Wiek instalacji [lata] (degradacja)",
            0.0,
            15.0,
            0.0,
            0.5,
            help=f"Degradacja: {tech.degradation_pct_per_year:g}%/rok (typ.)",
        )
        sc_key = st.selectbox(
            "Scenariusz M5 (miks, ceny)",
            list(scenarios),
            index=list(scenarios).index("bazowy") if "bazowy" in scenarios else 0,
            format_func=lambda k: scenarios[k].name_pl,
        )
        year = st.slider("Rok analizy", 2025, 2050, 2030)

    sc = scenarios[sc_key]
    try:
        res = hydrogen_demand(tech_key, production, sc, year, cf, age)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    with col_out:
        st.subheader("Zapotrzebowanie i wskaźniki")
        r1 = st.columns(4)
        r1[0].metric("Moc elektryczna", f"{res.power_el_mw:.2f} MW")
        r1[1].metric("Energia el.", f"{res.energy_el_mwh_per_year:,.0f} MWh/rok")
        r1[2].metric("Gaz ziemny", f"{res.gas_mwh_per_year:,.0f} MWh/rok")
        r1[3].metric("Woda", f"{res.water_m3_per_year:,.0f} m³/rok")
        r2 = st.columns(4)
        r2[0].metric("Produkcja", f"{res.production_t_per_year:,.0f} t H2/rok")
        r2[1].metric(
            "Sprawność (LHV)",
            f"{res.efficiency_lhv * 100:.1f}%",
            help=f"Hi(H2) = {h2_lhv_kwh_per_kg():.2f} kWh/kg (ISO 6976) / energia całkowita",
        )
        r2[2].metric(
            "Emisje zakres 1+2",
            f"{res.co2_total_kg_per_kg:.1f} kg CO2/kg H2",
            help=f"Zakres 1: {res.co2_scope1_kg_per_kg:.1f} · "
            f"zakres 2 (miks {year}): {res.co2_scope2_kg_per_kg:.1f}",
        )
        r2[3].metric(
            "Koszt energii",
            f"{energy_cost_pln_per_kg(res, sc, year):.1f} PLN/kg",
            help="Tylko nośniki energii wg cen M5 — pełne LCOH w M10.",
        )
        if res.heat_mwh_per_year > 0:
            st.info(
                f"♨️ SOEC wymaga pary: {res.heat_mwh_per_year:,.0f} MWh/rok ciepła "
                "(~150–200 °C) — potencjał integracji z ciepłem odpadowym."
            )

    st.divider()
    st.subheader(f"Porównanie technologii ({year}, scenariusz: {sc.name_pl})")
    rows = []
    for key, t in techs.items():
        r = hydrogen_demand(key, production, sc, year, cf, age)
        rows.append(
            {
                "Technologia": t.name_pl,
                "kWh el./kg": r.electricity_kwh_per_kg_aged,
                "kWh gazu/kg": t.fuel_gas_kwh_per_kg,
                "Sprawność LHV [%]": r.efficiency_lhv * 100,
                "kg CO2/kg (1+2)": r.co2_total_kg_per_kg,
                "Koszt energii [PLN/kg]": energy_cost_pln_per_kg(r, sc, year),
                "CAPEX [€/kW]": t.capex_eur_per_kw,
                "TRL": t.trl,
            }
        )
    df = pd.DataFrame(rows)
    c1, c2 = st.columns([3, 2], gap="large")
    with c1:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=df["Technologia"], y=df["kg CO2/kg (1+2)"], name="kg CO2/kg H2"))
        fig.add_trace(
            go.Scatter(
                x=df["Technologia"],
                y=df["Koszt energii [PLN/kg]"],
                name="koszt energii [PLN/kg]",
                yaxis="y2",
                mode="markers+lines",
            )
        )
        fig.update_layout(
            yaxis=dict(title="kg CO2/kg H2 (zakres 1+2)"),
            yaxis2=dict(title="PLN/kg", overlaying="y", side="right"),
            height=420,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, config={"displaylogo": False})
    with c2:
        st.dataframe(df.round(1), hide_index=True, width="stretch")

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Dane:** IEA Global Hydrogen Review 2023/2024 (zużycie systemowe z BoP);
wartości orientacyjne min/typ/max w `data/hydrogen_production.yaml`.

**Sprawność LHV:** `η = Hi(H2) / e_całk`, Hi(H2) = 33,33 kWh/kg z ISO 6976
(M1). **Degradacja:** liniowy wzrost zużycia energii elektrycznej
o wartość %/rok (typową dla technologii).

**Emisje:** zakres 1 — rezydualne CO2 (SMR+CCS: wychwyt 90–95%);
zakres 2 — energia elektryczna × emisyjność miksu ze scenariusza M5;
emisje gazu w SMR/pirolizie ujęte w zakresie 1 technologii.
**Wniosek systemowy:** elektroliza na dzisiejszym miksie PL (≈0,66 t/MWh)
daje ~30–37 kg CO2/kg H2 — kilkukrotnie więcej niż SMR bez CCS; sens
klimatyczny zapewnia dopiero zasilanie OZE/niskoemisyjne.

**Koszt energii:** tylko nośniki wg M5 — pełne LCOH (CAPEX, OPEX, woda,
degradacja stosu) w module M10.
            """)
