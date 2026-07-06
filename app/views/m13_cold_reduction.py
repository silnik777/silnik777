"""M13 — Zimna redukcja: bilans stacji redukcyjnej w trzech wariantach."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.cold_reduction import (
    heat_source_from_compression,
    heat_sources,
    station_balance,
    station_presets,
    variant_economics,
)
from core.composition import GasComposition
from core.compression import compress
from core.config import load_data_file
from core.economics import DEFAULT_LIFETIME_YEARS, DEFAULT_WACC, expander_station_economics
from core.expanders import expander_technologies
from core.gas_properties import compute_properties
from core.prices import all_scenarios
from core.units import celsius_to_kelvin, mpa_to_pa


def render() -> None:
    st.title("M13 · Zimna redukcja — bilans stacji")
    st.caption(
        "Warianty: JT z podgrzewem · ekspander z odzyskiem (M4) · zimna "
        "redukcja bez podgrzewu · źródła ciepła i hydraty: data/"
    )

    col_in, col_out = st.columns([2, 3], gap="large")

    with col_in:
        st.subheader("Gaz i stacja")
        compositions = load_data_file("gas_compositions.yaml")["compositions"]
        gas_key = st.selectbox(
            "Skład", list(compositions), format_func=lambda k: compositions[k]["name_pl"]
        )
        composition = GasComposition.predefined(gas_key)

        presets = station_presets()
        preset_key = st.selectbox(
            "Wariant stacji (edytowalny)",
            list(presets),
            format_func=lambda k: presets[k]["name_pl"],
        )
        preset = presets[preset_key]
        st.caption(f"ℹ️ {preset['source']}")
        c1, c2, c3 = st.columns(3)
        p_in_mpa = c1.number_input("p wlot [MPa]", 0.2, 12.0, float(preset["p_in_mpa"]), 0.1)
        p_out_mpa = c2.number_input("p wylot [MPa]", 0.1, 10.0, float(preset["p_out_mpa"]), 0.1)
        t_in_c = c3.number_input("T wlotu [°C]", -20.0, 40.0, float(preset["t_in_c"]), 1.0)
        flow_nm3_h = st.number_input("Strumień [Nm³/h]", 10.0, 500000.0, 5000.0, 100.0)

        st.subheader("Ograniczenie temperatury wylotowej")
        t_min_mode = st.radio(
            "Minimalna T wylotowa",
            ["auto: hydraty + margines", "0 °C (armatura/grunt)", "własna"],
            help="Tryb auto: korelacja Towlera-Mokhataba + margines 3 K.",
        )
        t_min_k: float | None = None
        if t_min_mode == "0 °C (armatura/grunt)":
            t_min_k = 273.15
        elif t_min_mode == "własna":
            t_min_k = celsius_to_kelvin(
                st.number_input("Minimalna T wylotowa [°C]", -30.0, 30.0, 3.0, 0.5)
            )

        st.subheader("Ekspander (wariant 2)")
        techs = expander_technologies()
        tech_key = st.selectbox("Technologia", list(techs), format_func=lambda k: techs[k].name_pl)
        tech = techs[tech_key]
        jt_position = st.radio("Reduktor JT", ["za", "przed"], horizontal=True)

        st.subheader("Źródło ciepła podgrzewu")
        computed_source = None
        with st.expander("🔥 Policz ciepło odpadowe sprężarki (M2)"):
            st.caption(
                "Zbuduj źródło ciepła z **policzonego** sprężania (M2) zamiast "
                "wpisu statycznego: poziom temperatury i dostępna moc cieplna "
                "wynikają z bilansu chłodnic."
            )
            use_computed = st.checkbox("Użyj policzonego ciepła sprężarki jako źródła")
            k1, k2 = st.columns(2)
            comp_p_in = k1.number_input("p ssania sprężarki [MPa]", 0.1, 12.0, 0.4, 0.1)
            comp_p_out = k2.number_input("p tłoczenia sprężarki [MPa]", 0.2, 25.0, 5.5, 0.1)
            k3, k4 = st.columns(2)
            comp_t_in_c = k3.number_input("T ssania [°C]", -20.0, 60.0, 20.0, 1.0)
            comp_flow = k4.number_input("Strumień sprężany [Nm³/h]", 10.0, 500000.0, 5000.0, 100.0)
            comp_stages = st.number_input("Liczba stopni", 1, 6, 2)
            comp_eta = st.slider("Sprawność politropowa", 0.5, 0.9, 0.78, 0.01)
        sources = heat_sources()
        source_key = st.selectbox("Źródło", list(sources), format_func=lambda k: sources[k].name_pl)
        source = sources[source_key]

        st.subheader("Ceny energii")
        scenarios = all_scenarios()
        price_mode = st.radio(
            "Źródło cen",
            ["scenariusz M5", "ceny robocze (data/)"],
            help="Scenariusz M5 spina M13 z resztą narzędzia (jedno źródło cen).",
        )
        scenario = None
        econ_year: int | None = None
        if price_mode == "scenariusz M5":
            sc_key = st.selectbox(
                "Scenariusz cenowy (M5)",
                list(scenarios),
                index=list(scenarios).index("bazowy") if "bazowy" in scenarios else 0,
                format_func=lambda k: scenarios[k].name_pl,
            )
            scenario = scenarios[sc_key]
            econ_year = st.slider("Rok analizy cen", 2025, 2050, 2030)

        hours = st.number_input("Czas pracy [h/rok]", 100.0, 8760.0, 8000.0, 100.0)

    if p_out_mpa >= p_in_mpa:
        st.error("Ciśnienie wylotowe musi być niższe od wlotowego.")
        st.stop()

    # Opcjonalne źródło ciepła z policzonego sprężania (M2 → M13).
    if use_computed:
        if comp_p_out <= comp_p_in:
            st.error("Sprężarka: ciśnienie tłoczenia musi być wyższe od ssania.")
            st.stop()
        try:
            rho_n_comp = compute_properties(composition, 101_325.0, 273.15).density_kg_per_m3
            comp_result = compress(
                composition,
                mpa_to_pa(comp_p_in),
                celsius_to_kelvin(comp_t_in_c),
                mpa_to_pa(comp_p_out),
                eta=comp_eta,
                n_stages=int(comp_stages),
                model="politropowy",
            )
            computed_source = heat_source_from_compression(
                comp_result, comp_flow * rho_n_comp / 3600.0
            )
        except ValueError as exc:
            st.error(f"Ciepło odpadowe sprężarki: {exc}")
            st.stop()
        source = computed_source
        st.info(
            f"🔥 Źródło z M2: **{source.name_pl}** — zasilanie "
            f"{source.supply_temp_c:.0f} °C, dostępna moc {source.available_kw:.0f} kW."
        )

    if source.note:
        st.caption(f"ℹ️ {source.note}")

    rho_n = compute_properties(composition, 101_325.0, 273.15).density_kg_per_m3
    mass_flow = flow_nm3_h * rho_n / 3600.0

    try:
        variants = station_balance(
            composition,
            mpa_to_pa(p_in_mpa),
            celsius_to_kelvin(t_in_c),
            mpa_to_pa(p_out_mpa),
            mass_flow,
            t_out_min_k=t_min_k,
            expander_eta=tech.eta_typical,
            expander_max_ratio=tech.max_expansion_ratio,
            jt_position=jt_position,
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    economics = {}
    for v in variants:
        try:
            economics[v.variant_key] = variant_economics(
                v, source, hours_per_year=hours, scenario=scenario, year=econ_year
            )
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
            return

    with col_out:
        st.subheader("Porównanie wariantów")
        rows = []
        for v in variants:
            eco = economics[v.variant_key]
            rows.append(
                {
                    "Wariant": v.name_pl,
                    "Podgrzew do [°C]": (
                        v.t_preheat_required_k - 273.15
                        if v.t_preheat_required_k is not None
                        else None
                    ),
                    "Moc podgrzewu [kW]": v.preheat_duty_w / 1e3,
                    "Moc odzysk. [kW]": v.power_recovered_w / 1e3,
                    "T wylotu [°C]": v.t_out_k - 273.15,
                    "Chłód [kW]": v.cooling_potential_w / 1e3,
                    "Koszt netto [tys. zł/r]": eco.net_cost_pln_per_year / 1e3,
                    "Źródło ciepła OK": "✅" if eco.heat_source_ok else "❌",
                }
            )
        st.dataframe(pd.DataFrame(rows).round(1), hide_index=True, width="stretch")

        for v in variants:
            for w in v.warnings:
                st.warning(f"**{v.name_pl}**: {w}")
        if any(not economics[v.variant_key].heat_source_ok for v in variants):
            cap = (
                f", limit mocy {source.available_kw:.0f} kW"
                if source.available_kw is not None
                else ""
            )
            st.error(
                f"❌ Źródło '{source.name_pl}' (zasilanie {source.supply_temp_c:g} °C, "
                f"pinch 10 K{cap}) nie pokrywa wymaganego podgrzewu — wybierz "
                "gorętsze/mocniejsze źródło."
            )

        fig = go.Figure()
        names = [v.name_pl for v in variants]
        fig.add_trace(
            go.Bar(
                name="koszt podgrzewu",
                x=names,
                y=[economics[v.variant_key].preheat_cost_pln_per_year / 1e3 for v in variants],
                marker_color="#d62728",
            )
        )
        fig.add_trace(
            go.Bar(
                name="przychód z energii",
                x=names,
                y=[
                    -economics[v.variant_key].electricity_revenue_pln_per_year / 1e3
                    for v in variants
                ],
                marker_color="#2ca02c",
            )
        )
        fig.update_layout(
            barmode="relative",
            yaxis_title="tys. zł/rok (koszt +, przychód −)",
            height=400,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        price_note = (
            f"Ceny ze scenariusza M5 „{scenario.name_pl}”, rok {econ_year}."
            if scenario is not None
            else "Ceny robocze (data/reduction_stations.yaml)."
        )
        st.caption(f"{price_note} Pominięto CAPEX — porównanie OPEX.")

        # --- Opłacalność ekspandera (M4/M13 → M10) -------------------------
        st.subheader("💰 Opłacalność ekspandera (M10)")
        exp_variant = next((v for v in variants if v.variant_key == "ekspander"), None)
        jt_variant = next((v for v in variants if v.variant_key == "jt"), None)
        if scenario is None:
            st.info(
                "Analiza NPV/IRR/LCOE ekspandera wymaga scenariusza cenowego M5 "
                "(przełącz „Źródło cen” na scenariusz M5)."
            )
        elif exp_variant is None or exp_variant.power_recovered_w <= 0:
            st.info("Wybrany wariant ekspandera nie odzyskuje mocy — brak projektu do wyceny.")
        else:
            wl, wr = st.columns(2)
            wacc = wl.number_input("WACC (realny)", 0.01, 0.20, DEFAULT_WACC, 0.005, format="%.3f")
            lifetime = int(wr.number_input("Okres analizy [lata]", 5, 40, DEFAULT_LIFETIME_YEARS))
            try:
                ee = expander_station_economics(
                    exp_variant,
                    jt_variant,
                    tech,
                    source,
                    scenario,
                    start_year=int(econ_year),
                    hours_per_year=hours,
                    wacc=wacc,
                    lifetime_years=lifetime,
                )
            except ValueError as exc:
                st.error(str(exc))
            else:
                m = st.columns(4)
                m[0].metric("CAPEX", f"{ee.capex_pln / 1e6:,.2f} mln zł")
                m[1].metric("LCOE ekspandera", f"{ee.lcoe_pln_per_mwh:,.0f} zł/MWh")
                m[2].metric(
                    "NPV",
                    f"{ee.npv_pln / 1e6:,.2f} mln zł",
                    delta="opłacalny" if ee.npv_pln > 0 else "nieopłacalny",
                )
                m[3].metric(
                    "IRR",
                    f"{ee.irr * 100:.1f}%" if ee.irr is not None else "—",
                )
                m2 = st.columns(3)
                m2[0].metric("Energia odzyskana", f"{ee.annual_energy_mwh:,.0f} MWh/rok")
                m2[1].metric(
                    "Dodatkowy podgrzew (vs JT)", f"{ee.extra_heat_mwh_per_year:,.0f} MWh/rok"
                )
                m2[2].metric(
                    "Zwrot (DPP)",
                    f"{ee.dpp_years:.1f} lat" if ee.dpp_years is not None else "> okres",
                )
                st.caption(
                    "Rachunek **przyrostowy** względem wariantu JT: CAPEX z mapy "
                    f"doboru M4 ({tech.capex_eur_per_kw_typical:.0f} €/kW · typ.), "
                    "dodatkowy podgrzew (ekspansja chłodzi silniej) wyceniony wg "
                    "wybranego źródła ciepła i ścieżek cen M5, przychód = energia "
                    "elektryczna × cena energii (rok po roku)."
                )

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Wariant JT:** podgrzew z bilansu dławienia `h(p₁, T₁) = h(p₂, T_min)` —
rozwiązanie bezpośrednie (bez iteracji), gaz rzeczywisty GERG-2008.

**Wariant ekspandera:** podgrzew z bisekcji T₁ tak, by T_wylotu = T_min;
rozprężanie chłodzi silniej niż dławienie ⇒ podgrzew większy niż w JT,
ale odzyskujemy energię elektryczną (moduł M4: η, limit r, reduktor JT).

**Zimna redukcja:** bez podgrzewu; „chłód" = entalpia ogrzania gazu od
T_wylotu do temperatury otoczenia (potencjał odzysku, np. chłodnictwo);
flagi: hydraty (screening Towler-Mokhatab + margines) i T < 0 °C.

**Źródła ciepła:** temperatura zasilania − pinch 10 K ogranicza osiągalny
podgrzew gazu. **Ciepło odpadowe sprężarki (M2)** można teraz **policzyć**:
poziom temperatury = najzimniejszy stopień − 10 K, dostępna moc = bilans
chłodnic międzystopniowych + końcowej; przy niewystarczającej mocy wariant
dostaje flagę ❌. Listę źródeł zasila też biblioteka technologii **M7**
(kocioł kondensacyjny, silnik kogeneracyjny, kolektor słoneczny, podgrzew
z PV, pompa ciepła) — z temperaturami zasilania i sprawnościami.

**Ceny:** preferencyjnie ze **scenariusza cenowego M5** (rok kalendarzowy —
jedno źródło prawdy z modułami M6–M11); ceny robocze z `data/` jako fallback.
Nośnik „odpadowe" (ciepło sprężarek) zawsze po koszcie krańcowym.

**Opłacalność ekspandera (M10):** rachunek przyrostowy względem JT —
CAPEX = moc odzyskana × €/kW technologii (mapa doboru M4), koszt =
dodatkowy podgrzew ponad JT wg źródła ciepła i cen M5, przychód = energia
elektryczna × cena energii (ścieżka M5 rok po roku); wynik: LCOE, NPV, IRR,
zdyskontowany okres zwrotu (WACC 7% realnie, 20 lat — edytowalne).
            """)
