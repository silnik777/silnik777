"""M15 — Sieć gazowa: graf ze śledzeniem składu i stref mieszania."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.calorific import calorific_values, quality_flags
from core.composition import GasComposition
from core.config import load_data_file
from core.methane_number import methane_number_assessment
from core.network import NetworkNode, NetworkPipe, NetworkResult, solve_network
from core.pipeline import pipe_materials
from core.units import bar_to_pa, celsius_to_kelvin

_KIND_LABELS = {
    "ciśnieniowy (zasilanie)": "cisnieniowy",
    "odbiorowy (pobór)": "odbiorowy",
    "wtłoczenie (biometan/H2)": "zrodlowy",
}

_DEFAULT_NODES = pd.DataFrame(
    {
        "Węzeł": ["Zasilanie GZ", "A", "Biometanownia", "B", "C"],
        "Typ": [
            "ciśnieniowy (zasilanie)",
            "odbiorowy (pobór)",
            "wtłoczenie (biometan/H2)",
            "odbiorowy (pobór)",
            "odbiorowy (pobór)",
        ],
        "Skład": ["gaz_E_typowy", None, "biometan", None, None],
        "Ciśnienie [bar(a)]": [55.0, None, None, None, None],
        "Pobór [Nm³/h]": [None, 20000.0, None, 15000.0, 10000.0],
        "Wtłoczenie [Nm³/h]": [None, None, 3000.0, None, None],
    }
)
_DEFAULT_PIPES = pd.DataFrame(
    {
        "Odcinek": ["R1", "R2", "R3", "R4", "R5 (pętla)"],
        "Z węzła": ["Zasilanie GZ", "A", "Biometanownia", "A", "Zasilanie GZ"],
        "Do węzła": ["A", "Biometanownia", "B", "C", "B"],
        "Średnica [mm]": [300.0, 250.0, 250.0, 200.0, 250.0],
        "Długość [km]": [8.0, 3.0, 3.0, 5.0, 12.0],
        "Materiał": ["stal", "stal", "stal", "pe_nowe", "stal"],
    }
)


def _layout_positions(result: NetworkResult) -> dict[str, tuple[float, float]]:
    """Prosty układ grafu: poziomy BFS od węzłów ciśnieniowych."""
    adjacency: dict[str, set[str]] = {n.name: set() for n in result.nodes}
    for pr in result.pipes:
        adjacency[pr.pipe.node_from].add(pr.pipe.node_to)
        adjacency[pr.pipe.node_to].add(pr.pipe.node_from)
    level: dict[str, int | None] = {n.name: None for n in result.nodes}
    queue = [n.name for n in result.nodes if n.kind == "cisnieniowy"]
    for name in queue:
        level[name] = 0
    while queue:
        current = queue.pop(0)
        for neighbor in adjacency[current]:
            if level[neighbor] is None:
                level[neighbor] = (level[current] or 0) + 1
                queue.append(neighbor)
    by_level: dict[int, list[str]] = {}
    for name, lvl in level.items():
        by_level.setdefault(lvl or 0, []).append(name)
    positions = {}
    for lvl, names in by_level.items():
        for i, name in enumerate(sorted(names)):
            positions[name] = (float(lvl), -float(i) + (len(names) - 1) / 2.0)
    return positions


_NODE_SYMBOLS = {"cisnieniowy": "square", "zrodlowy": "diamond", "odbiorowy": "circle"}


def _network_figure(
    result: NetworkResult, v_limit: float, color_mode: str, node_values: dict[str, float]
) -> go.Figure:
    pos = _layout_positions(result)
    fig = go.Figure()
    for pr in result.pipes:
        x0, y0 = pos[pr.pipe.node_from]
        x1, y1 = pos[pr.pipe.node_to]
        over = pr.velocity_m_per_s > v_limit
        fig.add_trace(
            go.Scatter(
                x=[x0, x1],
                y=[y0, y1],
                mode="lines",
                line=dict(width=3.0, color="#d62728" if over else "#7f7f7f"),
                hoverinfo="text",
                text=(
                    f"{pr.pipe.name}: {abs(pr.mass_flow_kg_per_s):.2f} kg/s · "
                    f"{pr.velocity_m_per_s:.1f} m/s · "
                    f"%H2 = {pr.composition.h2_mole_percent:.1f}"
                ),
                showlegend=False,
            )
        )
        xm, ym = (x0 + x1) / 2.0, (y0 + y1) / 2.0
        sign = 1.0 if pr.mass_flow_kg_per_s >= 0 else -1.0
        fig.add_annotation(
            x=xm + sign * (x1 - x0) * 0.001,
            y=ym + sign * (y1 - y0) * 0.001,
            ax=xm,
            ay=ym,
            axref="x",
            ayref="y",
            showarrow=True,
            arrowhead=2,
            arrowsize=1.6,
            arrowcolor="#444444",
        )
    fig.add_trace(
        go.Scatter(
            x=[pos[n.name][0] for n in result.nodes],
            y=[pos[n.name][1] for n in result.nodes],
            mode="markers+text",
            text=[f"{n.name}<br>{node_values[n.name]:.1f}" for n in result.nodes],
            textposition="top center",
            marker=dict(
                size=[24 if n.kind != "odbiorowy" else 17 for n in result.nodes],
                symbol=[_NODE_SYMBOLS[n.kind] for n in result.nodes],
                color=[node_values[n.name] for n in result.nodes],
                colorscale="Viridis" if color_mode == "Ciśnienie" else "Turbo",
                colorbar=dict(title=color_mode),
                line=dict(width=1, color="#333333"),
            ),
            hoverinfo="text",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=460,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig


def render() -> None:
    st.title("M15 · Sieć gazowa (graf)")
    st.caption(
        "Składy definiowane na wejściach (zasilania + wtłoczenia biometanu/H2) · "
        "strefy mieszania i jakość gazu w każdym węźle · solver Newtona na p², "
        "opory kalibrowane GERG-2008 (M3)"
    )

    compositions = load_data_file("gas_compositions.yaml")["compositions"]
    comp_keys = list(compositions)
    c1, c2 = st.columns(2)
    default_key = c1.selectbox(
        "Skład domyślny (dla zasilań bez własnego składu)",
        comp_keys,
        format_func=lambda k: compositions[k]["name_pl"],
    )
    default_comp = GasComposition.predefined(default_key)
    t_c = c2.number_input("T gazu [°C]", -20.0, 60.0, 10.0, 1.0)

    st.subheader("1️⃣ Węzły")
    st.caption(
        "**Zasilanie** — zadane ciśnienie i skład · **pobór** — odbiór w Nm³/h "
        "(0 = punkt łączeniowy) · **wtłoczenie** — stały strumień biometanu/H2 "
        "o własnym składzie. Wiersze dodajesz przyciskiem ＋."
    )
    nodes_df = st.data_editor(
        _DEFAULT_NODES,
        num_rows="dynamic",
        key="m15_nodes",
        column_config={
            "Typ": st.column_config.SelectboxColumn(options=list(_KIND_LABELS), required=True),
            "Skład": st.column_config.SelectboxColumn(
                options=comp_keys,
                help="Wymagany dla zasilań i wtłoczeń (odbiory dziedziczą z sieci).",
            ),
            "Ciśnienie [bar(a)]": st.column_config.NumberColumn(
                min_value=1.2, max_value=100.0, format="%.1f"
            ),
            "Pobór [Nm³/h]": st.column_config.NumberColumn(min_value=0.0, format="%.0f"),
            "Wtłoczenie [Nm³/h]": st.column_config.NumberColumn(min_value=0.0, format="%.0f"),
        },
        hide_index=True,
        width="stretch",
    )
    node_names = [str(n) for n in nodes_df["Węzeł"].dropna() if str(n).strip()]

    st.subheader("2️⃣ Odcinki")
    materials = pipe_materials()
    pipes_df = st.data_editor(
        _DEFAULT_PIPES,
        num_rows="dynamic",
        key="m15_pipes",
        column_config={
            "Z węzła": st.column_config.SelectboxColumn(options=node_names, required=True),
            "Do węzła": st.column_config.SelectboxColumn(options=node_names, required=True),
            "Średnica [mm]": st.column_config.NumberColumn(
                min_value=20.0, max_value=1500.0, format="%.0f"
            ),
            "Długość [km]": st.column_config.NumberColumn(
                min_value=0.05, max_value=1000.0, format="%.2f"
            ),
            "Materiał": st.column_config.SelectboxColumn(options=list(materials), required=True),
        },
        hide_index=True,
        width="stretch",
    )

    limits = load_data_file("quality_limits.yaml")
    v_limits = load_data_file("pipelines.yaml")["velocity_limits_m_per_s"]
    cc1, cc2 = st.columns(2)
    v_limit_key = cc1.selectbox(
        "Limit prędkości",
        list(v_limits),
        format_func=lambda k: f"{v_limits[k]['name_pl']} ({v_limits[k]['max']:g} m/s)",
    )
    v_max_limit = float(v_limits[v_limit_key]["max"])
    h2_limit = cc2.select_slider(
        "Próg zgodności %H2 (scenariuszowy)",
        options=limits["hydrogen_blend_thresholds"]["analysis_levels_mol_pct"],
        value=10,
    )

    # --- budowa modelu sieci z tabel ---
    try:
        nodes: list[NetworkNode] = []
        for _, row in nodes_df.iterrows():
            name = str(row["Węzeł"]).strip() if pd.notna(row["Węzeł"]) else ""
            if not name:
                continue
            kind = _KIND_LABELS.get(str(row["Typ"]), "odbiorowy")
            comp = (
                GasComposition.predefined(str(row["Skład"]))
                if pd.notna(row.get("Skład")) and str(row.get("Skład")).strip()
                else None
            )
            if kind == "cisnieniowy":
                if pd.isna(row["Ciśnienie [bar(a)]"]):
                    raise ValueError(f"Zasilanie '{name}': podaj ciśnienie.")
                nodes.append(
                    NetworkNode(
                        name,
                        "cisnieniowy",
                        pressure_pa=bar_to_pa(float(row["Ciśnienie [bar(a)]"])),
                        composition=comp,
                    )
                )
            elif kind == "zrodlowy":
                injection = (
                    float(row["Wtłoczenie [Nm³/h]"]) if pd.notna(row["Wtłoczenie [Nm³/h]"]) else 0.0
                )
                nodes.append(
                    NetworkNode(name, "zrodlowy", injection_nm3_per_h=injection, composition=comp)
                )
            else:
                offtake = float(row["Pobór [Nm³/h]"]) if pd.notna(row["Pobór [Nm³/h]"]) else 0.0
                nodes.append(NetworkNode(name, "odbiorowy", offtake_nm3_per_h=offtake))
        pipes: list[NetworkPipe] = []
        for _, row in pipes_df.iterrows():
            if pd.isna(row["Odcinek"]) or not str(row["Odcinek"]).strip():
                continue
            mat = materials[str(row["Materiał"])]
            pipes.append(
                NetworkPipe(
                    name=str(row["Odcinek"]).strip(),
                    node_from=str(row["Z węzła"]),
                    node_to=str(row["Do węzła"]),
                    diameter_m=float(row["Średnica [mm]"]) / 1e3,
                    length_m=float(row["Długość [km]"]) * 1e3,
                    roughness_m=mat.roughness_typical_mm / 1e3,
                )
            )
        result = solve_network(default_comp, nodes, pipes, celsius_to_kelvin(t_c))
    except (ValueError, KeyError) as exc:
        st.error(f"{exc}")
        st.stop()
        return

    # --- jakość gazu per węzeł (M1) ---
    wobbe_cfg = limits["wobbe_index_group_E"]
    quality_rows = []
    for n in result.nodes:
        cal = calorific_values(n.composition)
        flags = quality_flags(n.composition, cal, h2_limit_mol_pct=float(h2_limit))
        wobbe_ok = next(f.ok for f in flags if "Wobbego" in f.name_pl)
        h2_ok = next(f.ok for f in flags if "H2" in f.name_pl)
        mn = methane_number_assessment(n.composition)
        meets_e = wobbe_ok and h2_ok
        quality_rows.append(
            {
                "Węzeł": n.name,
                "p [bar(a)]": n.pressure_pa / 1e5,
                "%H2": n.composition.h2_mole_percent,
                "Hs [MJ/m³]": cal.hs_mj_per_m3,
                "Ws [MJ/m³]": cal.wobbe_superior_mj_per_m3,
                "MN": mn.value,
                "Gaz E (Wobbe)": "✅" if wobbe_ok else "❌",
                f"H2 ≤ {h2_limit}%": "✅" if h2_ok else "❌",
                f"MN ≥ {mn.min_limit:g}": "✅" if mn.ok else "❌",
                "Wymogi E łącznie": "✅" if meets_e else "❌",
            }
        )
    quality_df = pd.DataFrame(quality_rows)

    st.subheader("3️⃣ Wyniki")
    st.caption(
        f"Zbieżność: {result.newton_iterations} iteracji Newtona, "
        f"{result.outer_iterations} kalibracje (opory+składy) · maks. "
        f"niedobilans masy: {result.max_imbalance_kg_per_s:.2e} kg/s"
    )
    for w in result.warnings:
        st.warning(w)

    color_mode = st.radio(
        "Kolorowanie mapy (strefy)",
        ["Ciśnienie", "%H2", "Liczba Wobbego"],
        horizontal=True,
        help="%H2 i Wobbe pokazują strefy mieszania składów w sieci.",
    )
    if color_mode == "Ciśnienie":
        node_values = {n.name: n.pressure_pa / 1e5 for n in result.nodes}
    elif color_mode == "%H2":
        node_values = {n.name: n.composition.h2_mole_percent for n in result.nodes}
    else:
        node_values = dict(zip(quality_df["Węzeł"], quality_df["Ws [MJ/m³]"], strict=False))

    c_map, c_tab = st.columns([3, 2], gap="large")
    with c_map:
        st.plotly_chart(
            _network_figure(result, v_max_limit, color_mode, node_values),
            config={"displaylogo": False},
        )
        st.caption(
            "◼ zasilanie · ◆ wtłoczenie · ● odbiór · kolor = wybrana wielkość · "
            "czerwony odcinek = przekroczony limit prędkości"
        )
    with c_tab:
        st.markdown("**Pochodzenie gazu w węzłach (strefy mieszania)**")
        sources = sorted({s for n in result.nodes for s in n.source_shares})
        shares_df = pd.DataFrame(
            {
                "Węzeł": [n.name for n in result.nodes],
                **{
                    f"z „{s}” [%]": [n.source_shares.get(s, 0.0) * 100.0 for n in result.nodes]
                    for s in sources
                },
            }
        ).round(1)
        st.dataframe(shares_df, hide_index=True, width="stretch")
        st.caption(
            "Udziały molowe gazu z każdego punktu wejścia — 100% = strefa "
            "jednego źródła; wartości pośrednie = strefa mieszania."
        )

    st.markdown("**Parametry i jakość gazu w węzłach (wymogi gazu wysokometanowego E)**")
    st.dataframe(
        quality_df.round({"p [bar(a)]": 2, "%H2": 2, "Hs [MJ/m³]": 3, "Ws [MJ/m³]": 3, "MN": 1}),
        hide_index=True,
        width="stretch",
    )
    st.caption(
        f"Wymogi E: Wobbe {wobbe_cfg['min_mj_per_m3']}–{wobbe_cfg['max_mj_per_m3']} MJ/m³ "
        f"+ próg %H2 (scenariuszowy). Uwaga: Ws czystego H2 (≈48 MJ/m³) mieści się "
        "w widełkach E — dlatego kontrola %H2 i liczby metanowej jest niezbędna."
    )

    st.markdown("**Odcinki**")
    pipes_out = pd.DataFrame(
        {
            "Odcinek": [pr.pipe.name for pr in result.pipes],
            "Kierunek": [
                (
                    f"{pr.pipe.node_from} → {pr.pipe.node_to}"
                    if pr.mass_flow_kg_per_s >= 0
                    else f"{pr.pipe.node_to} → {pr.pipe.node_from}"
                )
                for pr in result.pipes
            ],
            "Przepływ [kg/s]": [abs(pr.mass_flow_kg_per_s) for pr in result.pipes],
            "%H2 w odcinku": [pr.composition.h2_mole_percent for pr in result.pipes],
            "Prędkość [m/s]": [pr.velocity_m_per_s for pr in result.pipes],
            "ΔP [bar]": [pr.pressure_drop_pa / 1e5 for pr in result.pipes],
            "Limit v": ["❌" if pr.velocity_m_per_s > v_max_limit else "✅" for pr in result.pipes],
        }
    ).round({"Przepływ [kg/s]": 3, "%H2 w odcinku": 2, "Prędkość [m/s]": 1, "ΔP [bar]": 2})
    st.dataframe(pipes_out, hide_index=True, width="stretch")

    c_dl1, c_dl2 = st.columns(2)
    c_dl1.download_button(
        "⬇️ Jakość gazu w węzłach (CSV)",
        data=quality_df.to_csv(index=False, sep=";").encode("utf-8-sig"),
        file_name="siec_jakosc_wezly.csv",
        mime="text/csv",
    )
    c_dl2.download_button(
        "⬇️ Odcinki (CSV)",
        data=pipes_out.to_csv(index=False, sep=";").encode("utf-8-sig"),
        file_name="siec_odcinki.csv",
        mime="text/csv",
    )

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Hydraulika:** `p_a² − p_b² = K·ṁ·|ṁ|`; opór K każdego odcinka kalibrowany
modelem marszowym M3 (GERG-2008 + Colebrook) przy bieżącym przepływie
i SKŁADZIE odcinka. Solver: Newton na p² + pętla zewnętrzna (opory, składy,
pobory objętościowe) do stabilizacji.

**Śledzenie składu:** w stanie ustalonym przepływ biegnie od wyższego p²
do niższego (graf kierunków bez cykli), więc skład węzła = **mieszanie
molowe dopływów** `x = Σ ṅᵢxᵢ / Σ ṅᵢ`, liczone w kolejności malejącego
ciśnienia. Udziały źródeł śledzone jak znaczniki — wyznaczają strefy
zasilania i mieszania. Pobory w Nm³/h przeliczane wg gęstości LOKALNEGO
składu węzła.

**Jakość gazu (M1):** dla składu każdego węzła — Hs, Ws (ISO 6976),
%H2, liczba metanowa; wymogi gazu wysokometanowego E = widełki Wobbego
(rozp. 2010/IRiESD) + scenariuszowy próg %H2. **Uwaga:** Ws czystego H2
mieści się w widełkach E, więc samo Wobbe nie wykrywa domieszki.

**Uproszczenia:** front mieszania skokowy (bez dyspersji wzdłużnej i
czasów przejścia — stan ustalony), węzeł ciśnieniowy zachowuje swój skład
(granica systemu), pominięte różnice wysokości.
            """)
