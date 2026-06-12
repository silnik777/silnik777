"""Benchmarking technologii na wspólnych wskaźnikach — moduł M11.

Porównanie technologii gazowych/wodorowych z PV, wiatrem, biomasą,
pompami ciepła i magazynami bateryjnymi:
    * LCOE/LCOH [PLN/MWh] — z silnika M10 (ceny ze ścieżek M5),
    * emisje [g CO2eq/kWh] — metodyka M7/M8 (gaz stechiometrycznie,
      prąd wg miksu, biomasa biogeniczna 0),
    * dyspozycyjność [0–1] — ocena zdolności pracy na żądanie
      (``data/benchmark_extras.yaml``, edytowalna),
    * TRL [1–9].

Ranking wielokryterialny: normalizacja min–max każdego kryterium do 0–1
(koszt i emisje: niższe = lepsze; dyspozycyjność i TRL: wyższe = lepsze),
suma ważona wagami użytkownika (domyślnie równe — uzgodnione).
LCOS magazynu bateryjnego:
    LCOS = (CAPEX·CRF + OPEX + koszt ładowania) / energia oddana rocznie,
    koszt ładowania = cena energii × przepustowość / sprawność round-trip.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.config import load_data_file
from core.economics import DEFAULT_WACC, lcoe_for_technology
from core.generation import generation_technologies, technology_indicators
from core.prices import PriceScenario, eur_pln_rate


@dataclass(frozen=True)
class BenchmarkEntry:
    """Technologia w rankingu — wspólne wskaźniki."""

    key: str
    name_pl: str
    lcox_pln_per_mwh: float
    co2_g_per_kwh: float
    dispatchability: float  # 0–1
    trl: int


@cache
def _extras() -> dict:
    return load_data_file("benchmark_extras.yaml")


def battery_lcos_pln_per_mwh(
    scenario: PriceScenario, year: int, wacc: float = DEFAULT_WACC
) -> float:
    """LCOS magazynu bateryjnego [PLN/MWh energii oddanej].

    Wzór: (CAPEX·CRF + OPEX + E_ład·cena_el) / E_oddana;
    E_oddana = pojemność × cykle/rok; E_ład = E_oddana / η_RT.
    """
    bat = _extras()["battery_storage"]
    capex_kwh = float(bat["capex_eur_per_kwh"]["typical"]) * eur_pln_rate()
    n = int(bat["lifetime_years"])
    crf = wacc / (1.0 - (1.0 + wacc) ** -n)
    cycles = float(bat["cycles_per_year"])
    rt = float(bat["round_trip_efficiency"])
    el_price = scenario.price("energia_elektryczna", year)

    discharged_mwh_per_mwh_cap = cycles  # MWh oddane rocznie na 1 MWh pojemności
    capex_term = capex_kwh * 1e3 * crf  # PLN/rok na MWh pojemności
    opex_term = capex_kwh * 1e3 * float(bat["opex_pct_capex_per_year"]) / 100.0
    charging = discharged_mwh_per_mwh_cap / rt * el_price
    return (capex_term + opex_term + charging) / discharged_mwh_per_mwh_cap


#: Technologie z M7 ujęte w rankingu (produkcja energii elektrycznej).
_RANKED_M7 = ("pv", "wiatr_ladowy", "ccgt", "silnik_kogeneracyjny", "ogniwo_pemfc", "silnik_h2")


def build_benchmark_entries(
    scenario: PriceScenario, year: int = 2030, wacc: float = DEFAULT_WACC
) -> list[BenchmarkEntry]:
    """Wskaźniki rankingowe dla technologii M7 + magazynu bateryjnego."""
    dispatch = _extras()["dispatchability"]
    techs = generation_technologies()
    entries: list[BenchmarkEntry] = []
    for key in _RANKED_M7:
        tech = techs[key]
        lcoe = lcoe_for_technology(key, scenario, start_year=year, wacc=wacc).lcox
        ind = technology_indicators(tech, scenario, year)
        entries.append(
            BenchmarkEntry(
                key=key,
                name_pl=tech.name_pl,
                lcox_pln_per_mwh=lcoe,
                co2_g_per_kwh=ind.g_co2_per_kwh_el or 0.0,
                dispatchability=float(dispatch[key]),
                trl=tech.trl,
            )
        )
    bat = _extras()["battery_storage"]
    grid_g = scenario.price("emisyjnosc_miksu", year) * 1e3
    rt = float(bat["round_trip_efficiency"])
    entries.append(
        BenchmarkEntry(
            key="bateria",
            name_pl=bat["name_pl"],
            lcox_pln_per_mwh=battery_lcos_pln_per_mwh(scenario, year, wacc),
            co2_g_per_kwh=grid_g / rt,  # ładowanie z sieci (zakres 2)
            dispatchability=float(dispatch["bateria"]),
            trl=int(bat["trl"]),
        )
    )
    return entries


@dataclass(frozen=True)
class RankedEntry:
    """Pozycja rankingu wielokryterialnego."""

    entry: BenchmarkEntry
    score: float  # 0–1 (wyżej = lepiej)
    criterion_scores: dict[str, float]


DEFAULT_WEIGHTS = {
    "koszt": 0.25,
    "emisje": 0.25,
    "dyspozycyjnosc": 0.25,
    "trl": 0.25,
}


def rank_technologies(
    entries: list[BenchmarkEntry],
    weights: dict[str, float] | None = None,
) -> list[RankedEntry]:
    """Ranking wielokryterialny (normalizacja min–max, suma ważona).

    Args:
        entries: wskaźniki technologii (``build_benchmark_entries``),
        weights: wagi kryteriów {koszt, emisje, dyspozycyjnosc, trl};
            domyślnie równe (0,25) — uzgodnione; suma musi być > 0.
    """
    if not entries:
        raise ValueError("Brak technologii do rankingu.")
    w = dict(DEFAULT_WEIGHTS if weights is None else weights)
    unknown = set(w) - set(DEFAULT_WEIGHTS)
    if unknown:
        raise ValueError(f"Nieznane kryteria wag: {', '.join(unknown)}.")
    total_w = sum(w.values())
    if total_w <= 0:
        raise ValueError("Suma wag musi być dodatnia.")
    w = {k: v / total_w for k, v in w.items()}

    def norm(values: list[float], lower_better: bool) -> list[float]:
        lo, hi = min(values), max(values)
        if hi - lo < 1e-12:
            return [1.0] * len(values)
        scores = [(v - lo) / (hi - lo) for v in values]
        return [1.0 - s for s in scores] if lower_better else scores

    costs = norm([e.lcox_pln_per_mwh for e in entries], lower_better=True)
    emissions = norm([e.co2_g_per_kwh for e in entries], lower_better=True)
    dispatch = norm([e.dispatchability for e in entries], lower_better=False)
    trl = norm([float(e.trl) for e in entries], lower_better=False)

    ranked = []
    for i, entry in enumerate(entries):
        criterion = {
            "koszt": costs[i],
            "emisje": emissions[i],
            "dyspozycyjnosc": dispatch[i],
            "trl": trl[i],
        }
        score = sum(w.get(k, 0.0) * v for k, v in criterion.items())
        ranked.append(RankedEntry(entry=entry, score=score, criterion_scores=criterion))
    return sorted(ranked, key=lambda r: -r.score)
