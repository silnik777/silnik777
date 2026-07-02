"""M15 — Sieć gazowa: prosty graf węzłów i odcinków (solver węzłowy)."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.composition import GasComposition
from core.config import load_data_file
from core.gas_properties import compute_properties
from core.network import NetworkNode, NetworkPipe, NetworkResult, solve_network
from core.pipeline import pipe_materials
from core.units import bar_to_pa, celsius_to_kelvin

_DEFAULT_NODES = pd.DataFrame(
    {
        "Węzeł": ["Zasilanie", "A", "B", "C"],
        "Typ": ["ciśnieniowy", "odbiorowy", "odbiorowy", "odbiorowy"],
        "Ciśnienie [bar(a)]": [55.0, None, None, None],
        "Pobór [Nm³/h]": [None, 20000.0, 15000.0, 10000.0],
    }
)
_DEFAULT_PIPES = pd.DataFrame(
    {
        "Odcinek": ["R1", "R2", "R3", "R4 (pętla)"],
        "Z węzła": ["Zasilanie", "A", "A", "Zasilanie"],
        "Do węzła": ["A", "B", "C", "B"],
        "Średnica [mm]": [300.0, 250.0, 200.0, 250.0],
        "Długość [km]": [8.0, 6.0, 5.0, 12.0],
        "Materiał": ["stal", "stal", "pe_nowe", "stal"],
    }
)


def _layout_positions(
    result: NetworkResult,
) -> dict[str, tuple[float, float]]:
    """Prosty układ grafu: poziomy BFS od węzłów ciśnieniowych."""
    adjacency: dict[str, set[str]] = {n.name: set() for n in result.nodes}
    for pr in result.pipes:
        adjacency[pr.pipe.node_from].add(pr.pipe.node_to)
        adjacency[pr.pipe.node_to].add(pr.pipe.node_from)
    level = {n.name: None for n in result.nodes}
    queue = [n.name for n in result.nodes if n.kind == "cisnieniowy"]
    for name in queue:
        level[name] = 0
    while queue:
        current = queue.pop(0)
        for neighbor in adjacency[current]:
            if level[neighbor] is None:
                level[neighbor] = level[current] + 1
                queue.append(neighbor)
    by_level: dict[int, list[str]] = {}
    for name, lvl in level.items():
        by_level.setdefault(lvl or 0, []).append(name)
    positions = {}
    for lvl, names in by_level.items():
        for i, name in enumerate(sorted(names)):
            positions[name] = (float(lvl), -float(i) + (len(names) - 1) / 2.0)
    return positions


def _network_figure(result: NetworkResult, v_limit: float) -> go.Figure:
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
                    f"{pr.pipe.name}: {abs(pr.mass_flow_kg_per_s):.2f} kg/s, "
                    f"{pr.velocity_m_per_s:.1f} m/s"
                ),
                showlegend=False,
            )
        )
        # strzałka kierunku przepływu w połowie odcinka
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
    node_x = [pos[n.name][0] for n in result.nodes]
    node_y = [pos[n.name][1] for n in result.nodes]
    fig.add_trace(
        go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers+text",
            text=[f"{n.name}<br>{n.pressure_pa / 1e5:.1f} bar" for n in result.nodes],
            textposition="top center",
            marker=dict(
                size=[26 if n.kind == "cisnieniowy" else 18 for n in result.nodes],
                symbol=["square" if n.kind == "cisnieniowy" else "circle" for n in result.nodes],
                color=[n.pressure_pa / 1e5 for n in result.nodes],
                colorscale="Viridis",
                colorbar=dict(title="bar(a)"),
                line=dict(width=1, color="#333333"),
            ),
            hoverinfo="text",
            showlegend=False,
        )
    )
    fig.update_layout(
        height=440,
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        margin=dict(l=20, r=20, t=20, b=20),
    )
    return fig


def render() -> None:
    st.title("M15 · Sieć gazowa (graf)")
    st.caption(
        "Prosty graf węzłów i odcinków (pętle dozwolone) · solver węzłowy "
        "Newtona na p² · opory kalibrowane modelem marszowym M3 (GERG-2008)"
    )

    compositions = load_data_file("gas_compositions.yaml")["compositions"]
    c1, c2, c3 = st.columns(3)
    gas_key = c1.selectbox(
        "Skład gazu (wspólny dla sieci)",
        list(compositions),
        format_func=lambda k: compositions[k]["name_pl"],
    )
    base = GasComposition.predefined(gas_key)
    h2_pct = 0.0
    if base.is_combustible and gas_key != "wodor_99999":
        h2_pct = c2.slider("Domieszka H2 [% mol]", 0.0, 100.0, 0.0, 5.0)
    composition = base.blend_with_hydrogen(h2_pct / 100.0) if h2_pct else base
    t_c = c3.number_input("T gazu [°C]", -20.0, 60.0, 10.0, 1.0)

    st.subheader("1️⃣ Węzły")
    st.caption(
        "Węzeł **ciśnieniowy** = zasilanie (podaj ciśnienie); **odbiorowy** = "
        "pobór gazu (0 = punkt łączeniowy). Dodawaj wiersze przyciskiem ＋."
    )
    nodes_df = st.data_editor(
        _DEFAULT_NODES,
        num_rows="dynamic",
        key="m15_nodes",
        column_config={
            "Typ": st.column_config.SelectboxColumn(
                options=["ciśnieniowy", "odbiorowy"], required=True
            ),
            "Ciśnienie [bar(a)]": st.column_config.NumberColumn(
                min_value=1.2, max_value=100.0, format="%.1f"
            ),
            "Pobór [Nm³/h]": st.column_config.NumberColumn(min_value=0.0, format="%.0f"),
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

    v_limits = load_data_file("pipelines.yaml")["velocity_limits_m_per_s"]
    v_limit_key = st.selectbox(
        "Limit prędkości",
        list(v_limits),
        format_func=lambda k: f"{v_limits[k]['name_pl']} ({v_limits[k]['max']:g} m/s)",
    )
    v_max_limit = float(v_limits[v_limit_key]["max"])

    # --- budowa modelu sieci z tabel ---
    rho_n = compute_properties(composition, 101_325.0, 273.15).density_kg_per_m3
    try:
        nodes = []
        for _, row in nodes_df.iterrows():
            name = str(row["Węzeł"]).strip() if pd.notna(row["Węzeł"]) else ""
            if not name:
                continue
            if row["Typ"] == "ciśnieniowy":
                if pd.isna(row["Ciśnienie [bar(a)]"]):
                    raise ValueError(f"Węzeł ciśnieniowy '{name}': podaj ciśnienie.")
                nodes.append(
                    NetworkNode(
                        name, "cisnieniowy", pressure_pa=bar_to_pa(float(row["Ciśnienie [bar(a)]"]))
                    )
                )
            else:
                offtake_nm3_h = (
                    float(row["Pobór [Nm³/h]"]) if pd.notna(row["Pobór [Nm³/h]"]) else 0.0
                )
                nodes.append(
                    NetworkNode(name, "odbiorowy", offtake_kg_per_s=offtake_nm3_h * rho_n / 3600.0)
                )
        pipes = []
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
        result = solve_network(composition, nodes, pipes, celsius_to_kelvin(t_c))
    except (ValueError, KeyError) as exc:
        st.error(f"{exc}")
        st.stop()
        return

    st.subheader("3️⃣ Wyniki")
    st.caption(
        f"Zbieżność: {result.newton_iterations} iteracji Newtona, "
        f"{result.outer_iterations} kalibracje oporów · maks. niedobilans masy: "
        f"{result.max_imbalance_kg_per_s:.2e} kg/s"
    )
    c_map, c_tab = st.columns([3, 2], gap="large")
    with c_map:
        st.plotly_chart(_network_figure(result, v_max_limit), config={"displaylogo": False})
        st.caption(
            "◼ węzeł ciśnieniowy (zasilanie) · ● węzeł odbiorowy · kolor = "
            "ciśnienie · czerwony odcinek = przekroczony limit prędkości"
        )
    with c_tab:
        st.markdown("**Węzły**")
        st.dataframe(
            pd.DataFrame(
                {
                    "Węzeł": [n.name for n in result.nodes],
                    "Typ": [n.kind for n in result.nodes],
                    "p [bar(a)]": [n.pressure_pa / 1e5 for n in result.nodes],
                    "Bilans [Nm³/h]": [n.supply_kg_per_s / rho_n * 3600.0 for n in result.nodes],
                }
            ).round(2),
            hide_index=True,
            width="stretch",
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
            "Przepływ [Nm³/h]": [
                abs(pr.mass_flow_kg_per_s) / rho_n * 3600.0 for pr in result.pipes
            ],
            "Prędkość [m/s]": [pr.velocity_m_per_s for pr in result.pipes],
            "ΔP [bar]": [pr.pressure_drop_pa / 1e5 for pr in result.pipes],
            "Re": [pr.reynolds for pr in result.pipes],
            "Limit v": ["❌" if pr.velocity_m_per_s > v_max_limit else "✅" for pr in result.pipes],
        }
    ).round({"Przepływ [Nm³/h]": 0, "Prędkość [m/s]": 1, "ΔP [bar]": 2, "Re": 0})
    st.dataframe(pipes_out, hide_index=True, width="stretch")
    st.download_button(
        "⬇️ Wyniki sieci (CSV)",
        data=pipes_out.to_csv(index=False, sep=";").encode("utf-8-sig"),
        file_name="siec_wyniki.csv",
        mime="text/csv",
    )

    with st.expander("📖 Założenia i wzory"):
        st.markdown("""
**Model:** przepływ ustalony, izotermiczny, jeden skład gazu w całej sieci;
hydraulika odcinka `p_a² − p_b² = K·ṁ·|ṁ|`, gdzie opór K jest kalibrowany
**dokładnym modelem marszowym M3** (GERG-2008 + Colebrook-White) przy
bieżącym przepływie — test: sieć 1-odcinkowa odtwarza wynik M3 < 0,2%.

**Solver:** bilans masy w węzłach odbiorowych, Newton-Raphson na
niewiadomych p² (tłumiony), pętla zewnętrzna aktualizuje opory aż do
stabilizacji; po stabilizacji domykający przebieg Newtona. Obsługiwane
sieci promieniowe i z pętlami.

**Poza zakresem tej wersji:** mieszanie różnych składów w węzłach
(śledzenie %H₂ w sieci), różnice wysokości, stany nieustalone, regulatory
ciśnienia wewnątrz sieci (stację redukcyjną modelujesz, dzieląc sieć na
dwie o różnych zasilaniach; bilans stacji — moduł M13).
            """)
