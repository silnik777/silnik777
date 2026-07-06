"""Bilans stacji redukcyjnej i zimna redukcja — moduł M13.

Warianty pracy stacji (p1, T1) → (p2, T_min):

* **JT z podgrzewem (klasyczny):** dławienie izentalpowe; wymagana
  temperatura przed redukcją z bilansu entalpii (h = const):
      h(p1, T1_req) = h(p2, T_min)  ⇒  T1_req z flashu (p1, h_target),
* **ekspander z podgrzewem (M4):** odzysk energii elektrycznej; T1_req
  z bisekcji (rozprężanie chłodzi mocniej niż JT ⇒ większy podgrzew),
* **zimna redukcja:** bez podgrzewu; chłód na wylocie jako produkt
  (potencjał odzysku chłodu względem temperatury otoczenia), oszczędność
  ciepła podgrzewu; flagi ryzyka hydratów (core.hydrates) i oblodzenia.

Minimalna temperatura wylotowa: domyślnie T_hyd(p2) + margines
(``data/expanders.yaml``); konfigurowalna (np. 0 °C — ochrona armatury
i gruntu, wymagania odbiorców).

Źródła ciepła podgrzewu (``data/reduction_stations.yaml``): temperatura
zasilania źródła ogranicza osiągalny podgrzew gazu:
    T1_req ≤ T_zasilania − pinch (domyślnie 10 K).
Proste porównanie kosztowe wg roboczych cen energii (pełne ścieżki — M5/M10).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.composition import GasComposition
from core.config import load_data_file
from core.expanders import ExpansionResult, expand
from core.gas_properties import _abstract_state, flash_ph, update_state_pt
from core.hydrates import HydrateCheck, check_hydrates


@dataclass(frozen=True)
class HeatSource:
    """Źródło ciepła podgrzewu gazu (``data/reduction_stations.yaml`` albo
    zbudowane z policzonego sprężania M2 — ``heat_source_from_compression``)."""

    key: str
    name_pl: str
    supply_temp_c: float
    energy_carrier: str
    efficiency_hi: float | None  # sprawność paliwowa (kotły/CHP)
    cop: float | None  # COP (pompa ciepła, grzałki)
    source: str
    note: str | None = None
    available_kw: float | None = None  # limit mocy cieplnej (None = bez limitu)

    def max_gas_temp_k(self, pinch_k: float) -> float:
        """Maksymalna osiągalna temperatura gazu po podgrzewie [K]."""
        return self.supply_temp_c + 273.15 - pinch_k

    def energy_input_per_heat(self) -> float:
        """Jednostkowe zużycie nośnika energii na 1 MWh ciepła [MWh/MWh]."""
        if self.cop is not None:
            return 1.0 / self.cop
        if self.efficiency_hi is not None:
            return 1.0 / self.efficiency_hi
        return 1.0


@cache
def heat_sources() -> dict[str, HeatSource]:
    """Rejestr źródeł ciepła: baza z ``data/reduction_stations.yaml``
    + technologie cieplne z biblioteki M7 (``core.generation``)."""
    raw = load_data_file("reduction_stations.yaml")["heat_sources"]
    result = {
        key: HeatSource(
            key=key,
            name_pl=item["name_pl"],
            supply_temp_c=float(item["supply_temp_c"]),
            energy_carrier=item["energy_carrier"],
            efficiency_hi=(float(item["efficiency_hi"]) if "efficiency_hi" in item else None),
            cop=float(item["cop"]) if "cop" in item else None,
            source=item["source"],
            note=item.get("note"),
        )
        for key, item in raw.items()
    }
    # Integracja M7→M13: technologie wytwarzania ciepła jako źródła podgrzewu
    from core.generation import heat_source_entries  # import lokalny (brak cyklu)

    for item in heat_source_entries():
        result[item["key"]] = HeatSource(
            key=item["key"],
            name_pl=item["name_pl"],
            supply_temp_c=float(item["supply_temp_c"]),
            energy_carrier=item["energy_carrier"],
            efficiency_hi=(float(item["efficiency_hi"]) if "efficiency_hi" in item else None),
            cop=float(item["cop"]) if "cop" in item else None,
            source=item["source"],
            note=item.get("note"),
        )
    return result


@cache
def station_presets() -> dict[str, dict]:
    """Predefiniowane warianty stacji redukcyjnych (edytowalne w UI)."""
    return load_data_file("reduction_stations.yaml")["station_presets"]


def _enthalpy(composition: GasComposition, p_pa: float, t_k: float) -> float:
    state = _abstract_state(composition)
    update_state_pt(state, p_pa, t_k)
    return state.hmass()


def required_inlet_temp_jt_k(
    composition: GasComposition,
    pressure_in_pa: float,
    pressure_out_pa: float,
    t_out_min_k: float,
) -> float:
    """Temperatura przed reduktorem JT zapewniająca T_wylot = T_min [K].

    Bilans entalpii dławienia: h(p1, T1_req) = h(p2, T_min) — rozwiązanie
    bezpośrednie z flashu (p1, h_target), bez iteracji.
    """
    state = _abstract_state(composition)
    update_state_pt(state, pressure_out_pa, t_out_min_k)
    h_target = state.hmass()
    flash_ph(state, pressure_in_pa, h_target)
    return state.T()


def required_inlet_temp_expander_k(
    composition: GasComposition,
    pressure_in_pa: float,
    pressure_out_pa: float,
    t_out_min_k: float,
    eta: float,
    max_expansion_ratio: float | None = None,
    jt_position: str = "za",
    tolerance_k: float = 0.01,
) -> tuple[float, ExpansionResult]:
    """Temperatura przed ekspanderem zapewniająca T_wylot = T_min (bisekcja).

    Funkcja T_wylot(T_wlot) jest monotonicznie rosnąca — bisekcja w przedziale
    [T_min, T_min + 250 K] do zbieżności ``tolerance_k``.

    Returns:
        (wymagana temperatura wlotu [K], wynik rozprężania przy tej temp.).
    """
    lo, hi = t_out_min_k, t_out_min_k + 250.0

    def outlet(t_in: float) -> float:
        return expand(
            composition,
            pressure_in_pa,
            t_in,
            pressure_out_pa,
            eta,
            max_expansion_ratio,
            jt_position,
        ).temperature_out_k

    if outlet(hi) < t_out_min_k:
        raise ValueError(
            "Wymagany podgrzew przekracza 250 K powyżej temperatury minimalnej — "
            "sprawdź parametry (zbyt duży stosunek rozprężania?)."
        )
    while hi - lo > tolerance_k:
        mid = (lo + hi) / 2.0
        if outlet(mid) < t_out_min_k:
            lo = mid
        else:
            hi = mid
    result = expand(
        composition,
        pressure_in_pa,
        hi,
        pressure_out_pa,
        eta,
        max_expansion_ratio,
        jt_position,
    )
    return hi, result


@dataclass(frozen=True)
class VariantResult:
    """Wynik jednego wariantu pracy stacji redukcyjnej (na strumień ṁ)."""

    variant_key: str  # "jt" | "ekspander" | "zimna_redukcja"
    name_pl: str
    t_preheat_required_k: float | None  # None = bez podgrzewu
    preheat_duty_w: float  # moc podgrzewu gazu [W]
    power_recovered_w: float  # moc elektryczna z ekspandera [W]
    t_out_k: float
    cooling_potential_w: float  # chłód względem T_otoczenia (zimna redukcja)
    hydrate_check: HydrateCheck
    warnings: list[str]

    @property
    def hydrate_risk_at_outlet(self) -> bool:
        return self.hydrate_check.is_at_risk(self.t_out_k)


def station_balance(
    composition: GasComposition,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
    mass_flow_kg_per_s: float,
    t_out_min_k: float | None = None,
    expander_eta: float = 0.80,
    expander_max_ratio: float | None = 5.0,
    jt_position: str = "za",
    ambient_k: float = 288.15,
) -> list[VariantResult]:
    """Bilans stacji redukcyjnej w trzech wariantach (JT / ekspander / zimna).

    Args:
        composition: skład gazu (M1),
        pressure_in_pa, temperature_in_k: stan wlotowy stacji (przed podgrzewem),
        pressure_out_pa: ciśnienie wylotowe,
        mass_flow_kg_per_s: strumień masy gazu,
        t_out_min_k: minimalna temperatura wylotowa; None ⇒ automatycznie
            T_hyd(p_wylot) + margines (screening hydratowy, core.hydrates),
        expander_eta: sprawność izentropowa ekspandera (wariant 2),
        expander_max_ratio: limit stosunku rozprężania maszyny (None = brak),
        jt_position: położenie reduktora JT przy ekspanderze ("za"/"przed"),
        ambient_k: temperatura odniesienia dla potencjału chłodu.

    Returns:
        Lista trzech ``VariantResult`` (ujemny podgrzew nie występuje —
        gdy T1 już wystarcza, moc podgrzewu = 0).
    """
    if mass_flow_kg_per_s <= 0.0:
        raise ValueError("Strumień masy musi być dodatni.")
    hydrate = check_hydrates(composition, pressure_out_pa)
    auto_warnings: list[str] = []
    if t_out_min_k is None:
        if hydrate.min_safe_temperature_k is not None:
            t_out_min_k = hydrate.min_safe_temperature_k
            auto_warnings.append(
                f"Minimalna temperatura wylotowa przyjęta automatycznie: "
                f"T_hydratów({pressure_out_pa / 1e6:.2f} MPa) + "
                f"{hydrate.margin_k:g} K = {t_out_min_k - 273.15:.1f} °C."
            )
        else:
            t_out_min_k = 273.15
            auto_warnings.append(
                "Brak frakcji hydratotwórczej — przyjęto minimum 0 °C " "(ochrona armatury)."
            )

    h_in = _enthalpy(composition, pressure_in_pa, temperature_in_k)
    results: list[VariantResult] = []

    # --- Wariant 1: JT z podgrzewem ---------------------------------------
    t_req_jt = required_inlet_temp_jt_k(composition, pressure_in_pa, pressure_out_pa, t_out_min_k)
    t_preheat = max(t_req_jt, temperature_in_k)
    duty_jt = mass_flow_kg_per_s * max(
        0.0, _enthalpy(composition, pressure_in_pa, t_preheat) - h_in
    )
    from core.expanders import isenthalpic_outlet_temperature_k

    t_out_jt = isenthalpic_outlet_temperature_k(
        composition, pressure_in_pa, t_preheat, pressure_out_pa
    )
    results.append(
        VariantResult(
            variant_key="jt",
            name_pl="JT z podgrzewem (klasyczny)",
            t_preheat_required_k=t_preheat,
            preheat_duty_w=duty_jt,
            power_recovered_w=0.0,
            t_out_k=t_out_jt,
            cooling_potential_w=0.0,
            hydrate_check=hydrate,
            warnings=list(auto_warnings),
        )
    )

    # --- Wariant 2: ekspander z podgrzewem ---------------------------------
    try:
        t_req_exp, expansion = required_inlet_temp_expander_k(
            composition,
            pressure_in_pa,
            pressure_out_pa,
            t_out_min_k,
            expander_eta,
            expander_max_ratio,
            jt_position,
        )
        t_preheat_exp = max(t_req_exp, temperature_in_k)
        if t_preheat_exp > t_req_exp:
            expansion = expand(
                composition,
                pressure_in_pa,
                t_preheat_exp,
                pressure_out_pa,
                expander_eta,
                expander_max_ratio,
                jt_position,
            )
        duty_exp = mass_flow_kg_per_s * max(
            0.0, _enthalpy(composition, pressure_in_pa, t_preheat_exp) - h_in
        )
        results.append(
            VariantResult(
                variant_key="ekspander",
                name_pl="Ekspander z podgrzewem (odzysk energii)",
                t_preheat_required_k=t_preheat_exp,
                preheat_duty_w=duty_exp,
                power_recovered_w=expansion.power_w(mass_flow_kg_per_s),
                t_out_k=expansion.temperature_out_k,
                cooling_potential_w=0.0,
                hydrate_check=hydrate,
                warnings=list(auto_warnings)
                + (
                    [
                        f"Reduktor JT {expansion.jt_position} ekspanderem "
                        f"(r_maszyny = {expansion.expansion_ratio_expander:.2f}, "
                        f"r_całkowite = {expansion.expansion_ratio_total:.2f})."
                    ]
                    if expansion.jt_position != "brak"
                    else []
                ),
            )
        )
    except ValueError as exc:
        results.append(
            VariantResult(
                variant_key="ekspander",
                name_pl="Ekspander z podgrzewem (odzysk energii)",
                t_preheat_required_k=None,
                preheat_duty_w=0.0,
                power_recovered_w=0.0,
                t_out_k=float("nan"),
                cooling_potential_w=0.0,
                hydrate_check=hydrate,
                warnings=[f"Wariant niewykonalny: {exc}"],
            )
        )

    # --- Wariant 3: zimna redukcja (bez podgrzewu) --------------------------
    t_out_cold = isenthalpic_outlet_temperature_k(
        composition, pressure_in_pa, temperature_in_k, pressure_out_pa
    )
    # Potencjał chłodu: ciepło potrzebne do ogrzania gazu z T_out do T_otoczenia
    cooling = mass_flow_kg_per_s * max(
        0.0,
        _enthalpy(composition, pressure_out_pa, ambient_k)
        - _enthalpy(composition, pressure_out_pa, t_out_cold),
    )
    cold_warnings = list(auto_warnings)
    if hydrate.is_at_risk(t_out_cold):
        cold_warnings.append(
            f"❄️ Ryzyko hydratów: T_wylot = {t_out_cold - 273.15:.1f} °C < "
            f"{(hydrate.min_safe_temperature_k or 0) - 273.15:.1f} °C "
            "(T_hyd + margines) — wymagane osuszenie gazu / inhibicja / "
            "częściowy podgrzew."
        )
    if t_out_cold < 273.15:
        cold_warnings.append(
            "Temperatura wylotowa poniżej 0 °C — ryzyko oblodzenia armatury "
            "i przemarzania gruntu; wymagana ocena materiałowa."
        )
    results.append(
        VariantResult(
            variant_key="zimna_redukcja",
            name_pl="Zimna redukcja (bez podgrzewu)",
            t_preheat_required_k=None,
            preheat_duty_w=0.0,
            power_recovered_w=0.0,
            t_out_k=t_out_cold,
            cooling_potential_w=cooling,
            hydrate_check=hydrate,
            warnings=cold_warnings,
        )
    )
    return results


@dataclass(frozen=True)
class VariantEconomics:
    """Proste porównanie kosztów rocznych wariantu (ceny robocze, nie M5)."""

    variant_key: str
    heat_source_key: str
    heat_source_ok: bool  # czy źródło osiąga wymaganą temperaturę podgrzewu
    preheat_cost_pln_per_year: float
    electricity_revenue_pln_per_year: float
    net_cost_pln_per_year: float


#: Nośniki M13 mające ścieżkę cenową w scenariuszach M5.
_M5_CARRIERS = ("energia_elektryczna", "gaz_ziemny", "biomasa", "wodor", "wegiel")


def _resolve_prices(scenario, year: int | None) -> tuple[dict[str, float], str]:
    """Ceny nośników: ze scenariusza M5 (preferowane) albo robocze (fallback).

    Zwraca (ceny, opis źródła cen). „odpadowe" nie ma ścieżki w M5 —
    zawsze z cen roboczych (koszt krańcowy).
    """
    working = {
        k: float(v)
        for k, v in load_data_file("reduction_stations.yaml")["working_prices_pln_per_mwh"].items()
        if isinstance(v, (int, float))
    }
    if scenario is None:
        return working, "ceny robocze (data/reduction_stations.yaml)"
    if year is None:
        raise ValueError("Podaj rok analizy dla scenariusza cenowego M5.")
    prices = dict(working)
    for carrier in _M5_CARRIERS:
        prices[carrier] = scenario.price(carrier, year)
    return prices, f"scenariusz M5 „{scenario.name_pl}”, rok {year}"


def variant_economics(
    variant: VariantResult,
    heat_source: HeatSource,
    hours_per_year: float = 8000.0,
    electricity_price_pln_per_mwh: float | None = None,
    prices_pln_per_mwh: dict[str, float] | None = None,
    pinch_k: float | None = None,
    scenario=None,
    year: int | None = None,
) -> VariantEconomics:
    """Roczne koszty/przychody wariantu stacji.

    Ceny: preferencyjnie ze **scenariusza M5** (``scenario`` + ``year`` —
    jedno źródło prawdy z resztą narzędzia); bez scenariusza — ceny robocze
    z ``data/reduction_stations.yaml`` (fallback, oznaczony). „odpadowe"
    zawsze wg cen roboczych (koszt krańcowy, brak ścieżki rynkowej).

    Koszt podgrzewu = moc × czas × cena nośnika / (η lub COP);
    przychód = energia elektryczna z ekspandera × cena energii.
    Sprawdzane ograniczenia źródła: temperatura zasilania (pinch) oraz —
    dla źródeł z limitem (ciepło odpadowe z konkretnej sprężarki M2) —
    dostępna moc cieplna.
    """
    resolved, _ = _resolve_prices(scenario, year)
    if prices_pln_per_mwh is None:
        prices_pln_per_mwh = resolved
    if electricity_price_pln_per_mwh is None:
        electricity_price_pln_per_mwh = prices_pln_per_mwh["energia_elektryczna"]
    if pinch_k is None:
        pinch_k = float(load_data_file("expanders.yaml")["defaults"]["preheater_pinch_k"])

    source_ok = True
    if variant.t_preheat_required_k is not None:
        source_ok = variant.t_preheat_required_k <= heat_source.max_gas_temp_k(pinch_k)
    if heat_source.available_kw is not None:
        source_ok = source_ok and (
            variant.preheat_duty_w / 1e3 <= heat_source.available_kw * (1 + 1e-9)
        )

    if heat_source.energy_carrier not in prices_pln_per_mwh:
        raise ValueError(
            f"Brak ceny nośnika '{heat_source.energy_carrier}' — dostępne: "
            f"{', '.join(prices_pln_per_mwh)}."
        )
    carrier_price = prices_pln_per_mwh[heat_source.energy_carrier]
    heat_mwh_year = variant.preheat_duty_w / 1e6 * hours_per_year
    cost = heat_mwh_year * heat_source.energy_input_per_heat() * carrier_price
    revenue = variant.power_recovered_w / 1e6 * hours_per_year * electricity_price_pln_per_mwh
    return VariantEconomics(
        variant_key=variant.variant_key,
        heat_source_key=heat_source.key,
        heat_source_ok=source_ok,
        preheat_cost_pln_per_year=cost,
        electricity_revenue_pln_per_year=revenue,
        net_cost_pln_per_year=cost - revenue,
    )


def heat_source_from_compression(
    compression_result,
    mass_flow_kg_per_s: float,
    approach_k: float = 10.0,
    cooldown_to_k: float | None = None,
    name_pl: str = "ciepło odpadowe sprężarki (policzone w M2)",
) -> HeatSource:
    """Buduje źródło ciepła M13 z POLICZONEGO sprężania M2 (nie z danych).

    Temperatura zasilania wody = najniższa temperatura tłoczenia spośród
    stopni − ``approach_k`` (wymiennik odzysku; najzimniejszy stopień
    limituje wspólny obieg wody). Dostępna moc = ciepło chłodnic
    międzystopniowych + chłodnicy końcowej (do ``cooldown_to_k``,
    domyślnie temperatura ssania).

    Args:
        compression_result: wynik ``core.compression.compress`` (M2),
        mass_flow_kg_per_s: strumień sprężanego gazu [kg/s],
        approach_k: przewężenie temperaturowe wymiennika [K],
        cooldown_to_k: temperatura schłodzenia w chłodnicy końcowej.
    """
    if mass_flow_kg_per_s <= 0:
        raise ValueError("Strumień sprężanego gazu musi być dodatni.")
    min_stage_out_k = min(s.temperature_out_k for s in compression_result.stages)
    supply_c = min_stage_out_k - approach_k - 273.15
    if supply_c <= 5.0:
        raise ValueError(
            "Sprężarka o zbyt niskiej temperaturze tłoczenia "
            f"({min_stage_out_k - 273.15:.0f} °C) — brak użytecznego ciepła."
        )
    target_k = cooldown_to_k if cooldown_to_k is not None else compression_result.temperature_in_k
    available_w = (
        compression_result.cooling_duty_w(mass_flow_kg_per_s)
        + compression_result.aftercooler_heat_j_per_kg(target_k) * mass_flow_kg_per_s
    )
    return HeatSource(
        key="m2_sprezarka_policzona",
        name_pl=name_pl,
        supply_temp_c=supply_c,
        energy_carrier="odpadowe",
        efficiency_hi=1.0,
        cop=None,
        source=(
            f"Policzone (M2): {compression_result.pressure_in_pa / 1e5:.1f}→"
            f"{compression_result.pressure_out_pa / 1e5:.1f} bar, "
            f"{len(compression_result.stages)} stopni"
        ),
        note=f"Limit mocy cieplnej: {available_w / 1e3:.0f} kW (z bilansu chłodnic).",
        available_kw=available_w / 1e3,
    )
