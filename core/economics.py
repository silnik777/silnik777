"""Ekonomia projektów: NPV/IRR/DPP, koszty uśrednione LCOx, tornado — M10.

Metodyka (standard analiz techniczno-ekonomicznych energetyki):
    * NPV = Σ_t CF_t / (1+r)^t,  r — WACC realny (domyślnie 7%),
    * IRR — stopa zerująca NPV (bisekcja; None, gdy brak zmiany znaku),
    * DPP — zdyskontowany okres zwrotu (interpolowany; None, gdy brak),
    * koszt uśredniony (levelized):
          LCOx = Σ_t (K_t·d_t) / Σ_t (Q_t·d_t),   d_t = (1+r)^-t,
      gdzie K_t — koszty roku t (CAPEX wg harmonogramu, OPEX, energia,
      CO2, minus przychody uboczne), Q_t — produkcja (MWh, kg H2, ...);
      równoważnie dla stałych strumieni: LCOx = CAPEX·CRF/Q + OPEX/Q + ...,
      CRF = r/(1−(1+r)^−N) — test walidacyjny porównuje obie drogi,
    * wartość rezydualna: amortyzacja liniowa do zera w czasie życia
      aktywa — gdy okres analizy < czas życia, rezydualna trafia jako
      przychód w ostatnim roku,
    * analiza wrażliwości: tornado ±20% (konfigurowalne) na parametrach
      wejściowych funkcji celu.

Założenia domyślne uzgodnione z użytkownikiem: WACC 7% (realny), okres
analizy 20 lat, rezydualna liniowa do zera. Ceny nośników i CO2 —
ścieżki scenariuszy M5 (ceny realne; spójność z realnym WACC).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from core.prices import PriceScenario

DEFAULT_WACC = 0.07
DEFAULT_LIFETIME_YEARS = 20


# --- Podstawowe wskaźniki ----------------------------------------------------


def npv(cash_flows: Mapping[int, float], wacc: float = DEFAULT_WACC) -> float:
    """Wartość bieżąca netto strumienia {rok względny: CF [PLN]}."""
    if wacc <= -1.0:
        raise ValueError("WACC musi być większy od −100%.")
    return sum(cf / (1.0 + wacc) ** t for t, cf in cash_flows.items())


def irr(cash_flows: Mapping[int, float], tol: float = 1e-7) -> float | None:
    """Wewnętrzna stopa zwrotu (bisekcja w przedziale −99%…300%).

    Returns:
        IRR albo None, gdy NPV nie zmienia znaku w przedziale (projekt
        bez zwrotu albo zawsze dodatni).
    """
    lo, hi = -0.99, 3.0
    f_lo, f_hi = npv(cash_flows, lo), npv(cash_flows, hi)
    if f_lo * f_hi > 0:
        return None
    for _ in range(200):
        mid = (lo + hi) / 2.0
        f_mid = npv(cash_flows, mid)
        if abs(f_mid) < tol or hi - lo < tol:
            return mid
        if f_lo * f_mid <= 0:
            hi, f_hi = mid, f_mid
        else:
            lo, f_lo = mid, f_mid
    return (lo + hi) / 2.0


def discounted_payback_years(
    cash_flows: Mapping[int, float], wacc: float = DEFAULT_WACC
) -> float | None:
    """Zdyskontowany okres zwrotu [lata] (interpolacja liniowa w roku zwrotu)."""
    cumulative = 0.0
    previous = 0.0
    for t in sorted(cash_flows):
        previous = cumulative
        cumulative += cash_flows[t] / (1.0 + wacc) ** t
        if previous < 0.0 <= cumulative:
            year_cf = cumulative - previous
            return t - cumulative / year_cf if year_cf > 0 else float(t)
    return None


def residual_value_pln(capex_pln: float, asset_life_years: float, analysis_years: float) -> float:
    """Wartość rezydualna: amortyzacja liniowa do zera w czasie życia aktywa."""
    if asset_life_years <= 0:
        raise ValueError("Czas życia aktywa musi być dodatni.")
    if analysis_years >= asset_life_years:
        return 0.0
    return capex_pln * (1.0 - analysis_years / asset_life_years)


# --- Koszt uśredniony (levelized) -------------------------------------------


@dataclass(frozen=True)
class LevelizedCostResult:
    """Wynik kosztu uśrednionego z dekompozycją składników."""

    lcox: float  # [PLN/jedn. produkcji]
    components: dict[str, float]  # dekompozycja LCOx na składniki
    discounted_output: float
    cash_flows: dict[int, float]  # koszty(−)/przychody(+) bez sprzedaży produktu


def levelized_cost(
    capex_pln: float,
    output_per_year: Mapping[int, float] | float,
    costs_per_year: Mapping[str, Mapping[int, float] | float],
    wacc: float = DEFAULT_WACC,
    lifetime_years: int = DEFAULT_LIFETIME_YEARS,
    capex_schedule: Mapping[int, float] | None = None,
    revenues_per_year: Mapping[str, Mapping[int, float] | float] | None = None,
    asset_life_years: float | None = None,
) -> LevelizedCostResult:
    """Koszt uśredniony produkcji LCOx = Σ koszty·d / Σ produkcja·d.

    Args:
        capex_pln: nakłady inwestycyjne łącznie [PLN],
        output_per_year: produkcja roczna (stała liczba albo {rok: ilość});
            lata 1..N,
        costs_per_year: {nazwa składnika: koszt roczny [PLN] (stały albo
            {rok: PLN})} — np. OPEX, energia, CO2,
        wacc: stopa dyskontowa realna,
        lifetime_years: okres analizy N,
        capex_schedule: {rok względny ≤ 0 lub 1..: udział CAPEX}; domyślnie
            całość w roku 0,
        revenues_per_year: przychody uboczne (ciepło odpadowe, O2, węgiel
            z pirolizy) — pomniejszają LCOx (metoda kosztu netto),
        asset_life_years: czas życia aktywa dla wartości rezydualnej
            (None = równy okresowi analizy ⇒ rezydualna 0).

    Raises:
        ValueError: produkcja zdyskontowana ≤ 0 albo błędny harmonogram.
    """
    if capex_pln < 0:
        raise ValueError("CAPEX nie może być ujemny.")
    schedule = dict(capex_schedule) if capex_schedule else {0: 1.0}
    if abs(sum(schedule.values()) - 1.0) > 1e-6:
        raise ValueError(
            f"Harmonogram CAPEX musi sumować się do 1 (jest {sum(schedule.values()):.4f})."
        )

    years = range(1, lifetime_years + 1)

    def annual(value: Mapping[int, float] | float, year: int) -> float:
        if isinstance(value, Mapping):
            return float(value.get(year, 0.0))
        return float(value)

    disc = {t: (1.0 + wacc) ** -t for t in range(min(min(schedule), 0), lifetime_years + 1)}

    discounted_output = sum(annual(output_per_year, t) * disc[t] for t in years)
    if discounted_output <= 0:
        raise ValueError("Zdyskontowana produkcja musi być dodatnia.")

    components: dict[str, float] = {}
    cash_flows: dict[int, float] = {}

    capex_disc = sum(capex_pln * share * disc[t] for t, share in schedule.items())
    components["CAPEX"] = capex_disc / discounted_output
    for t, share in schedule.items():
        cash_flows[t] = cash_flows.get(t, 0.0) - capex_pln * share

    for name, value in costs_per_year.items():
        comp_disc = sum(annual(value, t) * disc[t] for t in years)
        components[name] = comp_disc / discounted_output
        for t in years:
            cash_flows[t] = cash_flows.get(t, 0.0) - annual(value, t)

    if revenues_per_year:
        for name, value in revenues_per_year.items():
            comp_disc = sum(annual(value, t) * disc[t] for t in years)
            components[f"− {name}"] = -comp_disc / discounted_output
            for t in years:
                cash_flows[t] = cash_flows.get(t, 0.0) + annual(value, t)

    if asset_life_years is not None:
        residual = residual_value_pln(capex_pln, asset_life_years, lifetime_years)
        if residual > 0:
            components["− wartość rezydualna"] = (
                -residual * disc[lifetime_years] / (discounted_output)
            )
            cash_flows[lifetime_years] = cash_flows.get(lifetime_years, 0.0) + residual

    return LevelizedCostResult(
        lcox=sum(components.values()),
        components=components,
        discounted_output=discounted_output,
        cash_flows=cash_flows,
    )


def project_metrics(
    levelized: LevelizedCostResult,
    product_price_per_unit: float,
    output_per_year: Mapping[int, float] | float,
    wacc: float = DEFAULT_WACC,
    lifetime_years: int = DEFAULT_LIFETIME_YEARS,
) -> dict[str, float | None]:
    """NPV/IRR/DPP projektu przy zadanej cenie sprzedaży produktu."""

    def annual(value: Mapping[int, float] | float, year: int) -> float:
        if isinstance(value, Mapping):
            return float(value.get(year, 0.0))
        return float(value)

    cf = dict(levelized.cash_flows)
    for t in range(1, lifetime_years + 1):
        cf[t] = cf.get(t, 0.0) + product_price_per_unit * annual(output_per_year, t)
    return {
        "npv_pln": npv(cf, wacc),
        "irr": irr(cf),
        "dpp_years": discounted_payback_years(cf, wacc),
    }


# --- Analiza wrażliwości (tornado) ------------------------------------------


@dataclass(frozen=True)
class TornadoEntry:
    """Wpływ ±zmiany jednego parametru na wynik funkcji celu."""

    parameter: str
    low_value: float
    high_value: float
    base_value: float

    @property
    def span(self) -> float:
        return abs(self.high_value - self.low_value)


def tornado_analysis(
    base_params: Mapping[str, float],
    evaluate: Callable[[Mapping[str, float]], float],
    relative_change: float = 0.20,
) -> list[TornadoEntry]:
    """Analiza tornado: każdy parametr ±``relative_change`` (domyślnie ±20%).

    Returns:
        Lista posortowana malejąco po rozpiętości wpływu.
    """
    base = evaluate(base_params)
    entries = []
    for name in base_params:
        low = dict(base_params)
        high = dict(base_params)
        low[name] = base_params[name] * (1.0 - relative_change)
        high[name] = base_params[name] * (1.0 + relative_change)
        entries.append(
            TornadoEntry(
                parameter=name,
                low_value=evaluate(low),
                high_value=evaluate(high),
                base_value=base,
            )
        )
    return sorted(entries, key=lambda e: -e.span)


# --- Wygodne kalkulatory LCOH / LCOE na bazie M5/M6/M7 ----------------------


def lcoh_for_technology(
    technology_key: str,
    scenario: PriceScenario,
    start_year: int = 2030,
    production_kg_per_h: float = 100.0,
    capacity_factor: float = 0.9,
    wacc: float = DEFAULT_WACC,
    lifetime_years: int = DEFAULT_LIFETIME_YEARS,
    include_ets: bool = True,
    o2_revenue_pln_per_kg_h2: float = 0.0,
    heat_revenue_pln_per_year: float = 0.0,
) -> LevelizedCostResult:
    """LCOH [PLN/kg H2] dla technologii z M6, ceny ze ścieżek M5.

    Koszty roczne liczone po latach kalendarzowych ``start_year + t``:
    energia elektryczna i gaz wg ścieżek cen, CO2 (zakres 1) × EUA;
    degradacja zwiększa zużycie energii elektrycznej w czasie.
    """
    from core.hydrogen import hydrogen_technologies
    from core.prices import eur_pln_rate

    tech = hydrogen_technologies()[technology_key]
    hours = 8760.0 * capacity_factor
    kg_year = production_kg_per_h * hours

    power_kw = tech.electricity_kwh_per_kg * production_kg_per_h
    if tech.capex_basis == "kW energii elektrycznej":
        capex = power_kw * tech.capex_eur_per_kw * eur_pln_rate()
    else:  # na kW H2 (Hi)
        from core.hydrogen import h2_lhv_kwh_per_kg

        capex = production_kg_per_h * h2_lhv_kwh_per_kg() * tech.capex_eur_per_kw * eur_pln_rate()

    el_costs, gas_costs, co2_costs = {}, {}, {}
    for t in range(1, lifetime_years + 1):
        year = start_year + t - 1
        degr = 1.0 + tech.degradation_pct_per_year / 100.0 * (t - 1)
        el_mwh = tech.electricity_kwh_per_kg * degr * kg_year / 1e3
        el_costs[t] = el_mwh * scenario.price("energia_elektryczna", year)
        gas_costs[t] = tech.fuel_gas_kwh_per_kg * kg_year / 1e3 * scenario.price("gaz_ziemny", year)
        if include_ets:
            co2_costs[t] = (
                tech.direct_co2_kg_per_kg_h2
                * kg_year
                / 1e3
                * scenario.price_pln_per_t_co2("eua", year)
            )

    costs: dict[str, Mapping[int, float] | float] = {
        "OPEX": capex * tech.opex_pct_capex_per_year / 100.0,
        "energia elektryczna": el_costs,
        "gaz ziemny": gas_costs,
    }
    if include_ets:
        costs["CO2 (EUA)"] = co2_costs
    revenues: dict[str, Mapping[int, float] | float] = {}
    if o2_revenue_pln_per_kg_h2 > 0:
        revenues["tlen"] = o2_revenue_pln_per_kg_h2 * kg_year
    if heat_revenue_pln_per_year > 0:
        revenues["ciepło odpadowe"] = heat_revenue_pln_per_year

    return levelized_cost(
        capex_pln=capex,
        output_per_year=kg_year,
        costs_per_year=costs,
        wacc=wacc,
        lifetime_years=lifetime_years,
        revenues_per_year=revenues or None,
    )


def lcoe_for_technology(
    technology_key: str,
    scenario: PriceScenario,
    start_year: int = 2030,
    capacity_kw: float = 1000.0,
    wacc: float = DEFAULT_WACC,
    lifetime_years: int = DEFAULT_LIFETIME_YEARS,
    opex_pct_capex: float = 3.0,
    include_ets: bool = True,
) -> LevelizedCostResult:
    """LCOE [PLN/MWh el.] dla technologii elektrycznych/kogeneracyjnych z M7.

    Produkcja = moc × cf (PV/wiatr: cf z biblioteki; paliwowe: cf 0,85).
    Kogeneracja — SPÓJNA alokacja metodą energetyczną (jak w M7): paliwo,
    CO2 ORAZ CAPEX/OPEX obciążają energię elektryczną proporcjonalnie do
    jej udziału energetycznego (η_el/η_całk); wynik = LCOE części
    elektrycznej wg metody energetycznej (alternatywy: metoda elektrowni
    zastępczej, kredyt ciepła — poza zakresem, nota w UI).
    """
    from core.generation import fuel_emission_g_co2_per_kwh, generation_technologies
    from core.prices import eur_pln_rate

    tech = generation_technologies()[technology_key]
    if tech.eta_el is None:
        raise ValueError(f"Technologia '{technology_key}' nie produkuje energii elektrycznej.")

    free_fuel = tech.fuel in ("slonce", "wiatr")
    cf = tech.eta_el if free_fuel else 0.85
    mwh_year = capacity_kw * 8760.0 * cf / 1e3
    capex = capacity_kw * tech.capex_eur_per_kw * eur_pln_rate()
    if tech.category == "kogeneracja" and tech.eta_heat:
        # alokacja energetyczna CAPEX na produkt elektryczny
        capex *= tech.eta_el / tech.eta_total

    fuel_costs, co2_costs = {}, {}
    eta_basis = tech.eta_total if tech.category == "kogeneracja" else tech.eta_el
    for t in range(1, lifetime_years + 1):
        year = start_year + t - 1
        if not free_fuel:
            fuel_costs[t] = mwh_year / eta_basis * scenario.price(tech.fuel, year)
            if include_ets and tech.fuel != "energia_elektryczna":
                g_per_kwh = fuel_emission_g_co2_per_kwh(tech.fuel, scenario, year)
                t_co2 = mwh_year / eta_basis * g_per_kwh / 1e3  # g/kWh ≡ kg/MWh
                co2_costs[t] = t_co2 / 1e3 * scenario.price_pln_per_t_co2("eua", year)

    costs: dict[str, Mapping[int, float] | float] = {
        "OPEX": capex * opex_pct_capex / 100.0,
    }
    if fuel_costs:
        costs["paliwo"] = fuel_costs
    if co2_costs:
        costs["CO2 (EUA)"] = co2_costs

    return levelized_cost(
        capex_pln=capex,
        output_per_year=mwh_year,
        costs_per_year=costs,
        wacc=wacc,
        lifetime_years=lifetime_years,
    )


# --- Mostek M4/M13 → M10: opłacalność ekspandera na stacji redukcyjnej ------


@dataclass(frozen=True)
class ExpanderEconomicsResult:
    """Opłacalność ekspandera na stacji (przyrostowo względem wariantu JT)."""

    capex_pln: float
    annual_energy_mwh: float
    extra_heat_mwh_per_year: float  # dodatkowy podgrzew ponad wariant JT
    lcoe_pln_per_mwh: float  # koszt uśredniony energii z ekspandera
    components: dict[str, float]
    npv_pln: float
    irr: float | None
    dpp_years: float | None


def expander_station_economics(
    expander_variant,
    jt_variant,
    technology,
    heat_source,
    scenario: PriceScenario,
    start_year: int = 2030,
    hours_per_year: float = 8000.0,
    wacc: float = DEFAULT_WACC,
    lifetime_years: int = DEFAULT_LIFETIME_YEARS,
    opex_pct_capex: float = 3.0,
) -> ExpanderEconomicsResult:
    """Ekonomika ekspandera na stacji redukcyjnej (integracja M13+M4→M10).

    Rachunek PRZYROSTOWY względem stanu istniejącego (wariant JT):
        * CAPEX = moc odzyskana × CAPEX/kW technologii (biblioteka M4),
        * koszt roczny = OPEX (% CAPEX) + DODATKOWY podgrzew ponad wariant
          JT (ekspansja chłodzi silniej) wyceniony wg źródła ciepła M13
          i ścieżek cen M5 po latach kalendarzowych,
        * produkt = energia elektryczna odzyskana [MWh/rok],
        * NPV/IRR/DPP przy przychodzie = energia × cena energii ze ścieżki
          M5 (rok po roku).

    Args:
        expander_variant, jt_variant: wyniki ``station_balance`` (M13),
        technology: ``ExpanderTechnology`` (M4),
        heat_source: ``HeatSource`` (M13/M7/M2),
        scenario: scenariusz cenowy M5 (jedno źródło prawdy cen).
    """
    from core.cold_reduction import _resolve_prices
    from core.prices import eur_pln_rate

    power_kw = expander_variant.power_recovered_w / 1e3
    if power_kw <= 0:
        raise ValueError("Wariant ekspanderowy nie odzyskuje mocy — brak projektu.")
    capex = power_kw * technology.capex_eur_per_kw_typical * eur_pln_rate()
    annual_mwh = power_kw / 1e3 * hours_per_year
    extra_heat_mwh = (
        max(0.0, expander_variant.preheat_duty_w - jt_variant.preheat_duty_w) / 1e6 * hours_per_year
    )

    heat_costs: dict[int, float] = {}
    revenues_by_year: dict[int, float] = {}
    for t in range(1, lifetime_years + 1):
        year = start_year + t - 1
        prices, _ = _resolve_prices(scenario, year)
        carrier_price = prices[heat_source.energy_carrier]
        heat_costs[t] = extra_heat_mwh * heat_source.energy_input_per_heat() * carrier_price
        revenues_by_year[t] = annual_mwh * scenario.price("energia_elektryczna", year)

    levelized = levelized_cost(
        capex_pln=capex,
        output_per_year=annual_mwh,
        costs_per_year={
            "OPEX": capex * opex_pct_capex / 100.0,
            "dodatkowy podgrzew (vs JT)": heat_costs,
        },
        wacc=wacc,
        lifetime_years=lifetime_years,
    )
    cash_flows = dict(levelized.cash_flows)
    for t, revenue in revenues_by_year.items():
        cash_flows[t] = cash_flows.get(t, 0.0) + revenue
    return ExpanderEconomicsResult(
        capex_pln=capex,
        annual_energy_mwh=annual_mwh,
        extra_heat_mwh_per_year=extra_heat_mwh,
        lcoe_pln_per_mwh=levelized.lcox,
        components=levelized.components,
        npv_pln=npv(cash_flows, wacc),
        irr=irr(cash_flows),
        dpp_years=discounted_payback_years(cash_flows, wacc),
    )


# --- LCOHeat (koszt uśredniony ciepła, technologie cieplne M7) ---------------


def lcoheat_for_technology(
    technology_key: str,
    scenario: PriceScenario,
    start_year: int = 2030,
    capacity_kw_heat: float = 1000.0,
    capacity_factor: float = 0.5,
    wacc: float = DEFAULT_WACC,
    lifetime_years: int = DEFAULT_LIFETIME_YEARS,
    opex_pct_capex: float = 2.5,
    include_ets: bool = True,
) -> LevelizedCostResult:
    """LCOHeat [PLN/MWh ciepła] dla technologii cieplnej z M7 (kategoria „cieplo").

    Produkcja ciepła = moc cieplna × 8760 × cf. Koszt nośnika na MWh ciepła
    = cena paliwa/energii ÷ sprawność cieplną (dla pomp ciepła η_heat = COP,
    więc dzielimy przez COP); dla paliw kopalnych doliczany koszt CO2 (EUA,
    zakres 1). Dla paliw darmowych (słońce) i energii elektrycznej emisje nie
    są liczone bezpośrednio (energia el. — zakres 2, ujęty w cenie).

    CAPEX = moc cieplna × CAPEX/kW (biblioteka M7 — nakłady na kW ciepła).
    Kogeneracja obsługiwana przez alokację energetyczną w M10 (LCOE) i M13 —
    tu wspieramy technologie stricte cieplne.

    Raises:
        ValueError: technologia nie produkuje ciepła albo jest kogeneracją.
    """
    from core.generation import generation_technologies, technology_indicators
    from core.prices import eur_pln_rate

    tech = generation_technologies()[technology_key]
    if tech.eta_heat is None:
        raise ValueError(f"Technologia '{technology_key}' nie produkuje ciepła.")
    if tech.category != "cieplo":
        raise ValueError(
            f"LCOHeat wspiera technologie cieplne (kategoria „cieplo”); "
            f"'{technology_key}' to '{tech.category}' — ciepło kogeneracji rozliczane "
            "metodą energetyczną w M10/M13."
        )

    mwh_heat_year = capacity_kw_heat * 8760.0 * capacity_factor / 1e3
    capex = capacity_kw_heat * tech.capex_eur_per_kw * eur_pln_rate()

    fuel_costs, co2_costs = {}, {}
    for t in range(1, lifetime_years + 1):
        year = start_year + t - 1
        ind = technology_indicators(tech, scenario, year)
        if ind.fuel_cost_pln_per_mwh_heat:
            fuel_costs[t] = ind.fuel_cost_pln_per_mwh_heat * mwh_heat_year
        if include_ets and tech.fuel not in ("slonce", "wiatr", "energia_elektryczna"):
            if ind.g_co2_per_kwh_heat:
                t_co2 = mwh_heat_year * ind.g_co2_per_kwh_heat / 1e3  # g/kWh ≡ kg/MWh
                co2_costs[t] = t_co2 / 1e3 * scenario.price_pln_per_t_co2("eua", year)

    costs: dict[str, Mapping[int, float] | float] = {"OPEX": capex * opex_pct_capex / 100.0}
    if fuel_costs:
        costs["paliwo/energia"] = fuel_costs
    if co2_costs:
        costs["CO2 (EUA)"] = co2_costs

    return levelized_cost(
        capex_pln=capex,
        output_per_year=mwh_heat_year,
        costs_per_year=costs,
        wacc=wacc,
        lifetime_years=lifetime_years,
    )


# --- LCOS (koszt uśredniony magazynowania energii) --------------------------


@dataclass(frozen=True)
class StorageCostResult:
    """LCOS z dekompozycją i kluczowymi wielkościami cyklu."""

    lcos_pln_per_mwh: float
    components: dict[str, float]  # CAPEX / OPEX / energia ładowania [PLN/MWh]
    annual_discharged_mwh: float
    annual_charged_mwh: float


def lcos_for_storage(
    capex_pln: float,
    energy_capacity_mwh: float,
    round_trip_efficiency: float,
    cycles_per_year: float,
    charge_price_pln_per_mwh: float,
    wacc: float = DEFAULT_WACC,
    lifetime_years: int = DEFAULT_LIFETIME_YEARS,
    opex_pct_capex: float = 2.0,
    depth_of_discharge: float = 1.0,
) -> StorageCostResult:
    """LCOS [PLN/MWh rozładowanej] — koszt uśredniony magazynowania energii.

    LCOS = (CAPEX·CRF + OPEX + koszt ładowania) / energia rozładowana rocznie,
    gdzie energia rozładowana = pojemność × głębokość × liczba cykli,
    energia ładowania = rozładowana / sprawność round-trip (straty cyklu),
    koszt ładowania = energia ładowania × cena energii.

    Model dla linepacku/CAES (M12) i porównań z bateriami/PHES (M11):
    pojemność i round-trip z M12; CAPEX i cykle — wejście użytkownika.

    Args:
        capex_pln: nakłady łączne na magazyn [PLN],
        energy_capacity_mwh: pojemność energetyczna (na cykl),
        round_trip_efficiency: sprawność round-trip (0–1),
        cycles_per_year: liczba pełnych cykli rocznie,
        charge_price_pln_per_mwh: cena energii ładowania (M5),
        depth_of_discharge: głębokość rozładowania (0–1).

    Raises:
        ValueError: parametry poza zakresem fizycznym.
    """
    if energy_capacity_mwh <= 0 or cycles_per_year <= 0:
        raise ValueError("Pojemność i liczba cykli muszą być dodatnie.")
    if not 0.0 < round_trip_efficiency <= 1.0:
        raise ValueError("Sprawność round-trip musi być w (0, 1].")
    if not 0.0 < depth_of_discharge <= 1.0:
        raise ValueError("Głębokość rozładowania musi być w (0, 1].")

    discharged = energy_capacity_mwh * depth_of_discharge * cycles_per_year
    charged = discharged / round_trip_efficiency
    charge_cost = charged * charge_price_pln_per_mwh

    res = levelized_cost(
        capex_pln=capex_pln,
        output_per_year=discharged,
        costs_per_year={
            "OPEX": capex_pln * opex_pct_capex / 100.0,
            "energia ładowania": charge_cost,
        },
        wacc=wacc,
        lifetime_years=lifetime_years,
    )
    return StorageCostResult(
        lcos_pln_per_mwh=res.lcox,
        components=res.components,
        annual_discharged_mwh=discharged,
        annual_charged_mwh=charged,
    )
