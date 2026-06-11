"""Charakterystyki technologii wytwarzania ciepła i energii elektrycznej — M7.

Benchmark technologii od kopalnych po bezemisyjne
(``data/generation_technologies.yaml``, wg katalogów Danish Energy Agency
i IEA WEO — wartości orientacyjne). Ujednolicone wskaźniki:

* sprawność elektryczna / cieplna wg Hi (pompy ciepła: COP sezonowy,
  PV/wiatr: współczynnik wykorzystania mocy),
* emisje jednostkowe [g CO2/kWh produktu]:
    - paliwa gazowe — stechiometrycznie ze składu (M8, gaz E),
    - węgiel/biomasa — wskaźniki z pliku danych (IPCC; biomasa: 0,
      CO2 biogeniczny),
    - energia elektryczna — emisyjność miksu (ścieżka M5, zakres 2),
    - słońce/wiatr/wodór — 0 w miejscu wytwarzania,
* koszt paliwowy [PLN/MWh produktu] = cena nośnika (M5) / sprawność.

Integracja z M13: technologie cieplne (kategorie ciepło/kogeneracja)
zasilają listę źródeł podgrzewu gazu (``heat_source_entries``).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.composition import GasComposition
from core.config import load_data_file
from core.emissions import combustion_emissions
from core.prices import PriceScenario

#: Paliwa bez kosztu nośnika (zasoby darmowe).
_FREE_FUELS = ("slonce", "wiatr")

#: Paliwa rozliczane wg miksu elektroenergetycznego (zakres 2).
_GRID_FUEL = "energia_elektryczna"


@dataclass(frozen=True)
class GenerationTechnology:
    """Technologia wytwórcza z biblioteki M7."""

    key: str
    name_pl: str
    category: str  # cieplo | energia_elektryczna | kogeneracja
    fuel: str
    eta_el: float | None
    eta_el_range: tuple[float, float] | None
    eta_heat: float | None
    eta_heat_range: tuple[float, float] | None
    supply_temp_c: float | None
    scale_range_kw: tuple[float, float]
    capex_eur_per_kw: float
    capex_range: tuple[float, float]
    trl: int
    emission_class: str  # kopalne | alternatywne | niskoemisyjne | bezemisyjne
    source: str
    notes: tuple[str, ...] = ()

    @property
    def eta_total(self) -> float:
        """Sprawność całkowita (el. + ciepło) wg Hi."""
        return (self.eta_el or 0.0) + (self.eta_heat or 0.0)


def _typ(raw: dict) -> float:
    return float(raw["typical"])


def _rng(raw: dict) -> tuple[float, float]:
    return float(raw["min"]), float(raw["max"])


@cache
def generation_technologies() -> dict[str, GenerationTechnology]:
    """Rejestr technologii M7 z ``data/generation_technologies.yaml``."""
    raw = load_data_file("generation_technologies.yaml")["technologies"]
    result = {}
    for key, item in raw.items():
        notes = tuple(
            str(item[n])
            for n in ("eta_heat_note", "eta_el_note", "emission_note", "h2_ready_note")
            if n in item
        )
        result[key] = GenerationTechnology(
            key=key,
            name_pl=item["name_pl"],
            category=item["category"],
            fuel=item["fuel"],
            eta_el=_typ(item["eta_el"]) if "eta_el" in item else None,
            eta_el_range=_rng(item["eta_el"]) if "eta_el" in item else None,
            eta_heat=_typ(item["eta_heat"]) if "eta_heat" in item else None,
            eta_heat_range=_rng(item["eta_heat"]) if "eta_heat" in item else None,
            supply_temp_c=(float(item["supply_temp_c"]) if "supply_temp_c" in item else None),
            scale_range_kw=tuple(item["scale_range_kw"]),
            capex_eur_per_kw=_typ(item["capex_eur_per_kw"]),
            capex_range=_rng(item["capex_eur_per_kw"]),
            trl=int(item["trl"]),
            emission_class=item["emission_class"],
            source=item["source"],
            notes=notes,
        )
    return result


@cache
def _gas_fuel_g_co2_per_kwh() -> float:
    """Emisja spalania gazu E [g CO2/kWh paliwa wg Hi] — stechiometria M8."""
    return combustion_emissions(GasComposition.predefined("gaz_E_typowy")).g_co2_per_kwh_hi


def fuel_emission_g_co2_per_kwh(
    fuel: str, scenario: PriceScenario | None = None, year: int = 2030
) -> float:
    """Emisja jednostkowa nośnika [g CO2/kWh] (paliwo wg Hi; prąd wg miksu)."""
    if fuel == "gaz_ziemny":
        return _gas_fuel_g_co2_per_kwh()
    if fuel == _GRID_FUEL:
        if scenario is None:
            raise ValueError("Dla energii elektrycznej wymagany scenariusz M5 (miks).")
        return scenario.price("emisyjnosc_miksu", year) * 1e3  # t/MWh → g/kWh
    if fuel in _FREE_FUELS or fuel == "wodor":
        return 0.0
    factors = load_data_file("generation_technologies.yaml")["fuel_emission_factors_kg_co2_per_gj"]
    if fuel in factors:
        return float(factors[fuel]["value"]) * 3.6  # kg/GJ → g/kWh
    raise ValueError(f"Brak wskaźnika emisji dla paliwa '{fuel}'.")


@dataclass(frozen=True)
class TechnologyIndicators:
    """Ujednolicone wskaźniki technologii dla zadanego roku/scenariusza."""

    technology: GenerationTechnology
    g_co2_per_kwh_el: float | None
    g_co2_per_kwh_heat: float | None
    fuel_cost_pln_per_mwh_el: float | None
    fuel_cost_pln_per_mwh_heat: float | None


def technology_indicators(
    tech: GenerationTechnology, scenario: PriceScenario, year: int
) -> TechnologyIndicators:
    """Wskaźniki emisyjne i paliwowe technologii.

    Kogeneracja: nakład paliwa dzielony na produkty proporcjonalnie do ich
    udziału energetycznego (metoda energetyczna — uproszczenie; alternatywy:
    metoda elektrowni zastępczej/egzergetyczna — nota w UI).
    """
    fuel_g = fuel_emission_g_co2_per_kwh(tech.fuel, scenario, year)
    if tech.fuel in _FREE_FUELS:
        fuel_price = 0.0
    else:
        fuel_price = scenario.price(tech.fuel, year)

    eta_el, eta_heat = tech.eta_el, tech.eta_heat
    g_el = g_heat = None
    c_el = c_heat = None
    if tech.category == "kogeneracja" and eta_el and eta_heat:
        # metoda energetyczna: jednostka paliwa na jednostkę produktu = 1/η_total
        eta_total = eta_el + eta_heat
        g_el = g_heat = fuel_g / eta_total
        c_el = c_heat = fuel_price / eta_total
    else:
        if eta_el:
            g_el = fuel_g / eta_el if tech.fuel not in _FREE_FUELS else 0.0
            c_el = fuel_price / eta_el
        if eta_heat:
            g_heat = fuel_g / eta_heat if tech.fuel not in _FREE_FUELS else 0.0
            c_heat = fuel_price / eta_heat
    return TechnologyIndicators(
        technology=tech,
        g_co2_per_kwh_el=g_el,
        g_co2_per_kwh_heat=g_heat,
        fuel_cost_pln_per_mwh_el=c_el,
        fuel_cost_pln_per_mwh_heat=c_heat,
    )


def heat_source_entries() -> list[dict]:
    """Technologie cieplne M7 jako kandydaci na źródła podgrzewu gazu (M13).

    Zwraca słowniki zgodne ze strukturą ``heat_sources`` w
    ``data/reduction_stations.yaml``: temperatura zasilania, sprawność/COP,
    nośnik energii (klucz cen M5/M13).
    """
    entries = []
    for tech in generation_technologies().values():
        if tech.category not in ("cieplo", "kogeneracja") or tech.eta_heat is None:
            continue
        if tech.supply_temp_c is None:
            continue
        entry = {
            "key": f"m7_{tech.key}",
            "name_pl": f"{tech.name_pl} (M7)",
            "supply_temp_c": tech.supply_temp_c,
            "energy_carrier": ("odpadowe" if tech.fuel in _FREE_FUELS else tech.fuel),
            "source": f"Biblioteka M7: {tech.source}",
        }
        if tech.fuel == _GRID_FUEL:
            entry["cop"] = tech.eta_heat
        else:
            # kogeneracja: ciepło rozliczone metodą energetyczną
            entry["efficiency_hi"] = (
                tech.eta_total if tech.category == "kogeneracja" else tech.eta_heat
            )
        entries.append(entry)
    return entries
