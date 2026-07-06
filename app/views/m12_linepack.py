"""M12 — Linepack: pojemność energetyczna odcinka gazociągu."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.composition import GasComposition
from core.config import load_data_file
from core.linepack import linepack
from core.units import bar_to_pa, celsius_to_kelvin


def render() -> None:
    st.title("M12 · Linepack")
    st.caption(
        "Pojemność energetyczna odcinka dla widełek ciśnień i składu · "
        "round-trip ze sprężaniem (M2) · gęstości GERG-2008 (M1)"
    )

    col_in, col_out = st.columns([2, 3], gap="large")
    with col_in:
        st.subheader("Gaz i odcinek")
        compositions = load_data_file("gas_compositions.yaml")["compositions"]
        gas_key = st.selectbox(
            "Skład", list(compositions), format_func=lambda k: compositions[k]["name_pl"]
        )
        base = GasComposition.predefined(gas_key)
        h2_pct = 0.0
        if base.is_combustible and gas_key != "wodor_99999":
            h2_pct = st.slider("Domieszka H2 [% mol]", 0.0, 100.0, 0.0, 5.0)
        composition = base.blend_with_hydrogen(h2_pct / 100.0) if h2_pct else base
        if not composition.is_combustible:
            st.info(
                "ℹ️ Gaz niepalny — tryb **CAES** (magazynowanie energii w sprężonym "
                "powietrzu): zamiast energii chemicznej liczymy energię elektryczną "
                "odzyskaną przy rozprężaniu bufora."
            )

        c1, c2 = st.columns(2)
        diameter_mm = c1.number_input("Średnica wewn. [mm]", 50.0, 1500.0, 500.0, 10.0)
        length_km = c2.number_input("Długość [km]", 0.5, 500.0, 50.0, 1.0)
        c3, c4, c5 = st.columns(3)
        p_min_bar = c3.number_input("p min [bar(a)]", 1.5, 100.0, 45.0, 1.0)
        p_max_bar = c4.number_input("p max [bar(a)]", 2.0, 100.0, 55.0, 1.0)
        t_c = c5.number_input("T gazu [°C]", -10.0, 40.0, 10.0, 1.0)
        load_mw = st.number_input("Pobór do analizy dynamiki [MW]", 1.0, 5000.0, 50.0, 5.0)

    if p_max_bar <= p_min_bar:
        st.error("p max musi być większe od p min.")
        st.stop()

    try:
        res = linepack(
            composition,
            diameter_mm / 1e3,
            length_km * 1e3,
            bar_to_pa(p_min_bar),
            bar_to_pa(p_max_bar),
            celsius_to_kelvin(t_c),
        )
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    with col_out:
        if res.is_combustible:
            st.subheader("Pojemność (energia chemiczna)")
            r1 = st.columns(4)
            r1[0].metric("Objętość geometryczna", f"{res.geometric_volume_m3:,.0f} m³")
            r1[1].metric("Bufor (p_max−p_min)", f"{res.buffer_energy_mwh:,.1f} MWh")
            r1[2].metric("Zawartość przy p_max", f"{res.energy_total_at_pmax_mwh:,.0f} MWh")
            r1[3].metric("Masa bufora", f"{res.buffer_mass_kg / 1e3:,.1f} t")
            r2 = st.columns(3)
            r2[0].metric(
                f"Czas pokrycia {load_mw:g} MW",
                f"{res.buffer_hours_at_load(load_mw):,.1f} h",
            )
            r2[1].metric("Energia napełnienia", f"{res.compression_kwh_el:,.0f} kWh el.")
            r2[2].metric(
                "Koszt energetyczny cyklu",
                f"{res.compression_kwh_el_per_mwh:.2f} kWh el./MWh",
                help="Energia sprężania p_min→p_max na MWh energii chemicznej bufora.",
            )
        else:
            st.subheader("Magazyn CAES (energia elektryczna)")
            r1 = st.columns(4)
            r1[0].metric("Objętość geometryczna", f"{res.geometric_volume_m3:,.0f} m³")
            r1[1].metric("Masa bufora powietrza", f"{res.buffer_mass_kg / 1e3:,.1f} t")
            r1[2].metric("Energia napełnienia", f"{res.compression_kwh_el / 1e3:,.1f} MWh el.")
            r1[3].metric("Energia odzyskana", f"{res.caes_recovered_mwh:,.1f} MWh el.")
            r2 = st.columns(3)
            r2[0].metric(
                "Sprawność round-trip",
                f"{res.caes_round_trip_efficiency * 100:.0f}%",
                help="Odzysk (rozprężanie, M4) / napełnienie (sprężanie, M2). "
                "Model diabatyczny (ciepło sprężania oddane do gruntu).",
            )
            r2[1].metric(
                f"Czas pokrycia {load_mw:g} MW",
                f"{res.buffer_hours_at_load(load_mw):,.2f} h",
            )
            st.caption(
                "Model diabatyczny: gaz w rurze stygnie do temperatury gruntu, "
                "więc round-trip jest niższy niż CAES adiabatycznego z magazynem "
                "ciepła. Wynik orientacyjny — do weryfikacji projektowej."
            )

        if not res.is_combustible:
            return

        st.subheader("Porównanie: GZ bazowy / mieszaniny / H2")
        rows = []
        cmp_base = GasComposition.predefined("gaz_E_typowy") if gas_key == "wodor_99999" else base
        for label, comp in [
            ("gaz bazowy", cmp_base),
            ("+20% H2", cmp_base.blend_with_hydrogen(0.20)),
            ("100% H2", GasComposition.pure("H2")),
        ]:
            r = linepack(
                comp,
                diameter_mm / 1e3,
                length_km * 1e3,
                bar_to_pa(p_min_bar),
                bar_to_pa(p_max_bar),
                celsius_to_kelvin(t_c),
            )
            rows.append(
                {
                    "Gaz": label,
                    "Bufor [MWh]": r.buffer_energy_mwh,
                    "Czas pokrycia [h]": r.buffer_hours_at_load(load_mw),
                    "kWh el./MWh": r.compression_kwh_el_per_mwh,
                }
            )
        df = pd.DataFrame(rows)
        fig = go.Figure(go.Bar(x=df["Gaz"], y=df["Bufor [MWh]"], name="bufor [MWh]"))
        fig.add_trace(
            go.Scatter(
                x=df["Gaz"],
                y=df["kWh el./MWh"],
                name="kWh el./MWh",
                yaxis="y2",
                mode="markers+lines",
            )
        )
        fig.update_layout(
            yaxis=dict(title="bufor [MWh]"),
            yaxis2=dict(title="kWh el./MWh", overlaying="y", side="right"),
            height=380,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        st.dataframe(df.round(2), hide_index=True, width="stretch")

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Masa w odcinku:** `m(p) = ρ(p,T)·V` — gęstość rzeczywista GERG-2008;
relacja ścisła `ρ = p·M/(Z·R·T)` (test < 0,5%). Zmienność Z(p) podnosi
bufor o ~10–12% względem przybliżenia stałym Z̄.

**Bufor roboczy:** `Δm·Hi` między poziomami ciśnień średnich p_min/p_max
(uproszczenie: pomijamy profil ciśnienia wzdłuż odcinka — dla oszacowań
plus/minus kilka procent). **Dynamika:** czas = energia bufora / pobór.

**Round-trip (M2):** praca cyklu **całkowana po stanie bufora** w 8 krokach
ciśnienia — kolejne porcje Δmᵢ sprężane od p_min do bieżącego (rosnącego)
ciśnienia bufora, a przy opróżnianiu rozprężane od bieżącego (malejącego)
ciśnienia do p_min. Pojedynczy skok p_min→p_max dla całej masy zawyżałby
oba strumienie o ~10–20% (przeciwciśnienie/odzysk zmieniają się w trakcie).
Sprężanie politropowe (η 0,82, napęd 0,95), rozprężanie CAES (η 0,80). Dla
H2 bufor objętościowo ~3× mniejszy, a koszt sprężania na MWh kilkukrotnie
wyższy — oba efekty widoczne w porównaniu.
            """)
