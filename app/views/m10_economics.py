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
    lcoheat_for_technology,
    lcos_for_storage,
    project_metrics,
    tornado_analysis,
)
from core.generation import generation_technologies
from core.hydrogen import hydrogen_technologies
from core.prices import all_scenarios, eur_pln_rate


def render() -> None:
    st.title("M10 · Ekonomia (LCOH / LCOE / LCOHeat / LCOS)")
    st.caption(
        "Koszty uśrednione z dekompozycją · wodór, energia el., ciepło, magazyn · "
        "ceny ze ścieżek M5 · WACC 7% realnie, 20 lat (edytowalne) · NPV/IRR/DPP · tornado ±20%"
    )

    scenarios = all_scenarios()
    col_in, col_out = st.columns([2, 3], gap="large")

    modes = {
        "LCOH — wodór (M6)": "lcoh",
        "LCOE — energia el. (M7)": "lcoe",
        "LCOHeat — ciepło (M7)": "lcoheat",
        "LCOS — magazyn energii": "lcos",
    }
    with col_in:
        st.subheader("Projekt")
        mode_label = st.radio("Rodzaj analizy", list(modes))
        mode_key = modes[mode_label]
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

        if mode_key == "lcos":
            st.markdown("##### Magazyn energii (LCOS)")
            energy_mwh = st.number_input("Pojemność na cykl [MWh]", 0.1, 100000.0, 50.0, 1.0)
            rt = st.slider("Sprawność round-trip", 0.2, 1.0, 0.55, 0.01)
            cycles = st.number_input("Liczba cykli / rok", 1.0, 8760.0, 200.0, 10.0)
            capex_mln = st.number_input("CAPEX [mln PLN]", 0.1, 100000.0, 100.0, 1.0)
            charge_default = float(sc.price("energia_elektryczna", start_year))
            charge_price = st.number_input(
                "Cena energii ładowania [PLN/MWh]",
                0.0,
                5000.0,
                charge_default,
                10.0,
                help="Domyślnie cena energii elektrycznej ze scenariusza M5 w roku startu.",
            )
            opex_pct = st.number_input("OPEX [% CAPEX/rok]", 0.0, 20.0, 2.0, 0.5)

        if mode_key == "lcoh":
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
        elif mode_key == "lcoe":
            gen = generation_technologies()
            el_techs = {k: t for k, t in gen.items() if t.eta_el is not None}
            tech_key = st.selectbox(
                "Technologia (M7)", list(el_techs), format_func=lambda k: el_techs[k].name_pl
            )
            capacity = st.number_input("Moc [kW]", 10.0, 1e6, 1000.0, 100.0)
            unit = "PLN/MWh"
            price_default = 450.0
        elif mode_key == "lcoheat":
            gen = generation_technologies()
            heat_techs = {k: t for k, t in gen.items() if t.category == "cieplo"}
            tech_key = st.selectbox(
                "Technologia cieplna (M7)",
                list(heat_techs),
                format_func=lambda k: heat_techs[k].name_pl,
            )
            capacity = st.number_input("Moc cieplna [kW]", 10.0, 1e6, 1000.0, 100.0)
            cf_heat = st.slider("Współczynnik wykorzystania", 0.1, 1.0, 0.4, 0.05)
            unit = "PLN/MWh"
            price_default = 250.0

        if mode_key != "lcos":
            product_price = st.number_input(
                f"Cena sprzedaży produktu [{unit}]",
                0.0,
                10000.0,
                price_default,
                1.0,
                help="Do NPV/IRR/DPP; przy cenie = LCOx wynik NPV ≈ 0.",
            )

    # --- LCOS: dedykowany kalkulator magazynu (poza ścieżką NPV/tornado) ------
    if mode_key == "lcos":
        try:
            sres = lcos_for_storage(
                capex_pln=capex_mln * 1e6,
                energy_capacity_mwh=energy_mwh,
                round_trip_efficiency=rt,
                cycles_per_year=cycles,
                charge_price_pln_per_mwh=charge_price,
                wacc=wacc,
                lifetime_years=lifetime,
                opex_pct_capex=opex_pct,
            )
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
            return
        with col_out:
            st.subheader("LCOS — koszt uśredniony magazynowania")
            m = st.columns(3)
            m[0].metric("LCOS", f"{sres.lcos_pln_per_mwh:,.0f} PLN/MWh")
            m[1].metric("Energia rozładowana", f"{sres.annual_discharged_mwh:,.0f} MWh/rok")
            m[2].metric("Energia ładowania", f"{sres.annual_charged_mwh:,.0f} MWh/rok")
            comp_df = pd.DataFrame(
                {"Składnik": list(sres.components), "PLN/MWh": list(sres.components.values())}
            )
            fig = go.Figure(go.Bar(x=comp_df["PLN/MWh"], y=comp_df["Składnik"], orientation="h"))
            fig.update_layout(xaxis_title="PLN/MWh rozładowanej", height=300, showlegend=False)
            st.plotly_chart(fig, config={"displaylogo": False})
            st.caption(
                "LCOS = (CAPEX·CRF + OPEX + koszt ładowania) / energia rozładowana. "
                "Energia ładowania = rozładowana / round-trip (straty cyklu). Dla "
                "linepacku/CAES pojemność i round-trip weź z M12; cena ładowania ze "
                "scenariusza M5. Porównanie z bateriami/PHES — moduł M11."
            )
        return

    def compute(params: dict) -> float:
        if mode_key == "lcoh":
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
        if mode_key == "lcoheat":
            return lcoheat_for_technology(
                tech_key,
                sc,
                start_year,
                capacity_kw_heat=params["moc"],
                capacity_factor=cf_heat,
                wacc=params["WACC"],
                lifetime_years=lifetime,
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
        if mode_key == "lcoh":
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
        elif mode_key == "lcoheat":
            result = lcoheat_for_technology(
                tech_key, sc, start_year, capacity, cf_heat, wacc, lifetime
            )
            output_year = capacity * 8760.0 * cf_heat / 1e3
            base_params = {"moc": capacity, "WACC": wacc}
        else:
            result = lcoe_for_technology(tech_key, sc, start_year, capacity, wacc, lifetime)
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
        if mode_key == "lcoh":
            r1[1].metric("LCOH [€/kg]", f"{result.lcox / eur_pln_rate():.2f}")
        else:
            r1[1].metric("LCOx [€/MWh]", f"{result.lcox / eur_pln_rate():.1f}")
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

**LCOHeat (ciepło, M7):** produkcja = moc cieplna × 8760 × wykorzystanie;
koszt nośnika = cena paliwa/energii ÷ sprawność cieplną (pompy ciepła: ÷COP);
CO2 (EUA) dla paliw kopalnych. Technologie kategorii „cieplo" (kotły, pompy
ciepła, kolektory); ciepło kogeneracji rozliczane metodą energetyczną (M13).

**LCOS (magazyn):** `LCOS = (CAPEX·CRF + OPEX + koszt ładowania) / energia
rozładowana`; energia ładowania = rozładowana / round-trip. Dla linepacku/
CAES pojemność i round-trip z M12; cena ładowania ze scenariusza M5.

**NPV/IRR/DPP** przy zadanej cenie sprzedaży; test spójności: cena = LCOx
⇒ NPV = 0, IRR = WACC. **Wartość rezydualna**: liniowa do zera w czasie
życia aktywa (przy 20/20 lat = 0).

**Pominięto:** podatki/amortyzację podatkową (analiza pre-tax, realna),
koszty bilansowania, ubezpieczenia — do kalibracji w danych.
            """)
