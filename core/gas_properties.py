"""Właściwości termofizyczne gazów i mieszanin przy zadanych (p, T) — moduł M1.

Model: CoolProp, backend HEOS — wielopłynowe równania stanu wysokiej
dokładności z modelem mieszanin Kunz–Wagner (GERG-2008):
    Kunz O., Wagner W., "The GERG-2008 Wide-Range Equation of State for
    Natural Gases and Other Mixtures", J. Chem. Eng. Data 57 (2012) 3032-3091.

Zakres domyślnej walidacji narzędzia: p ≤ 10 MPa, T = −20…60 °C
(poza nim obliczenie jest wykonywane, ale wynik dostaje ostrzeżenie;
GERG-2008 formalnie obejmuje 90–450 K i do 35 MPa).

Lepkość: model CoolProp (korelacje referencyjne + ECS dla mieszanin);
gdy niedostępna dla danej mieszaniny — reguła Wilke'a (1950) na lepkościach
czystych składników przy p = 101,325 kPa (przybliżenie niskociśnieniowe,
oznaczane w wyniku polem ``viscosity_method`` i ostrzeżeniem).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import CoolProp.CoolProp as CP

from core.composition import GasComposition, components_registry
from core.units import mpa_to_pa

#: Domyślny zakres walidacji (uzgodniony z użytkownikiem; magazynowanie > 10 MPa
#: jest dopuszczalne — generuje tylko ostrzeżenie).
DEFAULT_P_MAX_PA: float = mpa_to_pa(10.0)
DEFAULT_T_MIN_K: float = 253.15  # −20 °C
DEFAULT_T_MAX_K: float = 333.15  # +60 °C


@dataclass(frozen=True)
class GasProperties:
    """Komplet właściwości w punkcie (p, T) z metadanymi metodyki."""

    pressure_pa: float
    temperature_k: float
    molar_mass_kg_per_kmol: float
    z_factor: float  # współczynnik ściśliwości Z [-]
    density_kg_per_m3: float
    molar_density_kmol_per_m3: float
    cp_j_per_kg_k: float
    cv_j_per_kg_k: float
    cp_over_cv: float  # γ = cp/cv [-]
    isentropic_exponent: float  # κ = w²·ρ/p (rzeczywisty wykładnik izentropy) [-]
    joule_thomson_k_per_pa: float
    speed_of_sound_m_per_s: float
    viscosity_pa_s: float | None
    viscosity_method: str  # "CoolProp" | "Wilke (niskociśnieniowa)" | "niedostępna"
    warnings: list[str] = field(default_factory=list)

    @property
    def joule_thomson_k_per_bar(self) -> float:
        """Współczynnik Joule'a-Thomsona w jednostce praktycznej [K/bar]."""
        return self.joule_thomson_k_per_pa * 1.0e5


def _abstract_state(composition: GasComposition) -> CP.AbstractState:
    """Buduje stan CoolProp HEOS dla składu (czysty płyn lub mieszanina)."""
    registry = components_registry()
    names = [registry[key].coolprop_name for key, _ in composition.fractions]
    state = CP.AbstractState("HEOS", "&".join(names))
    if len(names) > 1:
        state.set_mole_fractions([x for _, x in composition.fractions])
    return state


def _wilke_viscosity_pa_s(composition: GasComposition, temperature_k: float) -> float:
    """Lepkość mieszaniny regułą Wilke'a (1950) — przybliżenie niskociśnieniowe.

    Wzór: μ_mix = Σ_i x_i·μ_i / Σ_j x_j·φ_ij,
    φ_ij = [1 + (μ_i/μ_j)^½·(M_j/M_i)^¼]² / [8·(1 + M_i/M_j)]^½.
    Źródło: Wilke C.R., J. Chem. Phys. 18 (1950) 517; zakres ważności:
    gaz rozrzedzony (p bliskie atmosferycznemu), błąd typowo < 2–4%.
    """
    registry = components_registry()
    keys = [k for k, _ in composition.fractions]
    x = [v for _, v in composition.fractions]
    mu = [
        CP.PropsSI("V", "T", temperature_k, "P", 101_325.0, registry[k].coolprop_name) for k in keys
    ]
    m = [registry[k].molar_mass_kg_per_kmol for k in keys]
    result = 0.0
    for i in range(len(keys)):
        denom = 0.0
        for j in range(len(keys)):
            phi = (1.0 + math.sqrt(mu[i] / mu[j]) * (m[j] / m[i]) ** 0.25) ** 2 / math.sqrt(
                8.0 * (1.0 + m[i] / m[j])
            )
            denom += x[j] * phi
        result += x[i] * mu[i] / denom
    return result


def update_state_pt(state: CP.AbstractState, pressure_pa: float, temperature_k: float) -> bool:
    """Flash (p, T) z obejściem zawodnej analizy stabilności faz CoolProp.

    Dla mieszanin bogatych w H2 analiza stabilności faz CoolProp potrafi
    zawieść nawet w jednoznacznej fazie gazowej ("One stationary point",
    "No density solutions") — wtedy wymuszamy fazę gazową i powtarzamy flash.

    Returns:
        True, jeśli konieczne było wymuszenie fazy gazowej (wynik bez
        kontroli kondensacji — wymaga ostrzeżenia w warstwie wywołującej).

    Raises:
        ValueError: gdy flash zawodzi także po wymuszeniu fazy (komunikat PL).
    """
    try:
        state.update(CP.PT_INPUTS, pressure_pa, temperature_k)
        return False
    except Exception:
        state.specify_phase(CP.iphase_gas)
        try:
            state.update(CP.PT_INPUTS, pressure_pa, temperature_k)
            return True
        except Exception as exc:  # CoolProp rzuca ValueError z komunikatem EN
            raise ValueError(
                "Nie udało się obliczyć stanu termodynamicznego dla zadanych (p, T) — "
                "punkt może leżeć w obszarze dwufazowym lub poza zakresem równania "
                f"stanu. Szczegóły CoolProp: {exc}"
            ) from exc


def _range_warnings(pressure_pa: float, temperature_k: float) -> list[str]:
    warnings: list[str] = []
    if pressure_pa > DEFAULT_P_MAX_PA:
        warnings.append(
            f"Ciśnienie {pressure_pa / 1e6:.2f} MPa przekracza domyślny zakres walidacji "
            "narzędzia (10 MPa) — dopuszczalne np. dla magazynowania; GERG-2008 "
            "obowiązuje do 35 MPa."
        )
    if not DEFAULT_T_MIN_K <= temperature_k <= DEFAULT_T_MAX_K:
        warnings.append(
            f"Temperatura {temperature_k - 273.15:.1f} °C jest poza domyślnym zakresem "
            "walidacji narzędzia (−20…60 °C)."
        )
    return warnings


def compute_properties(
    composition: GasComposition,
    pressure_pa: float,
    temperature_k: float,
) -> GasProperties:
    """Oblicza właściwości termofizyczne mieszaniny w punkcie (p, T).

    Wielkości i wzory:
        * Z = p·v_m/(R·T) — z równania stanu (HEOS/GERG-2008),
        * κ (rzeczywisty wykładnik izentropy) = w²·ρ/p, gdzie w — prędkość
          dźwięku; dla gazu doskonałego κ = cp/cv,
        * μ_JT = (∂T/∂p)_h — współczynnik Joule'a-Thomsona.

    Args:
        composition: skład molowy gazu,
        pressure_pa: ciśnienie bezwzględne [Pa], zakres > 0,
        temperature_k: temperatura [K], zakres > 0.

    Returns:
        ``GasProperties`` — wartości SI + lista ostrzeżeń (np. punkt pracy
        poza domyślnym zakresem walidacji narzędzia).

    Raises:
        ValueError: dane poza zakresem fizycznym lub stan dwufazowy /
            poza zakresem równania stanu (komunikat po polsku).
    """
    if pressure_pa <= 0.0:
        raise ValueError(f"Ciśnienie musi być dodatnie (otrzymano {pressure_pa} Pa).")
    if temperature_k <= 0.0:
        raise ValueError(f"Temperatura musi być dodatnia (otrzymano {temperature_k} K).")

    state = _abstract_state(composition)
    warnings = _range_warnings(pressure_pa, temperature_k)
    phase_forced = update_state_pt(state, pressure_pa, temperature_k)

    if phase_forced:
        warnings.append(
            "Analiza stabilności faz CoolProp zawiodła dla tej mieszaniny — "
            "przyjęto fazę gazową bez kontroli kondensacji (zweryfikuj punkt rosy)."
        )
    elif state.phase() not in (
        CP.iphase_gas,
        CP.iphase_supercritical_gas,
        CP.iphase_supercritical,
    ):
        warnings.append(
            "Uwaga: punkt pracy nie jest jednoznacznie w fazie gazowej "
            "(możliwa kondensacja cięższych składników)."
        )

    density = state.rhomass()
    speed = state.speed_sound()
    viscosity: float | None
    method = "CoolProp"
    try:
        viscosity = state.viscosity()
    except Exception:
        try:
            viscosity = _wilke_viscosity_pa_s(composition, temperature_k)
            method = "Wilke (niskociśnieniowa)"
            warnings.append(
                "Lepkość mieszaniny niedostępna w CoolProp — zastosowano regułę "
                "Wilke'a (1950) przy p = 101,325 kPa (przybliżenie niskociśnieniowe)."
            )
        except Exception:
            viscosity = None
            method = "niedostępna"
            warnings.append("Lepkość niedostępna dla tej mieszaniny.")

    return GasProperties(
        pressure_pa=pressure_pa,
        temperature_k=temperature_k,
        molar_mass_kg_per_kmol=state.molar_mass() * 1.0e3,
        z_factor=state.compressibility_factor(),
        density_kg_per_m3=density,
        molar_density_kmol_per_m3=state.rhomolar() / 1.0e3,
        cp_j_per_kg_k=state.cpmass(),
        cv_j_per_kg_k=state.cvmass(),
        cp_over_cv=state.cpmass() / state.cvmass(),
        isentropic_exponent=speed**2 * density / pressure_pa,
        joule_thomson_k_per_pa=state.first_partial_deriv(CP.iT, CP.iP, CP.iHmass),
        speed_of_sound_m_per_s=speed,
        viscosity_pa_s=viscosity,
        viscosity_method=method,
        warnings=warnings,
    )
