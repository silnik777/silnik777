"""Ładowanie danych konfiguracyjnych z katalogu ``data/``.

Zasady:
    * współczynniki, progi i biblioteki technologii leżą w plikach YAML/JSON
      w katalogu ``data/`` — edytowalne bez zmian w kodzie;
    * każdy plik ma sekcję ``meta`` z polami ``description`` i ``updated``,
      a poszczególne wartości — pole ``source`` (norma / raport) oraz
      opcjonalnie ``note`` (np. "wartość orientacyjna — do weryfikacji");
    * katalog danych można nadpisać zmienną środowiskową ``GAS_RD_DATA_DIR``
      (przydatne w kontenerze / na Azure).
"""

from __future__ import annotations

import json
import os
from functools import cache
from pathlib import Path
from typing import Any

import yaml

#: Klucze wymagane w sekcji ``meta`` każdego pliku danych.
REQUIRED_META_KEYS = ("description", "updated")


def data_dir() -> Path:
    """Zwraca katalog z danymi konfiguracyjnymi.

    Domyślnie ``<repo>/data``; można nadpisać zmienną ``GAS_RD_DATA_DIR``.
    """
    env_dir = os.environ.get("GAS_RD_DATA_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parent.parent / "data"


class ConfigError(ValueError):
    """Błąd struktury lub zawartości pliku danych konfiguracyjnych."""


def _validate_meta(content: dict[str, Any], path: Path) -> None:
    meta = content.get("meta")
    if not isinstance(meta, dict):
        raise ConfigError(
            f"Plik danych '{path.name}' nie zawiera wymaganej sekcji 'meta' "
            f"(z polami: {', '.join(REQUIRED_META_KEYS)})."
        )
    missing = [key for key in REQUIRED_META_KEYS if key not in meta]
    if missing:
        raise ConfigError(
            f"Sekcja 'meta' w pliku '{path.name}' nie zawiera pól: {', '.join(missing)}."
        )


@cache
def load_data_file(filename: str) -> dict[str, Any]:
    """Wczytuje plik YAML/JSON z katalogu danych i waliduje sekcję ``meta``.

    Args:
        filename: nazwa pliku w katalogu danych, np. ``"quality_limits.yaml"``.

    Returns:
        Zawartość pliku jako słownik (wynik jest cache'owany).

    Raises:
        FileNotFoundError: gdy plik nie istnieje (komunikat po polsku).
        ConfigError: gdy struktura pliku jest niepoprawna.
    """
    path = data_dir() / filename
    if not path.is_file():
        raise FileNotFoundError(f"Nie znaleziono pliku danych: {path}")

    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        content = json.loads(text)
    else:
        content = yaml.safe_load(text)

    if not isinstance(content, dict):
        raise ConfigError(
            f"Plik danych '{path.name}' musi zawierać słownik na najwyższym poziomie."
        )
    _validate_meta(content, path)
    return content


def clear_cache() -> None:
    """Czyści cache wczytanych plików (np. po edycji danych w trakcie pracy)."""
    load_data_file.cache_clear()
