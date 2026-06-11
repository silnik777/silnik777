"""Produkcja wodoru: technologie i kalkulator zapotrzebowania — moduł M6.

Biblioteka technologii (``data/hydrogen_production.yaml``): AEL, PEM, SOEC,
AEM, SMR+CCS, piroliza metanu — parametry orientacyjne wg IEA Global
Hydrogen Review 2023/2024 (zużycie energii systemowe, woda, praca częściowa,
degradacja, CAPEX/OPEX, ciśnienie/czystość, TRL).

Sprawność energetyczna odniesiona do wartości opałowej wodoru
Hi(H2) = 33,33 kWh/kg (ISO 6976, M1): η_LHV = 33,33 / e_całk [kWh/kg].

Emisje jednostkowe [kg CO2/kg H2]:
    * zakres 1 — bezpośrednie (rezydualne CO2 z SMR+CCS; spalanie gazu
      procesowego ujęte w danych technologii),
    * zakres 2 — energia elektryczna × emisyjność miksu (ścieżka M5),
    * gaz ziemny (SMR/piroliza) — emisja ze spalania/konwersji gazu ujęta
      w ``direct_co2``; dodatkowo raportujemy zużycie gazu.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.calorific import calorific_values
from core.composition import GasComposition
from core.config import load_data_file
from core.prices import PriceScenario


def _rng(raw: dict | float, key: str = "typical") -> float:
    """Wartość typowa z pola {min,typical,max} albo liczby."""
    if isinstance(raw, dict):
        return float(raw[key])
    return float(raw)


def _range_tuple(raw: dict | float) -> tuple[float, float]:
    if isinstance(raw, dict):
        return float(raw["min"]), float(raw["max"])
    return float(raw), float(raw)


@dataclass(frozen=True)
class HydrogenTechnology:
    """Technologia produkcji H2 (wartości typowe + zakresy, źródła w data/)."""

    key: str
    name_pl: str
    electricity_kwh_per_kg: float
    electricity_range: tuple[float, float]
    fuel_gas_kwh_per_kg: float
    fuel_gas_range: tuple[float, float]
    heat_kwh_per_kg: float
    water_l_per_kg: float
    water_range: tuple[float, float]
    part_load_pct: tuple[float, float]
    degradation_pct_per_year: float
    stack_lifetime_h: tuple[float, float]
    capex_eur_per_kw: float
    capex_basis: str  # "kW energii elektrycznej" | "kW H2 (Hi)"
    opex_pct_capex_per_year: float
    pressure_out_bar: float
    purity_pct: float
    direct_co2_kg_per_kg_h2: float
    trl: int
    source: str
    notes: tuple[str, ...] = ()

    @property
    def total_energy_kwh_per_kg(self) -> float:
        """Całkowite zużycie energii (el. + gaz + ciepło) [kWh/kg H2]."""
        return self.electricity_kwh_per_kg + self.fuel_gas_kwh_per_kg + self.heat_kwh_per_kg


@cache
def hydrogen_technologies() -> dict[str, HydrogenTechnology]:
    """Rejestr technologii produkcji H2 z ``data/hydrogen_production.yaml``."""
    raw = load_data_file("hydrogen_production.yaml")["technologies"]
    result = {}
    for key, item in raw.items():
        capex_key = (
            "capex_eur_per_kw_el" if "capex_eur_per_kw_el" in item else "capex_eur_per_kw_h2"
        )
        notes = tuple(
            str(item[n])
            for n in ("heat_note", "purity_note", "capture_note", "byproduct_note")
            if n in item
        )
        result[key] = HydrogenTechnology(
            key=key,
            name_pl=item["name_pl"],
            electricity_kwh_per_kg=_rng(item["electricity_kwh_per_kg"]),
            electricity_range=_range_tuple(item["electricity_kwh_per_kg"]),
            fuel_gas_kwh_per_kg=_rng(item["fuel_gas_kwh_per_kg"]),
            fuel_gas_range=_range_tuple(item["fuel_gas_kwh_per_kg"]),
            heat_kwh_per_kg=float(item.get("heat_kwh_per_kg", 0.0)),
            water_l_per_kg=_rng(item["water_l_per_kg"]),
            water_range=_range_tuple(item["water_l_per_kg"]),
            part_load_pct=tuple(item["part_load_pct"]),
            degradation_pct_per_year=_rng(item["degradation_pct_per_year"]),
            stack_lifetime_h=tuple(item["stack_lifetime_h"]),
            capex_eur_per_kw=_rng(item[capex_key]),
            capex_basis=("kW energii elektrycznej" if capex_key.endswith("_el") else "kW H2 (Hi)"),
            opex_pct_capex_per_year=float(item["opex_pct_capex_per_year"]),
            pressure_out_bar=float(item["pressure_out_bar"]),
            purity_pct=float(item["purity_pct"]),
            direct_co2_kg_per_kg_h2=_rng(item["direct_co2_kg_per_kg_h2"]),
            trl=int(item["trl"]),
            source=item["source"],
            notes=notes,
        )
    return result


def h2_lhv_kwh_per_kg() -> float:
    """Wartość opałowa H2 [kWh/kg] z metody ISO 6976 (M1) — ok. 33,33."""
    return calorific_values(GasComposition.pure("H2")).hi_kwh_per_kg


@dataclass(frozen=True)
class HydrogenDemandResult:
    """Zapotrzebowanie i wskaźniki dla zadanej produkcji H2."""

    technology: HydrogenTechnology
    production_kg_per_h: float
    capacity_factor: float
    years_of_degradation: float
    electricity_kwh_per_kg_aged: float  # po degradacji
    power_el_mw: float
    energy_el_mwh_per_year: float
    gas_mwh_per_year: float
    heat_mwh_per_year: float
    water_m3_per_year: float
    production_t_per_year: float
    efficiency_lhv: float
    co2_scope1_kg_per_kg: float
    co2_scope2_kg_per_kg: float

    @property
    def co2_total_kg_per_kg(self) -> float:
        return self.co2_scope1_kg_per_kg + self.co2_scope2_kg_per_kg


def hydrogen_demand(
    technology_key: str,
    production_kg_per_h: float,
    scenario: PriceScenario,
    year: int = 2030,
    capacity_factor: float = 0.9,
    years_of_degradation: float = 0.0,
) -> HydrogenDemandResult:
    """Kalkulator zapotrzebowania dla zadanej produkcji H2.

    Args:
        technology_key: klucz z ``hydrogen_technologies()``,
        production_kg_per_h: produkcja H2 przy pracy [kg/h], > 0,
        scenario: scenariusz M5 (emisyjność miksu dla zakresu 2),
        year: rok analizy (wskaźnik miksu),
        capacity_factor: współczynnik wykorzystania (0–1],
        years_of_degradation: wiek instalacji [lata] — zużycie energii
            elektrycznej rośnie o ``degradation_pct_per_year`` rocznie
            (liniowo; dotyczy elektrolizerów).

    Returns:
        ``HydrogenDemandResult`` — moc, energie roczne, woda, sprawność,
        emisje jednostkowe zakresu 1 i 2.
    """
    techs = hydrogen_technologies()
    if technology_key not in techs:
        raise ValueError(f"Nieznana technologia '{technology_key}'. Dostępne: {', '.join(techs)}.")
    if production_kg_per_h <= 0:
        raise ValueError("Produkcja musi być dodatnia.")
    if not 0 < capacity_factor <= 1:
        raise ValueError("Współczynnik wykorzystania musi być w (0, 1].")
    if years_of_degradation < 0:
        raise ValueError("Wiek instalacji nie może być ujemny.")

    tech = techs[technology_key]
    degr = 1.0 + tech.degradation_pct_per_year / 100.0 * years_of_degradation
    el_aged = tech.electricity_kwh_per_kg * degr

    hours = 8760.0 * capacity_factor
    production_t_year = production_kg_per_h * hours / 1e3
    energy_el_mwh = el_aged * production_kg_per_h * hours / 1e3
    gas_mwh = tech.fuel_gas_kwh_per_kg * production_kg_per_h * hours / 1e3
    heat_mwh = tech.heat_kwh_per_kg * production_kg_per_h * hours / 1e3

    grid_factor = scenario.price("emisyjnosc_miksu", year)  # t CO2/MWh
    scope2_per_kg = el_aged / 1e3 * grid_factor * 1e3  # kg CO2/kg H2

    lhv = h2_lhv_kwh_per_kg()
    total = el_aged + tech.fuel_gas_kwh_per_kg + tech.heat_kwh_per_kg
    return HydrogenDemandResult(
        technology=tech,
        production_kg_per_h=production_kg_per_h,
        capacity_factor=capacity_factor,
        years_of_degradation=years_of_degradation,
        electricity_kwh_per_kg_aged=el_aged,
        power_el_mw=el_aged * production_kg_per_h / 1e3,
        energy_el_mwh_per_year=energy_el_mwh,
        gas_mwh_per_year=gas_mwh,
        heat_mwh_per_year=heat_mwh,
        water_m3_per_year=tech.water_l_per_kg * production_kg_per_h * hours / 1e3,
        production_t_per_year=production_t_year,
        efficiency_lhv=lhv / total if total > 0 else 0.0,
        co2_scope1_kg_per_kg=tech.direct_co2_kg_per_kg_h2,
        co2_scope2_kg_per_kg=scope2_per_kg,
    )


def energy_cost_pln_per_kg(
    result: HydrogenDemandResult, scenario: PriceScenario, year: int
) -> float:
    """Koszt energii (el. + gaz) na 1 kg H2 [PLN/kg] wg cen scenariusza M5.

    Uproszczenie: tylko nośniki energii (bez CAPEX/OPEX/wody — pełne LCOH
    w module M10).
    """
    el_pln = result.electricity_kwh_per_kg_aged / 1e3 * scenario.price("energia_elektryczna", year)
    gas_pln = result.technology.fuel_gas_kwh_per_kg / 1e3 * scenario.price("gaz_ziemny", year)
    return el_pln + gas_pln
