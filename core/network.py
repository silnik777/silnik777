"""Proste grafy sieci gazowej ze śledzeniem składu — M15.

Model sieci (steady-state, izotermiczny):
    * węzły **ciśnieniowe** — zasilania o zadanym ciśnieniu i WŁASNYM
      składzie gazu (np. gaz E z sieci przesyłowej),
    * węzły **wtłoczenia** — zadany strumień wtłaczany [Nm³/h] o własnym
      składzie (biometanownia, elektrolizer H2),
    * węzły **odbiorowe** — zadany pobór (kg/s albo Nm³/h; 0 = punkt
      łączeniowy),
    * odcinki: rury (dozwolone pętle).

Hydraulika: p_a² − p_b² = K·ṁ·|ṁ|; opór K kalibrowany modelem marszowym M3
(GERG-2008 + Colebrook-White) przy bieżącym przepływie i SKŁADZIE odcinka.
Solver: tłumiony Newton-Raphson na u = p²; pętla zewnętrzna naprzemiennie:
(1) rozwiązuje przepływy, (2) śledzi składy, (3) aktualizuje opory
i pobory objętościowe — aż do stabilizacji.

Śledzenie składu (strefy mieszania):
    w stanie ustalonym przepływ biegnie wyłącznie od wyższego p² do
    niższego, więc graf kierunków przepływu jest acykliczny (DAG) — składy
    liczone są mieszaniem MOLOWYM dopływów w kolejności malejącego
    ciśnienia węzłów:
        x_mix = Σ ṅ_i·x_i / Σ ṅ_i,   ṅ = ṁ/M.
    Równolegle śledzone są udziały molowe gazu z każdego źródła
    (jak znaczniki) — to wprost wyznacza strefy zasilania i mieszania.

Założenia (jawne): węzeł ciśnieniowy zachowuje swój zdefiniowany skład
(granica systemu — duży kolektor); pominięte różnice wysokości; przepływ
ustalony; odcinek przyjmuje skład węzła górnego (dyspersja wzdłużna
pominięta — front mieszania traktowany skokowo).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.pipeline import MIN_OUTLET_PRESSURE_PA, friction_factor, pressure_profile
from core.units import R_UNIVERSAL_J_PER_MOL_K

#: Maksymalne iteracje pętli zewnętrznej (opory K + składy + pobory).
MAX_OUTER_ITER = 12
#: Maksymalne iteracje Newtona (pętla wewnętrzna).
MAX_NEWTON_ITER = 80
#: Regularyzacja pochodnej przy małej różnicy p² [Pa²].
_EPS_U = 1.0e8
#: Próg pomijalnego strumienia molowego przy mieszaniu [kmol/s].
_EPS_MOLAR = 1e-12

_NODE_KINDS = ("cisnieniowy", "odbiorowy", "zrodlowy")


@dataclass(frozen=True)
class NetworkNode:
    """Węzeł sieci.

    Rodzaje:
        * ``cisnieniowy`` — zasilanie: wymagane ``pressure_pa``; skład
          z ``composition`` (None = skład domyślny sieci),
        * ``odbiorowy`` — pobór: ``offtake_kg_per_s`` i/lub
          ``offtake_nm3_per_h`` (przeliczany wg LOKALNEGO składu węzła),
        * ``zrodlowy`` — wtłoczenie o stałym strumieniu: wymagane
          ``injection_nm3_per_h`` > 0 oraz ``composition``.
    """

    name: str
    kind: str
    pressure_pa: float | None = None
    offtake_kg_per_s: float = 0.0
    offtake_nm3_per_h: float = 0.0
    injection_nm3_per_h: float = 0.0
    composition: GasComposition | None = None


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
    """Wynik węzła: ciśnienie, bilans, skład i pochodzenie gazu."""

    name: str
    kind: str
    pressure_pa: float
    supply_kg_per_s: float  # >0: gaz oddawany do sieci; pobory ze znakiem −
    composition: GasComposition
    source_shares: dict[str, float]  # udział molowy gazu z każdego źródła


@dataclass(frozen=True)
class PipeResult:
    """Wynik odcinka: przepływ (znak: + = od node_from do node_to)."""

    pipe: NetworkPipe
    mass_flow_kg_per_s: float
    pressure_from_pa: float
    pressure_to_pa: float
    velocity_m_per_s: float
    reynolds: float
    composition: GasComposition  # skład gazu płynącego odcinkiem (węzeł górny)

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
        if node.kind not in _NODE_KINDS:
            raise ValueError(
                f"Węzeł '{node.name}': typ musi być jednym z: {', '.join(_NODE_KINDS)}."
            )
        if node.kind == "cisnieniowy":
            if node.pressure_pa is None or node.pressure_pa <= MIN_OUTLET_PRESSURE_PA:
                raise ValueError(
                    f"Węzeł ciśnieniowy '{node.name}' wymaga ciśnienia "
                    f"> {MIN_OUTLET_PRESSURE_PA / 1e5:.2f} bar(a)."
                )
        elif node.kind == "zrodlowy":
            if node.injection_nm3_per_h <= 0:
                raise ValueError(
                    f"Węzeł wtłoczenia '{node.name}' wymaga dodatniego strumienia "
                    "wtłaczania [Nm³/h]."
                )
            if node.composition is None:
                raise ValueError(
                    f"Węzeł wtłoczenia '{node.name}' wymaga zdefiniowanego składu "
                    "gazu (biometan, wodór itd.)."
                )
        else:  # odbiorowy
            if node.offtake_kg_per_s < 0 or node.offtake_nm3_per_h < 0:
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

    adjacency: dict[str, set[str]] = {n.name: set() for n in nodes}
    for pipe in pipes:
        adjacency[pipe.node_from].add(pipe.node_to)
        adjacency[pipe.node_to].add(pipe.node_from)
    reached: set[str] = set()
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
    """Opór K z uogólnionego równania przepływu (start/fallback kalibracji)."""
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
        return _analytic_resistance(
            composition, pipe, pressure_high_pa, temperature_k, mass_flow_abs
        )


def _mix_molar(
    contributions: list[tuple[GasComposition, dict[str, float], float]],
) -> tuple[GasComposition, dict[str, float]] | None:
    """Miesza dopływy molowo: [(skład, udziały źródeł, ṅ [kmol/s]), ...]."""
    total = sum(n for _, _, n in contributions)
    if total < _EPS_MOLAR:
        return None
    component_moles: dict[str, float] = {}
    source_moles: dict[str, float] = {}
    for comp, shares, moles in contributions:
        if moles < _EPS_MOLAR:
            continue
        for key, x in comp.fractions:
            component_moles[key] = component_moles.get(key, 0.0) + x * moles
        for source, share in shares.items():
            source_moles[source] = source_moles.get(source, 0.0) + share * moles
    mixed = GasComposition.from_fractions({k: v / total for k, v in component_moles.items()})
    shares = {s: v / total for s, v in source_moles.items()}
    return mixed, shares


def solve_network(
    composition: GasComposition,
    nodes: list[NetworkNode],
    pipes: list[NetworkPipe],
    temperature_k: float = 283.15,
) -> NetworkResult:
    """Rozwiązuje sieć: ciśnienia, przepływy, składy i strefy mieszania.

    Args:
        composition: skład DOMYŚLNY sieci — używany dla węzłów ciśnieniowych
            bez własnego składu,
        nodes: węzły (≥ 1 ciśnieniowy; wtłoczenia wymagają składu),
        pipes: odcinki (dozwolone pętle),
        temperature_k: temperatura gazu (stała w sieci).

    Raises:
        ValueError: błędna topologia/dane albo brak zbieżności solvera.
    """
    by_name, order = _validate_network(nodes, pipes)
    unknown = [name for name in order if by_name[name].kind != "cisnieniowy"]
    idx = {name: i for i, name in enumerate(unknown)}

    fixed_u = {
        name: float(by_name[name].pressure_pa) ** 2
        for name in order
        if by_name[name].kind == "cisnieniowy"
    }

    # składy źródeł (węzły ciśnieniowe i wtłoczenia)
    source_comp: dict[str, GasComposition] = {}
    for name in order:
        node = by_name[name]
        if node.kind == "cisnieniowy":
            source_comp[name] = node.composition or composition
        elif node.kind == "zrodlowy":
            source_comp[name] = node.composition  # walidacja gwarantuje nie-None

    rho_n_cache: dict[GasComposition, float] = {}

    def rho_n(comp: GasComposition) -> float:
        if comp not in rho_n_cache:
            rho_n_cache[comp] = compute_properties(comp, 101_325.0, 273.15).density_kg_per_m3
        return rho_n_cache[comp]

    # bieżące składy węzłów (start: skład domyślny; źródła — własny)
    node_comp: dict[str, GasComposition] = {
        name: source_comp.get(name, composition) for name in order
    }
    node_shares: dict[str, dict[str, float]] = {
        name: ({name: 1.0} if name in source_comp else {}) for name in order
    }

    def demand_kg(name: str) -> float:
        """Pobór netto węzła [kg/s] wg bieżącego składu (wtłoczenie ujemne)."""
        node = by_name[name]
        value = node.offtake_kg_per_s
        if node.offtake_nm3_per_h > 0:
            value += node.offtake_nm3_per_h * rho_n(node_comp[name]) / 3600.0
        if node.kind == "zrodlowy":
            value -= node.injection_nm3_per_h * rho_n(source_comp[name]) / 3600.0
        return value

    demands = {name: demand_kg(name) for name in unknown}
    total_scale = sum(abs(v) for v in demands.values())
    tol = 1e-6 * max(1.0, total_scale)

    u = np.full(len(unknown), 0.96 * min(fixed_u.values()), dtype=float)
    resistances = {
        pipe.name: _analytic_resistance(
            composition, pipe, max(fixed_u.values()) ** 0.5, temperature_k, 0.0
        )
        for pipe in pipes
    }
    pipe_comp: dict[str, GasComposition] = {pipe.name: composition for pipe in pipes}

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
            f[idx[name]] -= demands[name]
        return f

    def jacobian(u_vec: np.ndarray) -> np.ndarray:
        jac = np.zeros((len(unknown), len(unknown)))
        for pipe in pipes:
            du = u_of(pipe.node_from, u_vec) - u_of(pipe.node_to, u_vec)
            deriv = 1.0 / (2.0 * np.sqrt(resistances[pipe.name] * max(abs(du), _EPS_U)))
            i_from = idx.get(pipe.node_from)
            i_to = idx.get(pipe.node_to)
            if i_to is not None:
                if i_from is not None:
                    jac[i_to, i_from] += deriv
                jac[i_to, i_to] -= deriv
            if i_from is not None:
                if i_to is not None:
                    jac[i_from, i_to] += deriv
                jac[i_from, i_from] -= deriv
        return jac

    def track_compositions(u_vec: np.ndarray) -> list[str]:
        """Aktualizuje node_comp/node_shares mieszaniem molowym po DAG-u przepływu."""
        tracking_warnings: list[str] = []
        ordered = sorted(order, key=lambda n: -u_of(n, u_vec))
        for name in ordered:
            node = by_name[name]
            if node.kind == "cisnieniowy":
                continue  # granica systemu: skład zdefiniowany
            contributions: list[tuple[GasComposition, dict[str, float], float]] = []
            for pipe in pipes:
                m = pipe_flow(pipe, u_vec)
                upstream, downstream = (
                    (pipe.node_from, pipe.node_to) if m >= 0 else (pipe.node_to, pipe.node_from)
                )
                if downstream != name or abs(m) < 1e-12:
                    continue
                up_comp = node_comp[upstream]
                moles = abs(m) / (up_comp.molar_mass_kg_per_kmol / 1e3) / 1e3  # kmol/s
                contributions.append((up_comp, node_shares[upstream] or {upstream: 1.0}, moles))
            if node.kind == "zrodlowy":
                inj_comp = source_comp[name]
                inj_kg = node.injection_nm3_per_h * rho_n(inj_comp) / 3600.0
                moles = inj_kg / (inj_comp.molar_mass_kg_per_kmol / 1e3) / 1e3
                contributions.append((inj_comp, {name: 1.0}, moles))
            mixed = _mix_molar(contributions)
            if mixed is None:
                tracking_warnings.append(
                    f"Węzeł '{name}': brak dopływu (strefa zastoju) — przyjęto "
                    "skład domyślny sieci."
                )
                node_comp[name] = composition
                node_shares[name] = {}
            else:
                node_comp[name], node_shares[name] = mixed
        # składy odcinków = skład węzła górnego
        for pipe in pipes:
            m = pipe_flow(pipe, u_vec)
            upstream = pipe.node_from if m >= 0 else pipe.node_to
            pipe_comp[pipe.name] = node_comp[upstream]
        return tracking_warnings

    newton_total = 0
    outer_done = 0
    stable = False
    tracking_warnings: list[str] = []
    for outer in range(MAX_OUTER_ITER):
        outer_done = outer + 1
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
        if stable:
            break
        # --- śledzenie składów, aktualizacja poborów i oporów ---
        tracking_warnings = track_compositions(u)
        max_change = 0.0
        for name in unknown:
            new_demand = demand_kg(name)
            old = demands[name]
            scale = max(abs(old), abs(new_demand), 1e-9)
            max_change = max(max_change, abs(new_demand - old) / scale)
            demands[name] = new_demand
        for pipe in pipes:
            m_abs = abs(pipe_flow(pipe, u))
            p_high = max(u_of(pipe.node_from, u), u_of(pipe.node_to, u)) ** 0.5
            new_k = _calibrated_resistance(pipe_comp[pipe.name], pipe, p_high, temperature_k, m_abs)
            old_k = resistances[pipe.name]
            max_change = max(max_change, abs(new_k - old_k) / old_k)
            resistances[pipe.name] = new_k
        if max_change < 1e-3:
            stable = True  # domykający przebieg Newtona z finalnym stanem

    for name in unknown:
        p_node = u[idx[name]] ** 0.5
        if p_node < MIN_OUTLET_PRESSURE_PA:
            raise ValueError(
                f"Ciśnienie w węźle '{name}' spada do {p_node / 1e5:.2f} bar(a) "
                f"(poniżej {MIN_OUTLET_PRESSURE_PA / 1e5:.2f}) — pobory "
                "przekraczają przepustowość sieci."
            )

    pipe_results: list[PipeResult] = []
    for pipe in pipes:
        m = pipe_flow(pipe, u)
        p_from = u_of(pipe.node_from, u) ** 0.5
        p_to = u_of(pipe.node_to, u) ** 0.5
        comp = pipe_comp[pipe.name]
        props = compute_properties(comp, max(p_from, p_to), temperature_k)
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
                composition=comp,
            )
        )

    node_results: list[NodeResult] = []
    for name in order:
        node = by_name[name]
        pressure = u_of(name, u) ** 0.5
        if node.kind == "cisnieniowy":
            supply = sum(
                pr.mass_flow_kg_per_s if pr.pipe.node_from == name else 0.0 for pr in pipe_results
            ) + sum(
                -pr.mass_flow_kg_per_s if pr.pipe.node_to == name else 0.0 for pr in pipe_results
            )
            shares = {name: 1.0}
        else:
            supply = -demands[name]
            shares = node_shares[name]
        node_results.append(
            NodeResult(
                name=name,
                kind=node.kind,
                pressure_pa=pressure,
                supply_kg_per_s=supply,
                composition=node_comp[name],
                source_shares=shares,
            )
        )

    return NetworkResult(
        nodes=node_results,
        pipes=pipe_results,
        newton_iterations=newton_total,
        outer_iterations=outer_done,
        max_imbalance_kg_per_s=float(np.max(np.abs(residual(u)))) if unknown else 0.0,
        warnings=tracking_warnings,
    )
