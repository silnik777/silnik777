"""Karta oceny projektu B+R: zapis, ocena wielokryterialna, porównanie — M14.

Karta projektu zbiera wskaźniki wyznaczone w modułach M1–M13 (pole
``gdzie_policzyc`` każdego kryterium wskazuje właściwy moduł) w jeden
rekord; projekty są zapisywane jako JSON w ``data/projects/`` i mogą być
porównywane rankingiem wielokryterialnym (ta sama metodyka co M11:
normalizacja min–max w obrębie porównywanych projektów + suma ważona).

Kryterium wchodzi do oceny tylko wtedy, gdy WSZYSTKIE porównywane projekty
mają jego wartość (inaczej jest pomijane — lista pominiętych w wyniku);
wagi są wtedy renormalizowane.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from functools import cache
from pathlib import Path

from core.config import data_dir, load_data_file

PROJECTS_SUBDIR = "projects"


@dataclass(frozen=True)
class Criterion:
    """Kryterium oceny z rejestru ``data/project_criteria.yaml``."""

    key: str
    name_pl: str
    unit: str
    direction: str  # "wyzej" | "nizej"
    category: str  # techniczne | ekonomiczne | ekologiczne
    default_weight: float
    gdzie_policzyc: str


@cache
def criteria_registry() -> dict[str, Criterion]:
    """Rejestr kryteriów oceny projektów."""
    raw = load_data_file("project_criteria.yaml")["criteria"]
    result = {}
    for key, item in raw.items():
        if item["direction"] not in ("wyzej", "nizej"):
            raise ValueError(f"Kryterium '{key}': kierunek musi być 'wyzej'/'nizej'.")
        result[key] = Criterion(
            key=key,
            name_pl=item["name_pl"],
            unit=item["unit"],
            direction=item["direction"],
            category=item["category"],
            default_weight=float(item["default_weight"]),
            gdzie_policzyc=item["gdzie_policzyc"],
        )
    return result


@dataclass(frozen=True)
class ProjectCard:
    """Karta projektu B+R: opis + wskaźniki {klucz kryterium: wartość}."""

    name: str
    description: str
    indicators: dict[str, float]
    created: str = field(default_factory=lambda: date.today().isoformat())
    notes: str = ""

    def __post_init__(self) -> None:
        registry = criteria_registry()
        unknown = set(self.indicators) - set(registry)
        if unknown:
            raise ValueError(
                f"Nieznane wskaźniki: {', '.join(sorted(unknown))}. "
                f"Dostępne: {', '.join(registry)}."
            )


def _projects_dir() -> Path:
    path = data_dir() / PROJECTS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def _slug(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_\-]+", "_", name).strip("_")
    if not slug:
        raise ValueError("Nazwa projektu musi zawierać litery lub cyfry.")
    return slug[:64]


def save_project(card: ProjectCard) -> Path:
    """Zapisuje kartę projektu do JSON; zwraca ścieżkę pliku."""
    path = _projects_dir() / f"{_slug(card.name)}.json"
    payload = {
        "name": card.name,
        "description": card.description,
        "indicators": card.indicators,
        "created": card.created,
        "notes": card.notes,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_projects() -> dict[str, ProjectCard]:
    """Wczytuje wszystkie zapisane projekty {slug: karta}."""
    result = {}
    for file in sorted(_projects_dir().glob("*.json")):
        raw = json.loads(file.read_text(encoding="utf-8"))
        result[file.stem] = ProjectCard(
            name=raw["name"],
            description=raw.get("description", ""),
            indicators={k: float(v) for k, v in raw.get("indicators", {}).items()},
            created=raw.get("created", ""),
            notes=raw.get("notes", ""),
        )
    return result


def delete_project(slug: str) -> None:
    """Usuwa zapisany projekt."""
    path = _projects_dir() / f"{slug}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Brak projektu '{slug}'.")
    path.unlink()


@dataclass(frozen=True)
class ProjectScore:
    """Wynik oceny projektu w porównaniu."""

    card: ProjectCard
    score: float  # 0–1
    criterion_scores: dict[str, float]


@dataclass(frozen=True)
class ComparisonResult:
    """Ranking projektów + metadane porównania."""

    ranked: list[ProjectScore]
    used_criteria: list[str]
    skipped_criteria: list[str]  # brak wartości w którymś projekcie


def compare_projects(
    cards: list[ProjectCard],
    weights: dict[str, float] | None = None,
) -> ComparisonResult:
    """Ranking wielokryterialny projektów (min–max + suma ważona).

    Args:
        cards: ≥ 2 karty projektów,
        weights: wagi {klucz kryterium: waga ≥ 0}; domyślnie z rejestru.

    Raises:
        ValueError: < 2 projektów albo brak wspólnych kryteriów / wag.
    """
    if len(cards) < 2:
        raise ValueError("Porównanie wymaga co najmniej dwóch projektów.")
    registry = criteria_registry()
    w = {k: c.default_weight for k, c in registry.items()}
    if weights:
        unknown = set(weights) - set(registry)
        if unknown:
            raise ValueError(f"Nieznane kryteria wag: {', '.join(sorted(unknown))}.")
        w.update(weights)

    used, skipped = [], []
    for key in registry:
        if all(key in c.indicators for c in cards) and w.get(key, 0.0) > 0:
            used.append(key)
        else:
            skipped.append(key)
    if not used:
        raise ValueError(
            "Brak wspólnych kryteriów z dodatnią wagą — uzupełnij wskaźniki "
            "we wszystkich porównywanych projektach."
        )
    total_w = sum(w[k] for k in used)

    def norm(key: str) -> list[float]:
        values = [c.indicators[key] for c in cards]
        lo, hi = min(values), max(values)
        if hi - lo < 1e-12:
            return [1.0] * len(values)
        scores = [(v - lo) / (hi - lo) for v in values]
        if registry[key].direction == "nizej":
            scores = [1.0 - s for s in scores]
        return scores

    per_criterion = {key: norm(key) for key in used}
    ranked = []
    for i, card in enumerate(cards):
        crit_scores = {key: per_criterion[key][i] for key in used}
        score = sum(w[key] * crit_scores[key] for key in used) / total_w
        ranked.append(ProjectScore(card=card, score=score, criterion_scores=crit_scores))
    return ComparisonResult(
        ranked=sorted(ranked, key=lambda r: -r.score),
        used_criteria=used,
        skipped_criteria=skipped,
    )
