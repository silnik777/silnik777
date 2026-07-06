"""Skład molowy gazu: walidacja, normalizacja, mieszanie (M1).

Składniki i ich dane (nazwy CoolProp, ciepła spalania ISO 6976) pochodzą
z pliku ``data/components.yaml``. Udziały przechowujemy jako ułamki molowe
(suma = 1); wejście w procentach obsługuje ``GasComposition.from_percent``.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache

import CoolProp.CoolProp as CP

from core.config import load_data_file

#: Tolerancja sumy udziałów molowych (po przeliczeniu z %).
SUM_TOLERANCE = 1.0e-4


@dataclass(frozen=True)
class ComponentInfo:
    """Dane składnika gazu (źródła w ``data/components.yaml``)."""

    key: str
    name_pl: str
    formula: str
    coolprop_name: str
    hhv_molar_25c_kj_per_mol: float
    h2o_mol_per_mol: int
    source: str
    note: str | None = None

    @property
    def molar_mass_kg_per_kmol(self) -> float:
        """Masa molowa z bazy CoolProp [kg/kmol]."""
        return _coolprop_molar_mass(self.coolprop_name)


@cache
def _coolprop_molar_mass(coolprop_name: str) -> float:
    return CP.PropsSI("molemass", coolprop_name) * 1.0e3  # kg/mol → kg/kmol


@cache
def components_registry() -> dict[str, ComponentInfo]:
    """Rejestr obsługiwanych składników wczytany z ``data/components.yaml``."""
    raw = load_data_file("components.yaml")["components"]
    return {
        key: ComponentInfo(
            key=key,
            name_pl=item["name_pl"],
            formula=item["formula"],
            coolprop_name=item["coolprop_name"],
            hhv_molar_25c_kj_per_mol=float(item["hhv_molar_25c_kj_per_mol"]),
            h2o_mol_per_mol=int(item["h2o_mol_per_mol"]),
            source=item["source"],
            note=item.get("note"),
        )
        for key, item in raw.items()
    }


@dataclass(frozen=True)
class GasComposition:
    """Skład molowy gazu (ułamki molowe, suma = 1).

    Tworzenie przez ``from_fractions``/``from_percent`` gwarantuje walidację:
    znane składniki, udziały nieujemne, suma = 1 ± tolerancja.
    """

    fractions: tuple[tuple[str, float], ...]

    # --- konstrukcja ---------------------------------------------------

    @staticmethod
    def _validate(fractions: dict[str, float]) -> dict[str, float]:
        registry = components_registry()
        unknown = [k for k in fractions if k not in registry]
        if unknown:
            raise ValueError(
                f"Nieznane składniki: {', '.join(unknown)}. " f"Obsługiwane: {', '.join(registry)}."
            )
        negative = {k: v for k, v in fractions.items() if v < 0.0}
        if negative:
            raise ValueError(f"Udziały molowe nie mogą być ujemne: {negative}.")
        cleaned = {k: float(v) for k, v in fractions.items() if v > 0.0}
        if not cleaned:
            raise ValueError("Skład gazu jest pusty — podaj co najmniej jeden składnik.")
        total = sum(cleaned.values())
        if abs(total - 1.0) > SUM_TOLERANCE:
            raise ValueError(
                f"Suma udziałów molowych musi wynosić 1 (100%), a wynosi {total:.6f} "
                f"({total * 100:.4f}%). Popraw skład lub użyj normalizacji."
            )
        # Dokładna renormalizacja resztkowej odchyłki (≤ tolerancja).
        return {k: v / total for k, v in cleaned.items()}

    @classmethod
    def from_fractions(cls, fractions: dict[str, float]) -> GasComposition:
        """Tworzy skład z ułamków molowych (suma = 1 ± 1e-4)."""
        valid = cls._validate(fractions)
        return cls(fractions=tuple(sorted(valid.items())))

    @classmethod
    def from_percent(cls, percent: dict[str, float]) -> GasComposition:
        """Tworzy skład z udziałów w % molowych (suma = 100 ± 0,01%)."""
        return cls.from_fractions({k: v / 100.0 for k, v in percent.items()})

    @classmethod
    def pure(cls, component_key: str) -> GasComposition:
        """Czysty składnik, np. ``GasComposition.pure("H2")``."""
        return cls.from_fractions({component_key: 1.0})

    @classmethod
    def predefined(cls, key: str) -> GasComposition:
        """Skład predefiniowany z ``data/gas_compositions.yaml``."""
        compositions = load_data_file("gas_compositions.yaml")["compositions"]
        if key not in compositions:
            raise ValueError(
                f"Brak predefiniowanego składu '{key}'. Dostępne: {', '.join(compositions)}."
            )
        return cls.from_percent(compositions[key]["mole_percent"])

    # --- dostęp ---------------------------------------------------------

    def as_dict(self) -> dict[str, float]:
        """Ułamki molowe jako słownik {składnik: ułamek}."""
        return dict(self.fractions)

    def fraction(self, component_key: str) -> float:
        """Ułamek molowy składnika (0, jeśli nieobecny)."""
        return self.as_dict().get(component_key, 0.0)

    @property
    def h2_mole_percent(self) -> float:
        """Udział molowy wodoru [%]."""
        return self.fraction("H2") * 100.0

    @property
    def molar_mass_kg_per_kmol(self) -> float:
        """Masa molowa mieszaniny: M = Σ x_j·M_j [kg/kmol]."""
        registry = components_registry()
        return sum(x * registry[k].molar_mass_kg_per_kmol for k, x in self.fractions)

    @property
    def is_combustible(self) -> bool:
        """Czy gaz jest palny (zawiera składnik o dodatnim cieple spalania)."""
        registry = components_registry()
        return any(
            registry[k].hhv_molar_25c_kj_per_mol > 0.0 and x > 0.0 for k, x in self.fractions
        )

    # --- operacje -------------------------------------------------------

    def blend(self, other: GasComposition, other_fraction: float) -> GasComposition:
        """Mieszanina molowa: (1−y)·self + y·other.

        Args:
            other: drugi gaz (np. czysty H2),
            other_fraction: udział molowy ``other`` w mieszaninie, 0–1.
        """
        if not 0.0 <= other_fraction <= 1.0:
            raise ValueError(
                f"Udział domieszki musi być w zakresie 0–1 (otrzymano {other_fraction})."
            )
        if other_fraction == 0.0:
            return self
        if other_fraction == 1.0:
            return other
        mixed: dict[str, float] = {}
        for key, x in self.fractions:
            mixed[key] = mixed.get(key, 0.0) + (1.0 - other_fraction) * x
        for key, x in other.fractions:
            mixed[key] = mixed.get(key, 0.0) + other_fraction * x
        return GasComposition.from_fractions(mixed)

    def blend_with_hydrogen(self, h2_mole_fraction: float) -> GasComposition:
        """Mieszanina z czystym H2 o zadanym udziale molowym H2 (0–1)."""
        return self.blend(GasComposition.pure("H2"), h2_mole_fraction)

    @classmethod
    def from_mixture(
        cls, streams: list[tuple[GasComposition, float]]
    ) -> GasComposition:
        """Mieszanina molowa N strumieni: ``[(skład, udział_molowy), …]``.

        Udziały muszą sumować się do 1 (tolerancja ``SUM_TOLERANCE``). Służy do
        łączenia gazu bazowego z domieszkami (wodór o danej klasie czystości,
        biometan) w jednym kroku, z zachowaniem bilansu molowego.
        """
        total = sum(f for _, f in streams)
        if abs(total - 1.0) > SUM_TOLERANCE:
            raise ValueError(
                f"Udziały strumieni muszą sumować się do 1 (jest {total:.4f})."
            )
        mixed: dict[str, float] = {}
        for comp, frac in streams:
            if frac < 0.0:
                raise ValueError("Udział strumienia nie może być ujemny.")
            for key, x in comp.fractions:
                mixed[key] = mixed.get(key, 0.0) + frac * x
        return cls.from_fractions(mixed)
