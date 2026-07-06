"""Granice wybuchowości mieszaniny (LEL/UEL) — moduł M1.

Reguła Le Chateliera dla mieszaniny gazów palnych:
    LEL_mix = 1 / Σ (yᵢ / LELᵢ),   UEL_mix = 1 / Σ (yᵢ / UELᵢ),
gdzie yᵢ to udział składnika palnego i w SUMIE składników palnych
(Σ yᵢ = 1). Składniki niepalne (N₂, CO₂, O₂, He, Ar) są wyłączone z sumy —
wynik dotyczy części palnej gazu. Obecność inertów w rzeczywistości zawęża
zakres palności; ujęcie to jest przesiewowe (screening) — do weryfikacji
dla warunków procesowych (T, obecność inertów).

Dane składnikowe: ``data/flammability.yaml`` (NFPA 497 / ISO 10156).
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from core.composition import GasComposition
from core.config import load_data_file


@cache
def _limits() -> dict[str, dict[str, float]]:
    raw = load_data_file("flammability.yaml")["limits_vol_pct_in_air"]
    return {k: {"lel": float(v["lel"]), "uel": float(v["uel"])} for k, v in raw.items()}


@dataclass(frozen=True)
class FlammabilityResult:
    """Granice wybuchowości mieszaniny (część palna), % obj. w powietrzu."""

    lel_vol_pct: float  # dolna granica wybuchowości (LEL)
    uel_vol_pct: float  # górna granica wybuchowości (UEL)
    combustible_fraction: float  # udział molowy części palnej (0–1)
    source: str
    note: str


def flammability_limits(composition: GasComposition) -> FlammabilityResult | None:
    """Granice wybuchowości mieszaniny regułą Le Chateliera.

    Returns:
        ``FlammabilityResult`` albo None, gdy gaz nie zawiera składników
        palnych o zdefiniowanych granicach.
    """
    limits = _limits()
    flammable = [(k, x) for k, x in composition.fractions if k in limits and x > 0.0]
    total = sum(x for _, x in flammable)
    if total <= 0.0:
        return None

    inv_lel = sum((x / total) / limits[k]["lel"] for k, x in flammable)
    inv_uel = sum((x / total) / limits[k]["uel"] for k, x in flammable)
    meta = load_data_file("flammability.yaml")["meta"]
    inert = 1.0 - total
    note = "Wynik dla części palnej gazu (reguła Le Chateliera)."
    if inert > 0.005:
        note += (
            f" Udział składników niepalnych {inert * 100:.1f}% obj. — w rzeczywistości "
            "zawęża zakres palności (ujęcie przesiewowe)."
        )
    return FlammabilityResult(
        lel_vol_pct=1.0 / inv_lel,
        uel_vol_pct=1.0 / inv_uel,
        combustible_fraction=total,
        source=str(meta["source"]).strip(),
        note=note,
    )
