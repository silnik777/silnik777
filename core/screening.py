"""Merit order i screening curves technologii wytwórczych (moduł M7).

* **Screening curve:** roczny koszt na 1 kW mocy w funkcji współczynnika
  wykorzystania (capacity factor):
      K(cf) = CAPEX/kW·CRF + OPEX_stały/kW + cf·8,760·k_zmienny [PLN/kW·rok],
  gdzie k_zmienny [PLN/MWh] = koszt paliwa/energii (÷sprawność) + koszt CO2
  (EUA). Przecięcia krzywych pokazują, która technologia jest najtańsza dla
  danego wykorzystania (podstawa vs szczyt).
* **Merit order:** uszeregowanie technologii wg krótkookresowego kosztu
  krańcowego (zmiennego) — kolejność załączania w dyspozycji.

Koszty krańcowe i emisyjne z M7 (``core.generation.technology_indicators``,
metoda energetyczna dla kogeneracji), ceny ze ścieżek M5, CRF z WACC (M10).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.generation import generation_technologies, technology_indicators
from core.prices import PriceScenario, eur_pln_rate


def _crf(wacc: float, lifetime_years: int) -> float:
    return wacc / (1.0 - (1.0 + wacc) ** -lifetime_years)


def variable_cost_pln_per_mwh(
    technology_key: str, scenario: PriceScenario, year: int, include_ets: bool = True
) -> float:
    """Krótkookresowy koszt krańcowy (zmienny) energii elektrycznej [PLN/MWh].

    Paliwo/energia ÷ sprawność (metoda energetyczna dla kogeneracji) + koszt
    CO2 (EUA) dla paliw emisyjnych. Bez CAPEX/OPEX stałego.
    """
    tech = generation_technologies()[technology_key]
    if tech.eta_el is None:
        raise ValueError(f"Technologia '{technology_key}' nie produkuje energii elektrycznej.")
    ind = technology_indicators(tech, scenario, year)
    var = ind.fuel_cost_pln_per_mwh_el or 0.0
    if include_ets and ind.g_co2_per_kwh_el:
        t_co2_per_mwh = ind.g_co2_per_kwh_el / 1e3  # g/kWh ≡ kg/MWh → /1000 = t/MWh
        var += t_co2_per_mwh / 1e3 * scenario.price_pln_per_t_co2("eua", year)
    return var


def annual_cost_per_kw(
    technology_key: str,
    scenario: PriceScenario,
    year: int,
    capacity_factor: float,
    wacc: float = 0.07,
    lifetime_years: int = 20,
    opex_pct_capex: float = 3.0,
    include_ets: bool = True,
) -> float:
    """Roczny koszt na 1 kW mocy przy zadanym współczynniku wykorzystania [PLN/kW·rok]."""
    tech = generation_technologies()[technology_key]
    capex_per_kw = tech.capex_eur_per_kw * eur_pln_rate()
    fixed = capex_per_kw * _crf(wacc, lifetime_years) + capex_per_kw * opex_pct_capex / 100.0
    var = variable_cost_pln_per_mwh(technology_key, scenario, year, include_ets)
    return fixed + capacity_factor * 8.760 * var  # 8760 kWh/kW = 8,760 MWh/kW


@dataclass(frozen=True)
class ScreeningCurve:
    """Krzywa kosztu rocznego technologii vs współczynnik wykorzystania."""

    technology_key: str
    name_pl: str
    capacity_factors: list[float]
    cost_per_kw_year: list[float]
    fixed_cost_per_kw_year: float  # przecięcie z osią (cf=0)
    variable_cost_pln_per_mwh: float


def screening_curves(
    technology_keys: list[str],
    scenario: PriceScenario,
    year: int,
    wacc: float = 0.07,
    lifetime_years: int = 20,
    opex_pct_capex: float = 3.0,
    n_points: int = 21,
    include_ets: bool = True,
) -> list[ScreeningCurve]:
    """Krzywe screeningowe dla zbioru technologii (cf od 0 do 1)."""
    techs = generation_technologies()
    cfs = [i / (n_points - 1) for i in range(n_points)]
    curves: list[ScreeningCurve] = []
    for key in technology_keys:
        capex_per_kw = techs[key].capex_eur_per_kw * eur_pln_rate()
        fixed = capex_per_kw * _crf(wacc, lifetime_years) + capex_per_kw * opex_pct_capex / 100.0
        var = variable_cost_pln_per_mwh(key, scenario, year, include_ets)
        curves.append(
            ScreeningCurve(
                technology_key=key,
                name_pl=techs[key].name_pl,
                capacity_factors=cfs,
                cost_per_kw_year=[fixed + cf * 8.760 * var for cf in cfs],
                fixed_cost_per_kw_year=fixed,
                variable_cost_pln_per_mwh=var,
            )
        )
    return curves


@dataclass(frozen=True)
class MeritOrderEntry:
    """Pozycja w merit order (uszeregowaniu wg kosztu krańcowego)."""

    technology_key: str
    name_pl: str
    marginal_cost_pln_per_mwh: float
    g_co2_per_kwh_el: float | None


def merit_order(
    technology_keys: list[str],
    scenario: PriceScenario,
    year: int,
    include_ets: bool = True,
) -> list[MeritOrderEntry]:
    """Uszeregowanie technologii wg krótkookresowego kosztu krańcowego (rosnąco)."""
    techs = generation_technologies()
    entries = []
    for key in technology_keys:
        if techs[key].eta_el is None:
            continue
        ind = technology_indicators(techs[key], scenario, year)
        entries.append(
            MeritOrderEntry(
                technology_key=key,
                name_pl=techs[key].name_pl,
                marginal_cost_pln_per_mwh=variable_cost_pln_per_mwh(
                    key, scenario, year, include_ets
                ),
                g_co2_per_kwh_el=ind.g_co2_per_kwh_el,
            )
        )
    return sorted(entries, key=lambda e: e.marginal_cost_pln_per_mwh)
