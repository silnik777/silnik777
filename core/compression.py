"""Energia sprężania między punktami pracy (p1,T1)→(p2,T2) — moduł M2.

Modele pracy sprężania (gaz rzeczywisty, właściwości z M1 / CoolProp):

* **izotermiczna** (teoretyczne minimum z chłodzeniem doskonałym):
      w_T = Δg|_T = (h2 − h1) − T·(s2 − s1)   [J/kg]
  (odwracalna praca techniczna przy T = const; dla gazu doskonałego
  przechodzi w R·T·ln(p2/p1)/M),
* **izentropowa**: w_s = h(p2, s1) − h(p1, T1); rzeczywista praca stopnia
  w = w_s / η_s, stan wylotowy z flashu (h1 + w, p2),
* **politropowa**: całka po drodze sprężania realizowana numerycznie jako
  N małych stopni izentropowych ze sprawnością politropową η_p w każdym
  kroku (definicja sprawności politropowej jako granicy małych stopni —
  Schultz J.M., "The Polytropic Analysis of Centrifugal Compressors",
  J. Eng. Power 84 (1962) 69–82),
* **wielostopniowa z chłodzeniem międzystopniowym**: równy spręż na stopień
  r = (p2/p1)^(1/n), chłodzenie do zadanej temperatury między stopniami;
  ciepło odpadowe = Σ [h(wylot stopnia) − h(po chłodnicy)].

Biblioteka technologii sprężarek (sprawności min/typ/max, mapy stosowalności,
TRL): ``data/compressors.yaml`` — wartości orientacyjne z podanymi źródłami.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache

import CoolProp.CoolProp as CP

from core.composition import GasComposition
from core.config import load_data_file
from core.gas_properties import _abstract_state, compute_properties, update_state_pt
from core.units import NORMAL_0C, j_to_kwh

#: Liczba podkroków całkowania politropowego (zbieżność < 0,05% dla r ≤ 4).
POLYTROPIC_SUBSTEPS = 25


# --- Biblioteka technologii --------------------------------------------------


@dataclass(frozen=True)
class CompressorTechnology:
    """Technologia sprężarki z biblioteki ``data/compressors.yaml``."""

    key: str
    name_pl: str
    efficiency_model: str  # "izentropowa" | "politropowa"
    eta_min: float
    eta_typical: float
    eta_max: float
    max_pressure_ratio_per_stage: float
    pressure_ratio_per_stage_range: tuple[float, float]
    max_discharge_pressure_mpa: float
    flow_range_nm3_per_h: tuple[float, float]
    h2_ready: bool
    h2_note: str
    trl: int
    source: str


@cache
def compressor_technologies() -> dict[str, CompressorTechnology]:
    """Rejestr technologii sprężarek z ``data/compressors.yaml``."""
    raw = load_data_file("compressors.yaml")["technologies"]
    return {
        key: CompressorTechnology(
            key=key,
            name_pl=item["name_pl"],
            efficiency_model=item["efficiency_model"],
            eta_min=float(item["eta"]["min"]),
            eta_typical=float(item["eta"]["typical"]),
            eta_max=float(item["eta"]["max"]),
            max_pressure_ratio_per_stage=float(item["max_pressure_ratio_per_stage"]),
            pressure_ratio_per_stage_range=tuple(item["pressure_ratio_per_stage_range"]),
            max_discharge_pressure_mpa=float(item["max_discharge_pressure_mpa"]),
            flow_range_nm3_per_h=tuple(item["flow_range_nm3_per_h"]),
            h2_ready=bool(item["h2_ready"]),
            h2_note=item["h2_note"],
            trl=int(item["trl"]),
            source=item["source"],
        )
        for key, item in raw.items()
    }


def applicable_technologies(
    flow_nm3_per_h: float, discharge_pressure_mpa: float
) -> dict[str, bool]:
    """Mapa stosowalności technologii dla zadanego przepływu i ciśnienia tłoczenia."""
    result = {}
    for key, tech in compressor_technologies().items():
        lo, hi = tech.flow_range_nm3_per_h
        result[key] = (
            lo <= flow_nm3_per_h <= hi and discharge_pressure_mpa <= tech.max_discharge_pressure_mpa
        )
    return result


# --- Pomocnicze flashe -------------------------------------------------------


def _flash_gas(state: CP.AbstractState, pair: int, v1: float, v2: float) -> None:
    """Flash CoolProp z wymuszoną fazą gazową.

    Stosowany wewnątrz stopni sprężania: jeśli ssanie jest w fazie gazowej
    (pełna kontrola stabilności na wejściu ``compress``), to sprężany,
    gorący gaz pozostaje gazem — pominięcie analizy stabilności faz skraca
    flash mieszanin ~500× bez zmiany wyniku.
    """
    state.specify_phase(CP.iphase_gas)
    try:
        state.update(pair, v1, v2)
        return
    except Exception:
        # Solver jednofazowy bywa zawodny (np. flash p-s czystego H2 przy
        # wysokim ciśnieniu) — fallback do pełnego flashu ze stabilnością faz.
        state.unspecify_phase()
        try:
            state.update(pair, v1, v2)
        except Exception as exc:
            raise ValueError(
                f"Flash termodynamiczny nie powiódł się. Szczegóły CoolProp: {exc}"
            ) from exc


# --- Praca sprężania ---------------------------------------------------------


def isothermal_work_j_per_kg(
    composition: GasComposition,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
) -> float:
    """Odwracalna praca izotermiczna sprężania [J/kg].

    Wzór: w_T = (h2 − h1) − T·(s2 − s1) (zmiana funkcji Gibbsa przy T = const);
    teoretyczne minimum pracy przy doskonałym chłodzeniu. Gaz rzeczywisty
    (HEOS/GERG-2008). Zakres ważności: jak GERG-2008 (90–450 K, ≤ 35 MPa).
    """
    _validate_pressures(pressure_in_pa, pressure_out_pa)
    state = _abstract_state(composition)
    update_state_pt(state, pressure_in_pa, temperature_in_k)
    h1, s1 = state.hmass(), state.smass()
    update_state_pt(state, pressure_out_pa, temperature_in_k)
    h2, s2 = state.hmass(), state.smass()
    return (h2 - h1) - temperature_in_k * (s2 - s1)


@dataclass(frozen=True)
class StageResult:
    """Wynik jednego stopnia sprężania (+ chłodnica za stopniem, jeśli jest)."""

    pressure_in_pa: float
    pressure_out_pa: float
    temperature_in_k: float
    temperature_out_k: float  # temperatura tłoczenia (przed chłodnicą)
    work_j_per_kg: float
    intercooler_heat_j_per_kg: float  # 0, gdy brak chłodnicy za stopniem
    intercooler_outlet_k: float | None  # temperatura gazu po chłodnicy


@dataclass(frozen=True)
class CompressionResult:
    """Wynik sprężania (jedno- lub wielostopniowego) na 1 kg gazu."""

    composition: GasComposition
    pressure_in_pa: float
    temperature_in_k: float
    pressure_out_pa: float
    model: str  # "izentropowy" | "politropowy"
    eta: float
    stages: list[StageResult] = field(default_factory=list)

    @property
    def work_j_per_kg(self) -> float:
        """Całkowita praca wewnętrzna sprężania [J/kg]."""
        return sum(s.work_j_per_kg for s in self.stages)

    @property
    def work_kwh_per_kg(self) -> float:
        """Energia właściwa sprężania [kWh/kg]."""
        return j_to_kwh(self.work_j_per_kg)

    @property
    def intercooling_heat_j_per_kg(self) -> float:
        """Ciepło odebrane w chłodnicach międzystopniowych [J/kg] (≥ 0)."""
        return sum(s.intercooler_heat_j_per_kg for s in self.stages)

    @property
    def outlet_temperature_k(self) -> float:
        """Temperatura tłoczenia ostatniego stopnia (przed chłodnicą końcową) [K]."""
        return self.stages[-1].temperature_out_k

    @property
    def max_stage_outlet_k(self) -> float:
        """Najwyższa temperatura tłoczenia spośród stopni [K]."""
        return max(s.temperature_out_k for s in self.stages)

    def work_kwh_per_nm3(self) -> float:
        """Energia właściwa odniesiona do Nm³ gazu (0 °C; 101,325 kPa) [kWh/Nm³]."""
        rho_n = compute_properties(
            self.composition, NORMAL_0C.pressure_pa, NORMAL_0C.temperature_k
        ).density_kg_per_m3
        return self.work_kwh_per_kg * rho_n

    def power_w(self, mass_flow_kg_per_s: float) -> float:
        """Moc wewnętrzna sprężania dla zadanego strumienia masy [W]."""
        return self.work_j_per_kg * mass_flow_kg_per_s

    def cooling_duty_w(self, mass_flow_kg_per_s: float) -> float:
        """Moc cieplna chłodzenia międzystopniowego [W]."""
        return self.intercooling_heat_j_per_kg * mass_flow_kg_per_s

    def aftercooler_heat_j_per_kg(self, target_k: float) -> float:
        """Ciepło chłodnicy końcowej do temperatury ``target_k`` [J/kg].

        Poziom temperaturowy ciepła: od ``outlet_temperature_k`` do ``target_k``
        przy ciśnieniu tłoczenia (potencjał odzysku ciepła).
        """
        state = _abstract_state(self.composition)
        update_state_pt(state, self.pressure_out_pa, self.outlet_temperature_k)
        h_hot = state.hmass()
        update_state_pt(state, self.pressure_out_pa, target_k)
        return max(0.0, h_hot - state.hmass())


def _validate_pressures(pressure_in_pa: float, pressure_out_pa: float) -> None:
    if pressure_in_pa <= 0.0 or pressure_out_pa <= 0.0:
        raise ValueError("Ciśnienia muszą być dodatnie.")
    if pressure_out_pa <= pressure_in_pa:
        raise ValueError(
            f"Ciśnienie tłoczenia ({pressure_out_pa / 1e5:.2f} bar) musi być wyższe "
            f"od ssania ({pressure_in_pa / 1e5:.2f} bar)."
        )


def _isentropic_stage(
    state: CP.AbstractState,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
    eta_isentropic: float,
) -> tuple[float, float]:
    """Praca i temperatura wylotowa stopnia izentropowego ze sprawnością η_s.

    w_s = h(p2, s1) − h1;  w = w_s/η_s;  T2 z flashu (h1 + w, p2).
    Flashe z wymuszoną fazą gazową (kontrola stabilności: raz, w ``compress``).
    """
    _flash_gas(state, CP.PT_INPUTS, pressure_in_pa, temperature_in_k)
    h1, s1 = state.hmass(), state.smass()
    _flash_gas(state, CP.PSmass_INPUTS, pressure_out_pa, s1)
    h2s = state.hmass()
    work = (h2s - h1) / eta_isentropic
    _flash_gas(state, CP.HmassP_INPUTS, h1 + work, pressure_out_pa)
    return work, state.T()


def _polytropic_stage(
    state: CP.AbstractState,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
    eta_polytropic: float,
    substeps: int = POLYTROPIC_SUBSTEPS,
) -> tuple[float, float]:
    """Stopień politropowy: N małych kroków izentropowych z η_p (Schultz 1962)."""
    ratio_step = (pressure_out_pa / pressure_in_pa) ** (1.0 / substeps)
    p, t = pressure_in_pa, temperature_in_k
    total = 0.0
    for _ in range(substeps):
        p_next = p * ratio_step
        work, t = _isentropic_stage(state, p, t, p_next, eta_polytropic)
        total += work
        p = p_next
    return total, t


def compress(
    composition: GasComposition,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
    eta: float,
    n_stages: int = 1,
    model: str = "izentropowy",
    intercool_to_k: float | None = None,
) -> CompressionResult:
    """Sprężanie wielostopniowe z chłodzeniem międzystopniowym.

    Args:
        composition: skład gazu (M1),
        pressure_in_pa / temperature_in_k: stan ssania,
        pressure_out_pa: ciśnienie tłoczenia,
        eta: sprawność (izentropowa lub politropowa — wg ``model``), 0–1,
        n_stages: liczba stopni; równy spręż na stopień r = (p2/p1)^(1/n),
        model: "izentropowy" | "politropowy",
        intercool_to_k: temperatura po chłodnicach międzystopniowych
            (domyślnie temperatura ssania); chłodnice bez strat ciśnienia
            (uproszczenie — typowo Δp < 1–2%).

    Returns:
        ``CompressionResult`` z pracą, stopniami i ciepłem odpadowym.
    """
    _validate_pressures(pressure_in_pa, pressure_out_pa)
    if not 0.0 < eta <= 1.0:
        raise ValueError(f"Sprawność musi być w przedziale (0, 1] (otrzymano {eta}).")
    if n_stages < 1:
        raise ValueError("Liczba stopni musi być ≥ 1.")
    if model not in ("izentropowy", "politropowy"):
        raise ValueError("Model musi być 'izentropowy' albo 'politropowy'.")

    t_intercool = temperature_in_k if intercool_to_k is None else intercool_to_k
    ratio = (pressure_out_pa / pressure_in_pa) ** (1.0 / n_stages)
    state = _abstract_state(composition)
    # Pełna kontrola stabilności faz na ssaniu (raz); stopnie pracują na
    # flashach z wymuszoną fazą gazową (gorący gaz — patrz _flash_gas).
    update_state_pt(state, pressure_in_pa, temperature_in_k)
    stage_fn = _isentropic_stage if model == "izentropowy" else _polytropic_stage

    stages: list[StageResult] = []
    p, t = pressure_in_pa, temperature_in_k
    for i in range(n_stages):
        p_out = pressure_out_pa if i == n_stages - 1 else p * ratio
        work, t_out = stage_fn(state, p, t, p_out, eta)
        heat = 0.0
        t_after: float | None = None
        if i < n_stages - 1:
            update_state_pt(state, p_out, t_out)
            h_hot = state.hmass()
            update_state_pt(state, p_out, t_intercool)
            heat = max(0.0, h_hot - state.hmass())
            t_after = t_intercool
        stages.append(
            StageResult(
                pressure_in_pa=p,
                pressure_out_pa=p_out,
                temperature_in_k=t,
                temperature_out_k=t_out,
                work_j_per_kg=work,
                intercooler_heat_j_per_kg=heat,
                intercooler_outlet_k=t_after,
            )
        )
        p, t = p_out, (t_after if t_after is not None else t_out)

    return CompressionResult(
        composition=composition,
        pressure_in_pa=pressure_in_pa,
        temperature_in_k=temperature_in_k,
        pressure_out_pa=pressure_out_pa,
        model=model,
        eta=eta,
        stages=stages,
    )


@dataclass(frozen=True)
class StageSweepPoint:
    """Punkt analizy liczby stopni."""

    n_stages: int
    work_j_per_kg: float
    max_stage_outlet_c: float
    t_limit_ok: bool


def optimal_stage_count(
    composition: GasComposition,
    pressure_in_pa: float,
    temperature_in_k: float,
    pressure_out_pa: float,
    eta: float,
    model: str = "izentropowy",
    max_stages: int = 6,
    t_discharge_limit_k: float | None = None,
    marginal_gain_threshold: float = 0.05,
) -> tuple[int, list[StageSweepPoint]]:
    """Optymalna liczba stopni sprężania z chłodzeniem międzystopniowym.

    Kryteria: (1) temperatura tłoczenia każdego stopnia ≤ limit
    (domyślnie z ``data/compressors.yaml``), (2) dalsze zwiększanie liczby
    stopni daje zysk energii < ``marginal_gain_threshold`` (domyślnie 5% —
    poniżej tej wartości dodatkowy stopień zwykle nie broni się kosztowo:
    CAPEX, straty ciśnienia w chłodnicach).

    Returns:
        (rekomendowana liczba stopni, lista punktów analizy 1..max_stages).
    """
    if t_discharge_limit_k is None:
        t_limit_c = float(load_data_file("compressors.yaml")["defaults"]["t_discharge_limit_c"])
        t_discharge_limit_k = t_limit_c + 273.15

    sweep: list[StageSweepPoint] = []
    for n in range(1, max_stages + 1):
        result = compress(
            composition, pressure_in_pa, temperature_in_k, pressure_out_pa, eta, n, model
        )
        sweep.append(
            StageSweepPoint(
                n_stages=n,
                work_j_per_kg=result.work_j_per_kg,
                max_stage_outlet_c=result.max_stage_outlet_k - 273.15,
                t_limit_ok=result.max_stage_outlet_k <= t_discharge_limit_k,
            )
        )

    recommended = max_stages
    for i, point in enumerate(sweep):
        if not point.t_limit_ok:
            continue
        if i + 1 < len(sweep):
            gain = (point.work_j_per_kg - sweep[i + 1].work_j_per_kg) / point.work_j_per_kg
            if gain < marginal_gain_threshold:
                recommended = point.n_stages
                break
        else:
            recommended = point.n_stages
    return recommended, sweep
