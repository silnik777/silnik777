"""M1 — Właściwości gazów i mieszanin: strona Streamlit.

Warstwa prezentacji; wszystkie obliczenia w ``core`` (composition,
gas_properties, calorific).
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.blending import (
    biomethane_compositions,
    hydrogen_grade_composition,
    hydrogen_grades,
    max_hydrogen_for_group_e,
    propane_enrichment_for_group_e,
)
from core.calorific import calorific_values, energy_density_at_state, quality_flags
from core.composition import GasComposition, components_registry
from core.config import load_data_file
from core.gas_properties import compute_properties
from core.methane_number import methane_number_assessment
from core.units import (
    REFERENCE_CONDITIONS,
    bar_to_pa,
    celsius_to_kelvin,
)


@st.cache_data(show_spinner=False)
def _wobbe_vs_h2_curve(base_fractions: tuple[tuple[str, float], ...], ref_key: str) -> pd.DataFrame:
    """Krzywe Ws i Hs w funkcji udziału H2 (0–100% mol) dla bazowego składu."""
    from core.methane_number import methane_number

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
                "MN": methane_number(comp) if comp.is_combustible else None,
            }
        )
    return pd.DataFrame(rows)


def _composition_editor(
    default_key: str,
    compositions: dict | None = None,
    label: str = "Skład bazowy",
    key_prefix: str = "editor",
    help_text: str = "Predefiniowane składy z data/gas_compositions.yaml — edytowalne poniżej.",
) -> GasComposition | None:
    """Edytor składu molowego; zwraca skład albo None przy błędzie walidacji.

    Uogólniony: ``compositions`` pozwala podać dowolną bibliotekę składów
    (np. biometanu), a ``key_prefix`` odróżnia instancje edytora na stronie.
    """
    registry = components_registry()
    if compositions is None:
        compositions = load_data_file("gas_compositions.yaml")["compositions"]

    options = list(compositions)
    labels = {k: compositions[k]["name_pl"] for k in options}
    selected = st.selectbox(
        label,
        options,
        format_func=lambda k: labels[k],
        index=options.index(default_key) if default_key in options else 0,
        help=help_text,
        key=f"{key_prefix}_sel",
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
                min_value=0.0, max_value=100.0, step=0.0001, format="%.4f"
            ),
        },
        hide_index=True,
        key=f"{key_prefix}_{selected}",
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
            if st.button("Znormalizuj skład do 100%", key=f"{key_prefix}_norm"):
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


def _verdict_banner(composition, flags, mn, cal) -> None:
    """Górny werdykt: jednoznaczny status zgodności + 4 kluczowe wskaźniki.

    Zamiast 24 kafelków naraz — najpierw ODPOWIEDŹ (czy gaz spełnia wymogi
    grupy E), potem szczegóły w zakładkach niżej.
    """
    if not composition.is_combustible:
        st.info(
            "ℹ️ Gaz niepalny (np. powietrze) — ocena jakościowa gazu wysokometanowego "
            "grupy E nie dotyczy. Właściwości termodynamiczne w zakładce poniżej."
        )
        return

    failed = [f.name_pl for f in flags if not f.ok]
    if mn is not None and not mn.ok:
        failed.append("liczba metanowa")

    if not failed:
        st.success(
            "### ✅ Gaz spełnia wymogi gazu wysokometanowego (grupa E)\n"
            "Wszystkie kryteria jakościowe w normie (Wobbe, próg %H₂, liczba metanowa)."
        )
    else:
        st.error(
            "### ❌ Gaz NIE spełnia wszystkich wymogów grupy E\n"
            "Poza normą: **" + ", ".join(failed) + "** — szczegóły w zakładce „Jakość i "
            "kaloryczność”."
        )

    wobbe_flag = next((f for f in flags if "Wobbe" in f.name_pl), None)
    k = st.columns(4)
    if wobbe_flag is not None:
        k[0].metric(
            "Wobbe (Ws)",
            f"{wobbe_flag.value:.1f} {wobbe_flag.unit}",
            delta="w normie" if wobbe_flag.ok else "poza normą",
            delta_color="normal" if wobbe_flag.ok else "inverse",
            help=f"Widełki grupy E: {wobbe_flag.limit_min:g}–{wobbe_flag.limit_max:g} "
            f"{wobbe_flag.unit}.",
        )
    h2_pct = composition.h2_mole_percent
    k[1].metric(
        "Udział H₂",
        f"{h2_pct:.1f} % mol",
        help="Sam wskaźnik Wobbego nie wykrywa H₂ (Ws czystego H₂ ≈ 48 MJ/m³ mieści "
        "się w widełkach E) — dlatego kontrolujemy udział %H₂ osobno.",
    )
    if mn is not None:
        k[2].metric(
            "Liczba metanowa",
            f"{mn.value:.0f}",
            delta="OK" if mn.ok else f"< {mn.min_limit:g}",
            delta_color="normal" if mn.ok else "inverse",
            help="Odporność na spalanie stukowe w silnikach gazowych; spada z H₂.",
        )
    k[3].metric("Wartość opałowa Hi", f"{cal.hi_mj_per_m3:.2f} MJ/m³")


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
        grades = hydrogen_grades()
        h2_grade_key = st.selectbox(
            "Klasa czystości H₂",
            list(grades),
            format_func=lambda k: grades[k]["name_pl"],
            help="Strumień wodoru z data/hydrogen_grades.yaml (zanieczyszczenia "
            "śladowe mają pomijalny wpływ — klasa dla realizmu i dokumentacji źródła).",
        )
        h2_pct = st.slider(
            "Udział H₂ w mieszaninie [% mol]",
            0.0,
            100.0,
            0.0,
            step=0.5,
            help="Mieszanie molowe składu bazowego ze strumieniem H₂ wybranej klasy.",
        )

        st.subheader("Domieszka biometanu")
        bm_pct = st.slider(
            "Udział biometanu [% mol]",
            0.0,
            100.0,
            0.0,
            step=0.5,
            help="Drugi strumień domieszki: biometan sieciowy lub własny skład.",
        )
        bm_stream = None
        if bm_pct > 0.0:
            bm_source = st.radio(
                "Skład biometanu",
                ["z biblioteki", "własny"],
                horizontal=True,
            )
            bm_lib = biomethane_compositions()
            if bm_source == "z biblioteki":
                bm_key = st.selectbox(
                    "Typowy skład biometanu",
                    list(bm_lib),
                    format_func=lambda k: bm_lib[k]["name_pl"],
                )
                if note := bm_lib[bm_key].get("note"):
                    st.caption(f"ℹ️ {note}")
                bm_stream = GasComposition.from_percent(bm_lib[bm_key]["mole_percent"])
            else:
                bm_stream = _composition_editor(
                    "biometan_sieciowy",
                    compositions=bm_lib,
                    label="Skład biometanu (edytowalny)",
                    key_prefix="bm_editor",
                    help_text="Typowe składy biometanu — edytowalne poniżej.",
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
    if h2_pct + bm_pct > 100.0 + 1e-6:
        st.error("Suma domieszek (H₂ + biometan) nie może przekraczać 100% mol.")
        st.stop()
    if bm_pct > 0.0 and bm_stream is None:
        st.stop()  # błąd składu biometanu już zgłoszony w edytorze

    h2_stream = hydrogen_grade_composition(h2_grade_key)
    streams = [(base, (100.0 - h2_pct - bm_pct) / 100.0), (h2_stream, h2_pct / 100.0)]
    if bm_pct > 0.0:
        streams.append((bm_stream, bm_pct / 100.0))
    composition = GasComposition.from_mixture(streams)
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

    flags = quality_flags(composition, cal, h2_limit_mol_pct=float(h2_limit))
    mn = methane_number_assessment(composition) if composition.is_combustible else None

    hlim = None
    enrichment = None
    if composition.is_combustible:
        hlim = max_hydrogen_for_group_e(base, h2_stream, h2_policy_mole_pct=float(h2_limit))
        enrichment = propane_enrichment_for_group_e(composition)

    with col_out:
        _verdict_banner(composition, flags, mn, cal)
        for w in props.warnings:
            st.warning(w)

        if hlim is not None:
            st.markdown("##### Granica domieszki H₂ i korekta")
            st.metric(
                "Maks. udział H₂ dla grupy E (gaz bazowy)",
                f"{hlim.max_h2_mole_pct:.1f} % mol",
                help=f"Ograniczenie wiążące: **{hlim.binding}**. Liczba metanowa "
                f"ogranicza przy {hlim.mn_limited_pct:.0f}%, liczba Wobbego przy "
                f"{hlim.wobbe_limited_pct:.0f}% (Ws czystego H₂ ≈ 48 MJ/m³ mieści się "
                f"w paśmie E — dlatego zwykle wiąże MN lub próg %H₂).",
            )
            if h2_pct > hlim.max_h2_mole_pct + 1e-6:
                st.warning(
                    f"⚠️ Bieżąca domieszka H₂ = {h2_pct:g}% przekracza maksimum "
                    f"{hlim.max_h2_mole_pct:.1f}% mol dla grupy E (wiąże: {hlim.binding})."
                )

        if enrichment is not None and enrichment.needed:
            if enrichment.feasible:
                writer = st.success if enrichment.mn_ok_after else st.warning
                writer(
                    f"🧪 **Propanowanie:** dodaj **{enrichment.propane_mole_pct:.2f}% mol "
                    f"propanu (C₃H₈)** → liczba Wobbego "
                    f"{enrichment.wobbe_before_mj_per_m3:.1f} → "
                    f"{enrichment.wobbe_after_mj_per_m3:.1f} MJ/m³ (dolna granica pasma E). "
                    f"Liczba metanowa {enrichment.mn_before:.0f} → {enrichment.mn_after:.0f}."
                )
                st.caption(enrichment.note)
            else:
                st.error("🧪 Propanowanie: " + enrichment.note)

    st.divider()
    tab_q, tab_props, tab_h2 = st.tabs(
        [
            "✅ Jakość i kaloryczność",
            "🔬 Właściwości termodynamiczne (p, T)",
            "🔀 Wpływ domieszki H₂",
        ]
    )

    with tab_q:
        st.markdown("##### Zgodność jakościowa (norma grupy E)")
        _show_flags(flags)
        if mn is not None:
            ok_txt = "✅ " if mn.ok else "❌ "
            (st.success if mn.ok else st.error)(
                ok_txt + f"**Liczba metanowa (MN)**: {mn.value:.1f} "
                f"(limit silnikowy ≥ {mn.min_limit:g})"
            )
            st.caption(f"Źródło: {mn.source} · {mn.note}")

        st.markdown(f"##### Wartości kaloryczne i Wobbe ({reference.name})")
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
        st.caption(
            f"Podstawa objętości: {reference.description}; spalanie 25 °C (ISO 6976). "
            "Wartości certyfikacyjne wg akredytowanej analizy."
        )

    with tab_props:
        st.markdown(f"##### Stan: p = {pressure_bar:g} bar(a), T = {temperature_c:g} °C")
        r3 = st.columns(4)
        r3[0].metric("Ściśliwość Z", f"{props.z_factor:.5f}")
        r3[1].metric("Gęstość ρ", f"{props.density_kg_per_m3:.3f} kg/m³")
        r3[2].metric("cp", f"{props.cp_j_per_kg_k / 1e3:.3f} kJ/(kg·K)")
        r3[3].metric("cv", f"{props.cv_j_per_kg_k / 1e3:.3f} kJ/(kg·K)")
        r4 = st.columns(4)
        r4[0].metric("γ = cp/cv", f"{props.cp_over_cv:.4f}")
        r4[1].metric("Wykładnik izentropy κ", f"{props.isentropic_exponent:.4f}")
        r4[2].metric("Współczynnik J-T", f"{props.joule_thomson_k_per_bar:.4f} K/bar")
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
        st.markdown("##### Gęstość energii przy stanie roboczym")
        r6 = st.columns(3)
        r6[0].metric("Hi przy (p,T)", f"{energy['hi_mj_per_m3_at_state']:.2f} MJ/m³")
        r6[1].metric("Hs przy (p,T)", f"{energy['hs_mj_per_m3_at_state']:.2f} MJ/m³")
        r6[2].metric("Hi (masowo)", f"{cal.hi_kwh_per_kg:.3f} kWh/kg")

    with tab_h2:
        st.markdown("##### Ws, Hs, Hi w funkcji udziału H₂ (0–100 % mol)")
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
        fig.add_trace(
            go.Scatter(x=curve["H2 [% mol]"], y=curve["Hs [MJ/m³]"], name="Hs", mode="lines")
        )
        fig.add_trace(
            go.Scatter(x=curve["H2 [% mol]"], y=curve["Hi [MJ/m³]"], name="Hi", mode="lines")
        )
        fig.add_trace(
            go.Scatter(
                x=curve["H2 [% mol]"],
                y=curve["MN"],
                name="liczba metanowa (oś prawa)",
                mode="lines",
                yaxis="y2",
                line=dict(dash="dot"),
            )
        )
        mn_limit = float(load_data_file("methane_number.yaml")["engine_limit"]["min_mn"])
        fig.add_hline(
            y=mn_limit,
            line_dash="dash",
            line_color="orange",
            yref="y2",
            annotation_text=f"limit MN {mn_limit:g}",
            annotation_position="bottom right",
        )
        fig.add_vline(x=h2_pct, line_dash="dot", annotation_text=f"{h2_pct:g}% H₂")
        if hlim is not None and hlim.max_h2_mole_pct < 100.0:
            fig.add_vline(
                x=hlim.max_h2_mole_pct,
                line_dash="dash",
                line_color="red",
                annotation_text=f"max {hlim.max_h2_mole_pct:.0f}% ({hlim.binding})",
                annotation_position="top right",
            )
        fig.update_layout(
            xaxis_title="Udział H₂ [% mol]",
            yaxis=dict(title=f"MJ/m³ ({reference.name})"),
            yaxis2=dict(title="liczba metanowa", overlaying="y", side="right", range=[0, 105]),
            legend=dict(orientation="h"),
            height=450,
        )
        st.plotly_chart(fig, config={"displaylogo": False})
        st.caption(
            "Czerwona linia = maksymalny udział H₂ dla grupy E (ograniczenie wiążące). "
            "Ws (Wobbe) pozostaje w paśmie E nawet dla dużych udziałów H₂ — o granicy "
            "decyduje zwykle **liczba metanowa** (oś prawa) albo scenariuszowy próg %H₂."
        )

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

**Domieszki (H₂ + biometan):** skład końcowy = mieszanie molowe trzech
strumieni (gaz bazowy + wodór wybranej klasy czystości + biometan z biblioteki
lub własny). **Maks. udział H₂ dla grupy E** wyznaczany przez bisekcję dla
każdego kryterium (Wobbe ≥ 45 MJ/m³, liczba metanowa ≥ limit, próg %H₂);
wiąże najniższe. Uwaga: Ws czystego H₂ ≈ 48 MJ/m³ jest w paśmie E — dlatego
Wobbe zwykle NIE ogranicza H₂, a wiąże liczba metanowa lub próg %H₂.

**Propanowanie (korekta Wobbego):** gdy domieszka obniża Ws poniżej pasma E,
narzędzie liczy (bisekcja) udział propanu C₃H₈ przywracający Ws do dolnej
granicy. Propan podnosi Wobbe/kaloryczność, ale OBNIŻA liczbę metanową
(MN(C₃H₈) ≈ 34) — wynik podaje MN po wzbogaceniu, bo korekta Wobbego nie
gwarantuje pełnej zgodności E.

**Wykładnik izentropy (rzeczywisty):** `κ = w²·ρ/p` (w — prędkość dźwięku);
dla gazu doskonałego κ = cp/cv.

**Lepkość:** korelacje referencyjne CoolProp (mieszaniny: model ECS);
w razie niedostępności — reguła Wilke'a (1950), przybliżenie niskociśnieniowe
(oznaczane przy wyniku).

**Walidacja:** testy automatyczne porównują wyniki z wartościami referencyjnymi
(ISO 6976, NIST WebBook, entalpie tworzenia ATcT/CODATA, literatura) —
tolerancje: Z, ρ, cp ≤ 0,5%; wartości kaloryczne ≤ 0,1%. Szczegóły:
`tests/reference_data.py`.

**Dlaczego te biblioteki (dobór świadomy):** GERG-2008 jest międzynarodowym
wzorcem równania stanu dla gazu ziemnego i jego mieszanin z wodorem
(ISO 20765-2, następca AGA8) — stosowanym w rozliczeniach handlowych. ISO 6976
to norma kaloryczności/Wobbego w gazownictwie. To najwyższy dostępny standard
dokładności dla tego zakresu p,T; równania sześcienne (Peng-Robinson, SRK)
byłyby szybsze, ale mniej dokładne dla ρ/Z (krok wstecz). Jedyna realna
alternatywa to komercyjny **NIST REFPROP** (ten sam model GERG-2008 dla gazu
ziemnego, nowsze parametry binarne H₂) — marginalny zysk dokładności kosztem
licencji; nieuzasadniony dla narzędzia przesiewowego B+R.
            """)
