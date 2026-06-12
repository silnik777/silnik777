"""Eksport wyników do XLSX i CSV (pod Power BI i obieg dokumentów) — M14.

XLSX: arkusze "Projekty" (wskaźniki), "Ranking" (ocena wielokryterialna),
"Kryteria" (definicje i wagi). CSV: płaska tabela wskaźników (separator ';',
kodowanie UTF-8 z BOM — zgodne z polskim Excelem i Power BI).
"""

from __future__ import annotations

import io

import pandas as pd

from core.project_card import ComparisonResult, ProjectCard, criteria_registry


def projects_dataframe(cards: list[ProjectCard]) -> pd.DataFrame:
    """Tabela wskaźników projektów (wiersze = projekty)."""
    registry = criteria_registry()
    rows = []
    for card in cards:
        row: dict[str, object] = {
            "Projekt": card.name,
            "Opis": card.description,
            "Data utworzenia": card.created,
        }
        for key, crit in registry.items():
            row[f"{crit.name_pl} [{crit.unit}]"] = card.indicators.get(key)
        row["Uwagi"] = card.notes
        rows.append(row)
    return pd.DataFrame(rows)


def ranking_dataframe(comparison: ComparisonResult) -> pd.DataFrame:
    """Tabela rankingu z wynikami cząstkowymi."""
    registry = criteria_registry()
    rows = []
    for place, ps in enumerate(comparison.ranked, start=1):
        row: dict[str, object] = {
            "Miejsce": place,
            "Projekt": ps.card.name,
            "Wynik [0–1]": round(ps.score, 4),
        }
        for key in comparison.used_criteria:
            row[f"{registry[key].name_pl} (ocena)"] = round(ps.criterion_scores[key], 4)
        rows.append(row)
    return pd.DataFrame(rows)


def criteria_dataframe(weights: dict[str, float] | None = None) -> pd.DataFrame:
    """Tabela definicji kryteriów (+ zastosowane wagi)."""
    registry = criteria_registry()
    return pd.DataFrame(
        [
            {
                "Kryterium": c.name_pl,
                "Jednostka": c.unit,
                "Kierunek": "wyższa lepsza" if c.direction == "wyzej" else "niższa lepsza",
                "Kategoria": c.category,
                "Waga": (weights or {}).get(key, c.default_weight),
                "Gdzie policzyć": c.gdzie_policzyc,
            }
            for key, c in registry.items()
        ]
    )


def export_xlsx(
    cards: list[ProjectCard],
    comparison: ComparisonResult | None = None,
    weights: dict[str, float] | None = None,
) -> bytes:
    """Skoroszyt XLSX (bajty — do ``st.download_button`` / zapisu na dysk)."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        projects_dataframe(cards).to_excel(writer, sheet_name="Projekty", index=False)
        if comparison is not None:
            ranking_dataframe(comparison).to_excel(writer, sheet_name="Ranking", index=False)
        criteria_dataframe(weights).to_excel(writer, sheet_name="Kryteria", index=False)
    return buffer.getvalue()


def export_csv(cards: list[ProjectCard]) -> bytes:
    """CSV wskaźników projektów (';', UTF-8 BOM — polski Excel/Power BI)."""
    return projects_dataframe(cards).to_csv(index=False, sep=";").encode("utf-8-sig")
