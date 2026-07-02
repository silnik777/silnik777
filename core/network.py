"""Proste grafy sieci gazowej: solver węzłowy ustalonego przepływu — M15.

Model sieci (steady-state, izotermiczny, jeden skład gazu w całej sieci):
    * węzły: **ciśnieniowe** (zadane p — stacje zasilające) i **odbiorowe**
      (zadany pobór masowy; pobór 0 = węzeł pośredni/łączeniowy),
    * odcinki: rury o zadanej średnicy/długości/chropowatości, łączące węzły;
      dozwolone sieci promieniowe i z pętlami (oczkami).

Metoda:
    * hydraulika odcinka w postaci uogólnionego równania przepływu:
          p_a² − p_b² = K·ṁ·|ṁ|,
      gdzie opór K jest **kalibrowany dokładnym modelem marszowym M3**
      (GERG-2008, Colebrook-White): K = (p_in² − p_out²)/ṁ² z przebiegu
      ``pressure_profile`` przy bieżącym przepływie — sieć liczy się szybko,
      a pozostaje spójna z resztą narzędzia (test: pojedynczy odcinek
      odtwarza wynik M3 z dokładnością < 0,2%),
    * bilans masy w każdym węźle odbiorowym: Σ ṁ_dopływające = pobór,
    * rozwiązanie: Newton-Raphson na niewiadomych u_i = p_i² (tłumiony,
      z regularyzacją jakobianu przy Δu → 0), pętla zewnętrzna aktualizuje
      opory K aż do ich stabilizacji.

Ograniczenia (jawne): jeden skład gazu w całej sieci (śledzenie mieszania
składów w węzłach — poza zakresem tej wersji), pominięte różnice wysokości,
przepływ ustalony (bez dynamiki).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.pipeline import MIN_OUTLET_PRESSURE_PA, friction_factor, pressure_profile
from core.units import R_UNIVERSAL_J_PER_MOL_K

#: Maksymalne iteracje pętli zewnętrznej (aktualizacja oporów K).
MAX_OUTER_ITER = 8
#: Maksymalne iteracje Newtona (pętla wewnętrzna).
MAX_NEWTON_ITER = 80
#: Regularyzacja pochodnej przy małej różnicy p² [Pa²].
_EPS_U = 1.0e8


@dataclass(frozen=True)
class NetworkNode:
    """Węzeł sieci: ciśnieniowy (zadane p) albo odbiorowy (zadany pobór)."""

    name: str
    kind: str  # "cisnieniowy" | "odbiorowy"
    pressure_pa: float | None = None  # dla ciśnieniowych
    offtake_kg_per_s: float = 0.0  # dla odbiorowych (0 = węzeł pośredni)


@dataclass(frozen=True)
class NetworkPipe:
    """Odcinek sieci między dwoma węzłami."""

    name: str
    node_from: str
    node_to: str
    diameter_m: float
    length_m: float
    roughness_m: float


@dataclass(frozen=True)
class NodeResult:
    """Wynik węzła: ciśnienie i bilans."""

    name: str
    kind: str
    pressure_pa: float
    supply_kg_per_s: float  # >0: zasilanie sieci (węzły ciśnieniowe); pobór ze znakiem −


@dataclass(frozen=True)
class PipeResult:
    """Wynik odcinka: przepływ (znak: + = od node_from do node_to)."""

    pipe: NetworkPipe
    mass_flow_kg_per_s: float
    pressure_from_pa: float
    pressure_to_pa: float
    velocity_m_per_s: float
    reynolds: float

    @property
    def pressure_drop_pa(self) -> float:
        return abs(self.pressure_from_pa - self.pressure_to_pa)


@dataclass(frozen=True)
class NetworkResult:
    """Rozwiązanie sieci + metryki jakości zbieżności."""

    nodes: list[NodeResult]
    pipes: list[PipeResult]
    newton_iterations: int
    outer_iterations: int
    max_imbalance_kg_per_s: float
    warnings: list[str] = field(default_factory=list)


def _validate_network(
    nodes: list[NetworkNode], pipes: list[NetworkPipe]
) -> tuple[dict[str, NetworkNode], list[str]]:
    if not nodes:
        raise ValueError("Sieć nie zawiera węzłów.")
    if not pipes:
        raise ValueError("Sieć nie zawiera odcinków.")
    by_name: dict[str, NetworkNode] = {}
    for node in nodes:
        if not node.name.strip():
            raise ValueError("Każdy węzeł musi mieć nazwę.")
        if node.name in by_name:
            raise ValueError(f"Powtórzona nazwa węzła: '{node.name}'.")
        if node.kind not in ("cisnieniowy", "odbiorowy"):
            raise ValueError(f"Węzeł '{node.name}': typ musi być 'cisnieniowy' albo 'odbiorowy'.")
        if node.kind == "cisnieniowy":
            if node.pressure_pa is None or node.pressure_pa <= MIN_OUTLET_PRESSURE_PA:
                raise ValueError(
                    f"Węzeł ciśnieniowy '{node.name}' wymaga ciśnienia "
                    f"> {MIN_OUTLET_PRESSURE_PA / 1e5:.2f} bar(a)."
                )
        elif node.offtake_kg_per_s < 0:
            raise ValueError(f"Węzeł '{node.name}': pobór nie może być ujemny.")
        by_name[node.name] = node

    pressure_nodes = [n for n in nodes if n.kind == "cisnieniowy"]
    if not pressure_nodes:
        raise ValueError("Sieć wymaga co najmniej jednego węzła ciśnieniowego (zasilania).")

    seen_pipe_names = set()
    for pipe in pipes:
        if pipe.name in seen_pipe_names:
            raise ValueError(f"Powtórzona nazwa odcinka: '{pipe.name}'.")
        seen_pipe_names.add(pipe.name)
        for endpoint in (pipe.node_from, pipe.node_to):
            if endpoint not in by_name:
                raise ValueError(
                    f"Odcinek '{pipe.name}' wskazuje nieistniejący węzeł "
                    f"'{endpoint}'. Dostępne: {', '.join(by_name)}."
                )
        if pipe.node_from == pipe.node_to:
            raise ValueError(f"Odcinek '{pipe.name}' łączy węzeł z samym sobą.")
        if pipe.diameter_m <= 0 or pipe.length_m <= 0 or pipe.roughness_m < 0:
            raise ValueError(f"Odcinek '{pipe.name}': niefizyczne wymiary.")

    # spójność grafu: BFS od węzłów ciśnieniowych
    adjacency: dict[str, set[str]] = {n.name: set() for n in nodes}
    for pipe in pipes:
        adjacency[pipe.node_from].add(pipe.node_to)
        adjacency[pipe.node_to].add(pipe.node_from)
    reached = set()
    queue = [n.name for n in pressure_nodes]
    while queue:
        current = queue.pop()
        if current in reached:
            continue
        reached.add(current)
        queue.extend(adjacency[current] - reached)
    unreached = set(by_name) - reached
    if unreached:
        raise ValueError("Węzły bez połączenia z zasilaniem: " + ", ".join(sorted(unreached)) + ".")
    return by_name, [n.name for n in nodes]


def _analytic_resistance(
    composition: GasComposition,
    pipe: NetworkPipe,
    pressure_pa: float,
    temperature_k: float,
    mass_flow_abs: float,
) -> float:
    """Opór K z uogólnionego równania przepływu (start/fallback kalibracji).

    K = λ·(16/π²)·(Z·R·T/M)·L/D⁵ — λ z Colebrooka przy bieżącym Re
    (λ = 0,015 przy przepływie ~0), Z przy ciśnieniu odniesienia węzła.
    """
    props = compute_properties(composition, pressure_pa, temperature_k)
    m_molar = composition.molar_mass_kg_per_kmol / 1e3
    if mass_flow_abs > 1e-9 and props.viscosity_pa_s:
        reynolds = 4.0 * mass_flow_abs / (np.pi * pipe.diameter_m * props.viscosity_pa_s)
        lam = friction_factor(reynolds, pipe.roughness_m / pipe.diameter_m)
    else:
        lam = 0.015
    return (
        lam
        * (16.0 / np.pi**2)
        * (props.z_factor * R_UNIVERSAL_J_PER_MOL_K * temperature_k / m_molar)
        * pipe.length_m
        / pipe.diameter_m**5
    )


def _calibrated_resistance(
    composition: GasComposition,
    pipe: NetworkPipe,
    pressure_high_pa: float,
    temperature_k: float,
    mass_flow_abs: float,
) -> float:
    """Opór K skalibrowany modelem marszowym M3 (GERG-2008) przy bieżącym ṁ."""
    if mass_flow_abs < 1e-6:
        return _analytic_resistance(
            composition, pipe, pressure_high_pa, temperature_k, mass_flow_abs
        )
    try:
        res = pressure_profile(
            composition,
            pipe.diameter_m,
            pipe.length_m,
            pipe.roughness_m,
            mass_flow_abs,
            pressure_high_pa,
            temperature_k,
            n_segments=15,
            inlet_check=False,
        )
        return (res.pressure_in_pa**2 - res.pressure_out_pa**2) / mass_flow_abs**2
    except ValueError:
        # przepływ chwilowo za duży dla odcinka — wróć do wzoru analitycznego
        return _analytic_resistance(
            composition, pipe, pressure_high_pa, temperature_k, mass_flow_abs
        )


def solve_network(
    composition: GasComposition,
    nodes: list[NetworkNode],
    pipes: list[NetworkPipe],
    temperature_k: float = 283.15,
) -> NetworkResult:
    """Rozwiązuje sieć: ciśnienia w węzłach i przepływy w odcinkach.

    Args:
        composition: wspólny skład gazu w sieci (M1),
        nodes: węzły (≥ 1 ciśnieniowy; pobory w kg/s),
        pipes: odcinki (dozwolone pętle),
        temperature_k: temperatura gazu (stała w sieci).

    Raises:
        ValueError: błędna topologia/dane albo brak zbieżności solvera
            (komunikaty po polsku, wskazujące element sieci).
    """
    by_name, order = _validate_network(nodes, pipes)
    unknown = [name for name in order if by_name[name].kind == "odbiorowy"]
    idx = {name: i for i, name in enumerate(unknown)}

    fixed_u = {
        name: float(by_name[name].pressure_pa) ** 2
        for name in order
        if by_name[name].kind == "cisnieniowy"
    }
    total_demand = sum(by_name[name].offtake_kg_per_s for name in unknown)
    tol = 1e-6 * max(1.0, total_demand)

    # start: u nieco poniżej najniższego zasilania
    u = np.full(len(unknown), 0.96 * min(fixed_u.values()), dtype=float)
    resistances = {
        pipe.name: _analytic_resistance(
            composition, pipe, max(fixed_u.values()) ** 0.5, temperature_k, 0.0
        )
        for pipe in pipes
    }

    def u_of(name: str, u_vec: np.ndarray) -> float:
        return fixed_u[name] if name in fixed_u else float(u_vec[idx[name]])

    def pipe_flow(pipe: NetworkPipe, u_vec: np.ndarray) -> float:
        du = u_of(pipe.node_from, u_vec) - u_of(pipe.node_to, u_vec)
        return float(np.sign(du) * np.sqrt(abs(du) / resistances[pipe.name]))

    def residual(u_vec: np.ndarray) -> np.ndarray:
        f = np.zeros(len(unknown))
        for pipe in pipes:
            m = pipe_flow(pipe, u_vec)
            if pipe.node_to in idx:
                f[idx[pipe.node_to]] += m
            if pipe.node_from in idx:
                f[idx[pipe.node_from]] -= m
        for name in unknown:
            f[idx[name]] -= by_name[name].offtake_kg_per_s
        return f

    def jacobian(u_vec: np.ndarray) -> np.ndarray:
        jac = np.zeros((len(unknown), len(unknown)))
        for pipe in pipes:
            du = u_of(pipe.node_from, u_vec) - u_of(pipe.node_to, u_vec)
            deriv = 1.0 / (2.0 * np.sqrt(resistances[pipe.name] * max(abs(du), _EPS_U)))
            i_from = idx.get(pipe.node_from)
            i_to = idx.get(pipe.node_to)
            # m = sign(du)·sqrt(|du|/K); dm/du_from = +deriv, dm/du_to = −deriv
            if i_to is not None:
                if i_from is not None:
                    jac[i_to, i_from] += deriv
                jac[i_to, i_to] -= deriv
            if i_from is not None:
                if i_to is not None:
                    jac[i_from, i_to] += deriv
                jac[i_from, i_from] -= deriv
        return jac

    newton_total = 0
    outer_done = 0
    k_stable = False
    for outer in range(MAX_OUTER_ITER):
        outer_done = outer + 1
        # --- Newton na u (stałe K) ---
        converged = False
        for _ in range(MAX_NEWTON_ITER):
            newton_total += 1
            f = residual(u)
            if np.max(np.abs(f)) < tol:
                converged = True
                break
            try:
                step = np.linalg.solve(jacobian(u), -f)
            except np.linalg.LinAlgError as exc:
                raise ValueError(
                    "Solver sieci: osobliwy układ równań — sprawdź, czy każdy "
                    "węzeł odbiorowy ma połączenie z zasilaniem."
                ) from exc
            norm0 = float(np.linalg.norm(f))
            alpha = 1.0
            for _ in range(8):
                u_new = np.maximum(u + alpha * step, (0.5 * MIN_OUTLET_PRESSURE_PA) ** 2)
                if float(np.linalg.norm(residual(u_new))) < norm0:
                    break
                alpha *= 0.5
            u = u_new
        if not converged:
            raise ValueError(
                "Solver sieci nie zbiegł — prawdopodobnie pobory przekraczają "
                "przepustowość sieci przy zadanych ciśnieniach zasilania."
            )
        if k_stable:
            # domykający Newton wykonany z ustabilizowanymi K — koniec
            break
        # --- aktualizacja oporów K modelem marszowym ---
        max_change = 0.0
        for pipe in pipes:
            m_abs = abs(pipe_flow(pipe, u))
            p_high = max(u_of(pipe.node_from, u), u_of(pipe.node_to, u)) ** 0.5
            new_k = _calibrated_resistance(composition, pipe, p_high, temperature_k, m_abs)
            old_k = resistances[pipe.name]
            max_change = max(max_change, abs(new_k - old_k) / old_k)
            resistances[pipe.name] = new_k
        if max_change < 1e-3:
            k_stable = True  # jeszcze jeden przebieg Newtona z finalnymi K

    # --- kontrola ciśnień minimalnych ---
    warnings: list[str] = []
    for name in unknown:
        p_node = u[idx[name]] ** 0.5
        if p_node < MIN_OUTLET_PRESSURE_PA:
            raise ValueError(
                f"Ciśnienie w węźle '{name}' spada do {p_node / 1e5:.2f} bar(a) "
                f"(poniżej {MIN_OUTLET_PRESSURE_PA / 1e5:.2f}) — pobory "
                "przekraczają przepustowość sieci."
            )

    # --- wyniki ---
    pipe_results: list[PipeResult] = []
    for pipe in pipes:
        m = pipe_flow(pipe, u)
        p_from = u_of(pipe.node_from, u) ** 0.5
        p_to = u_of(pipe.node_to, u) ** 0.5
        props = compute_properties(composition, max(p_from, p_to), temperature_k)
        area = np.pi * pipe.diameter_m**2 / 4.0
        velocity = abs(m) / (props.density_kg_per_m3 * area)
        reynolds = (
            4.0 * abs(m) / (np.pi * pipe.diameter_m * props.viscosity_pa_s)
            if props.viscosity_pa_s
            else 0.0
        )
        pipe_results.append(
            PipeResult(
                pipe=pipe,
                mass_flow_kg_per_s=m,
                pressure_from_pa=p_from,
                pressure_to_pa=p_to,
                velocity_m_per_s=velocity,
                reynolds=reynolds,
            )
        )

    node_results: list[NodeResult] = []
    for name in order:
        node = by_name[name]
        pressure = u_of(name, u) ** 0.5
        if node.kind == "cisnieniowy":
            supply = sum(
                -pr.mass_flow_kg_per_s if pr.pipe.node_to == name else 0.0 for pr in pipe_results
            ) + sum(
                pr.mass_flow_kg_per_s if pr.pipe.node_from == name else 0.0 for pr in pipe_results
            )
        else:
            supply = -node.offtake_kg_per_s
        node_results.append(
            NodeResult(name=name, kind=node.kind, pressure_pa=pressure, supply_kg_per_s=supply)
        )

    return NetworkResult(
        nodes=node_results,
        pipes=pipe_results,
        newton_iterations=newton_total,
        outer_iterations=outer_done,
        max_imbalance_kg_per_s=float(np.max(np.abs(residual(u)))) if unknown else 0.0,
        warnings=warnings,
    )
