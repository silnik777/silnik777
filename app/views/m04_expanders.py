"""M4 — Ekspandery: macierz doboru i punkt pracy (strona Streamlit)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.cold_reduction import station_presets
from core.composition import GasComposition
from core.config import load_data_file
from core.expanders import expand, expander_technologies, selection_matrix
from core.gas_properties import compute_properties
from core.hydrates import check_hydrates
from core.units import celsius_to_kelvin, mpa_to_pa


def render() -> None:
    st.title("M4 · Ekspandery")
    st.caption(
        "Odzysk energii z redukcji ciśnienia · biblioteka technologii: "
        "data/expanders.yaml (wartości orientacyjne ze źródłami)"
    )

    col_in, col_out = st.columns([2, 3], gap="large")

    with col_in:
        st.subheader("Gaz")
        compositions = load_data_file("gas_compositions.yaml")["compositions"]
        gas_key = st.selectbox(
            "Skład", list(compositions), format_func=lambda k: compositions[k]["name_pl"]
        )
        composition = GasComposition.predefined(gas_key)

        st.subheader("Punkt pracy (stacja redukcyjna)")
        presets = station_presets()
        preset_key = st.selectbox(
            "Wariant stacji (edytowalny)",
            list(presets),
            format_func=lambda k: presets[k]["name_pl"],
        )
        preset = presets[preset_key]
        c1, c2, c3 = st.columns(3)
        p_in_mpa = c1.number_input("p wlot [MPa]", 0.2, 12.0, float(preset["p_in_mpa"]), 0.1)
        p_out_mpa = c2.number_input("p wylot [MPa]", 0.1, 10.0, float(preset["p_out_mpa"]), 0.1)
        t_in_c = c3.number_input(
            "T przed ekspanderem [°C]",
            -10.0,
            120.0,
            40.0,
            1.0,
            help="Temperatura PO podgrzewie (dobór podgrzewu: moduł M13).",
        )
        flow_nm3_h = st.number_input("Strumień [Nm³/h]", 10.0, 500000.0, 5000.0, 100.0)
        jt_position = st.radio(
            "Reduktor JT przy przekroczeniu r_max maszyny",
            ["za", "przed"],
            horizontal=True,
            help="Część redukcji ponad limit stosunku rozprężania maszyny "
            "realizuje reduktor JT przed albo za ekspanderem.",
        )

    if p_out_mpa >= p_in_mpa:
        st.error("Ciśnienie wylotowe musi być niższe od wlotowego.")
        st.stop()

    p_in, p_out = mpa_to_pa(p_in_mpa), mpa_to_pa(p_out_mpa)
    t_in = celsius_to_kelvin(t_in_c)
    ratio = p_in / p_out

    try:
        entries = selection_matrix(composition, p_in, t_in, p_out, flow_nm3_h, jt_position)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    with col_out:
        st.subheader(f"Macierz doboru (r = {ratio:.2f}, {flow_nm3_h:,.0f} Nm³/h)")
        df = pd.DataFrame(
            {
                "Technologia": [e.technology.name_pl for e in entries],
                "Wykonalna": ["✅" if e.feasible else "❌" for e in entries],
                "Moc [kW]": [e.power_kw for e in entries],
                "η typ.": [e.technology.eta_typical for e in entries],
                "r_max": [e.technology.max_expansion_ratio for e in entries],
                "Reduktor JT": ["tak" if e.ratio_needs_jt else "—" for e in entries],
                "CAPEX [tys. €]": [e.capex_eur_estimate / 1e3 for e in entries],
                "€/kW": [e.technology.capex_eur_per_kw_typical for e in entries],
                "TRL": [e.technology.trl for e in entries],
            }
        ).round({"Moc [kW]": 1, "CAPEX [tys. €]": 0})
        st.dataframe(df, hide_index=True, width="stretch")
        st.caption(
            "Wykonalność: przepływ i moc w mapie stosowalności technologii. "
            "CAPEX = moc × typowy koszt jednostkowy (orientacyjnie)."
        )

        fig = go.Figure(
            go.Bar(
                x=[e.technology.name_pl for e in entries],
                y=[e.power_kw for e in entries],
                marker_color=["#2ca02c" if e.feasible else "#bbbbbb" for e in entries],
                text=[f"{e.power_kw:.0f} kW" for e in entries],
            )
        )
        fig.update_layout(yaxis_title="Moc odzyskana [kW]", height=380, showlegend=False)
        st.plotly_chart(fig, config={"displaylogo": False})

    st.divider()
    st.subheader("Szczegóły wybranej technologii")
    techs = expander_technologies()
    tech_key = st.selectbox("Technologia", list(techs), format_func=lambda k: techs[k].name_pl)
    tech = techs[tech_key]
    eta = st.slider("Sprawność izentropowa η", tech.eta_min, tech.eta_max, tech.eta_typical, 0.01)
    st.caption(
        f"Zakres η: {tech.eta_min:.2f}–{tech.eta_max:.2f} · r na maszynę: "
        f"{tech.expansion_ratio_range[0]:g}–{tech.expansion_ratio_range[1]:g} · "
        f"CAPEX {tech.capex_eur_per_kw_range[0]:g}–{tech.capex_eur_per_kw_range[1]:g} €/kW · "
        f"{tech.h2_note} · Źródło: {tech.source}"
    )

    try:
        result = expand(composition, p_in, t_in, p_out, eta, tech.max_expansion_ratio, jt_position)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    rho_n = compute_properties(composition, 101_325.0, 273.15).density_kg_per_m3
    mass_flow = flow_nm3_h * rho_n / 3600.0
    hydrate = check_hydrates(composition, p_out)

    r1 = st.columns(4)
    r1[0].metric("Moc odzyskana", f"{result.power_w(mass_flow) / 1e3:.1f} kW")
    r1[1].metric("Praca właściwa", f"{result.work_j_per_kg / 1e3:.2f} kJ/kg")
    r1[2].metric("T za ekspanderem", f"{result.temperature_expander_out_k - 273.15:.1f} °C")
    r1[3].metric("T za układem", f"{result.temperature_out_k - 273.15:.1f} °C")
    r2 = st.columns(4)
    r2[0].metric(
        "Sprawność odzysku",
        f"{result.work_j_per_kg / result.work_isentropic_j_per_kg * 100:.0f}%",
        help="Praca odzyskana / praca izentropowa pełnej redukcji (η=1, bez limitu r).",
    )
    r2[1].metric("r ekspandera", f"{result.expansion_ratio_expander:.2f}")
    r2[2].metric("Reduktor JT", result.jt_position)
    if hydrate.min_safe_temperature_k is not None:
        r2[3].metric(
            "Min. T bezpieczna (hydraty)",
            f"{hydrate.min_safe_temperature_k - 273.15:.1f} °C",
        )
    if hydrate.is_at_risk(result.temperature_out_k):
        st.warning(
            "❄️ Temperatura za układem poniżej progu hydratowego — zwiększ "
            "podgrzew (dobór podgrzewu i źródła ciepła: moduł M13) albo "
            "zastosuj osuszanie/inhibicję."
        )
    for w in hydrate.warnings:
        st.caption(f"ℹ️ {w}")

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Rozprężanie:** `w = η_s·(h₁ − h(p₂, s₁))` (gaz rzeczywisty GERG-2008);
stan wylotowy z flashu (h₁−w, p₂). Mieszaniny: flashe h-p / p-s rozwiązywane
bisekcją po T w fazie gazowej (natywne flashe CoolProp dla mieszanin wymagają
otoczki fazowej).

**Limit stosunku rozprężania:** gdy r > r_max maszyny, nadwyżkę przejmuje
**reduktor JT** (dławienie izentalpowe) przed lub za ekspanderem — praca
odzyskana w obu konfiguracjach jest zbliżona (test < 5%); różnią się
temperatury pośrednie i gabaryt maszyny.

**Hydraty:** korelacja Towlera-Mokhataba (2005), frakcja bez H₂/He przy
pełnym ciśnieniu (konserwatywnie), margines +3 K (konfigurowalny) —
screening; rzeczywiste ryzyko zależy od zawartości wody w gazie.

**Biblioteka technologii** (`data/expanders.yaml`): sprawności, mapy
przepływ×moc, r_max, CAPEX/kW, TRL — **wartości orientacyjne** (Kostowski
2013, dane producentów) do weryfikacji ofertami.
            """)
