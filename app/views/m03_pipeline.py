"""M3 — Gazociągi: strona Streamlit (przepustowość energetyczna GZ/H2/mieszanin)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

from core.composition import GasComposition
from core.compression import compress
from core.config import load_data_file
from core.gas_properties import compute_properties
from core.pipeline import max_mass_flow_kg_per_s, pipe_materials, pressure_profile
from core.units import bar_to_pa, celsius_to_kelvin


@st.cache_data(show_spinner="Obliczanie przepustowości dla porównywanych gazów…")
def _gas_comparison(
    base_fractions: tuple[tuple[str, float], ...],
    diameter_m: float,
    length_m: float,
    roughness_m: float,
    p_in_pa: float,
    p_out_pa: float,
    t_k: float,
) -> pd.DataFrame:
    """Porównanie przepustowości energetycznej tej samej rury dla GZ/H2/mieszanin.

    Energia tłoczenia: rekompresja p_wylot→p_wlot sprężarką odśrodkową
    (η politropowa 0,82 — wartość typowa z data/compressors.yaml).
    """
    base = GasComposition(fractions=base_fractions)
    rows = []
    for label, comp in [
        ("gaz bazowy", base),
        ("+10% H2", base.blend_with_hydrogen(0.10)),
        ("+20% H2", base.blend_with_hydrogen(0.20)),
        ("100% H2", GasComposition.pure("H2")),
    ]:
        m_max = max_mass_flow_kg_per_s(
            comp, diameter_m, length_m, roughness_m, p_in_pa, p_out_pa, t_k
        )
        res = pressure_profile(comp, diameter_m, length_m, roughness_m, m_max, p_in_pa, t_k)
        mw = res.energy_flow_mw()
        recomp = compress(comp, p_out_pa, t_k, p_in_pa, eta=0.82, model="politropowy")
        pump_kw = recomp.power_w(m_max) / 1e3
        rows.append(
            {
                "Gaz": label,
                "Strumień [kg/s]": m_max,
                "Strumień [Nm³/h]": res.volume_flow_nm3_per_h(),
                "Energia [MW]": mw,
                "Prędkość max [m/s]": res.max_velocity_m_per_s,
                "Tłoczenie [kWh/MWh]": pump_kw / mw if mw > 0 else float("nan"),
            }
        )
    df = pd.DataFrame(rows)
    df["% energii GZ"] = df["Energia [MW]"] / df.loc[0, "Energia [MW]"] * 100.0
    return df


def render() -> None:
    st.title("M3 · Gazociągi")
    st.caption(
        "Model marszowy: Darcy-Weisbach + Colebrook-White, lokalne właściwości "
        "GERG-2008 · przepływ izotermiczny (rura zakopana)"
    )

    col_in, col_out = st.columns([2, 3], gap="large")

    with col_in:
        st.subheader("Gaz")
        compositions = load_data_file("gas_compositions.yaml")["compositions"]
        gas_key = st.selectbox(
            "Skład bazowy",
            list(compositions),
            format_func=lambda k: compositions[k]["name_pl"],
        )
        base = GasComposition.predefined(gas_key)
        h2_pct = 0.0
        if gas_key != "wodor_99999":
            h2_pct = st.slider("Domieszka H2 [% mol]", 0.0, 100.0, 0.0, 5.0)
        composition = base.blend_with_hydrogen(h2_pct / 100.0)

        st.subheader("Rura")
        c1, c2 = st.columns(2)
        diameter_mm = c1.number_input("Średnica wewn. [mm]", 20.0, 1500.0, 300.0, 10.0)
        length_km = c2.number_input("Długość [km]", 0.1, 1000.0, 20.0, 1.0)

        materials = pipe_materials()
        mat_key = st.selectbox(
            "Materiał", list(materials), format_func=lambda k: materials[k].name_pl
        )
        mat = materials[mat_key]
        lo, hi = mat.roughness_range_mm
        roughness_mm = st.slider(
            "Chropowatość bezwzględna k [mm]",
            lo,
            hi,
            mat.roughness_typical_mm,
            help=f"Zakres dla materiału: {lo}–{hi} mm. Źródło: {mat.source}",
        )
        if mat.note:
            st.caption(f"ℹ️ {mat.note}")

        st.subheader("Warunki pracy")
        c3, c4, c5 = st.columns(3)
        p_in_bar = c3.number_input("p wlot [bar(a)]", 1.2, 100.0, 55.0, 1.0)
        p_out_bar = c4.number_input("p wylot min [bar(a)]", 1.1, 99.0, 45.0, 1.0)
        t_c = c5.number_input("T gazu [°C]", -20.0, 60.0, 10.0, 1.0)

        v_limits = load_data_file("pipelines.yaml")["velocity_limits_m_per_s"]
        v_limit_key = st.selectbox(
            "Limit prędkości",
            list(v_limits),
            format_func=lambda k: f"{v_limits[k]['name_pl']} ({v_limits[k]['max']:g} m/s)",
        )
        v_max_limit = float(v_limits[v_limit_key]["max"])

    if p_out_bar >= p_in_bar:
        st.error("Ciśnienie wylotowe musi być niższe od wlotowego.")
        st.stop()

    p_in, p_out = bar_to_pa(p_in_bar), bar_to_pa(p_out_bar)
    t_k = celsius_to_kelvin(t_c)
    d_m = diameter_mm / 1e3
    l_m = length_km * 1e3
    rough_m = roughness_mm / 1e3

    try:
        m_max = max_mass_flow_kg_per_s(composition, d_m, l_m, rough_m, p_in, p_out, t_k)
        if m_max <= 0:
            st.error("Brak przepustowości dla zadanych ciśnień — sprawdź parametry.")
            st.stop()
        result = pressure_profile(composition, d_m, l_m, rough_m, m_max, p_in, t_k)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    with col_out:
        st.subheader("Przepustowość maksymalna (p wylot = p min)")
        for w in result.warnings:
            st.warning(w)
        r1 = st.columns(4)
        r1[0].metric("Strumień masy", f"{result.mass_flow_kg_per_s:.2f} kg/s")
        r1[1].metric("Strumień objętości", f"{result.volume_flow_nm3_per_h():,.0f} Nm³/h")
        r1[2].metric("Przepustowość energet.", f"{result.energy_flow_mw():.1f} MW")
        r1[3].metric("Spadek ciśnienia", f"{result.pressure_drop_pa / 1e5:.2f} bar")
        r2 = st.columns(4)
        v_max = result.max_velocity_m_per_s
        r2[0].metric(
            "Prędkość max",
            f"{v_max:.1f} m/s",
            delta=f"limit {v_max_limit:g} m/s",
            delta_color="inverse" if v_max > v_max_limit else "normal",
        )
        r2[1].metric("Re (wlot)", f"{result.reynolds_inlet:,.0f}")
        r2[2].metric("λ (wlot)", f"{result.friction_factor_inlet:.4f}")
        props_in = compute_properties(composition, p_in, t_k)
        r2[3].metric("ρ (wlot)", f"{props_in.density_kg_per_m3:.2f} kg/m³")
        if v_max > v_max_limit:
            st.error(
                f"❌ Prędkość {v_max:.1f} m/s przekracza limit {v_max_limit:g} m/s "
                f"({v_limits[v_limit_key]['name_pl']}) — przepustowość ograniczona "
                "prędkością, nie ciśnieniem."
            )

        st.subheader("Profile wzdłuż trasy")
        km = [
            i * l_m / 1e3 / (len(result.pressure_profile_pa) - 1)
            for i in range(len(result.pressure_profile_pa))
        ]
        fig = make_subplots(specs=[[{"secondary_y": True}]])
        fig.add_trace(
            go.Scatter(
                x=km,
                y=[p / 1e5 for p in result.pressure_profile_pa],
                name="ciśnienie [bar]",
                mode="lines",
            ),
            secondary_y=False,
        )
        fig.add_trace(
            go.Scatter(
                x=km[1:],
                y=result.velocity_profile_m_per_s,
                name="prędkość [m/s]",
                mode="lines",
                line=dict(dash="dash"),
            ),
            secondary_y=True,
        )
        fig.add_hline(
            y=v_max_limit, line_dash="dot", secondary_y=True, annotation_text="limit prędkości"
        )
        fig.update_xaxes(title_text="Długość [km]")
        fig.update_yaxes(title_text="Ciśnienie [bar(a)]", secondary_y=False)
        fig.update_yaxes(title_text="Prędkość [m/s]", secondary_y=True)
        fig.update_layout(height=420, legend=dict(orientation="h"))
        st.plotly_chart(fig, config={"displaylogo": False})

    st.divider()
    st.subheader("Ta sama rura: GZ vs mieszaniny vs 100% H2")
    base_for_cmp = GasComposition.predefined("gaz_E_typowy") if gas_key == "wodor_99999" else base
    try:
        df = _gas_comparison(base_for_cmp.fractions, d_m, l_m, rough_m, p_in, p_out, t_k)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    c_l, c_r = st.columns([3, 2], gap="large")
    with c_l:
        fig2 = make_subplots(specs=[[{"secondary_y": True}]])
        fig2.add_trace(
            go.Bar(x=df["Gaz"], y=df["Energia [MW]"], name="przepustowość [MW]"),
            secondary_y=False,
        )
        fig2.add_trace(
            go.Scatter(
                x=df["Gaz"],
                y=df["Tłoczenie [kWh/MWh]"],
                name="energia tłoczenia [kWh/MWh]",
                mode="lines+markers",
            ),
            secondary_y=True,
        )
        fig2.update_yaxes(title_text="MW", secondary_y=False)
        fig2.update_yaxes(title_text="kWh el. / MWh paliwa", secondary_y=True)
        fig2.update_layout(height=400, legend=dict(orientation="h"))
        st.plotly_chart(fig2, config={"displaylogo": False})
    with c_r:
        st.dataframe(
            df.round(
                {
                    "Strumień [kg/s]": 2,
                    "Strumień [Nm³/h]": 0,
                    "Energia [MW]": 1,
                    "Prędkość max [m/s]": 1,
                    "Tłoczenie [kWh/MWh]": 2,
                    "% energii GZ": 1,
                }
            ),
            hide_index=True,
            width="stretch",
        )
        st.caption(
            "Energia tłoczenia: rekompresja p_wylot→p_wlot (odśrodkowa, "
            "η politropowa 0,82) na MWh przesłanej energii (Hi)."
        )

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Model marszowy:** rura dzielona na 50 segmentów; w każdym lokalna gęstość
i lepkość (GERG-2008, M1), prędkość z równania ciągłości `v = ṁ/(ρ·A)`,
spadek ciśnienia **Darcy-Weisbach**: `Δp = λ·(L/D)·ρ·v²/2`.

**Współczynnik tarcia λ:** równanie **Colebrooka-White'a**
`1/√λ = −2·log₁₀(k/(3,7·D) + 2,51/(Re·√λ))` (iteracyjnie; start: jawne
przybliżenie Serghidesa 1984). Re < 2300: λ = 64/Re. Walidacja: punkty
z wykresu Moody'ego + granica Nikuradse + zgodność z ogólnym równaniem
przepływu (testy automatyczne, < 3%).

**Przepływ izotermiczny** (rura zakopana, T ≈ const) — typowe założenie dla
gazociągów dystrybucyjnych. Pominięto: różnice wysokości, człon kinetyczny
(istotny dopiero przy v > 0,3·a — wtedy ostrzeżenie).

**Przepustowość maksymalna:** bisekcja strumienia masy do osiągnięcia
zadanego minimalnego ciśnienia wylotowego.

**Chropowatości** (`data/pipelines.yaml`): stal eksploatowana k = 0,05 mm
(0,02–0,10), PE100 nowe 0,007 mm (0,0015–0,01), **HDPE starsze 0,02 mm
(0,01–0,05) — wartość orientacyjna**: PE nie koroduje, wzrost chropowatości
wynika z osadów i zarysowań; zalecana weryfikacja pomiarami spadków ciśnień.

**Limity prędkości** — praktyka projektowa (hałas, erozja); konfigurowalne.
            """)
