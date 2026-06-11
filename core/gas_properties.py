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
from functools import cache

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


@cache
def _abstract_state(composition: GasComposition) -> CP.AbstractState:
    """Stan CoolProp HEOS dla składu (cache per skład — budowa jest kosztowna).

    Uwaga: obiekt jest współdzielony i mutowalny — każdy użytkownik musi
    wykonać własny flash (``update_state_pt``/``state.update``) przed odczytem.
    Nie nadaje się do użycia współbieżnego z wielu wątków.
    """
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
    state.unspecify_phase()  # stan może być współdzielony (cache) — reset
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


def _solve_temperature_gas(
    state: CP.AbstractState,
    pressure_pa: float,
    target_value: float,
    prop: str,
    t_lo_k: float = 200.0,
    t_hi_k: float = 800.0,
    tol_k: float = 1e-4,
) -> None:
    """Rozwiązuje T tak, by h(p,T) lub s(p,T) = wartość zadana (faza gazowa).

    Bisekcja na szybkich flashach (p,T) z wymuszoną fazą gazową — entalpia
    i entropia są monotonicznie rosnące po T przy stałym p (cp > 0), więc
    pierwiastek jest jednoznaczny. Stosowane dla mieszanin, dla których
    natywne flashe h-p / p-s CoolProp wymagają budowy otoczki fazowej.
    Dolny kraniec przedziału jest podnoszony, jeśli flash gazowy nie ma tam
    rozwiązania (obszar gęstej fazy).
    """
    getter = CP.AbstractState.hmass if prop == "h" else CP.AbstractState.smass
    state.specify_phase(CP.iphase_gas)

    def value_at(t_k: float) -> float:
        state.update(CP.PT_INPUTS, pressure_pa, t_k)
        return getter(state)

    v_lo: float | None = None
    for _ in range(25):
        try:
            v_lo = value_at(t_lo_k)
            break
        except Exception:
            t_lo_k += 15.0
    if v_lo is None:
        raise ValueError("Nie znaleziono dolnego krańca przedziału temperatur (flash gazowy).")
    # Cel poniżej dolnego krańca (głęboka ekspansja): schodź w dół, dopóki
    # flash gazowy ma rozwiązanie (nad linią nasycenia).
    while target_value < v_lo and t_lo_k > 95.0:
        try:
            v_lo = value_at(t_lo_k - 10.0)
            t_lo_k -= 10.0
        except Exception:
            break
    try:
        v_hi = value_at(t_hi_k)
    except Exception:
        t_hi_k = 600.0
        v_hi = value_at(t_hi_k)

    if not v_lo <= target_value <= v_hi:
        raise ValueError(
            f"Wartość docelowa ({prop}) poza przedziałem temperatur "
            f"{t_lo_k:.0f}–{t_hi_k:.0f} K przy p = {pressure_pa / 1e5:.2f} bar "
            "(możliwa kondensacja przy głębokiej ekspansji)."
        )
    while t_hi_k - t_lo_k > tol_k:
        t_mid = (t_lo_k + t_hi_k) / 2.0
        if value_at(t_mid) < target_value:
            t_lo_k = t_mid
        else:
            t_hi_k = t_mid
    value_at(t_hi_k)  # stan końcowy


def _flash_native_gas_first(state: CP.AbstractState, pair: int, v1: float, v2: float) -> None:
    """Natywny flash CoolProp: najpierw z fazą gazową, fallback pełny."""
    state.specify_phase(CP.iphase_gas)
    try:
        state.update(pair, v1, v2)
        return
    except Exception:
        state.unspecify_phase()
        try:
            state.update(pair, v1, v2)
        except Exception as exc:
            raise ValueError(
                f"Flash termodynamiczny nie powiódł się. Szczegóły CoolProp: {exc}"
            ) from exc


def flash_ph(state: CP.AbstractState, pressure_pa: float, h_target_j_per_kg: float) -> None:
    """Flash (p, h): czyste płyny natywnie; mieszaniny — bisekcja po T.

    Natywny flash h-p CoolProp dla mieszanin wymaga zbudowanej otoczki
    fazowej (kosztowna i zawodna dla składów z H2) — zamiast tego
    rozwiązujemy h(p,T) = h* w fazie gazowej (``_solve_temperature_gas``).
    """
    if len(state.fluid_names()) == 1:
        _flash_native_gas_first(state, CP.HmassP_INPUTS, h_target_j_per_kg, pressure_pa)
    else:
        _solve_temperature_gas(state, pressure_pa, h_target_j_per_kg, "h")


def flash_ps(state: CP.AbstractState, pressure_pa: float, s_target_j_per_kg_k: float) -> None:
    """Flash (p, s): czyste płyny natywnie; mieszaniny — bisekcja po T."""
    if len(state.fluid_names()) == 1:
        _flash_native_gas_first(state, CP.PSmass_INPUTS, pressure_pa, s_target_j_per_kg_k)
    else:
        _solve_temperature_gas(state, pressure_pa, s_target_j_per_kg_k, "s")


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
    elif state.phase() in (CP.iphase_twophase, CP.iphase_liquid):
        # Klasyfikacja faz CoolProp dla mieszanin powyżej ciśnienia
        # pseudokrytycznego bywa niejednoznaczna ("unknown") — ostrzegamy
        # tylko przy jednoznacznie wykrytej cieczy / obszarze dwufazowym.
        warnings.append(
            "Uwaga: punkt pracy w obszarze dwufazowym lub ciekłym "
            "(kondensacja cięższych składników)."
        )

    density = state.rhomass()
    speed = state.speed_sound()
    viscosity: float | None
    method = "CoolProp"
    try:
        viscosity = state.viscosity()
        if not math.isfinite(viscosity):
            # Model ECS lepkości mieszanin punktowo zwraca NaN bez wyjątku —
            # ponawiamy z minimalną perturbacją temperatury (+0,02 K).
            update_state_pt(state, pressure_pa, temperature_k + 0.02)
            viscosity = state.viscosity()
            update_state_pt(state, pressure_pa, temperature_k)
            if not math.isfinite(viscosity):
                raise ValueError("Lepkość ECS zwraca NaN.")
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
