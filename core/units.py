"""Jednostki, stałe fizyczne i przeliczniki dla całego silnika obliczeniowego.

Konwencja jednostek (obowiązuje w całym pakiecie ``core``):
    * wielkości fizyczne przechowujemy w SI, a jednostka jest częścią nazwy
      zmiennej / parametru, np. ``pressure_pa``, ``temperature_k``,
      ``molar_mass_kg_per_kmol``, ``energy_mj``;
    * przeliczenia na jednostki "branżowe" (bar, Nm³, kWh) wykonują wyłącznie
      funkcje z tego modułu — nigdzie indziej nie ma "magicznych" stałych.

Warunki odniesienia (referencyjne) dla objętości gazu:
    * 0 °C / 101,325 kPa  — warunki normalne, podstawa "Nm³" w polskim
      gazownictwie (ISO 6976: warunki odniesienia objętości 273,15 K),
    * 15 °C / 101,325 kPa — warunki standardowe ISO 13443,
    * 25 °C / 101,325 kPa — temperatura odniesienia spalania wg ISO 6976.

Źródła:
    * CODATA 2018 — stała gazowa R,
    * ISO 6976:2016 — warunki odniesienia dla wartości kalorycznych,
    * ISO 13443:1996 — standardowe warunki odniesienia dla gazu ziemnego.
"""

from __future__ import annotations

from dataclasses import dataclass

# --- Stałe fizyczne -------------------------------------------------------

#: Uniwersalna stała gazowa [J/(mol·K)] — CODATA 2018 (wartość dokładna).
R_UNIVERSAL_J_PER_MOL_K: float = 8.31446261815324

#: Ciśnienie odniesienia (atmosfera fizyczna) [Pa].
P_REFERENCE_PA: float = 101_325.0

#: Zero bezwzględne w skali Celsjusza [°C].
ABSOLUTE_ZERO_C: float = -273.15


# --- Warunki odniesienia ---------------------------------------------------


@dataclass(frozen=True)
class ReferenceCondition:
    """Warunki odniesienia (p, T) dla objętości gazu.

    Attributes:
        name: krótki identyfikator (używany w UI i konfiguracji),
        temperature_k: temperatura odniesienia [K],
        pressure_pa: ciśnienie odniesienia [Pa],
        description: opis z podaniem normy źródłowej.
    """

    name: str
    temperature_k: float
    pressure_pa: float
    description: str

    def molar_volume_m3_per_kmol(self) -> float:
        """Objętość molowa gazu doskonałego w tych warunkach [m³/kmol].

        Wzór: V_m = R·T / p (równanie stanu gazu doskonałego),
        R w J/(kmol·K) = 1000·R[J/(mol·K)].
        Uwaga: dla gazów rzeczywistych objętość molowa wymaga korekty
        współczynnikiem ściśliwości Z (moduł M1) — przy ciśnieniu
        odniesienia ~0,1 MPa błąd pominięcia Z wynosi < 0,3 % dla gazu
        ziemnego i < 0,07 % dla H2.
        """
        r_j_per_kmol_k = R_UNIVERSAL_J_PER_MOL_K * 1.0e3
        return r_j_per_kmol_k * self.temperature_k / self.pressure_pa


#: Warunki normalne 0 °C / 101,325 kPa — podstawa "Nm³" (ISO 6976, PN-C-04750).
NORMAL_0C = ReferenceCondition(
    name="normalne (0°C)",
    temperature_k=273.15,
    pressure_pa=P_REFERENCE_PA,
    description="Warunki normalne: 273,15 K; 101,325 kPa (ISO 6976 — objętość).",
)

#: Warunki standardowe 15 °C / 101,325 kPa (ISO 13443).
STANDARD_15C = ReferenceCondition(
    name="standardowe (15°C)",
    temperature_k=288.15,
    pressure_pa=P_REFERENCE_PA,
    description="Warunki standardowe: 288,15 K; 101,325 kPa (ISO 13443).",
)

#: Warunki 25 °C / 101,325 kPa — temperatura odniesienia spalania wg ISO 6976.
STANDARD_25C = ReferenceCondition(
    name="spalanie (25°C)",
    temperature_k=298.15,
    pressure_pa=P_REFERENCE_PA,
    description="Temperatura odniesienia spalania: 298,15 K; 101,325 kPa (ISO 6976).",
)

#: Słownik warunków odniesienia dostępnych w UI / konfiguracji.
REFERENCE_CONDITIONS: dict[str, ReferenceCondition] = {
    "0C": NORMAL_0C,
    "15C": STANDARD_15C,
    "25C": STANDARD_25C,
}


# --- Walidacja -------------------------------------------------------------


def require_positive(value: float, quantity_pl: str) -> None:
    """Sprawdza, czy wielkość fizyczna jest dodatnia; komunikat po polsku."""
    if not value > 0.0:
        raise ValueError(f"{quantity_pl} musi być dodatnia (otrzymano: {value!r}).")


# --- Temperatura -----------------------------------------------------------


def celsius_to_kelvin(temperature_c: float) -> float:
    """Przelicza temperaturę °C → K. Zakres ważności: T ≥ 0 K."""
    temperature_k = temperature_c - ABSOLUTE_ZERO_C
    if temperature_k < 0.0:
        raise ValueError(
            f"Temperatura {temperature_c} °C jest poniżej zera bezwzględnego "
            f"({ABSOLUTE_ZERO_C} °C)."
        )
    return temperature_k


def kelvin_to_celsius(temperature_k: float) -> float:
    """Przelicza temperaturę K → °C. Zakres ważności: T ≥ 0 K."""
    if temperature_k < 0.0:
        raise ValueError(f"Temperatura bezwzględna nie może być ujemna ({temperature_k} K).")
    return temperature_k + ABSOLUTE_ZERO_C


# --- Ciśnienie --------------------------------------------------------------


def bar_to_pa(pressure_bar: float) -> float:
    """Przelicza ciśnienie bar → Pa (1 bar = 100 000 Pa)."""
    return pressure_bar * 1.0e5


def pa_to_bar(pressure_pa: float) -> float:
    """Przelicza ciśnienie Pa → bar."""
    return pressure_pa / 1.0e5


def mpa_to_pa(pressure_mpa: float) -> float:
    """Przelicza ciśnienie MPa → Pa."""
    return pressure_mpa * 1.0e6


def pa_to_mpa(pressure_pa: float) -> float:
    """Przelicza ciśnienie Pa → MPa."""
    return pressure_pa / 1.0e6


def kpa_to_pa(pressure_kpa: float) -> float:
    """Przelicza ciśnienie kPa → Pa."""
    return pressure_kpa * 1.0e3


# --- Energia ----------------------------------------------------------------

#: 1 kWh = 3,6 MJ (definicja).
MJ_PER_KWH: float = 3.6


def kwh_to_mj(energy_kwh: float) -> float:
    """Przelicza energię kWh → MJ (1 kWh = 3,6 MJ)."""
    return energy_kwh * MJ_PER_KWH


def mj_to_kwh(energy_mj: float) -> float:
    """Przelicza energię MJ → kWh."""
    return energy_mj / MJ_PER_KWH


def j_to_kwh(energy_j: float) -> float:
    """Przelicza energię J → kWh."""
    return energy_j / 3.6e6


def kwh_to_j(energy_kwh: float) -> float:
    """Przelicza energię kWh → J."""
    return energy_kwh * 3.6e6


def j_to_mj(energy_j: float) -> float:
    """Przelicza energię J → MJ."""
    return energy_j / 1.0e6


# --- Ilość gazu: Nm³ ↔ kmol ↔ kg -------------------------------------------


def volume_ref_to_kmol(
    volume_m3: float,
    reference: ReferenceCondition = NORMAL_0C,
) -> float:
    """Przelicza objętość gazu w warunkach odniesienia → ilość substancji [kmol].

    Wzór: n = V / V_m,  V_m = R·T_ref / p_ref (gaz doskonały).
    Dla ``reference=NORMAL_0C`` argument ``volume_m3`` oznacza Nm³.
    Zakres ważności: warunki odniesienia bliskie atmosferycznym
    (pominięcie Z daje błąd < 0,3 % — patrz ``ReferenceCondition``).
    """
    require_positive(volume_m3, "Objętość")
    return volume_m3 / reference.molar_volume_m3_per_kmol()


def kmol_to_volume_ref(
    amount_kmol: float,
    reference: ReferenceCondition = NORMAL_0C,
) -> float:
    """Przelicza ilość substancji [kmol] → objętość w warunkach odniesienia [m³].

    Wzór: V = n·V_m. Dla ``reference=NORMAL_0C`` wynik to Nm³.
    """
    require_positive(amount_kmol, "Ilość substancji")
    return amount_kmol * reference.molar_volume_m3_per_kmol()


def volume_ref_to_kg(
    volume_m3: float,
    molar_mass_kg_per_kmol: float,
    reference: ReferenceCondition = NORMAL_0C,
) -> float:
    """Przelicza objętość w warunkach odniesienia → masę [kg].

    Wzór: m = (V / V_m)·M. Dla ``reference=NORMAL_0C`` argument to Nm³.
    """
    require_positive(molar_mass_kg_per_kmol, "Masa molowa")
    return volume_ref_to_kmol(volume_m3, reference) * molar_mass_kg_per_kmol


def kg_to_volume_ref(
    mass_kg: float,
    molar_mass_kg_per_kmol: float,
    reference: ReferenceCondition = NORMAL_0C,
) -> float:
    """Przelicza masę [kg] → objętość w warunkach odniesienia [m³].

    Wzór: V = (m / M)·V_m. Dla ``reference=NORMAL_0C`` wynik to Nm³.
    """
    require_positive(mass_kg, "Masa")
    require_positive(molar_mass_kg_per_kmol, "Masa molowa")
    return kmol_to_volume_ref(mass_kg / molar_mass_kg_per_kmol, reference)
