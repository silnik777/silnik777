"""Emisje GHG: spalanie (stechiometria), ucieczki CH4, energia elektryczna — M8/M9.

Metodyka:
    * **Spalanie (zakres 1):** stechiometrycznie ze składu molowego (M1):
          e_CO2 = Σ x_j·nC_j·M_CO2 / V_m   [kg CO2/m³ w war. odniesienia],
      gdzie nC_j — liczba atomów węgla w składniku (pełne utlenienie C→CO2),
      V_m — rzeczywista objętość molowa w warunkach odniesienia (M1).
      CO2 zawarty w gazie (składnik CO2) również trafia do spalin — ujęty.
      Wynik dokładniejszy niż wskaźniki domyślne (IPCC 56,1 kg/GJ — test
      porównawczy ±5% dla gazu E).
    * **Ucieczki CH4 (zakres 1):** masa CH4 × GWP (IPCC AR6, tab. 7.15;
      ``data/emission_factors.yaml``) dla horyzontu 100/20 lat,
      metan kopalny albo biogeniczny.
    * **Energia elektryczna (zakres 2):** MWh × emisyjność miksu [t CO2/MWh]
      ze ścieżki scenariusza M5 (``core.prices``) dla zadanego roku.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.calorific import calorific_values
from core.composition import GasComposition, components_registry
from core.config import load_data_file
from core.prices import PriceScenario
from core.units import NORMAL_0C, ReferenceCondition

#: Masa molowa CO2 [kg/kmol] (IUPAC).
M_CO2_KG_PER_KMOL = 44.0095

#: Liczba atomów węgla utlenianych do CO2 w składnikach palnych;
#: składnik CO2 (1 mol C już utleniony) przechodzi do spalin bez zmiany.
_CARBON_ATOMS = {
    "CH4": 1,
    "C2H6": 2,
    "C3H8": 3,
    "nC4H10": 4,
    "iC4H10": 4,
    "nC5H12": 5,
    "iC5H12": 5,
    "nC6H14": 6,
    "CO2": 1,
    "N2": 0,
    "O2": 0,
    "He": 0,
    "H2": 0,
}


@cache
def gwp_factors() -> dict[str, dict]:
    """Współczynniki GWP z ``data/emission_factors.yaml`` (IPCC AR6)."""
    return load_data_file("emission_factors.yaml")["gwp"]


@dataclass(frozen=True)
class CombustionEmissions:
    """Wskaźniki emisji CO2 ze spalania dla zadanego składu (zakres 1)."""

    kg_co2_per_m3_ref: float  # na m³ w warunkach odniesienia (Nm³ dla 0 °C)
    kg_co2_per_kg: float
    g_co2_per_kwh_hi: float  # na kWh wg wartości opałowej
    g_co2_per_kwh_hs: float  # na kWh wg ciepła spalania
    kg_co2_per_gj_hi: float  # porównanie ze wskaźnikami IPCC/KOBiZE


def combustion_emissions(
    composition: GasComposition,
    volume_reference: ReferenceCondition = NORMAL_0C,
) -> CombustionEmissions:
    """Emisja CO2 ze spalania — stechiometrycznie ze składu (M1).

    Zakłada pełne utlenienie węgla (C→CO2); CO2 obecny w paliwie przechodzi
    do spalin. Wskaźniki masowe/objętościowe/energetyczne spójne z ISO 6976.
    """
    registry = components_registry()
    unknown = [k for k, _ in composition.fractions if k not in _CARBON_ATOMS]
    if unknown:
        raise ValueError(
            f"Brak danych o węglu dla składników: {', '.join(unknown)} — "
            "uzupełnij _CARBON_ATOMS w core/emissions.py."
        )

    cal = calorific_values(composition, volume_reference)
    # kmol CO2 na kmol gazu
    n_co2 = sum(x * _CARBON_ATOMS[k] for k, x in composition.fractions)
    kg_co2_per_kmol = n_co2 * M_CO2_KG_PER_KMOL
    kg_per_m3 = kg_co2_per_kmol / cal.molar_volume_m3_per_kmol
    kg_per_kg = kg_co2_per_kmol / sum(
        x * registry[k].molar_mass_kg_per_kmol for k, x in composition.fractions
    )
    hi_kwh_per_m3 = cal.hi_kwh_per_m3
    hs_kwh_per_m3 = cal.hs_kwh_per_m3
    return CombustionEmissions(
        kg_co2_per_m3_ref=kg_per_m3,
        kg_co2_per_kg=kg_per_kg,
        g_co2_per_kwh_hi=(kg_per_m3 / hi_kwh_per_m3 * 1e3) if hi_kwh_per_m3 > 0 else 0.0,
        g_co2_per_kwh_hs=(kg_per_m3 / hs_kwh_per_m3 * 1e3) if hs_kwh_per_m3 > 0 else 0.0,
        kg_co2_per_gj_hi=(kg_per_m3 / (cal.hi_mj_per_m3 / 1e3)) if cal.hi_mj_per_m3 > 0 else 0.0,
    )


def ch4_to_co2eq_kg(mass_ch4_kg: float, horizon: str = "GWP100", fossil: bool = True) -> float:
    """Ekwiwalent CO2 emisji metanu [kg CO2eq].

    Args:
        mass_ch4_kg: masa wyemitowanego CH4 [kg], ≥ 0,
        horizon: "GWP100" | "GWP20" (IPCC AR6),
        fossil: True — metan kopalny (29,8/82,5); False — biogeniczny
            (27,0/80,8); źródła w ``data/emission_factors.yaml``.
    """
    if mass_ch4_kg < 0:
        raise ValueError("Masa CH4 nie może być ujemna.")
    if horizon not in ("GWP100", "GWP20"):
        raise ValueError("Horyzont musi być 'GWP100' albo 'GWP20'.")
    key = "CH4_kopalny" if fossil else "CH4_biogeniczny"
    factor = float(gwp_factors()[key][horizon.lower()])
    return mass_ch4_kg * factor


@dataclass(frozen=True)
class LeakEmissions:
    """Emisje CO2eq z ucieczek gazu (frakcja CH4 wycieku × GWP)."""

    leaked_volume_m3_ref: float
    ch4_mass_kg: float
    co2eq_gwp100_kg: float
    co2eq_gwp20_kg: float


def leak_emissions(
    composition: GasComposition,
    leaked_volume_m3_ref: float,
    fossil: bool = True,
    volume_reference: ReferenceCondition = NORMAL_0C,
) -> LeakEmissions:
    """Emisje z ucieczki gazu o zadanej objętości (war. odniesienia).

    Liczy masę CH4 w wycieku (udział molowy × masa molowa / V_m) i przelicza
    na CO2eq dla obu horyzontów. CO2 zawarty w wycieku pomijamy (zwykle
    < 0,1% wpływu); H2 nie ma GWP bezpośredniego w ujęciu AR6 (pośredni
    efekt H2 — poza zakresem, nota w UI).
    """
    if leaked_volume_m3_ref < 0:
        raise ValueError("Objętość wycieku nie może być ujemna.")
    cal = calorific_values(composition, volume_reference)
    x_ch4 = composition.fraction("CH4")
    m_ch4 = components_registry()["CH4"].molar_mass_kg_per_kmol
    ch4_kg = leaked_volume_m3_ref / cal.molar_volume_m3_per_kmol * x_ch4 * m_ch4
    return LeakEmissions(
        leaked_volume_m3_ref=leaked_volume_m3_ref,
        ch4_mass_kg=ch4_kg,
        co2eq_gwp100_kg=ch4_to_co2eq_kg(ch4_kg, "GWP100", fossil),
        co2eq_gwp20_kg=ch4_to_co2eq_kg(ch4_kg, "GWP20", fossil),
    )


def electricity_emissions_t_co2(
    energy_mwh: float, scenario: PriceScenario, year: int | float
) -> float:
    """Emisje zakresu 2 z energii elektrycznej [t CO2].

    Wzór: E = MWh × wskaźnik emisyjności miksu [t CO2/MWh] ze ścieżki
    scenariusza M5 (KOBiZE — trajektoria malejąca do 2050, edytowalna).
    """
    if energy_mwh < 0:
        raise ValueError("Energia nie może być ujemna.")
    return energy_mwh * scenario.price("emisyjnosc_miksu", year)
