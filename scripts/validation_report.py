"""Raport walidacji M1: wartości obliczone vs referencyjne.

Uruchomienie: ``python scripts/validation_report.py`` (z katalogu repo).
Generuje tabelę markdown: wielkość / obliczona / referencja / odchyłka / źródło.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.calorific import calorific_values  # noqa: E402
from core.composition import GasComposition  # noqa: E402
from core.gas_properties import compute_properties  # noqa: E402
from tests.reference_data import CALORIFIC_REFERENCES, PROPERTY_REFERENCES  # noqa: E402


def main() -> None:
    rows: list[tuple[str, float, float, float, float, str]] = []

    for ref in PROPERTY_REFERENCES:
        props = compute_properties(
            GasComposition.pure(ref.component), ref.pressure_pa, ref.temperature_k
        )
        value = getattr(props, ref.quantity)
        label = (
            f"{ref.component}: {ref.quantity} "
            f"({ref.pressure_pa / 1e5:.3f} bar, {ref.temperature_k - 273.15:.0f} °C)"
        )
        rows.append(
            (
                label,
                value,
                ref.reference_value,
                abs(value - ref.reference_value) / ref.reference_value * 100,
                ref.rel_tolerance * 100,
                ref.source,
            )
        )

    for ref in CALORIFIC_REFERENCES:
        result = calorific_values(GasComposition.pure(ref.component))
        value = getattr(result, ref.quantity)
        rows.append(
            (
                f"{ref.label} [{ref.unit}]",
                value,
                ref.reference_value,
                abs(value - ref.reference_value) / ref.reference_value * 100,
                ref.rel_tolerance * 100,
                ref.source,
            )
        )

    print("| Wielkość | Obliczona | Referencja | Odchyłka | Tolerancja | Źródło |")
    print("|---|---|---|---|---|---|")
    for label, value, reference, dev_pct, tol_pct, source in rows:
        status = "✅" if dev_pct <= tol_pct else "❌"
        print(
            f"| {label} | {value:.5g} | {reference:.5g} | {dev_pct:.3f}% {status} "
            f"| ≤{tol_pct:.2g}% | {source} |"
        )


if __name__ == "__main__":
    main()
