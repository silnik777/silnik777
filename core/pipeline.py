"""Hydraulika gazociągów: spadek ciśnienia, przepustowość energetyczna — moduł M3.

Model marszowy przepływu izotermicznego (rura zakopana, T ≈ const):
rura dzielona na N segmentów; w każdym segmencie lokalna gęstość i lepkość
z M1 (HEOS/GERG-2008), prędkość z równania ciągłości v = ṁ/(ρ·A), spadek
ciśnienia Darcy-Weisbach:
    Δp = λ · (L_seg/D) · ρ·v²/2,
współczynnik tarcia λ z równania Colebrooka-White'a:
    1/√λ = −2·log10( k/(3,7·D) + 2,51/(Re·√λ) )
(Colebrook C.F., J. Inst. Civ. Eng. 11 (1939) 133; start iteracji z jawnego
przybliżenia Serghidesa, zbieżność < 1e-10). Zakres ważności: przepływ
turbulentny Re > 4000 (poniżej: λ = 64/Re, przepływ laminarny).

Model marszowy z lokalnymi właściwościami gazu rzeczywistego jest
dokładniejszy od wzorów praktycznych (Panhandle/Weymouth), które zakładają
stałe Z i ukrywają sprawność przepływu w stałych empirycznych.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

import CoolProp.CoolProp as CP

from core.calorific import calorific_values
from core.composition import GasComposition
from core.config import load_data_file
from core.gas_properties import (
    _abstract_state,
    _wilke_viscosity_pa_s,
    compute_properties,
)
from core.units import bar_to_pa

#: Minimalne ciśnienie wylotowe modelu (poniżej — przekroczona przepustowość).
MIN_OUTLET_PRESSURE_PA = bar_to_pa(1.1)


@dataclass(frozen=True)
class PipeMaterial:
    """Materiał rury z biblioteki ``data/pipelines.yaml``."""

    key: str
    name_pl: str
    roughness_typical_mm: float
    roughness_range_mm: tuple[float, float]
    source: str
    note: str | None = None


@cache
def pipe_materials() -> dict[str, PipeMaterial]:
    """Rejestr materiałów rur (chropowatości) z ``data/pipelines.yaml``."""
    raw = load_data_file("pipelines.yaml")["roughness_mm"]
    return {
        key: PipeMaterial(
            key=key,
            name_pl=item["name_pl"],
            roughness_typical_mm=float(item["typical"]),
            roughness_range_mm=tuple(item["range"]),
            source=item["source"],
            note=item.get("note"),
        )
        for key, item in raw.items()
    }


def friction_factor(reynolds: float, relative_roughness: float) -> float:
    """Współczynnik tarcia Darcy'ego λ.

    Re > 4000: Colebrook-White (iteracyjnie, start: przybliżenie Serghidesa,
    Serghides T.K., Chem. Eng. 91 (1984) 63–64); Re < 2300: λ = 64/Re;
    strefa przejściowa: interpolacja liniowa po Re (oznaczenie przybliżenia).

    Args:
        reynolds: liczba Reynoldsa [-], > 0,
        relative_roughness: k/D [-], ≥ 0.
    """
    if reynolds <= 0.0:
        raise ValueError(f"Liczba Reynoldsa musi być dodatnia (otrzymano {reynolds}).")
    if reynolds < 2300.0:
        return 64.0 / reynolds
    if reynolds < 4000.0:
        lam_2300 = 64.0 / 2300.0
        turb_4000 = _colebrook(4000.0, relative_roughness)
        frac = (reynolds - 2300.0) / (4000.0 - 2300.0)
        return lam_2300 + frac * (turb_4000 - lam_2300)
    return _colebrook(reynolds, relative_roughness)


def _colebrook(reynolds: float, relative_roughness: float) -> float:
    # Start: jawne przybliżenie Serghidesa (1984)
    def psi(x: float) -> float:
        return -2.0 * math.log10(relative_roughness / 3.7 + x / reynolds)

    a = psi(12.0)
    b = psi(2.51 * a)
    c = psi(2.51 * b)
    inv_sqrt = a - (b - a) ** 2 / (c - 2.0 * b + a)
    # Doiteracyjnie do pełnej zbieżności równania Colebrooka
    for _ in range(50):
        new = -2.0 * math.log10(relative_roughness / 3.7 + 2.51 * inv_sqrt / reynolds)
        if abs(new - inv_sqrt) < 1e-10:
            inv_sqrt = new
            break
        inv_sqrt = new
    return 1.0 / inv_sqrt**2


@dataclass(frozen=True)
class PipelineResult:
    """Wynik obliczenia hydraulicznego odcinka gazociągu."""

    composition: GasComposition
    diameter_m: float
    length_m: float
    roughness_m: float
    temperature_k: float
    mass_flow_kg_per_s: float
    pressure_profile_pa: list[float]  # N+1 punktów wzdłuż rury
    velocity_profile_m_per_s: list[float]
    reynolds_inlet: float
    friction_factor_inlet: float
    warnings: list[str]

    @property
    def pressure_in_pa(self) -> float:
        return self.pressure_profile_pa[0]

    @property
    def pressure_out_pa(self) -> float:
        return self.pressure_profile_pa[-1]

    @property
    def pressure_drop_pa(self) -> float:
        return self.pressure_in_pa - self.pressure_out_pa

    @property
    def max_velocity_m_per_s(self) -> float:
        return max(self.velocity_profile_m_per_s)

    def energy_flow_mw(self) -> float:
        """Przepustowość energetyczna: ṁ · Hi [MW] (wartość opałowa, M1)."""
        hi_mj_per_kg = calorific_values(self.composition).hi_mj_per_kg
        return self.mass_flow_kg_per_s * hi_mj_per_kg

    def volume_flow_nm3_per_h(self) -> float:
        """Strumień objętości w warunkach normalnych [Nm³/h]."""
        rho_n = compute_properties(self.composition, 101_325.0, 273.15).density_kg_per_m3
        return self.mass_flow_kg_per_s / rho_n * 3600.0


def pressure_profile(
    composition: GasComposition,
    diameter_m: float,
    length_m: float,
    roughness_m: float,
    mass_flow_kg_per_s: float,
    pressure_in_pa: float,
    temperature_k: float,
    n_segments: int | None = None,
    inlet_check: bool = True,
) -> PipelineResult:
    """Profil ciśnienia wzdłuż gazociągu (model marszowy, przepływ izotermiczny).

    Wydajność: pełna analiza stabilności faz (kosztowna dla mieszanin)
    wykonywana jest raz, na wlocie; wzdłuż rury flash z wymuszoną fazą
    gazową — fizycznie uzasadnione, bo ciśnienie wzdłuż trasy tylko spada,
    a T = const (oddalamy się od obszaru dwufazowego).

    Args:
        composition: skład gazu (M1),
        diameter_m: średnica wewnętrzna rury [m], > 0,
        length_m: długość odcinka [m], > 0,
        roughness_m: chropowatość bezwzględna k [m] (biblioteka:
            ``pipe_materials()``),
        mass_flow_kg_per_s: strumień masy [kg/s], > 0,
        pressure_in_pa: ciśnienie na wlocie [Pa] (bezwzględne),
        temperature_k: temperatura gazu (stała wzdłuż rury) [K],
        n_segments: liczba segmentów (domyślnie z ``data/pipelines.yaml``),
        inlet_check: pełna kontrola stabilności faz na wlocie (wyłączana
            wewnętrznie przez ``max_mass_flow_kg_per_s``, który wykonuje
            ją raz przed bisekcją).

    Raises:
        ValueError: parametry niefizyczne albo spadek ciśnienia poniżej
            minimalnego ciśnienia wylotowego (przekroczona przepustowość).
    """
    for value, name in (
        (diameter_m, "Średnica"),
        (length_m, "Długość"),
        (mass_flow_kg_per_s, "Strumień masy"),
        (pressure_in_pa, "Ciśnienie wlotowe"),
    ):
        if value <= 0.0:
            raise ValueError(f"{name} musi być dodatnia/dodatni (otrzymano {value!r}).")
    if roughness_m < 0.0:
        raise ValueError("Chropowatość nie może być ujemna.")

    cfg = load_data_file("pipelines.yaml")["flow_model"]
    if n_segments is None:
        n_segments = int(cfg["default_segments"])

    area = math.pi * diameter_m**2 / 4.0
    seg_len = length_m / n_segments
    rel_rough = roughness_m / diameter_m

    pressures = [pressure_in_pa]
    velocities: list[float] = []
    warnings: list[str] = []
    re_inlet = 0.0
    lambda_inlet = 0.0

    if inlet_check:
        # Pełna analiza stabilności faz — raz, na wlocie (najwyższe p na trasie).
        inlet_props = compute_properties(composition, pressure_in_pa, temperature_k)
        warnings.extend(inlet_props.warnings)

    state = _abstract_state(composition)
    state.specify_phase(CP.iphase_gas)
    wilke_mu: float | None = None
    last_mu: float | None = None

    p = pressure_in_pa
    try:
        for i in range(n_segments):
            state.update(CP.PT_INPUTS, p, temperature_k)
            rho = state.rhomass()
            velocity = mass_flow_kg_per_s / (rho * area)
            if wilke_mu is None:
                try:
                    mu = state.viscosity()
                except Exception:
                    mu = float("nan")
                if not math.isfinite(mu):
                    # Model ECS lepkości mieszanin potrafi punktowo zwrócić NaN
                    # (bez wyjątku) — bierzemy wartość z sąsiedniego segmentu
                    # (zmiana < 1%/segment), a bez niej regułę Wilke'a.
                    if last_mu is not None:
                        mu = last_mu
                    else:
                        wilke_mu = _wilke_viscosity_pa_s(composition, temperature_k)
                        mu = wilke_mu
                        warnings.append(
                            "Lepkość mieszaniny z reguły Wilke'a (1950) przy ciśnieniu "
                            "atmosferycznym — przybliżenie niskociśnieniowe."
                        )
                last_mu = mu
            else:
                mu = wilke_mu
            reynolds = rho * velocity * diameter_m / mu
            lam = friction_factor(reynolds, rel_rough)
            if i == 0:
                re_inlet, lambda_inlet = reynolds, lam
            dp = lam * (seg_len / diameter_m) * rho * velocity**2 / 2.0
            p -= dp
            if p < MIN_OUTLET_PRESSURE_PA:
                raise ValueError(
                    f"Ciśnienie spada poniżej {MIN_OUTLET_PRESSURE_PA / 1e5:.2f} bar po "
                    f"{(i + 1) * seg_len / 1000:.1f} km — przepustowość rury przekroczona "
                    f"dla strumienia {mass_flow_kg_per_s:.3g} kg/s."
                )
            velocities.append(velocity)
            pressures.append(p)

        if velocities:
            state.update(CP.PT_INPUTS, pressures[-1], temperature_k)
            if max(velocities) > 0.3 * state.speed_sound():
                warnings.append(
                    "Prędkość przekracza 0,3 prędkości dźwięku — model izotermiczny "
                    "przestaje być dokładny (przepływ ściśliwy szybkozmienny)."
                )
    finally:
        state.unspecify_phase()

    return PipelineResult(
        composition=composition,
        diameter_m=diameter_m,
        length_m=length_m,
        roughness_m=roughness_m,
        temperature_k=temperature_k,
        mass_flow_kg_per_s=mass_flow_kg_per_s,
        pressure_profile_pa=pressures,
        velocity_profile_m_per_s=velocities,
        reynolds_inlet=re_inlet,
        friction_factor_inlet=lambda_inlet,
        warnings=warnings,
    )


def max_mass_flow_kg_per_s(
    composition: GasComposition,
    diameter_m: float,
    length_m: float,
    roughness_m: float,
    pressure_in_pa: float,
    pressure_out_min_pa: float,
    temperature_k: float,
    iterations: int = 30,
) -> float:
    """Maksymalny strumień masy, przy którym p_wylot ≥ p_min (bisekcja).

    Zbieżność: przedział [0, ṁ_hi] zawężany ``iterations`` razy (30 iteracji
    ⇒ dokładność względna ~1e-9 · ṁ_hi). Bisekcja używa siatki 25 segmentów
    i pomija powtarzaną kontrolę stabilności faz (wykonana raz na wlocie);
    różnica wyniku względem pełnej siatki < 0,1% (testy).
    """
    if pressure_out_min_pa >= pressure_in_pa:
        raise ValueError("Ciśnienie wylotowe musi być niższe od wlotowego.")

    def outlet_pressure(m_flow: float) -> float | None:
        try:
            return pressure_profile(
                composition,
                diameter_m,
                length_m,
                roughness_m,
                m_flow,
                pressure_in_pa,
                temperature_k,
                n_segments=25,
                inlet_check=False,
            ).pressure_out_pa
        except ValueError:
            return None

    # Górna granica: prędkość bliska dźwiękowej na wlocie
    props = compute_properties(composition, pressure_in_pa, temperature_k)
    area = math.pi * diameter_m**2 / 4.0
    hi = 0.3 * props.speed_of_sound_m_per_s * props.density_kg_per_m3 * area
    lo = 0.0
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        p_out = outlet_pressure(mid)
        if p_out is not None and p_out >= pressure_out_min_pa:
            lo = mid
        else:
            hi = mid
    return lo


def min_diameter_m(
    composition: GasComposition,
    length_m: float,
    roughness_m: float,
    mass_flow_kg_per_s: float,
    pressure_in_pa: float,
    pressure_out_min_pa: float,
    temperature_k: float,
    iterations: int = 40,
    d_hi_m: float = 1.5,
) -> float:
    """Minimalna średnica wewnętrzna, przy której p_wylot ≥ p_min (bisekcja).

    Dobór rury dla zadanego przepływu i widełek ciśnień: większa średnica =
    mniejszy spadek ciśnienia, więc funkcja p_wylot(D) jest monotonicznie
    rosnąca — bisekcja w przedziale [d_lo, d_hi] do zbieżności.

    Raises:
        ValueError: gdy nawet ``d_hi_m`` nie wystarcza (zwiększ średnicę
            maksymalną albo widełki ciśnień) lub dane są niefizyczne.
    """
    if pressure_out_min_pa >= pressure_in_pa:
        raise ValueError("Ciśnienie wylotowe musi być niższe od wlotowego.")
    if mass_flow_kg_per_s <= 0:
        raise ValueError("Strumień masy musi być dodatni.")

    def outlet_pressure(d_m: float) -> float | None:
        try:
            return pressure_profile(
                composition,
                d_m,
                length_m,
                roughness_m,
                mass_flow_kg_per_s,
                pressure_in_pa,
                temperature_k,
                n_segments=25,
                inlet_check=False,
            ).pressure_out_pa
        except ValueError:
            return None

    p_hi = outlet_pressure(d_hi_m)
    if p_hi is None or p_hi < pressure_out_min_pa:
        raise ValueError(
            f"Nawet średnica {d_hi_m * 1e3:.0f} mm nie utrzyma ciśnienia "
            f"{pressure_out_min_pa / 1e5:.1f} bar przy przepływie "
            f"{mass_flow_kg_per_s:.3g} kg/s — zwiększ średnicę albo zmniejsz przepływ."
        )
    lo, hi = 0.01, d_hi_m
    for _ in range(iterations):
        mid = (lo + hi) / 2.0
        p_out = outlet_pressure(mid)
        if p_out is not None and p_out >= pressure_out_min_pa:
            hi = mid
        else:
            lo = mid
    return hi
