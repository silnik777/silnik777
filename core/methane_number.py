"""Liczba metanowa (Methane Number, MN) — odporność na spalanie stukowe (M1).

Model liniowy: MN = Σ x_j · MN_j (molowe mieszanie wartości składnikowych
z ``data/methane_number.yaml``). MN(CH4)=100, MN(H2)=0 są ścisłe z definicji
(Leiker 1972: MN = % obj. CH4 w mieszaninie odniesienia CH4/H2). Na osi
CH4–H2 model jest dokładny — istotne przy ocenie domieszki wodoru; dla
cięższych węglowodorów i inertów to przybliżenie (certyfikacja: EN 16726
Annex A / ASTM D8221, algorytm MWM — poza zakresem narzędzia).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.composition import GasComposition
from core.config import load_data_file


@cache
def _component_mn() -> dict[str, float]:
    return {k: float(v) for k, v in load_data_file("methane_number.yaml")["component_mn"].items()}


def methane_number(composition: GasComposition) -> float:
    """Liczba metanowa mieszaniny (model liniowy molowy) [-].

    Raises:
        ValueError: gdy któryś składnik nie ma zdefiniowanej MN w danych.
    """
    table = _component_mn()
    missing = [k for k, _ in composition.fractions if k not in table]
    if missing:
        raise ValueError(
            f"Brak liczby metanowej dla składników: {', '.join(missing)} — "
            "uzupełnij data/methane_number.yaml."
        )
    return sum(x * table[k] for k, x in composition.fractions)


@dataclass(frozen=True)
class MethaneNumberResult:
    """Liczba metanowa + ocena względem limitu silnikowego."""

    value: float
    min_limit: float
    ok: bool
    source: str
    note: str


def methane_number_assessment(composition: GasComposition) -> MethaneNumberResult:
    """Liczba metanowa z flagą zgodności (limit silnikowy z danych)."""
    data = load_data_file("methane_number.yaml")
    limit = float(data["engine_limit"]["min_mn"])
    value = methane_number(composition)
    return MethaneNumberResult(
        value=value,
        min_limit=limit,
        ok=value >= limit,
        source=data["engine_limit"]["source"],
        note=data["meta"]["note"],
    )
