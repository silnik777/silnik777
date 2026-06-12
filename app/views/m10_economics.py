"""M10 — Ekonomia: LCOH/LCOE, NPV/IRR/DPP, analiza wrażliwości (tornado)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.economics import (
    DEFAULT_LIFETIME_YEARS,
    DEFAULT_WACC,
    lcoe_for_technology,
    lcoh_for_technology,
    project_metrics,
    tornado_analysis,
)
from core.generation import generation_technologies
from core.hydrogen import hydrogen_technologies
from core.prices import all_scenarios, eur_pln_rate


def render() -> None:
    st.title("M10 · Ekonomia (LCOH / LCOE, NPV, IRR, DPP)")
    st.caption(
        "Koszty uśrednione z dekompozycją · ceny ze ścieżek M5 · "
        "WACC 7% realnie, 20 lat (edytowalne) · tornado ±20%"
    )

    scenarios = all_scenarios()
    col_in, col_out = st.columns([2, 3], gap="large")

    with col_in:
        st.subheader("Projekt")
        mode = st.radio("Rodzaj analizy", ["LCOH (wodór, M6)", "LCOE (energia el., M7)"])
        sc_key = st.selectbox(
            "Scenariusz cenowy (M5)",
            list(scenarios),
            index=list(scenarios).index("bazowy") if "bazowy" in scenarios else 0,
            format_func=lambda k: scenarios[k].name_pl,
        )
        sc = scenarios[sc_key]
        start_year = st.slider("Rok uruchomienia", 2025, 2045, 2030)
        c1, c2 = st.columns(2)
        wacc = c1.number_input("WACC (realny)", 0.01, 0.20, DEFAULT_WACC, 0.005, format="%.3f")
        lifetime = int(c2.number_input("Okres analizy [lata]", 5, 40, DEFAULT_LIFETIME_YEARS))

        if mode.startswith("LCOH"):
            techs = hydrogen_technologies()
            tech_key = st.selectbox(
                "Technologia H2", list(techs), format_func=lambda k: techs[k].name_pl
            )
            production = st.number_input("Produkcja H2 [kg/h]", 1.0, 50000.0, 100.0, 10.0)
            cf = st.slider("Współczynnik wykorzystania", 0.1, 1.0, 0.9, 0.05)
            o2_rev = st.number_input(
                "Przychód z O2 [PLN/kg H2]",
                0.0,
                10.0,
                0.0,
                0.1,
                help="~8 kg O2/kg H2; rynek lokalny — orientacyjnie 0–2 PLN/kg H2.",
            )
            heat_rev = st.number_input(
                "Przychód z ciepła odpadowego [tys. PLN/rok]", 0.0, 1e5, 0.0, 10.0
            )
            unit = "PLN/kg"
            price_default = 30.0
        else:
            gen = generation_technologies()
            el_techs = {k: t for k, t in gen.items() if t.eta_el is not None}
            tech_key = st.selectbox(
                "Technologia (M7)", list(el_techs), format_func=lambda k: el_techs[k].name_pl
            )
            capacity = st.number_input("Moc [kW]", 10.0, 1e6, 1000.0, 100.0)
            unit = "PLN/MWh"
            price_default = 450.0

        product_price = st.number_input(
            f"Cena sprzedaży produktu [{unit}]",
            0.0,
            10000.0,
            price_default,
            1.0,
            help="Do NPV/IRR/DPP; przy cenie = LCOx wynik NPV ≈ 0.",
        )

    def compute(params: dict) -> float:
        if mode.startswith("LCOH"):
            return lcoh_for_technology(
                tech_key,
                sc,
                start_year,
                production_kg_per_h=params["produkcja"],
                capacity_factor=min(params["wsp. wykorzystania"], 1.0),
                wacc=params["WACC"],
                lifetime_years=lifetime,
                o2_revenue_pln_per_kg_h2=o2_rev,
                heat_revenue_pln_per_year=heat_rev * 1e3,
            ).lcox
        return lcoe_for_technology(
            tech_key,
            sc,
            start_year,
            capacity_kw=params["moc"],
            wacc=params["WACC"],
            lifetime_years=lifetime,
        ).lcox

    try:
        if mode.startswith("LCOH"):
            result = lcoh_for_technology(
                tech_key,
                sc,
                start_year,
                production,
                cf,
                wacc,
                lifetime,
                o2_revenue_pln_per_kg_h2=o2_rev,
                heat_revenue_pln_per_year=heat_rev * 1e3,
            )
            output_year = production * 8760.0 * cf
            base_params = {"produkcja": production, "wsp. wykorzystania": cf, "WACC": wacc}
        else:
            result = lcoe_for_technology(tech_key, sc, start_year, capacity, wacc, lifetime)
            output_year = result.discounted_output  # tylko do NPV poniżej używamy rocznej:
            tech = generation_technologies()[tech_key]
            cf_used = tech.eta_el if tech.fuel in ("slonce", "wiatr") else 0.85
            output_year = capacity * 8760.0 * cf_used / 1e3
            base_params = {"moc": capacity, "WACC": wacc}
        metrics = project_metrics(result, product_price, output_year, wacc, lifetime)
        tornado = tornado_analysis(base_params, compute, 0.20)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    with col_out:
        st.subheader("Koszt uśredniony i wskaźniki projektu")
        r1 = st.columns(4)
        r1[0].metric(f"LCOx [{unit}]", f"{result.lcox:,.2f}")
        if mode.startswith("LCOH"):
            r1[1].metric("LCOH [€/kg]", f"{result.lcox / eur_pln_rate():.2f}")
        else:
            r1[1].metric("LCOE [€/MWh]", f"{result.lcox / eur_pln_rate():.1f}")
        r1[2].metric(
            "NPV",
            f"{metrics['npv_pln'] / 1e6:,.2f} mln PLN",
            delta="≥0 — opłacalny" if metrics["npv_pln"] >= 0 else "<0",
            delta_color="normal" if metrics["npv_pln"] >= 0 else "inverse",
        )
        irr_v = metrics["irr"]
        r1[3].metric("IRR", f"{irr_v * 100:.1f}%" if irr_v is not None else "brak")
        dpp = metrics["dpp_years"]
        st.caption(
            f"Zdyskontowany okres zwrotu: "
            f"{f'{dpp:.1f} lat' if dpp is not None else 'brak zwrotu w okresie analizy'} · "
            f"przy cenie sprzedaży {product_price:g} {unit}"
        )

        st.subheader("Dekompozycja LCOx")
        comp_df = pd.DataFrame(
            {"Składnik": list(result.components), "Udział": list(result.components.values())}
        )
        fig = go.Figure(
            go.Bar(
                x=comp_df["Udział"],
                y=comp_df["Składnik"],
                orientation="h",
                marker_color=["#d62728" if v >= 0 else "#2ca02c" for v in comp_df["Udział"]],
            )
        )
        fig.update_layout(xaxis_title=f"{unit}", height=320, showlegend=False)
        st.plotly_chart(fig, config={"displaylogo": False})

    st.divider()
    st.subheader("Analiza wrażliwości (tornado, ±20%)")
    fig2 = go.Figure()
    for e in reversed(tornado):
        fig2.add_trace(
            go.Bar(
                y=[e.parameter],
                x=[e.high_value - e.base_value],
                base=e.base_value,
                orientation="h",
                marker_color="#d62728",
                name="+20%",
                showlegend=False,
            )
        )
        fig2.add_trace(
            go.Bar(
                y=[e.parameter],
                x=[e.low_value - e.base_value],
                base=e.base_value,
                orientation="h",
                marker_color="#1f77b4",
                name="−20%",
                showlegend=False,
            )
        )
    fig2.add_vline(x=tornado[0].base_value, line_dash="dot", annotation_text="baza")
    fig2.update_layout(barmode="overlay", xaxis_title=f"LCOx [{unit}]", height=300)
    st.plotly_chart(fig2, config={"displaylogo": False})
    st.caption("🔵 parametr −20% · 🔴 parametr +20% (ceny nośników: zmieniaj scenariusz M5)")

    with st.expander("📖 Założenia i wzory"):
        st.markdown(f"""
**Koszt uśredniony:** `LCOx = Σ K_t·d_t / Σ Q_t·d_t`, `d_t = (1+r)^-t`;
walidacja niezależna wzorem annuitetowym `CAPEX·CRF/Q + OPEX/Q`
(test < 10⁻⁹). **WACC realny** (domyślnie 7%) — spójny z realnymi cenami M5.

**Koszty roczne po latach kalendarzowych** ze ścieżek M5: energia, gaz,
CO2 (EUA × kurs {eur_pln_rate():.2f}); degradacja elektrolizera zwiększa
zużycie energii w czasie. **Przychody uboczne** (O2, ciepło odpadowe)
pomniejszają LCOx (metoda kosztu netto).

**NPV/IRR/DPP** przy zadanej cenie sprzedaży; test spójności: cena = LCOx
⇒ NPV = 0, IRR = WACC. **Wartość rezydualna**: liniowa do zera w czasie
życia aktywa (przy 20/20 lat = 0).

**Pominięto:** podatki/amortyzację podatkową (analiza pre-tax, realna),
koszty bilansowania, ubezpieczenia — do kalibracji w danych.
            """)
