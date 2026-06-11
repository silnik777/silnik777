"""M13 — Zimna redukcja: bilans stacji redukcyjnej w trzech wariantach."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.cold_reduction import (
    heat_sources,
    station_balance,
    station_presets,
    variant_economics,
)
from core.composition import GasComposition
from core.config import load_data_file
from core.expanders import expander_technologies
from core.gas_properties import compute_properties
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
        sources = heat_sources()
        source_key = st.selectbox("Źródło", list(sources), format_func=lambda k: sources[k].name_pl)
        source = sources[source_key]
        if source.note:
            st.caption(f"ℹ️ {source.note}")
        hours = st.number_input("Czas pracy [h/rok]", 100.0, 8760.0, 8000.0, 100.0)

    if p_out_mpa >= p_in_mpa:
        st.error("Ciśnienie wylotowe musi być niższe od wlotowego.")
        st.stop()

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
            economics[v.variant_key] = variant_economics(v, source, hours_per_year=hours)
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
            st.error(
                f"❌ Źródło '{source.name_pl}' (zasilanie {source.supply_temp_c:g} °C, "
                "pinch 10 K) nie osiąga wymaganej temperatury podgrzewu — "
                "wybierz gorętsze źródło."
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
        st.caption(
            "Ceny robocze (edytowalne w data/reduction_stations.yaml; pełne "
            "ścieżki cenowe — moduł M5). Pominięto CAPEX — porównanie OPEX."
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
podgrzew gazu; ciepło odpadowe sprężarek (M2) ma koszt krańcowy ~0.
**Plan integracji:** docelowo (etap 5) listę źródeł zasili biblioteka
technologii wytwarzania **M7** (kocioł kondensacyjny, silnik kogeneracyjny,
kolektor słoneczny, podgrzew elektryczny z PV, pompa ciepła) — z jej
temperaturami zasilania, sprawnościami i kosztami; obecna lista w
`data/reduction_stations.yaml` to roboczy podzbiór.

**Ekonomia:** proste porównanie roczne OPEX wg cen roboczych; analiza
NPV/IRR z CAPEX — moduł M10 (etap 6).
            """)
