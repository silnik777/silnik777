"""M2 — Energia sprężania: strona Streamlit (porównanie GZ/H2/mieszanin)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.composition import GasComposition
from core.compression import (
    applicable_technologies,
    compress,
    compressor_technologies,
    isothermal_work_j_per_kg,
    optimal_stage_count,
)
from core.config import load_data_file
from core.units import bar_to_pa, celsius_to_kelvin, j_to_kwh


def _gas_selector(key: str) -> tuple[GasComposition, str]:
    """Wybór gazu: skład predefiniowany + opcjonalna domieszka H2."""
    compositions = load_data_file("gas_compositions.yaml")["compositions"]
    options = list(compositions)
    selected = st.selectbox(
        "Gaz",
        options,
        format_func=lambda k: compositions[k]["name_pl"],
        key=f"{key}_gas",
    )
    base = GasComposition.predefined(selected)
    h2_pct = 0.0
    if selected != "wodor_99999":
        h2_pct = st.slider("Domieszka H2 [% mol]", 0.0, 100.0, 0.0, 5.0, key=f"{key}_h2")
    comp = base.blend_with_hydrogen(h2_pct / 100.0)
    label = compositions[selected]["name_pl"]
    if h2_pct > 0:
        label += f" + {h2_pct:g}% H2"
    return comp, label


@st.cache_data(show_spinner=False)
def _comparison_table(
    base_fractions: tuple[tuple[str, float], ...],
    p_in_pa: float,
    t_in_k: float,
    p_out_pa: float,
    eta: float,
    model: str,
    n_stages: int,
) -> pd.DataFrame:
    """Energia sprężania dla GZ bazowego, mieszanin 10/20% H2 i czystego H2."""
    base = GasComposition(fractions=base_fractions)
    rows = []
    for label, comp in [
        ("gaz bazowy", base),
        ("+10% H2", base.blend_with_hydrogen(0.10)),
        ("+20% H2", base.blend_with_hydrogen(0.20)),
        ("100% H2", GasComposition.pure("H2")),
    ]:
        res = compress(comp, p_in_pa, t_in_k, p_out_pa, eta, n_stages, model)
        rows.append(
            {
                "Gaz": label,
                "kWh/kg": res.work_kwh_per_kg,
                "kWh/Nm³": res.work_kwh_per_nm3(),
                "T tłoczenia [°C]": res.outlet_temperature_k - 273.15,
            }
        )
    return pd.DataFrame(rows)


def render() -> None:
    st.title("M2 · Energia sprężania")
    st.caption(
        "Gaz rzeczywisty (GERG-2008) · stopnie izentropowe/politropowe · "
        "chłodzenie międzystopniowe · biblioteka technologii: data/compressors.yaml"
    )

    col_in, col_out = st.columns([2, 3], gap="large")

    with col_in:
        st.subheader("Gaz i punkt pracy")
        composition, gas_label = _gas_selector("m02")

        c1, c2 = st.columns(2)
        p_in_bar = c1.number_input("Ciśnienie ssania [bar(a)]", 0.1, 700.0, 2.0, 0.5)
        t_in_c = c2.number_input("Temperatura ssania [°C]", -40.0, 80.0, 15.0, 1.0)
        c3, c4 = st.columns(2)
        p_out_bar = c3.number_input("Ciśnienie tłoczenia [bar(a)]", 0.2, 1000.0, 60.0, 1.0)
        flow_nm3_h = c4.number_input("Strumień [Nm³/h]", 1.0, 2_000_000.0, 5000.0, 100.0)

        st.subheader("Technologia sprężarki")
        techs = compressor_technologies()
        tech_key = st.selectbox("Typ", list(techs), format_func=lambda k: techs[k].name_pl)
        tech = techs[tech_key]
        st.caption(
            f"Sprawność ({tech.efficiency_model}): zakres "
            f"**{tech.eta_min:.2f}–{tech.eta_max:.2f}**, typowa {tech.eta_typical:.2f} · "
            f"TRL {tech.trl} · spręż/stopień ≤ {tech.max_pressure_ratio_per_stage:g} · "
            f"źródło: {tech.source}"
        )
        eta = st.slider(
            "Sprawność η",
            tech.eta_min,
            tech.eta_max,
            tech.eta_typical,
            0.01,
            help="Zakres min–max z biblioteki technologii; domyślnie wartość typowa.",
        )
        model = "politropowy" if tech.efficiency_model == "politropowa" else "izentropowy"

        stages_mode = st.radio("Liczba stopni", ["auto (optymalna)", "ręcznie"], horizontal=True)
        n_stages_manual = 1
        if stages_mode == "ręcznie":
            n_stages_manual = int(st.number_input("Stopnie", 1, 10, 2))

    if p_out_bar <= p_in_bar:
        st.error("Ciśnienie tłoczenia musi być wyższe od ssania.")
        st.stop()

    p_in, p_out = bar_to_pa(p_in_bar), bar_to_pa(p_out_bar)
    t_in = celsius_to_kelvin(t_in_c)

    if composition.h2_mole_percent > 50.0 and not tech.h2_ready:
        st.warning(f"⚠️ {tech.name_pl}: {tech.h2_note}")
    if not applicable_technologies(flow_nm3_h, p_out / 1e6)[tech_key]:
        lo, hi = tech.flow_range_nm3_per_h
        st.warning(
            f"⚠️ Punkt pracy poza typową mapą stosowalności technologii "
            f"{tech.name_pl} (przepływ {lo:g}–{hi:g} Nm³/h, "
            f"p_tł ≤ {tech.max_discharge_pressure_mpa:g} MPa)."
        )

    try:
        recommended, sweep = optimal_stage_count(composition, p_in, t_in, p_out, eta, model)
        n_stages = recommended if stages_mode == "auto (optymalna)" else n_stages_manual
        result = compress(composition, p_in, t_in, p_out, eta, n_stages, model)
        w_iso = isothermal_work_j_per_kg(composition, p_in, t_in, p_out)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()
        return

    from core.gas_properties import compute_properties

    rho_n = compute_properties(composition, 101_325.0, 273.15).density_kg_per_m3
    mass_flow = flow_nm3_h * rho_n / 3600.0  # kg/s

    with col_out:
        st.subheader(f"Wyniki — {gas_label}, {n_stages} stopni")
        r1 = st.columns(4)
        r1[0].metric("Energia właściwa", f"{result.work_kwh_per_kg:.4f} kWh/kg")
        r1[1].metric("Energia właściwa", f"{result.work_kwh_per_nm3():.4f} kWh/Nm³")
        r1[2].metric("Moc wewnętrzna", f"{result.power_w(mass_flow) / 1e3:.1f} kW")
        r1[3].metric("T tłoczenia (ost. stopień)", f"{result.outlet_temperature_k - 273.15:.1f} °C")
        r2 = st.columns(4)
        r2[0].metric(
            "Chłodzenie międzystopniowe", f"{result.cooling_duty_w(mass_flow) / 1e3:.1f} kW"
        )
        aftercool = result.aftercooler_heat_j_per_kg(t_in) * mass_flow
        r2[1].metric("Chłodnica końcowa (do T ssania)", f"{aftercool / 1e3:.1f} kW")
        r2[2].metric("Minimum izotermiczne", f"{j_to_kwh(w_iso):.4f} kWh/kg")
        r2[3].metric(
            "Nadwyżka nad izotermą",
            f"{(result.work_j_per_kg / w_iso - 1) * 100:.1f}%",
            help="Potencjał poprawy przez chłodzenie (więcej stopni, ciecz jonowa itd.)",
        )
        st.caption(
            "Ciepło odpadowe dostępne na poziomie temperatur tłoczenia stopni "
            "(tabela poniżej) — potencjał odzysku w M13/M10."
        )

        st.subheader("Stopnie sprężania")
        st.dataframe(
            pd.DataFrame(
                {
                    "Stopień": range(1, len(result.stages) + 1),
                    "p ssania [bar]": [s.pressure_in_pa / 1e5 for s in result.stages],
                    "p tłoczenia [bar]": [s.pressure_out_pa / 1e5 for s in result.stages],
                    "T tłoczenia [°C]": [s.temperature_out_k - 273.15 for s in result.stages],
                    "Praca [kJ/kg]": [s.work_j_per_kg / 1e3 for s in result.stages],
                    "Chłodnica [kJ/kg]": [s.intercooler_heat_j_per_kg / 1e3 for s in result.stages],
                }
            ).round(2),
            hide_index=True,
            width="stretch",
        )

    st.divider()
    c_left, c_right = st.columns(2, gap="large")

    with c_left:
        st.subheader("Praca vs liczba stopni")
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=[p.n_stages for p in sweep],
                y=[j_to_kwh(p.work_j_per_kg) for p in sweep],
                marker_color=["#2ca02c" if p.t_limit_ok else "#d62728" for p in sweep],
                text=[f"{p.max_stage_outlet_c:.0f}°C" for p in sweep],
            )
        )
        fig.add_hline(y=j_to_kwh(w_iso), line_dash="dot", annotation_text="minimum izotermiczne")
        fig.update_layout(
            xaxis_title="Liczba stopni",
            yaxis_title="Energia właściwa [kWh/kg]",
            height=400,
            showlegend=False,
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        st.caption(
            f"Rekomendacja: **{recommended} stopni** (zielone — limit T tłoczenia "
            "spełniony; etykiety — najwyższa T stopnia)."
        )

    with c_right:
        st.subheader("Porównanie GZ / mieszaniny / H2")
        df = _comparison_table(
            (
                GasComposition.predefined("gaz_E_typowy").fractions
                if composition.h2_mole_percent == 100.0
                else composition.fractions
            ),
            p_in,
            t_in,
            p_out,
            eta,
            model,
            n_stages,
        )
        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=df["Gaz"], y=df["kWh/kg"], name="kWh/kg"))
        fig2.add_trace(
            go.Bar(x=df["Gaz"], y=df["kWh/Nm³"], name="kWh/Nm³", yaxis="y2", opacity=0.6)
        )
        fig2.update_layout(
            yaxis=dict(title="kWh/kg"),
            yaxis2=dict(title="kWh/Nm³", overlaying="y", side="right"),
            barmode="group",
            height=400,
            legend=dict(orientation="h"),
        )
        st.plotly_chart(fig2, config={"displaylogo": False})
        st.dataframe(df.round(4), hide_index=True, width="stretch")

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Praca izotermiczna** (minimum teoretyczne): `w_T = (h₂−h₁) − T·(s₂−s₁)`
(zmiana funkcji Gibbsa przy T = const, gaz rzeczywisty GERG-2008).

**Stopień izentropowy:** `w_s = h(p₂,s₁) − h₁`, praca rzeczywista `w = w_s/η_s`,
stan wylotowy z flashu (h₁+w, p₂). **Politropowy:** całka po drodze sprężania
jako 25 małych stopni izentropowych z η_p (Schultz, *J. Eng. Power* 1962).

**Wielostopniowe:** równy spręż na stopień `r = (p₂/p₁)^(1/n)`, chłodzenie
międzystopniowe do temperatury ssania, **bez strat ciśnienia w chłodnicach**
(uproszczenie; typowo Δp 1–2%). Rekomendowana liczba stopni: limit temperatury
tłoczenia (150 °C, konfigurowalne) + zysk krańcowy kolejnego stopnia ≥ 5%.

**Sprawności technologii** — wartości orientacyjne (min/typ/max) z syntezy
literatury: GPSA, IEA *The Future of Hydrogen* (2019), DNV (2022),
Sdanghi i in. (2019). Edycja: `data/compressors.yaml`.

**Moc wewnętrzna** — bez sprawności mechanicznej/elektrycznej napędu
(silnik, przekładnia: typowo dodatkowe 3–8%; zostaną ujęte w M10).
            """)
