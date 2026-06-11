"""M1 — Właściwości gazów i mieszanin: strona Streamlit.

Warstwa prezentacji; wszystkie obliczenia w ``core`` (composition,
gas_properties, calorific).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.calorific import calorific_values, energy_density_at_state, quality_flags
from core.composition import GasComposition, components_registry
from core.config import load_data_file
from core.gas_properties import compute_properties
from core.units import (
    REFERENCE_CONDITIONS,
    bar_to_pa,
    celsius_to_kelvin,
)


@st.cache_data(show_spinner=False)
def _wobbe_vs_h2_curve(base_fractions: tuple[tuple[str, float], ...], ref_key: str) -> pd.DataFrame:
    """Krzywe Ws i Hs w funkcji udziału H2 (0–100% mol) dla bazowego składu."""
    base = GasComposition(fractions=base_fractions)
    ref = REFERENCE_CONDITIONS[ref_key]
    rows = []
    for h2_pct in range(0, 101, 5):
        comp = base.blend_with_hydrogen(h2_pct / 100.0)
        cal = calorific_values(comp, ref)
        rows.append(
            {
                "H2 [% mol]": h2_pct,
                "Ws [MJ/m³]": cal.wobbe_superior_mj_per_m3,
                "Hs [MJ/m³]": cal.hs_mj_per_m3,
                "Hi [MJ/m³]": cal.hi_mj_per_m3,
            }
        )
    return pd.DataFrame(rows)


def _composition_editor(default_key: str) -> GasComposition | None:
    """Edytor składu molowego; zwraca skład albo None przy błędzie walidacji."""
    registry = components_registry()
    compositions = load_data_file("gas_compositions.yaml")["compositions"]

    options = list(compositions)
    labels = {k: compositions[k]["name_pl"] for k in options}
    selected = st.selectbox(
        "Skład bazowy",
        options,
        format_func=lambda k: labels[k],
        index=options.index(default_key) if default_key in options else 0,
        help="Predefiniowane składy z data/gas_compositions.yaml — edytowalne poniżej.",
    )
    base_pct = compositions[selected]["mole_percent"]
    if note := compositions[selected].get("note"):
        st.caption(f"ℹ️ {note}")

    df = pd.DataFrame(
        {
            "Składnik": [f"{registry[k].name_pl} ({registry[k].formula})" for k in registry],
            "Udział [% mol]": [float(base_pct.get(k, 0.0)) for k in registry],
        },
        index=list(registry),
    )
    edited = st.data_editor(
        df,
        column_config={
            "Składnik": st.column_config.TextColumn(disabled=True),
            "Udział [% mol]": st.column_config.NumberColumn(
                min_value=0.0, max_value=100.0, step=0.01, format="%.4f"
            ),
        },
        hide_index=True,
        key=f"editor_{selected}",
    )
    percent = {
        key: float(edited.loc[key, "Udział [% mol]"])
        for key in registry
        if edited.loc[key, "Udział [% mol]"] > 0.0
    }
    total = sum(percent.values())
    st.caption(f"Suma udziałów: **{total:.4f}% mol**")
    try:
        return GasComposition.from_percent(percent)
    except ValueError as exc:
        st.error(str(exc))
        if abs(total - 100.0) > 1e-4 and total > 0:
            if st.button("Znormalizuj skład do 100%"):
                normalized = {k: v / total * 100.0 for k, v in percent.items()}
                return GasComposition.from_percent(normalized)
        return None


def _show_flags(flags) -> None:
    for f in flags:
        limits = []
        if f.limit_min is not None:
            limits.append(f"min {f.limit_min:g}")
        if f.limit_max is not None:
            limits.append(f"max {f.limit_max:g}")
        text = f"**{f.name_pl}**: {f.value:.2f} {f.unit} ({', '.join(limits)} {f.unit})"
        (st.success if f.ok else st.error)(("✅ " if f.ok else "❌ ") + text)
        st.caption(f"Źródło: {f.source}" + (f" · {f.note}" if f.note else ""))


def render() -> None:
    st.title("M1 · Właściwości gazów i mieszanin")
    st.caption(
        "Model: CoolProp HEOS (mieszaniny: GERG-2008/Kunz-Wagner) · "
        "wartości kaloryczne: ISO 6976 (spalanie 25 °C)"
    )

    col_in, col_out = st.columns([2, 3], gap="large")

    with col_in:
        st.subheader("Skład gazu")
        base = _composition_editor("gaz_E_typowy")

        st.subheader("Domieszka wodoru")
        h2_pct = st.slider(
            "Udział H2 w mieszaninie [% mol]",
            0.0,
            100.0,
            0.0,
            step=0.5,
            help="Mieszanie molowe składu bazowego z czystym H2.",
        )

        st.subheader("Punkt pracy")
        c1, c2 = st.columns(2)
        pressure_bar = c1.number_input(
            "Ciśnienie bezwzględne [bar(a)]", 0.01, 1000.0, 5.0, step=0.5
        )
        temperature_c = c2.number_input("Temperatura [°C]", -150.0, 300.0, 15.0, step=1.0)

        ref_key = st.selectbox(
            "Warunki odniesienia objętości",
            ["0C", "15C"],
            format_func=lambda k: REFERENCE_CONDITIONS[k].description,
            help="Podstawa m³ dla wartości kalorycznych i liczby Wobbego (Nm³ = 0 °C).",
        )

        h2_limit = st.select_slider(
            "Próg zgodności %H2 (scenariuszowy)",
            options=load_data_file("quality_limits.yaml")["hydrogen_blend_thresholds"][
                "analysis_levels_mol_pct"
            ],
            value=10,
        )

    if base is None:
        st.stop()

    composition = base.blend_with_hydrogen(h2_pct / 100.0)
    reference = REFERENCE_CONDITIONS[ref_key]

    try:
        props = compute_properties(
            composition, bar_to_pa(pressure_bar), celsius_to_kelvin(temperature_c)
        )
        cal = calorific_values(composition, reference)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    with col_out:
        st.subheader("Zgodność jakościowa")
        _show_flags(quality_flags(composition, cal, h2_limit_mol_pct=float(h2_limit)))

        for w in props.warnings:
            st.warning(w)

        st.subheader("Wartości kaloryczne i Wobbe " f"({reference.name})")
        r1 = st.columns(4)
        r1[0].metric("Ciepło spalania Hs", f"{cal.hs_mj_per_m3:.3f} MJ/m³")
        r1[1].metric("Wartość opałowa Hi", f"{cal.hi_mj_per_m3:.3f} MJ/m³")
        r1[2].metric("Wobbe górna Ws", f"{cal.wobbe_superior_mj_per_m3:.3f} MJ/m³")
        r1[3].metric("Wobbe dolna Wi", f"{cal.wobbe_inferior_mj_per_m3:.3f} MJ/m³")
        r2 = st.columns(4)
        r2[0].metric("Hs", f"{cal.hs_kwh_per_m3:.4f} kWh/m³")
        r2[1].metric("Hi", f"{cal.hi_kwh_per_m3:.4f} kWh/m³")
        r2[2].metric("Hi (masowo)", f"{cal.hi_mj_per_kg:.2f} MJ/kg")
        r2[3].metric("Hi (masowo)", f"{cal.hi_kwh_per_kg:.3f} kWh/kg")

        st.subheader(f"Właściwości przy p = {pressure_bar:g} bar(a), T = {temperature_c:g} °C")
        r3 = st.columns(4)
        r3[0].metric("Z", f"{props.z_factor:.5f}")
        r3[1].metric("Gęstość ρ", f"{props.density_kg_per_m3:.3f} kg/m³")
        r3[2].metric("cp", f"{props.cp_j_per_kg_k / 1e3:.3f} kJ/(kg·K)")
        r3[3].metric("cv", f"{props.cv_j_per_kg_k / 1e3:.3f} kJ/(kg·K)")
        r4 = st.columns(4)
        r4[0].metric("γ = cp/cv", f"{props.cp_over_cv:.4f}")
        r4[1].metric("Wykładnik izentropy κ", f"{props.isentropic_exponent:.4f}")
        r4[2].metric("μ J-T", f"{props.joule_thomson_k_per_bar:.4f} K/bar")
        r4[3].metric("Prędkość dźwięku", f"{props.speed_of_sound_m_per_s:.1f} m/s")
        r5 = st.columns(4)
        r5[0].metric("Masa molowa", f"{props.molar_mass_kg_per_kmol:.3f} kg/kmol")
        r5[1].metric("Gęstość względna d", f"{cal.relative_density:.4f}")
        r5[2].metric(f"ρ ({reference.name})", f"{cal.density_ref_kg_per_m3:.4f} kg/m³")
        if props.viscosity_pa_s is not None:
            r5[3].metric(
                "Lepkość μ",
                f"{props.viscosity_pa_s * 1e6:.2f} µPa·s",
                help=f"Metoda: {props.viscosity_method}",
            )

        energy = energy_density_at_state(cal, props)
        st.subheader("Gęstość energii")
        r6 = st.columns(3)
        r6[0].metric("Hi przy (p,T)", f"{energy['hi_mj_per_m3_at_state']:.2f} MJ/m³")
        r6[1].metric("Hs przy (p,T)", f"{energy['hs_mj_per_m3_at_state']:.2f} MJ/m³")
        r6[2].metric("Hi (masowo)", f"{cal.hi_kwh_per_kg:.3f} kWh/kg")

    st.divider()
    st.subheader("Wpływ domieszki H2 na parametry jakościowe")
    curve = _wobbe_vs_h2_curve(base.fractions, ref_key)
    limits = load_data_file("quality_limits.yaml")["wobbe_index_group_E"]
    fig = go.Figure()
    fig.add_hrect(
        y0=limits["min_mj_per_m3"],
        y1=limits["max_mj_per_m3"],
        fillcolor="green",
        opacity=0.08,
        annotation_text="widełki Wobbego gr. E",
        annotation_position="top left",
    )
    fig.add_trace(
        go.Scatter(
            x=curve["H2 [% mol]"], y=curve["Ws [MJ/m³]"], name="Ws (Wobbe górna)", mode="lines"
        )
    )
    fig.add_trace(go.Scatter(x=curve["H2 [% mol]"], y=curve["Hs [MJ/m³]"], name="Hs", mode="lines"))
    fig.add_trace(go.Scatter(x=curve["H2 [% mol]"], y=curve["Hi [MJ/m³]"], name="Hi", mode="lines"))
    fig.add_vline(x=h2_pct, line_dash="dot", annotation_text=f"{h2_pct:g}% H2")
    fig.update_layout(
        xaxis_title="Udział H2 [% mol]",
        yaxis_title=f"MJ/m³ ({reference.name})",
        legend=dict(orientation="h"),
        height=450,
    )
    st.plotly_chart(fig, config={"displaylogo": False})

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Właściwości termofizyczne** — CoolProp (backend HEOS): wielopłynowe równania
stanu wysokiej dokładności; mieszaniny wg modelu **GERG-2008** (Kunz O., Wagner W.,
*J. Chem. Eng. Data* 57 (2012) 3032–3091). Zakres formalny GERG-2008: 90–450 K,
do 35 MPa; domyślny zakres walidacji narzędzia: **p ≤ 10 MPa, T = −20…60 °C**
(poza nim wynik z ostrzeżeniem).

**Wartości kaloryczne** — ISO 6976:2016: molowe ciepło spalania gazu doskonałego
przy 25 °C (tab. 3 normy): `Hs = Σ xⱼ·Hsⱼ`; wartość opałowa
`Hi = Hs − n(H2O)·44,016 kJ/mol`. Przeliczenie na objętość:
`Hs,V = Hs / (Z·R·Tref/pref)`.

**Odstępstwo od ISO 6976:** współczynnik ściśliwości Z w warunkach odniesienia
liczony z równania stanu (GERG-2008) zamiast współczynników sumacyjnych normy —
różnica < 0,1% (testy walidacyjne), metoda dokładniejsza dla mieszanin z H2.

**Gęstość względna:** `d = (M/M_air)·(Z_air/Z)`, `M_air = 28,9626 kg/kmol`
(ISO 6976), Z_air z CoolProp (walidacja: 0,99941 przy 0 °C — zgodne z normą).

**Liczba Wobbego:** `Ws = Hs,V / √d` (analogicznie Wi).

**Wykładnik izentropy (rzeczywisty):** `κ = w²·ρ/p` (w — prędkość dźwięku);
dla gazu doskonałego κ = cp/cv.

**Lepkość:** korelacje referencyjne CoolProp (mieszaniny: model ECS);
w razie niedostępności — reguła Wilke'a (1950), przybliżenie niskociśnieniowe
(oznaczane przy wyniku).

**Walidacja:** testy automatyczne porównują wyniki z wartościami referencyjnymi
(ISO 6976, NIST WebBook, entalpie tworzenia ATcT/CODATA, literatura) —
tolerancje: Z, ρ, cp ≤ 0,5%; wartości kaloryczne ≤ 0,1%. Szczegóły:
`tests/reference_data.py`.
            """)
