"""Wartości referencyjne do testów walidacyjnych M1 (NIST/ISO/literatura).

Każda pozycja: wielkość, warunki, wartość referencyjna, tolerancja względna,
źródło. Tolerancje projektu: Z, gęstość, cp ≤ 0,5%; wartości kaloryczne
≤ 0,1% (zakres p ≤ 10 MPa, T = −20…60 °C).

Uwaga: w środowisku wykonawczym bez dostępu do webbook.nist.gov użyto
wartości z ISO 6976 i literatury podstawowej; tabelę można rozszerzać
o punkty NIST (struktura na to gotowa).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PropertyReference:
    """Punkt referencyjny właściwości czystego gazu przy (p, T)."""

    component: str  # klucz składnika (rejestr w data/components.yaml)
    quantity: str  # atrybut GasProperties
    pressure_pa: float
    temperature_k: float
    reference_value: float
    rel_tolerance: float
    unit: str
    source: str


P_ATM = 101_325.0
T0 = 273.15
T25 = 298.15

PROPERTY_REFERENCES: list[PropertyReference] = [
    # --- Współczynnik ściśliwości Z w warunkach normalnych ---
    PropertyReference(
        "CH4",
        "z_factor",
        P_ATM,
        T0,
        0.9976,
        0.001,
        "-",
        "ISO 6976:2016 (tab. 2, Z = 1 − s², metan)",
    ),
    PropertyReference(
        "C2H6",
        "z_factor",
        P_ATM,
        T0,
        0.9900,
        0.001,
        "-",
        "ISO 6976:2016 (tab. 2, etan)",
    ),
    PropertyReference(
        "C3H8",
        "z_factor",
        P_ATM,
        T0,
        0.9789,
        0.0015,
        "-",
        "ISO 6976:2016 (tab. 2, propan)",
    ),
    PropertyReference(
        "N2",
        "z_factor",
        P_ATM,
        T0,
        0.99970,
        0.0005,
        "-",
        "ISO 6976:2016 (tab. 2, azot)",
    ),
    PropertyReference(
        "CO2",
        "z_factor",
        P_ATM,
        T0,
        0.99434,
        0.0015,
        "-",
        "ISO 6976:2016 (tab. 2, CO2); EOS Span-Wagner daje 0,9933",
    ),
    PropertyReference(
        "H2",
        "z_factor",
        P_ATM,
        T0,
        1.0006,
        0.0005,
        "-",
        "ISO 6976:2016 / literatura (wodór, 0 °C)",
    ),
    # --- Gęstość w warunkach normalnych (0 °C, 101,325 kPa) ---
    PropertyReference(
        "CH4",
        "density_kg_per_m3",
        P_ATM,
        T0,
        0.7175,
        0.005,
        "kg/m³",
        "Air Liquide Gas Encyclopedia / GESTIS (metan, gaz rzeczywisty)",
    ),
    PropertyReference(
        "H2",
        "density_kg_per_m3",
        P_ATM,
        T0,
        0.08988,
        0.005,
        "kg/m³",
        "CODATA / Air Liquide Gas Encyclopedia (wodór)",
    ),
    PropertyReference(
        "N2",
        "density_kg_per_m3",
        P_ATM,
        T0,
        1.2504,
        0.005,
        "kg/m³",
        "Air Liquide Gas Encyclopedia (azot)",
    ),
    PropertyReference(
        "CO2",
        "density_kg_per_m3",
        P_ATM,
        T0,
        1.977,
        0.005,
        "kg/m³",
        "Air Liquide Gas Encyclopedia (CO2)",
    ),
    # --- cp przy 25 °C, ciśnienie atmosferyczne (≈ gaz doskonały) ---
    PropertyReference(
        "CH4",
        "cp_j_per_kg_k",
        P_ATM,
        T25,
        35.69 / 16.043e-3,
        0.005,
        "J/(kg·K)",
        "NIST Chemistry WebBook: cp°(CH4, 298,15 K) = 35,69 J/(mol·K)",
    ),
    PropertyReference(
        "H2",
        "cp_j_per_kg_k",
        P_ATM,
        T25,
        28.836 / 2.01588e-3,
        0.005,
        "J/(kg·K)",
        "NIST Chemistry WebBook: cp°(H2, 298,15 K) = 28,836 J/(mol·K)",
    ),
    PropertyReference(
        "N2",
        "cp_j_per_kg_k",
        P_ATM,
        T25,
        29.124 / 28.0134e-3,
        0.005,
        "J/(kg·K)",
        "NIST Chemistry WebBook: cp°(N2, 298,15 K) = 29,124 J/(mol·K)",
    ),
    # --- Prędkość dźwięku (kontrola spójności, szersza tolerancja) ---
    PropertyReference(
        "H2",
        "speed_of_sound_m_per_s",
        P_ATM,
        T0,
        1261.0,
        0.015,
        "m/s",
        "Literatura (np. CRC Handbook): w(H2, 0 °C) ≈ 1261 m/s",
    ),
    PropertyReference(
        "CH4",
        "speed_of_sound_m_per_s",
        P_ATM,
        T0,
        430.0,
        0.015,
        "m/s",
        "Literatura (CRC Handbook): w(CH4, 0 °C) ≈ 430 m/s",
    ),
]


@dataclass(frozen=True)
class CalorificReference:
    """Punkt referencyjny metody ISO 6976."""

    label: str
    component: str
    quantity: str  # atrybut CalorificResult
    reference_value: float
    rel_tolerance: float
    unit: str
    source: str


CALORIFIC_REFERENCES: list[CalorificReference] = [
    # Weryfikacja krzyżowa molowych ciepł spalania: niezależne wartości
    # z entalpii tworzenia (ATcT/CODATA, pakiet chemicals 1.5.2).
    CalorificReference(
        "Hs molowe CH4",
        "CH4",
        "hs_molar_kj_per_mol",
        890.59,
        0.001,
        "kJ/mol",
        "Entalpie tworzenia ATcT/CODATA (chemicals 1.5.2)",
    ),
    CalorificReference(
        "Hs molowe C2H6",
        "C2H6",
        "hs_molar_kj_per_mol",
        1560.64,
        0.001,
        "kJ/mol",
        "Entalpie tworzenia ATcT/CODATA (chemicals 1.5.2)",
    ),
    CalorificReference(
        "Hs molowe C3H8",
        "C3H8",
        "hs_molar_kj_per_mol",
        2219.33,
        0.001,
        "kJ/mol",
        "Entalpie tworzenia ATcT/CODATA (chemicals 1.5.2)",
    ),
    CalorificReference(
        "Hs molowe H2",
        "H2",
        "hs_molar_kj_per_mol",
        285.82,
        0.001,
        "kJ/mol",
        "Entalpie tworzenia ATcT/CODATA (chemicals 1.5.2)",
    ),
    # Wartości objętościowe (25/0 °C) — literatura branżowa.
    CalorificReference(
        "Hs CH4 (25/0 °C)",
        "CH4",
        "hs_mj_per_m3",
        39.84,
        0.0025,
        "MJ/m³",
        "Literatura gazownicza (GPSA/ISO 6976): Hs(CH4) ≈ 39,84 MJ/m³",
    ),
    CalorificReference(
        "Hs H2 (25/0 °C)",
        "H2",
        "hs_mj_per_m3",
        12.75,
        0.0025,
        "MJ/m³",
        "Literatura wodorowa (DNV/IEA): Hs(H2) ≈ 12,75 MJ/m³",
    ),
    CalorificReference(
        "Hi H2 (25/0 °C)",
        "H2",
        "hi_mj_per_m3",
        10.78,
        0.0025,
        "MJ/m³",
        "Literatura wodorowa: Hi(H2) ≈ 10,78 MJ/m³",
    ),
    CalorificReference(
        "Hi H2 na kg",
        "H2",
        "hi_mj_per_kg",
        119.96,
        0.0025,
        "MJ/kg",
        "IEA/DNV: wartość opałowa wodoru 119,96 MJ/kg (33,33 kWh/kg)",
    ),
    CalorificReference(
        "Hi CH4 na kg",
        "CH4",
        "hi_mj_per_kg",
        50.03,
        0.0025,
        "MJ/kg",
        "Literatura (GPSA): Hi(CH4) ≈ 50,0 MJ/kg",
    ),
    CalorificReference(
        "Wobbe górna CH4 (25/0 °C)",
        "CH4",
        "wobbe_superior_mj_per_m3",
        53.47,
        0.003,
        "MJ/m³",
        "Literatura gazownicza: Ws(CH4) ≈ 53,4–53,5 MJ/m³",
    ),
    CalorificReference(
        "Gęstość względna CH4",
        "CH4",
        "relative_density",
        0.5549,
        0.003,
        "-",
        "ISO 6976 / literatura: d(CH4) ≈ 0,555",
    ),
]
