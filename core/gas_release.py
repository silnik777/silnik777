"""Straty gazu z niekontrolowanego wypływu (awaria/rozszczelnienie) — moduł strat.

Model wypływu przez otwór (kryza) z gazociągu pod ciśnieniem p₁ do otoczenia p₀:

* **Wypływ krytyczny (zablokowany, sonic):** gdy p₁/p₀ ≥ r_kryt =
  ((k+1)/2)^(k/(k−1)) — w otworze osiągana jest prędkość dźwięku; natężenie
  zależy tylko od stanu górnego (nie od p₀):
      ṁ = C_d·A·p₁·√[ k/(Z·R_s·T₁) · (2/(k+1))^((k+1)/(k−1)) ],
* **wypływ podkrytyczny (subsonic):** p₁/p₀ < r_kryt:
      ṁ = C_d·A·p₁·√[ 2k/((k−1)·Z·R_s·T₁) · (p₀/p₁)^(2/k)·(1−(p₀/p₁)^((k−1)/k)) ],

gdzie k — rzeczywisty wykładnik izentropy (κ z M1), Z — ściśliwość (M1),
R_s = R/M, A = πd²/4, C_d — współczynnik wypływu.

**Blowdown:** dla odcinka o objętości V opróżnianie liczone izotermicznie
(rura zakopana, T≈const): masa w rurze m(p)=ρ(p,T)·V; całkowanie
dm/dt = −ṁ(p) po krokach ciśnienia daje czas i profil.

**Strefa zagrożenia (opcjonalnie):** przesiewowy zasięg strumienia do stężenia
LEL — osiowy zanik stężenia w swobodnym strumieniu turbulentnym
(rząd wielkości, do weryfikacji modelem dyspersji).

Źródła: Perry's Chemical Engineers' Handbook (wypływ przez kryzę);
API 521 (blowdown); Birch et al. / Chen–Rodi (zanik osiowy strumienia).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from core.composition import GasComposition
from core.flammability import flammability_limits
from core.gas_properties import compute_properties
from core.units import NORMAL_0C, R_UNIVERSAL_J_PER_MOL_K

_R_UNIVERSAL_J_PER_KMOL_K = R_UNIVERSAL_J_PER_MOL_K * 1.0e3
_P_ATM_PA = 101_325.0


def critical_pressure_ratio(kappa: float) -> float:
    """Krytyczny stosunek ciśnień r_kryt = ((k+1)/2)^(k/(k−1))."""
    return ((kappa + 1.0) / 2.0) ** (kappa / (kappa - 1.0))


@dataclass(frozen=True)
class ReleaseResult:
    """Chwilowy wypływ gazu przez otwór (przy zadanym stanie górnym)."""

    choked: bool  # czy wypływ krytyczny (sonic)
    critical_pressure_ratio: float
    pressure_ratio: float  # p₁/p₀
    mass_flow_kg_per_s: float
    velocity_at_hole_m_per_s: float  # prędkość w otworze (sonic przy krytycznym)
    hole_area_m2: float
    density_upstream_kg_per_m3: float
    density_normal_kg_per_m3: float

    @property
    def volumetric_flow_upstream_m3_per_s(self) -> float:
        """Strumień objętości w warunkach górnych (p₁, T₁) [m³/s]."""
        return self.mass_flow_kg_per_s / self.density_upstream_kg_per_m3

    @property
    def volumetric_flow_nm3_per_h(self) -> float:
        """Strumień objętości w warunkach normalnych (0 °C, 101,325 kPa) [Nm³/h]."""
        return self.mass_flow_kg_per_s / self.density_normal_kg_per_m3 * 3600.0

    @property
    def volumetric_flow_nm3_per_min(self) -> float:
        return self.volumetric_flow_nm3_per_h / 60.0


def gas_release_rate(
    composition: GasComposition,
    pressure_upstream_pa: float,
    temperature_upstream_k: float,
    hole_diameter_m: float,
    discharge_coefficient: float = 0.62,
    pressure_ambient_pa: float = _P_ATM_PA,
) -> ReleaseResult:
    """Chwilowe natężenie wypływu gazu przez otwór (kryza).

    Args:
        composition: skład gazu (M1),
        pressure_upstream_pa, temperature_upstream_k: stan w gazociągu (górny),
        hole_diameter_m: średnica otworu/rozszczelnienia [m],
        discharge_coefficient: C_d (kryza ostrokrawędziowa ~0,6; pełny
            przekrój/gładki otwór → bliżej 1,0),
        pressure_ambient_pa: ciśnienie otoczenia (domyślnie atmosferyczne).

    Returns:
        ``ReleaseResult`` — reżim, natężenie masowe/objętościowe, prędkość.
    """
    if hole_diameter_m <= 0.0:
        raise ValueError("Średnica otworu musi być dodatnia.")
    if not 0.0 < discharge_coefficient <= 1.0:
        raise ValueError("Współczynnik wypływu C_d musi być w (0, 1].")
    if pressure_upstream_pa <= pressure_ambient_pa:
        raise ValueError("Ciśnienie w gazociągu musi przekraczać ciśnienie otoczenia.")

    props = compute_properties(composition, pressure_upstream_pa, temperature_upstream_k)
    k = props.isentropic_exponent
    z = props.z_factor
    r_s = _R_UNIVERSAL_J_PER_KMOL_K / props.molar_mass_kg_per_kmol  # R/M [J/(kg·K)]
    area = math.pi * hole_diameter_m**2 / 4.0
    ratio = pressure_upstream_pa / pressure_ambient_pa
    r_crit = critical_pressure_ratio(k)
    choked = ratio >= r_crit

    if choked:
        flux = math.sqrt(
            k / (z * r_s * temperature_upstream_k) * (2.0 / (k + 1.0)) ** ((k + 1.0) / (k - 1.0))
        )
        # prędkość w otworze = prędkość dźwięku w gardzieli (T* = T₁·2/(k+1))
        t_throat = temperature_upstream_k * 2.0 / (k + 1.0)
        velocity = math.sqrt(k * z * r_s * t_throat)
    else:
        pr = pressure_ambient_pa / pressure_upstream_pa
        flux = math.sqrt(
            2.0
            * k
            / ((k - 1.0) * z * r_s * temperature_upstream_k)
            * pr ** (2.0 / k)
            * (1.0 - pr ** ((k - 1.0) / k))
        )
        # prędkość wylotowa z bilansu izentropowego
        velocity = math.sqrt(
            2.0 * k / (k - 1.0) * z * r_s * temperature_upstream_k * (1.0 - pr ** ((k - 1.0) / k))
        )

    mass_flow = discharge_coefficient * area * pressure_upstream_pa * flux
    rho_n = compute_properties(
        composition, NORMAL_0C.pressure_pa, NORMAL_0C.temperature_k
    ).density_kg_per_m3
    return ReleaseResult(
        choked=choked,
        critical_pressure_ratio=r_crit,
        pressure_ratio=ratio,
        mass_flow_kg_per_s=mass_flow,
        velocity_at_hole_m_per_s=velocity,
        hole_area_m2=area,
        density_upstream_kg_per_m3=props.density_kg_per_m3,
        density_normal_kg_per_m3=rho_n,
    )


@dataclass(frozen=True)
class BlowdownResult:
    """Opróżnianie odcinka gazociągu przez otwór (model izotermiczny)."""

    total_lost_kg: float
    total_lost_nm3: float
    blowdown_time_s: float
    pipe_volume_m3: float
    times_s: list[float] = field(default_factory=list)
    pressures_pa: list[float] = field(default_factory=list)
    mass_flow_kg_per_s: list[float] = field(default_factory=list)

    @property
    def blowdown_time_min(self) -> float:
        return self.blowdown_time_s / 60.0


def blowdown(
    composition: GasComposition,
    pipe_volume_m3: float,
    pressure_initial_pa: float,
    temperature_k: float,
    hole_diameter_m: float,
    discharge_coefficient: float = 0.62,
    pressure_ambient_pa: float = _P_ATM_PA,
    n_steps: int = 40,
) -> BlowdownResult:
    """Opróżnianie odcinka o objętości V przez otwór — czas i profil ciśnienia.

    Model izotermiczny (rura zakopana, T≈const): masa m(p)=ρ(p,T)·V; w każdym
    kroku ciśnienia liczone chwilowe natężenie ṁ(p) i przyrost czasu
    Δt = Δm/ṁ_śr. Całkowanie od p_początkowego do p_otoczenia.

    Returns:
        ``BlowdownResult`` — całkowita strata (kg, Nm³), czas i profile.
    """
    if pipe_volume_m3 <= 0.0:
        raise ValueError("Objętość odcinka musi być dodatnia.")
    if pressure_initial_pa <= pressure_ambient_pa:
        raise ValueError("Ciśnienie początkowe musi przekraczać ciśnienie otoczenia.")

    rho_n = compute_properties(
        composition, NORMAL_0C.pressure_pa, NORMAL_0C.temperature_k
    ).density_kg_per_m3
    dp = (pressure_initial_pa - pressure_ambient_pa) / n_steps
    pressures = [pressure_initial_pa - i * dp for i in range(n_steps + 1)]
    masses = [
        compute_properties(composition, p, temperature_k).density_kg_per_m3 * pipe_volume_m3
        for p in pressures
    ]

    times = [0.0]
    rates = []
    t = 0.0
    for i in range(n_steps):
        p_mid = 0.5 * (pressures[i] + pressures[i + 1])
        rate = gas_release_rate(
            composition,
            p_mid,
            temperature_k,
            hole_diameter_m,
            discharge_coefficient,
            pressure_ambient_pa,
        ).mass_flow_kg_per_s
        rates.append(rate)
        dm = masses[i] - masses[i + 1]
        t += dm / rate
        times.append(t)

    total_lost_kg = masses[0] - masses[-1]
    return BlowdownResult(
        total_lost_kg=total_lost_kg,
        total_lost_nm3=total_lost_kg / rho_n,
        blowdown_time_s=t,
        pipe_volume_m3=pipe_volume_m3,
        times_s=times,
        pressures_pa=pressures,
        mass_flow_kg_per_s=rates,
    )


@dataclass(frozen=True)
class HazardZoneResult:
    """Przesiewowy zasięg strefy palnej strumienia (do stężenia LEL)."""

    distance_to_lel_m: float
    lel_vol_pct: float
    uel_vol_pct: float
    note: str


def flammable_jet_extent(
    composition: GasComposition,
    release: ReleaseResult,
    axial_decay_constant: float = 5.8,
) -> HazardZoneResult | None:
    """Przesiewowy zasięg osiowy strumienia do dolnej granicy palności (LEL).

    Osiowy zanik stężenia w swobodnym strumieniu turbulentnym:
        C_osi(x)/C_źródła ≈ K·(d_eff/x)·√(ρ_gaz/ρ_powietrze),
    stąd odległość do LEL (C_źródła = 100% obj.):
        x_LEL = K·d_eff·√(ρ_gaz/ρ_powietrze)·(100/LEL[%]).
    d_eff — średnica równoważna strumienia (dla wypływu krytycznego
    przekrój rozprężony), przyjęta z natężenia i prędkości w otworze.

    Model rzędu wielkości (screening) — NIE zastępuje analizy dyspersji.

    Returns:
        ``HazardZoneResult`` albo None dla gazu niepalnego.
    """
    flam = flammability_limits(composition)
    if flam is None:
        return None
    rho_air = 1.225  # kg/m³ (powietrze, ~15 °C)
    # średnica równoważna z natężenia masowego przy prędkości w otworze
    rho_hole = release.mass_flow_kg_per_s / (
        release.hole_area_m2 * release.velocity_at_hole_m_per_s
    )
    d_eff = math.sqrt(
        4.0 * release.mass_flow_kg_per_s / (math.pi * rho_hole * release.velocity_at_hole_m_per_s)
    )
    x_lel = (
        axial_decay_constant
        * d_eff
        * math.sqrt(release.density_upstream_kg_per_m3 / rho_air)
        * (100.0 / flam.lel_vol_pct)
    )
    return HazardZoneResult(
        distance_to_lel_m=x_lel,
        lel_vol_pct=flam.lel_vol_pct,
        uel_vol_pct=flam.uel_vol_pct,
        note=(
            "Oszacowanie rzędu wielkości (osiowy zanik strumienia swobodnego). "
            "Rzeczywisty zasięg zależy od wiatru, kierunku wypływu i przeszkód — "
            "do weryfikacji modelem dyspersji."
        ),
    )
