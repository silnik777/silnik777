"""Wartości kaloryczne, gęstość względna, liczba Wobbego — ISO 6976 (moduł M1).

Metoda (ISO 6976:2016):
    * molowe ciepło spalania mieszaniny (gaz doskonały, spalanie przy 25 °C):
          Hs_molar = Σ x_j · Hs_j   [kJ/mol],  Hs_j z tab. 3 normy,
    * wartość opałowa: Hi_molar = Hs_molar − n_H2O · L0,
          n_H2O = Σ x_j · b_j (mole wody ze spalenia), L0 = 44,016 kJ/mol,
    * przeliczenie na objętość w warunkach odniesienia (domyślnie 0 °C,
      101,325 kPa — podstawa Nm³):
          Hs_vol = Hs_molar / V_m,  V_m = Z_mix · R · T_ref / p_ref,
    * gęstość względna (gaz rzeczywisty): d = (M / M_air) · (Z_air / Z_mix),
    * liczba Wobbego: Ws = Hs_vol / √d (analogicznie Wi).

Odstępstwo od ISO 6976: współczynnik ściśliwości Z_mix oraz Z_air
w warunkach odniesienia liczymy z równania stanu (CoolProp HEOS/GERG-2008)
zamiast współczynników sumacyjnych normy — różnica < 0,1% (dla czystego CO2
maks. 0,11%), a metoda jest dokładniejsza dla mieszanin bogatych w H2.

Domyślna para warunków odniesienia: spalanie 25 °C / objętość 0 °C
(uzgodnione z użytkownikiem; polska praktyka rozliczeniowa).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import CoolProp.CoolProp as CP

from core.composition import GasComposition, components_registry
from core.config import load_data_file
from core.gas_properties import GasProperties
from core.units import (
    NORMAL_0C,
    ReferenceCondition,
    mj_to_kwh,
)


@dataclass(frozen=True)
class CalorificResult:
    """Wyniki metody ISO 6976 dla zadanego składu."""

    volume_reference: ReferenceCondition
    molar_mass_kg_per_kmol: float
    z_ref: float  # Z mieszaniny w warunkach odniesienia objętości [-]
    molar_volume_m3_per_kmol: float  # rzeczywista objętość molowa w war. odniesienia
    hs_molar_kj_per_mol: float  # ciepło spalania (brutto), gaz doskonały, 25 °C
    hi_molar_kj_per_mol: float  # wartość opałowa (netto), gaz doskonały, 25 °C
    hs_mj_per_m3: float  # ciepło spalania na m³ w war. odniesienia (Nm³ dla 0 °C)
    hi_mj_per_m3: float
    hs_mj_per_kg: float
    hi_mj_per_kg: float
    relative_density: float  # d — gęstość względna rzeczywista [-]
    density_ref_kg_per_m3: float  # gęstość w warunkach odniesienia [kg/m³]
    wobbe_superior_mj_per_m3: float  # Ws = Hs_vol / √d
    wobbe_inferior_mj_per_m3: float

    @property
    def hs_kwh_per_m3(self) -> float:
        """Ciepło spalania [kWh/m³ w warunkach odniesienia]."""
        return mj_to_kwh(self.hs_mj_per_m3)

    @property
    def hi_kwh_per_m3(self) -> float:
        """Wartość opałowa [kWh/m³ w warunkach odniesienia]."""
        return mj_to_kwh(self.hi_mj_per_m3)

    @property
    def hi_kwh_per_kg(self) -> float:
        """Wartość opałowa [kWh/kg]."""
        return mj_to_kwh(self.hi_mj_per_kg)

    @property
    def hs_kwh_per_kg(self) -> float:
        """Ciepło spalania [kWh/kg]."""
        return mj_to_kwh(self.hs_mj_per_kg)


@cache
def _iso_constants() -> dict:
    return load_data_file("components.yaml")["iso6976_constants"]


@cache
def _z_pure_air(temperature_k: float, pressure_pa: float) -> float:
    """Z suchego powietrza w warunkach odniesienia (CoolProp, model Lemmon 2000).

    Walidacja: ISO 6976 podaje Z_air(0 °C; 101,325 kPa) = 0,99941 —
    zgodność CoolProp lepsza niż 0,01% (test walidacyjny).
    """
    state = CP.AbstractState("HEOS", "Air")
    state.update(CP.PT_INPUTS, pressure_pa, temperature_k)
    return state.compressibility_factor()


def _z_mixture_at(composition: GasComposition, reference: ReferenceCondition) -> float:
    from core.gas_properties import _abstract_state, update_state_pt

    state = _abstract_state(composition)
    # W warunkach odniesienia (~0,1 MPa) faza gazowa jest jednoznaczna —
    # fallback wymuszonej fazy jest tu bezpieczny.
    update_state_pt(state, reference.pressure_pa, reference.temperature_k)
    return state.compressibility_factor()


def calorific_values(
    composition: GasComposition,
    volume_reference: ReferenceCondition = NORMAL_0C,
) -> CalorificResult:
    """Liczy wartości kaloryczne, gęstość względną i liczby Wobbego (ISO 6976).

    Args:
        composition: skład molowy gazu,
        volume_reference: warunki odniesienia objętości (domyślnie 0 °C —
            podstawa Nm³); temperatura odniesienia spalania: zawsze 25 °C
            (tab. 3 ISO 6976; para 25/0 °C uzgodniona jako domyślna).

    Returns:
        ``CalorificResult`` ze wszystkimi wielkościami w SI + MJ/kWh.
    """
    registry = components_registry()
    constants = _iso_constants()
    l0_kj_per_mol = float(constants["h2o_vaporization_25c_kj_per_mol"])
    m_air = float(constants["air_molar_mass_kg_per_kmol"])

    hs_molar = 0.0
    n_h2o = 0.0
    for key, x in composition.fractions:
        info = registry[key]
        hs_molar += x * info.hhv_molar_25c_kj_per_mol
        n_h2o += x * info.h2o_mol_per_mol
    hi_molar = hs_molar - n_h2o * l0_kj_per_mol

    z_ref = _z_mixture_at(composition, volume_reference)
    molar_volume = z_ref * volume_reference.molar_volume_m3_per_kmol()  # m³/kmol

    # kJ/mol == MJ/kmol ⇒ dzielenie przez m³/kmol daje MJ/m³.
    hs_vol = hs_molar / molar_volume
    hi_vol = hi_molar / molar_volume

    m_mix = composition.molar_mass_kg_per_kmol
    # kJ/mol ≡ MJ/kmol, więc MJ/kmol ÷ kg/kmol = MJ/kg.
    hs_mass = hs_molar / m_mix
    hi_mass = hi_molar / m_mix

    z_air = _z_pure_air(volume_reference.temperature_k, volume_reference.pressure_pa)
    relative_density = (m_mix / m_air) * (z_air / z_ref)
    density_ref = m_mix / molar_volume  # kg/m³ w warunkach odniesienia

    sqrt_d = relative_density**0.5
    return CalorificResult(
        volume_reference=volume_reference,
        molar_mass_kg_per_kmol=m_mix,
        z_ref=z_ref,
        molar_volume_m3_per_kmol=molar_volume,
        hs_molar_kj_per_mol=hs_molar,
        hi_molar_kj_per_mol=hi_molar,
        hs_mj_per_m3=hs_vol,
        hi_mj_per_m3=hi_vol,
        hs_mj_per_kg=hs_mass,
        hi_mj_per_kg=hi_mass,
        relative_density=relative_density,
        density_ref_kg_per_m3=density_ref,
        wobbe_superior_mj_per_m3=hs_vol / sqrt_d,
        wobbe_inferior_mj_per_m3=hi_vol / sqrt_d,
    )


def energy_density_at_state(
    calorific: CalorificResult, properties: GasProperties
) -> dict[str, float]:
    """Gęstość energii (wg wartości opałowej i ciepła spalania) przy (p, T).

    Wzory: e_vol = Hi_molar · ρ_molar(p,T) [MJ/m³]; e_mass = Hi_molar / M [MJ/kg].
    """
    rho_molar = properties.molar_density_kmol_per_m3  # kmol/m³
    return {
        "hi_mj_per_m3_at_state": calorific.hi_molar_kj_per_mol * rho_molar,
        "hs_mj_per_m3_at_state": calorific.hs_molar_kj_per_mol * rho_molar,
        "hi_mj_per_kg": calorific.hi_mj_per_kg,
        "hs_mj_per_kg": calorific.hs_mj_per_kg,
    }


# --- Flagi zgodności jakościowej -------------------------------------------


@dataclass(frozen=True)
class QualityFlag:
    """Wynik pojedynczego sprawdzenia jakościowego."""

    name_pl: str
    value: float
    unit: str
    limit_min: float | None
    limit_max: float | None
    ok: bool
    source: str
    note: str | None = None


def quality_flags(
    composition: GasComposition,
    calorific: CalorificResult,
    h2_limit_mol_pct: float | None = None,
) -> list[QualityFlag]:
    """Flagi zgodności: liczba Wobbego (gaz gr. E) i udział H2.

    Progi z ``data/quality_limits.yaml`` (edytowalne bez zmian w kodzie);
    próg H2 można nadpisać argumentem ``h2_limit_mol_pct``.
    """
    limits = load_data_file("quality_limits.yaml")
    wobbe_cfg = limits["wobbe_index_group_E"]
    flags: list[QualityFlag] = []

    if calorific.volume_reference.name == NORMAL_0C.name:
        ws = calorific.wobbe_superior_mj_per_m3
        flags.append(
            QualityFlag(
                name_pl="Liczba Wobbego (górna) — gaz grupy E",
                value=ws,
                unit="MJ/m³ (25/0 °C)",
                limit_min=float(wobbe_cfg["min_mj_per_m3"]),
                limit_max=float(wobbe_cfg["max_mj_per_m3"]),
                ok=float(wobbe_cfg["min_mj_per_m3"]) <= ws <= float(wobbe_cfg["max_mj_per_m3"]),
                source=str(wobbe_cfg["source"]).strip(),
                note=wobbe_cfg.get("note"),
            )
        )

    if h2_limit_mol_pct is not None:
        h2_cfg = limits["hydrogen_blend_thresholds"]
        h2_pct = composition.h2_mole_percent
        flags.append(
            QualityFlag(
                name_pl=f"Udział H2 ≤ {h2_limit_mol_pct:g}% mol (próg scenariuszowy)",
                value=h2_pct,
                unit="% mol",
                limit_min=None,
                limit_max=h2_limit_mol_pct,
                ok=h2_pct <= h2_limit_mol_pct,
                source=str(h2_cfg["source"]).strip(),
                note=h2_cfg.get("note"),
            )
        )
    return flags
