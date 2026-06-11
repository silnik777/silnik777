"""Ścieżki cenowe nośników energii, ETS/ETS2 i emisyjności miksu — moduł M5.

Scenariusze (niski/bazowy/wysoki) z ``data/price_scenarios.yaml``:
punkty kotwiczne {rok: wartość} interpolowane liniowo; poza skrajnymi
latami — wartość stała (najbliższa kotwica). Wszystkie wartości domyślne
są ORIENTACYJNE (rzędy wielkości TGE/IEA WEO/KOBiZE/EUA) — przeznaczone
do edycji; scenariusze użytkownika zapisywane są jako JSON w katalogu
``data/user_scenarios/`` (konfigurowalnym przez ``GAS_RD_DATA_DIR``).

Jednostki: nośniki energii PLN/MWh (wg Hi); EUA/ETS2 EUR/t CO2 (przeliczane
kursem z pliku danych); emisyjność miksu t CO2/MWh el.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from core.config import data_dir, load_data_file

#: Podkatalog na scenariusze użytkownika (JSON).
USER_SCENARIOS_SUBDIR = "user_scenarios"


@dataclass(frozen=True)
class PricePath:
    """Ścieżka wartości w czasie: punkty kotwiczne + interpolacja liniowa."""

    carrier: str
    unit: str
    anchors: tuple[tuple[int, float], ...]  # posortowane (rok, wartość)

    def value(self, year: int | float) -> float:
        """Wartość w roku ``year`` (interpolacja liniowa, poza zakresem: stała)."""
        anchors = self.anchors
        if year <= anchors[0][0]:
            return anchors[0][1]
        if year >= anchors[-1][0]:
            return anchors[-1][1]
        for (y0, v0), (y1, v1) in zip(anchors, anchors[1:], strict=False):
            if y0 <= year <= y1:
                return v0 + (v1 - v0) * (year - y0) / (y1 - y0)
        raise AssertionError("nieosiągalne — kotwice posortowane")


@dataclass(frozen=True)
class PriceScenario:
    """Scenariusz cenowy: komplet ścieżek dla wszystkich nośników."""

    key: str
    name_pl: str
    paths: dict[str, PricePath]
    is_user_defined: bool = False

    def price(self, carrier: str, year: int | float) -> float:
        """Cena/wartość nośnika w roku (jednostka wg ``carriers()``)."""
        if carrier not in self.paths:
            raise ValueError(
                f"Brak nośnika '{carrier}' w scenariuszu '{self.key}'. "
                f"Dostępne: {', '.join(self.paths)}."
            )
        return self.paths[carrier].value(year)

    def price_pln_per_t_co2(self, carrier: str, year: int | float) -> float:
        """Cena uprawnień [PLN/t CO2] (przeliczenie kursem EUR/PLN z danych)."""
        if carriers()[carrier]["unit"] != "EUR/t CO2":
            raise ValueError(f"Nośnik '{carrier}' nie jest ceną CO2.")
        return self.price(carrier, year) * eur_pln_rate()


def carriers() -> dict[str, dict]:
    """Słownik nośników: {klucz: {name_pl, unit}}."""
    return load_data_file("price_scenarios.yaml")["carriers"]


def eur_pln_rate() -> float:
    """Roboczy kurs EUR/PLN z pliku danych (edytowalny)."""
    return float(load_data_file("price_scenarios.yaml")["defaults"]["eur_pln"])


def _build_scenario(key: str, raw: dict, user: bool = False) -> PriceScenario:
    carrier_info = carriers()
    paths: dict[str, PricePath] = {}
    for carrier, anchors in raw["paths"].items():
        if carrier not in carrier_info:
            raise ValueError(
                f"Nieznany nośnik '{carrier}' w scenariuszu '{key}'. "
                f"Obsługiwane: {', '.join(carrier_info)}."
            )
        points = tuple(sorted((int(y), float(v)) for y, v in anchors.items()))
        if not points:
            raise ValueError(f"Pusta ścieżka '{carrier}' w scenariuszu '{key}'.")
        paths[carrier] = PricePath(
            carrier=carrier, unit=carrier_info[carrier]["unit"], anchors=points
        )
    return PriceScenario(
        key=key, name_pl=raw.get("name_pl", key), paths=paths, is_user_defined=user
    )


def builtin_scenarios() -> dict[str, PriceScenario]:
    """Scenariusze wbudowane (niski/bazowy/wysoki) z pliku danych."""
    raw = load_data_file("price_scenarios.yaml")["scenarios"]
    return {key: _build_scenario(key, item) for key, item in raw.items()}


def _user_dir() -> Path:
    path = data_dir() / USER_SCENARIOS_SUBDIR
    path.mkdir(parents=True, exist_ok=True)
    return path


def user_scenarios() -> dict[str, PriceScenario]:
    """Scenariusze użytkownika z ``data/user_scenarios/*.json``."""
    result: dict[str, PriceScenario] = {}
    for file in sorted(_user_dir().glob("*.json")):
        raw = json.loads(file.read_text(encoding="utf-8"))
        key = file.stem
        result[key] = _build_scenario(key, raw, user=True)
    return result


def all_scenarios() -> dict[str, PriceScenario]:
    """Scenariusze wbudowane + użytkownika (użytkownika nadpisują klucze)."""
    return {**builtin_scenarios(), **user_scenarios()}


def save_user_scenario(
    name: str, paths: dict[str, dict[int, float]], name_pl: str | None = None
) -> Path:
    """Zapisuje scenariusz użytkownika do JSON; zwraca ścieżkę pliku.

    Args:
        name: nazwa pliku/klucz (litery, cyfry, myślnik, podkreślenie),
        paths: {nośnik: {rok: wartość}} — walidowane jak scenariusze wbudowane,
        name_pl: nazwa wyświetlana (domyślnie = name).
    """
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", name):
        raise ValueError(
            "Nazwa scenariusza może zawierać tylko litery, cyfry, '-' i '_' " "(maks. 64 znaki)."
        )
    raw = {"name_pl": name_pl or name, "paths": paths}
    _build_scenario(name, raw, user=True)  # walidacja przed zapisem
    path = _user_dir() / f"{name}.json"
    path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def delete_user_scenario(name: str) -> None:
    """Usuwa scenariusz użytkownika (tylko z katalogu user_scenarios)."""
    path = _user_dir() / f"{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Brak scenariusza użytkownika '{name}'.")
    path.unlink()
