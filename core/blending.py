"""Domieszki i korekta jakości gazu grupy E (moduł M1).

Funkcje pomocnicze dla oceny wpływu domieszek (wodór, biometan) na zgodność
z wymaganiami gazu wysokometanowego E oraz dla korekty tej zgodności
propanowaniem:

* ``max_hydrogen_for_group_e`` — maksymalny udział H₂, przy którym gaz nadal
  spełnia wymogi E; zwraca ograniczenie wiążące (liczba Wobbego / liczba
  metanowa / próg %H₂). Kluczowa uwaga fizyczna: Ws czystego H₂ ≈ 48,3 MJ/m³
  mieści się w paśmie E (45–56,9), więc dla H₂ w gazie E zwykle wiąże liczba
  metanowa albo próg %H₂, a NIE liczba Wobbego,
* ``propane_enrichment_for_group_e`` — ile propanu (C₃H₈) dodać, aby przywrócić
  liczbę Wobbego do dolnej granicy pasma E (propanowanie/LPG). Propan podnosi
  Wobbe i wartość opałową, ale OBNIŻA liczbę metanową — wynik raportuje MN po
  wzbogaceniu, by uczciwie pokazać ten kompromis.

Ograniczenia jakościowe z ``data/quality_limits.yaml`` i ``data/
methane_number.yaml`` (edytowalne). Wszystkie wartości Wobbego liczone przy
warunkach odniesienia 25/0 °C (jak limity grupy E).
"""

from __future__ import annotations

from dataclasses import dataclass

from core.calorific import calorific_values
from core.composition import GasComposition
from core.config import load_data_file
from core.methane_number import methane_number
from core.units import REFERENCE_CONDITIONS

_REF_0C = REFERENCE_CONDITIONS["0C"]


def group_e_wobbe_limits() -> tuple[float, float]:
    """Dolna i górna granica liczby Wobbego (górnej) dla gazu E [MJ/m³]."""
    cfg = load_data_file("quality_limits.yaml")["wobbe_index_group_E"]
    return float(cfg["min_mj_per_m3"]), float(cfg["max_mj_per_m3"])


def engine_methane_number_limit() -> float:
    """Minimalna liczba metanowa (limit silnikowy) z danych."""
    return float(load_data_file("methane_number.yaml")["engine_limit"]["min_mn"])


def _wobbe(composition: GasComposition) -> float:
    return calorific_values(composition, _REF_0C).wobbe_superior_mj_per_m3


def _boundary_fraction(predicate, cap: float = 1.0, iters: int = 60) -> float | None:
    """Największy udział x ∈ [0, cap] spełniający monotoniczny ``predicate``.

    Zakłada, że obszar zgodności to [0, x_max] (metryka monotoniczna w x).
    Zwraca ``cap`` gdy cały zakres zgodny, 0.0 gdy nawet x=0 niezgodny.
    """
    if not predicate(0.0):
        return 0.0
    if predicate(cap):
        return cap
    lo, hi = 0.0, cap
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if predicate(mid):
            lo = mid
        else:
            hi = mid
    return lo


@dataclass(frozen=True)
class HydrogenLimit:
    """Maksymalny udział H₂ dla zgodności z grupą E i ograniczenie wiążące."""

    max_h2_mole_pct: float  # wiążący (najniższy z poniższych)
    binding: str  # "liczba metanowa" | "liczba Wobbego" | "próg %H₂" | "brak (100%)"
    wobbe_limited_pct: float  # 100.0 gdy Wobbe nie ogranicza w [0,100%]
    mn_limited_pct: float
    policy_limit_pct: float | None  # None gdy próg %H₂ nie podany


def max_hydrogen_for_group_e(
    base: GasComposition,
    h2_stream: GasComposition | None = None,
    h2_policy_mole_pct: float | None = None,
) -> HydrogenLimit:
    """Maksymalny udział H₂ (mol), przy którym gaz nadal spełnia wymogi E.

    Rozważane ograniczenia (monotoniczne w udziale H₂):
        * liczba Wobbego ≥ dolna granica pasma E,
        * liczba metanowa ≥ limit silnikowy,
        * (opcjonalnie) próg polityczny/scenariuszowy %H₂.

    Args:
        base: gaz bazowy (przed domieszką H₂),
        h2_stream: strumień wodoru (klasa czystości); domyślnie czysty H₂,
        h2_policy_mole_pct: próg %H₂ (scenariuszowy) — None pomija to kryterium.

    Returns:
        ``HydrogenLimit`` z wiążącym maksimum i wartościami per kryterium.
    """
    stream = h2_stream if h2_stream is not None else GasComposition.pure("H2")
    wobbe_min, _ = group_e_wobbe_limits()
    mn_limit = engine_methane_number_limit()

    def _blend(x: float) -> GasComposition:
        return base.blend(stream, x)

    wobbe_pct = (_boundary_fraction(lambda x: _wobbe(_blend(x)) >= wobbe_min) or 0.0) * 100.0
    mn_pct = (_boundary_fraction(lambda x: methane_number(_blend(x)) >= mn_limit) or 0.0) * 100.0

    candidates = {"liczba Wobbego": wobbe_pct, "liczba metanowa": mn_pct}
    if h2_policy_mole_pct is not None:
        candidates["próg %H₂"] = float(h2_policy_mole_pct)

    binding = min(candidates, key=candidates.get)
    max_pct = candidates[binding]
    if max_pct >= 99.999:
        binding = "brak (100%)"
    return HydrogenLimit(
        max_h2_mole_pct=max_pct,
        binding=binding,
        wobbe_limited_pct=wobbe_pct,
        mn_limited_pct=mn_pct,
        policy_limit_pct=(float(h2_policy_mole_pct) if h2_policy_mole_pct is not None else None),
    )


@dataclass(frozen=True)
class EnrichmentResult:
    """Wynik propanowania: ile C₃H₈ dodać, by przywrócić Wobbe do pasma E."""

    needed: bool  # czy propan jest w ogóle potrzebny
    feasible: bool  # czy osiągalne w rozsądnym zakresie (≤ cap)
    propane_mole_pct: float  # udział molowy dodanego propanu
    enriched: GasComposition
    wobbe_before_mj_per_m3: float
    wobbe_after_mj_per_m3: float
    wobbe_target_mj_per_m3: float
    mn_before: float
    mn_after: float
    mn_ok_after: bool
    note: str


def propane_enrichment_for_group_e(
    composition: GasComposition,
    max_propane_mole_pct: float = 30.0,
) -> EnrichmentResult:
    """Ile propanu dodać, aby liczba Wobbego wróciła do dolnej granicy pasma E.

    Propanowanie (wzbogacanie LPG) podnosi Wobbe i wartość opałową — stosowane,
    gdy domieszka (dużo H₂, inerty w biometanie) obniża Wobbe poniżej 45 MJ/m³.
    Propan **obniża** jednak liczbę metanową (MN(C₃H₈) ≈ 34), więc wynik podaje
    MN po wzbogaceniu i flagę limitu silnikowego — korekta Wobbego nie musi
    oznaczać pełnej zgodności E.

    Args:
        composition: gaz do skorygowania (po domieszkach),
        max_propane_mole_pct: górny sensowny limit propanowania [% mol].

    Returns:
        ``EnrichmentResult``; ``needed=False`` gdy Wobbe już w paśmie.
    """
    wobbe_min, _ = group_e_wobbe_limits()
    propane = GasComposition.pure("C3H8")
    mn_limit = engine_methane_number_limit()

    wobbe_before = _wobbe(composition)
    mn_before = methane_number(composition)

    if wobbe_before >= wobbe_min:
        return EnrichmentResult(
            needed=False,
            feasible=True,
            propane_mole_pct=0.0,
            enriched=composition,
            wobbe_before_mj_per_m3=wobbe_before,
            wobbe_after_mj_per_m3=wobbe_before,
            wobbe_target_mj_per_m3=wobbe_min,
            mn_before=mn_before,
            mn_after=mn_before,
            mn_ok_after=mn_before >= mn_limit,
            note="Liczba Wobbego już w paśmie grupy E — propanowanie zbędne.",
        )

    cap = max_propane_mole_pct / 100.0

    def _meets(p: float) -> bool:
        return _wobbe(composition.blend(propane, p)) >= wobbe_min

    if not _meets(cap):
        enriched = composition.blend(propane, cap)
        return EnrichmentResult(
            needed=True,
            feasible=False,
            propane_mole_pct=max_propane_mole_pct,
            enriched=enriched,
            wobbe_before_mj_per_m3=wobbe_before,
            wobbe_after_mj_per_m3=_wobbe(enriched),
            wobbe_target_mj_per_m3=wobbe_min,
            mn_before=mn_before,
            mn_after=methane_number(enriched),
            mn_ok_after=methane_number(enriched) >= mn_limit,
            note=(
                f"Nawet {max_propane_mole_pct:g}% propanu nie przywraca Wobbe do "
                "45 MJ/m³ — domieszka zbyt silnie rozcieńcza gaz (rozważ mniejszy "
                "udział domieszki)."
            ),
        )

    # najmniejszy propan p, przy którym Wobbe ≥ min (Wobbe rośnie z propanem)
    lo, hi = 0.0, cap
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if _meets(mid):
            hi = mid
        else:
            lo = mid
    propane_frac = hi
    enriched = composition.blend(propane, propane_frac)
    mn_after = methane_number(enriched)
    mn_ok = mn_after >= mn_limit
    note = "Propan przywraca liczbę Wobbego do pasma E. " + (
        "Liczba metanowa nadal w normie."
        if mn_ok
        else f"UWAGA: liczba metanowa po wzbogaceniu {mn_after:.0f} < {mn_limit:g} — "
        "propan poprawia Wobbe, ale pogarsza odporność na spalanie stukowe."
    )
    return EnrichmentResult(
        needed=True,
        feasible=True,
        propane_mole_pct=propane_frac * 100.0,
        enriched=enriched,
        wobbe_before_mj_per_m3=wobbe_before,
        wobbe_after_mj_per_m3=_wobbe(enriched),
        wobbe_target_mj_per_m3=wobbe_min,
        mn_before=mn_before,
        mn_after=mn_after,
        mn_ok_after=mn_ok,
        note=note,
    )


def hydrogen_grades() -> dict[str, dict]:
    """Klasy czystości wodoru z ``data/hydrogen_grades.yaml``."""
    return load_data_file("hydrogen_grades.yaml")["grades"]


def hydrogen_grade_composition(grade_key: str) -> GasComposition:
    """Skład strumienia wodoru dla wybranej klasy czystości."""
    grades = hydrogen_grades()
    if grade_key not in grades:
        raise ValueError(
            f"Nieznana klasa czystości H₂ '{grade_key}' — dostępne: {', '.join(grades)}."
        )
    return GasComposition.from_percent(grades[grade_key]["mole_percent"])


def biomethane_compositions() -> dict[str, dict]:
    """Biblioteka typowych składów biometanu z danych."""
    return load_data_file("biomethane_compositions.yaml")["compositions"]
