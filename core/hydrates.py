"""Równowagowa temperatura tworzenia hydratów gazu ziemnego (M4/M13).

Metoda: korelacja Towlera-Mokhataba (2005) typu wykresu Katza dla gazów
słodkich (bez H2S), oparta na gęstości względnej gazu:

    T_hyd [°F] = 13,47·ln(p[psia]) + 34,27·ln(SG)
                 − 1,675·ln(p[psia])·ln(SG) − 20,35

Źródło: Towler B.F., Mokhatab S., "Quickly estimate hydrate formation
conditions in natural gases", Hydrocarbon Processing 84(4) (2005) 61–62;
cytowana w: Mokhatab S. i in., Handbook of Natural Gas Transmission and
Processing. Zakres ważności: gaz słodki, SG = 0,55–1,0; dokładność ±2–3 K
(dla czystego CH4 korelacja zawyża T_hyd o kilka K — wynik po stronie
bezpiecznej).

Mieszaniny z wodorem: H2 praktycznie nie tworzy hydratów przy ciśnieniach
sieciowych (stabilne dopiero w skali setek MPa — Sloan & Koh, "Clathrate
Hydrates of Natural Gases", 3. wyd. 2008), a rozcieńczenie H2 obniża
równowagową temperaturę hydratów mieszaniny. Przyjmujemy podejście
KONSERWATYWNE: korelację liczymy dla frakcji gazu bez H2/He (renormalizowanej)
przy PEŁNYM ciśnieniu rurociągu — rzeczywista temperatura hydratów jest
niższa lub równa tak policzonej.

Uwaga interpretacyjna: ryzyko hydratów dotyczy gazu zawierającego wodę;
dla gazu osuszonego do sieciowego punktu rosy wody ryzyko jest odpowiednio
niższe — flaga ma charakter przesiewowy (screening).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from core.composition import GasComposition, components_registry
from core.config import load_data_file

#: Masa molowa suchego powietrza [kg/kmol] (ISO 6976) — do gęstości względnej.
_M_AIR_KG_PER_KMOL = 28.9626

#: Składniki nieuwzględniane w frakcji hydratotwórczej.
_NON_HYDRATE_FORMERS = ("H2", "He")

#: Zakres ważności korelacji (gęstość względna frakcji hydratotwórczej).
SG_VALID_RANGE = (0.55, 1.0)


@dataclass(frozen=True)
class HydrateCheck:
    """Wynik przesiewowej oceny ryzyka hydratów przy zadanym ciśnieniu."""

    hydrate_temperature_k: float | None  # None = brak frakcji hydratotwórczej
    margin_k: float  # zastosowany margines bezpieczeństwa
    min_safe_temperature_k: float | None  # T_hyd + margines
    hydrate_former_fraction: float  # udział molowy frakcji hydratotwórczej
    warnings: list[str]

    def is_at_risk(self, temperature_k: float) -> bool:
        """Czy temperatura gazu leży poniżej progu bezpieczeństwa."""
        if self.min_safe_temperature_k is None:
            return False
        return temperature_k < self.min_safe_temperature_k


def _hydrate_former_subset(
    composition: GasComposition,
) -> tuple[GasComposition | None, float]:
    """Frakcja hydratotwórcza (bez H2/He), renormalizowana; (None, 0) gdy pusta."""
    subset = {key: x for key, x in composition.fractions if key not in _NON_HYDRATE_FORMERS}
    total = sum(subset.values())
    if total <= 1e-9:
        return None, 0.0
    normalized = {k: v / total for k, v in subset.items()}
    return GasComposition.from_fractions(normalized), total


def hydrate_temperature_k(
    composition: GasComposition, pressure_pa: float
) -> tuple[float | None, list[str]]:
    """Równowagowa temperatura hydratów [K] wg Towlera-Mokhataba (2005).

    Args:
        composition: skład gazu (M1); frakcja H2/He jest pomijana
            (podejście konserwatywne — patrz docstring modułu),
        pressure_pa: ciśnienie bezwzględne [Pa], > 0.

    Returns:
        (T_hyd [K] albo None gdy brak frakcji hydratotwórczej,
         lista ostrzeżeń o zakresie ważności).
    """
    if pressure_pa <= 0.0:
        raise ValueError(f"Ciśnienie musi być dodatnie (otrzymano {pressure_pa} Pa).")

    formers, fraction = _hydrate_former_subset(composition)
    if formers is None:
        return None, ["Gaz bez składników hydratotwórczych (czysty H2/He) — brak ryzyka."]

    warnings: list[str] = []
    registry = components_registry()
    m_formers = sum(x * registry[k].molar_mass_kg_per_kmol for k, x in formers.fractions)
    sg = m_formers / _M_AIR_KG_PER_KMOL
    if not SG_VALID_RANGE[0] <= sg <= SG_VALID_RANGE[1]:
        warnings.append(
            f"Gęstość względna frakcji hydratotwórczej ({sg:.3f}) poza zakresem "
            f"ważności korelacji Towlera-Mokhataba ({SG_VALID_RANGE[0]}–"
            f"{SG_VALID_RANGE[1]}) — wynik traktować jako szacunek."
        )
    if fraction < 0.999:
        warnings.append(
            f"Domieszka H2/He ({(1 - fraction) * 100:.1f}% mol) pominięta "
            "konserwatywnie: korelacja dla frakcji GZ przy pełnym ciśnieniu — "
            "rzeczywista temperatura hydratów jest niższa."
        )

    p_psia = pressure_pa / 6894.757
    if p_psia <= 1.0:
        return None, warnings + ["Ciśnienie zbyt niskie dla korelacji (< 1 psia)."]

    ln_p, ln_sg = math.log(p_psia), math.log(sg)
    t_f = 13.47 * ln_p + 34.27 * ln_sg - 1.675 * ln_p * ln_sg - 20.35
    t_k = (t_f - 32.0) * 5.0 / 9.0 + 273.15
    return t_k, warnings


def check_hydrates(
    composition: GasComposition,
    pressure_pa: float,
    margin_k: float | None = None,
) -> HydrateCheck:
    """Przesiewowa ocena ryzyka hydratów: T_hyd + margines bezpieczeństwa.

    Args:
        composition: skład gazu,
        pressure_pa: ciśnienie, przy którym oceniamy ryzyko (zwykle wylot
            redukcji — najniższa temperatura) [Pa],
        margin_k: margines bezpieczeństwa [K]; domyślnie z
            ``data/expanders.yaml`` (3 K, praktyka 3–5 K).
    """
    if margin_k is None:
        margin_k = float(load_data_file("expanders.yaml")["defaults"]["hydrate_margin_k"])

    t_hyd, warnings = hydrate_temperature_k(composition, pressure_pa)
    _, fraction = _hydrate_former_subset(composition)
    return HydrateCheck(
        hydrate_temperature_k=t_hyd,
        margin_k=margin_k,
        min_safe_temperature_k=None if t_hyd is None else t_hyd + margin_k,
        hydrate_former_fraction=fraction,
        warnings=warnings,
    )
