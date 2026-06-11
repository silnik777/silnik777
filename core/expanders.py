"""Ekspandery — odzysk energii z redukcji ciśnienia gazu (moduł M4).

Model rozprężania (gaz rzeczywisty, HEOS/GERG-2008):
    w_s = h1 − h(p2, s1)            — praca izentropowa,
    w   = η_s · w_s                  — praca odzyskana,
    h2  = h1 − w, T2 z flashu (h2, p2).

Ograniczenia maszyn: każda technologia ma maksymalny stosunek rozprężania
(rozmiary/ekonomika) — gdy p1/p2 przekracza r_max, pozostałą redukcję
realizuje reduktor JT (izentalpowo) przed albo za ekspanderem
(``jt_position``). Biblioteka technologii: ``data/expanders.yaml``
(sprawności min/typ/max, mapy stosowalności, CAPEX/kW, TRL — wartości
orientacyjne ze źródłami).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.composition import GasComposition
from core.config import load_data_file
from core.gas_properties import (
    _abstract_state,
    compute_properties,
    flash_ph,
    flash_ps,
    update_state_pt,
)


@dataclass(frozen=True)
class ExpanderTechnology:
    """Technologia ekspandera z biblioteki ``data/expanders.yaml``."""

    key: str
    name_pl: str
    eta_min: float
    eta_typical: float
    eta_max: float
    max_expansion_ratio: float
    expansion_ratio_range: tuple[float, float]
    flow_range_nm3_per_h: tuple[float, float]
    power_range_kw: tuple[float, float]
    capex_eur_per_kw_typical: float
    capex_eur_per_kw_range: tuple[float, float]
    trl: int
    h2_note: str
    source: str


@cache
def expander_technologies() -> dict[str, ExpanderTechnology]:
    """Rejestr technologii ekspanderów z ``data/expanders.yaml``."""
    raw = load_data_file("expanders.yaml")["technologies"]
    return {
        key: ExpanderTechnology(
            key=key,
            name_pl=item["name_pl"],
            eta_min=float(item["eta"]["min"]),
            eta_typical=float(item["eta"]["typical"]),
            eta_max=float(item["eta"]["max"]),
            max_expansion_ratio=float(item["max_expansion_ratio"]),
            expansion_ratio_range=tuple(item["expansion_ratio_range"]),
            flow_range_nm3_per_h=tuple(item["flow_range_nm3_per_h"]),
            power_range_kw=tuple(item["power_range_kw"]),
            capex_eur_per_kw_typical=float(item["capex_eur_per_kw"]["typical"]),
            capex_eur_per_kw_range=(
                float(item["capex_eur_per_kw"]["min"]),
                float(item["capex_eur_per_kw"]["max"]),
            ),
            trl=int(item["trl"]),
            h2_note=item["h2_note"],
            source=item["source"],
        )
        for key, item in raw.items()
    }


@dataclass(frozen=True)
class ExpansionResult:
    """Wynik rozprężania 1 kg gazu (ekspander + ewentualny reduktor JT)."""

    composition: GasComposition
    pressure_in_pa: float
    temperature_in_k: float
    pressure_out_pa: float
    eta: float
    jt_position: str  # "za" | "przed" | "brak"
    expander_pressure_in_pa: float
    expander_pressure_out_pa: float
    work_j_per_kg: float  # praca odzyskana (na sprzęgle wewn.)
    work_isentropic_j_per_kg: float  # praca izentropowa pełnej redukcji (η=1)
    temperature_out_k: float  # za całym układem (ekspander + JT)
    temperature_expander_out_k: float  # bezpośrednio za ekspanderem

    @property
    def expansion_ratio_total(self) -> float:
        return self.pressure_in_pa / self.pressure_out_pa

    @property
    def expansion_ratio_expander(self) -> float:
        return self.expander_pressure_in_pa / self.expander_pressure_out_pa

    def power_w(self, mass_flow_kg_per_s: float) -> float:
        """Moc odzyskana [W] dla zadanego strumienia masy."""
        return self.work_j_per_kg * mass_flow_kg_per_s


def _validate(p_in: float, t_in: float, p_out: float, eta: float) -> None:
    if p_in <= 0.0 or p_out <= 0.0:
        raise ValueError("Ciśnienia muszą być dodatnie.")
    if p_out >= p_in:
        raise ValueError(
            f"Ciśnienie wylotowe ({p_out / 1e5:.2f} bar) musi być niższe "
            f"od wlotowego ({p_in / 1e5:.2f} bar)."
        )
    if t_in <= 0.0:
        raise ValueError("Temperatura musi być dodatnia.")
    if not 0.0 < eta <= 1.0:
        raise ValueError(f"Sprawność musi być w przedziale (0, 1] (otrzymano {eta}).")


def isenthalpic_outlet_temperature_k(
    composition: GasComposition,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
) -> float:
    """Temperatura za dławieniem izentalpowym (reduktor JT): h = const."""
    _validate(pressure_in_pa, temperature_in_k, pressure_out_pa, 1.0)
    state = _abstract_state(composition)
    update_state_pt(state, pressure_in_pa, temperature_in_k)
    h1 = state.hmass()
    flash_ph(state, pressure_out_pa, h1)
    return state.T()


def expand(
    composition: GasComposition,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
    eta: float,
    max_expansion_ratio: float | None = None,
    jt_position: str = "za",
) -> ExpansionResult:
    """Rozprężanie w ekspanderze z opcjonalnym reduktorem JT.

    Gdy p1/p2 > ``max_expansion_ratio``, ekspander realizuje stosunek r_max,
    a resztę redukcji przejmuje dławienie izentalpowe:
        * ``jt_position="za"``  — ekspander od p1 do p1/r_max, JT do p2
          (ekspander pracuje na wyższym ciśnieniu — większa praca na kg),
        * ``jt_position="przed"`` — JT od p1 do p2·r_max, ekspander do p2
          (niższa temperatura wlotu ekspandera po dławieniu).

    Args:
        composition: skład gazu (M1),
        pressure_in_pa/temperature_in_k: stan przed układem (po podgrzewie),
        pressure_out_pa: ciśnienie za układem,
        eta: sprawność izentropowa ekspandera (0–1),
        max_expansion_ratio: limit stosunku rozprężania maszyny
            (None = bez limitu, cała redukcja w ekspanderze),
        jt_position: "za" | "przed" — położenie reduktora JT.
    """
    _validate(pressure_in_pa, temperature_in_k, pressure_out_pa, eta)
    if jt_position not in ("za", "przed"):
        raise ValueError("jt_position musi być 'za' albo 'przed'.")

    ratio_total = pressure_in_pa / pressure_out_pa
    if max_expansion_ratio is not None and max_expansion_ratio < 1.0:
        raise ValueError("Maksymalny stosunek rozprężania musi być ≥ 1.")

    if max_expansion_ratio is None or ratio_total <= max_expansion_ratio:
        exp_p_in, exp_p_out = pressure_in_pa, pressure_out_pa
        position = "brak"
        t_exp_in = temperature_in_k
    elif jt_position == "za":
        exp_p_in = pressure_in_pa
        exp_p_out = pressure_in_pa / max_expansion_ratio
        position = "za"
        t_exp_in = temperature_in_k
    else:  # JT przed ekspanderem
        exp_p_out = pressure_out_pa
        exp_p_in = pressure_out_pa * max_expansion_ratio
        position = "przed"
        t_exp_in = isenthalpic_outlet_temperature_k(
            composition, pressure_in_pa, temperature_in_k, exp_p_in
        )

    state = _abstract_state(composition)
    # Pełna kontrola stabilności faz na wlocie ekspandera
    update_state_pt(state, exp_p_in, t_exp_in)
    h1, s1 = state.hmass(), state.smass()
    flash_ps(state, exp_p_out, s1)
    h2s = state.hmass()
    work = eta * (h1 - h2s)
    flash_ph(state, exp_p_out, h1 - work)
    t_expander_out = state.T()

    # Reduktor JT za ekspanderem (jeśli jest)
    if position == "za":
        t_out = isenthalpic_outlet_temperature_k(
            composition, exp_p_out, t_expander_out, pressure_out_pa
        )
    else:
        t_out = t_expander_out

    # Praca izentropowa pełnej redukcji (odniesienie, η=1, bez limitu r)
    update_state_pt(state, pressure_in_pa, temperature_in_k)
    h1_full, s1_full = state.hmass(), state.smass()
    flash_ps(state, pressure_out_pa, s1_full)
    w_isentropic_full = h1_full - state.hmass()

    return ExpansionResult(
        composition=composition,
        pressure_in_pa=pressure_in_pa,
        temperature_in_k=temperature_in_k,
        pressure_out_pa=pressure_out_pa,
        eta=eta,
        jt_position=position,
        expander_pressure_in_pa=exp_p_in,
        expander_pressure_out_pa=exp_p_out,
        work_j_per_kg=work,
        work_isentropic_j_per_kg=w_isentropic_full,
        temperature_out_k=t_out,
        temperature_expander_out_k=t_expander_out,
    )


@dataclass(frozen=True)
class SelectionEntry:
    """Wiersz macierzy doboru ekspandera dla punktu pracy."""

    technology: ExpanderTechnology
    flow_ok: bool
    ratio_needs_jt: bool  # True = wymagany reduktor JT (r_total > r_max)
    power_kw: float
    power_ok: bool
    capex_eur_estimate: float
    feasible: bool


def selection_matrix(
    composition: GasComposition,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
    flow_nm3_per_h: float,
    jt_position: str = "za",
) -> list[SelectionEntry]:
    """Macierz doboru: wykonalność i szacunkowa moc/CAPEX każdej technologii.

    Moc liczona przy sprawności typowej technologii i jej limicie stosunku
    rozprężania (nadmiar redukcji w JT). Wynik posortowany: wykonalne wg
    malejącej mocy, potem niewykonalne.
    """
    rho_n = compute_properties(composition, 101_325.0, 273.15).density_kg_per_m3
    mass_flow = flow_nm3_per_h * rho_n / 3600.0  # kg/s

    entries: list[SelectionEntry] = []
    for tech in expander_technologies().values():
        result = expand(
            composition,
            pressure_in_pa,
            temperature_in_k,
            pressure_out_pa,
            eta=tech.eta_typical,
            max_expansion_ratio=tech.max_expansion_ratio,
            jt_position=jt_position,
        )
        power_kw = result.power_w(mass_flow) / 1e3
        lo_f, hi_f = tech.flow_range_nm3_per_h
        lo_p, hi_p = tech.power_range_kw
        flow_ok = lo_f <= flow_nm3_per_h <= hi_f
        power_ok = lo_p <= power_kw <= hi_p
        entries.append(
            SelectionEntry(
                technology=tech,
                flow_ok=flow_ok,
                ratio_needs_jt=result.jt_position != "brak",
                power_kw=power_kw,
                power_ok=power_ok,
                capex_eur_estimate=power_kw * tech.capex_eur_per_kw_typical,
                feasible=flow_ok and power_ok,
            )
        )
    return sorted(entries, key=lambda e: (not e.feasible, -e.power_kw))
