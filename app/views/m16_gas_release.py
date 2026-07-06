"""Moduł strat gazu z awarii (rozszczelnienie/pęknięcie gazociągu)."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.composition import GasComposition
from core.config import load_data_file
from core.gas_release import blowdown, flammable_jet_extent, gas_release_rate
from core.units import celsius_to_kelvin, mpa_to_pa


def render() -> None:
    st.title("Straty gazu z awarii gazociągu")
    st.caption(
        "Niekontrolowany wypływ przez otwór/rozszczelnienie: wypływ krytyczny "
        "vs podkrytyczny · natężenie masowe i objętościowe · blowdown odcinka · "
        "strefa zagrożenia (LEL) · właściwości GERG-2008 (M1)"
    )

    col_in, col_out = st.columns([2, 3], gap="large")

    with col_in:
        st.subheader("Gaz i stan w gazociągu")
        compositions = load_data_file("gas_compositions.yaml")["compositions"]
        gas_key = st.selectbox(
            "Skład", list(compositions), format_func=lambda k: compositions[k]["name_pl"]
        )
        composition = GasComposition.predefined(gas_key)
        c1, c2 = st.columns(2)
        p_mpa = c1.number_input("Ciśnienie robocze [MPa]", 0.2, 12.0, 5.5, 0.1)
        t_c = c2.number_input("Temperatura gazu [°C]", -20.0, 60.0, 10.0, 1.0)

        st.subheader("Otwór / rozszczelnienie")
        hole_mm = st.number_input("Średnica otworu [mm]", 1.0, 1500.0, 50.0, 1.0)
        cd = st.slider(
            "Współczynnik wypływu C_d",
            0.5,
            1.0,
            0.62,
            0.01,
            help="Kryza ostrokrawędziowa ~0,6; pełne pęknięcie/gładki otwór → ~0,9–1,0.",
        )

        st.subheader("Blowdown odcinka (opcjonalnie)")
        do_blowdown = st.checkbox("Policz opróżnianie odcinka")
        b1, b2 = st.columns(2)
        seg_d_mm = b1.number_input("Średnica wewn. rury [mm]", 50.0, 1500.0, 300.0, 10.0)
        seg_len_km = b2.number_input("Długość odcinka [km]", 0.1, 100.0, 1.0, 0.1)

    p_pa = mpa_to_pa(p_mpa)
    t_k = celsius_to_kelvin(t_c)

    try:
        rel = gas_release_rate(composition, p_pa, t_k, hole_mm / 1e3, cd)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    with col_out:
        st.subheader("Chwilowy wypływ przez otwór")
        regime = "krytyczny (sonic)" if rel.choked else "podkrytyczny"
        st.markdown(
            f"Reżim wypływu: **{regime}** "
            f"(p₁/p₀ = {rel.pressure_ratio:.1f}, r_kryt = {rel.critical_pressure_ratio:.2f})"
        )
        m1 = st.columns(4)
        m1[0].metric("Natężenie masowe", f"{rel.mass_flow_kg_per_s:.2f} kg/s")
        m1[1].metric("Prędkość w otworze", f"{rel.velocity_at_hole_m_per_s:.0f} m/s")
        m1[2].metric("Wypływ", f"{rel.volumetric_flow_nm3_per_h:,.0f} Nm³/h")
        m1[3].metric("Wypływ", f"{rel.volumetric_flow_nm3_per_min:,.0f} Nm³/min")
        st.caption(
            f"Strumień w warunkach roboczych: {rel.volumetric_flow_upstream_m3_per_s:.3f} m³/s "
            f"(ρ = {rel.density_upstream_kg_per_m3:.1f} kg/m³). "
            "Wypływ krytyczny zależy tylko od stanu górnego, nie od otoczenia."
        )

        # Strefa zagrożenia (LEL)
        hz = flammable_jet_extent(composition, rel)
        if hz is not None:
            st.subheader("Strefa zagrożenia wybuchem (screening)")
            hcols = st.columns(3)
            hcols[0].metric("Zasięg do LEL (oś strumienia)", f"{hz.distance_to_lel_m:.1f} m")
            hcols[1].metric("LEL", f"{hz.lel_vol_pct:.2f} %obj")
            hcols[2].metric("UEL", f"{hz.uel_vol_pct:.1f} %obj")
            st.warning("⚠️ " + hz.note)
        else:
            st.info("Gaz niepalny — strefa zagrożenia wybuchem nie dotyczy.")

    if do_blowdown:
        seg_volume = math.pi * (seg_d_mm / 1e3) ** 2 / 4.0 * (seg_len_km * 1e3)
        try:
            bd = blowdown(composition, seg_volume, p_pa, t_k, hole_mm / 1e3, cd)
        except ValueError as exc:
            st.error(str(exc))
            st.stop()
            return

        st.divider()
        st.subheader("Blowdown — opróżnianie odcinka")
        bcols = st.columns(4)
        bcols[0].metric("Objętość odcinka", f"{seg_volume:,.0f} m³")
        bcols[1].metric("Utracony gaz", f"{bd.total_lost_nm3:,.0f} Nm³")
        bcols[2].metric("Masa utracona", f"{bd.total_lost_kg / 1e3:,.1f} t")
        bcols[3].metric("Czas opróżniania", f"{bd.blowdown_time_min:,.1f} min")

        bar = [p / 1e5 for p in bd.pressures_pa]
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=bd.times_s, y=bar, mode="lines", name="ciśnienie [bar(a)]"))
        fig.update_layout(
            xaxis_title="czas [s]",
            yaxis_title="ciśnienie w odcinku [bar(a)]",
            height=380,
            title="Spadek ciśnienia w odcinku podczas wypływu",
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        mid = list(zip(bd.times_s[1:], bd.mass_flow_kg_per_s, strict=False))
        rate_df = pd.DataFrame(
            {
                "czas [s]": [round(t, 1) for t, _ in mid],
                "natężenie [kg/s]": [round(r, 3) for _, r in mid],
            }
        )
        st.caption(
            "Model izotermiczny (rura zakopana, T≈const). Natężenie maleje wraz "
            "ze spadkiem ciśnienia — patrz tabela poniżej."
        )
        st.dataframe(rate_df, hide_index=True, width="stretch", height=220)

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Wypływ przez otwór (kryza):** stan w gazociągu (p₁, T₁), otoczenie p₀.
Reżim wg krytycznego stosunku ciśnień `r_kryt = ((k+1)/2)^(k/(k−1))`
(k — rzeczywisty wykładnik izentropy z M1):

* **krytyczny (sonic)**, gdy p₁/p₀ ≥ r_kryt:
  `ṁ = C_d·A·p₁·√[k/(Z·R_s·T₁)·(2/(k+1))^((k+1)/(k−1))]`; w otworze
  osiągana jest prędkość dźwięku (w gardzieli T* = T₁·2/(k+1)),
* **podkrytyczny**, gdy p₁/p₀ < r_kryt: pełny wzór izentropowy z p₀.

`A = πd²/4`, `R_s = R/M`, Z — ściśliwość (GERG-2008, M1). C_d ~0,6 (kryza)
do ~1,0 (pełne pęknięcie).

**Blowdown:** odcinek o objętości V, model izotermiczny (rura zakopana):
masa `m(p) = ρ(p,T)·V`; czas z całkowania `dt = dm/ṁ(p)` po krokach
ciśnienia; utracony gaz `Δm = V·(ρ(p₁)−ρ(p₀))`, przeliczony na Nm³ przez ρₙ.

**Strefa zagrożenia (screening):** osiowy zanik stężenia w swobodnym
strumieniu turbulentnym — zasięg do LEL rzędu
`x_LEL ≈ K·d_eff·√(ρ_gaz/ρ_pow)·(100/LEL[%])`, K≈5,8. Oszacowanie rzędu
wielkości; rzeczywisty zasięg zależy od wiatru, kierunku i przeszkód —
do weryfikacji modelem dyspersji (np. gaussowskim/CFD).

**Źródła:** Perry's Chemical Engineers' Handbook (wypływ przez kryzę);
API 521 (blowdown/odciążanie); Chen–Rodi / Birch (zanik osiowy strumienia);
granice LEL/UEL — NFPA 497 / ISO 10156 (moduł M1).
            """)
