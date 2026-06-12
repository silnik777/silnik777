"""Testy karty projektu (M14): zapis, porównanie, eksport."""

import pytest

from core import config
from core.export import export_csv, export_xlsx, projects_dataframe
from core.project_card import (
    ComparisonResult,
    ProjectCard,
    compare_projects,
    criteria_registry,
    delete_project,
    load_projects,
    save_project,
)


@pytest.fixture(autouse=True)
def _isolated_data_dir(tmp_path, monkeypatch):
    import shutil

    for f in config.data_dir().glob("*.yaml"):
        shutil.copy(f, tmp_path / f.name)
    monkeypatch.setenv("GAS_RD_DATA_DIR", str(tmp_path))
    config.clear_cache()
    yield
    config.clear_cache()


CARD_A = ProjectCard(
    name="Ekspander stacja I",
    description="Turboekspander 5,5→1,7 MPa",
    indicators={"trl": 9, "lcox": 380.0, "npv": 2.5, "redukcja_emisji": 1200.0},
)
CARD_B = ProjectCard(
    name="Elektrolizer PEM",
    description="PEM 1 MW przy stacji",
    indicators={"trl": 9, "lcox": 30.0, "npv": -0.5, "redukcja_emisji": 300.0},
)
CARD_C = ProjectCard(
    name="Zimna redukcja",
    description="Bez podgrzewu, odzysk chłodu",
    indicators={"trl": 6, "lcox": 100.0, "npv": 1.0, "redukcja_emisji": 800.0},
)


class TestRegistry:
    def test_three_categories(self):
        cats = {c.category for c in criteria_registry().values()}
        assert cats == {"techniczne", "ekonomiczne", "ekologiczne"}

    def test_each_criterion_has_module_hint(self):
        for c in criteria_registry().values():
            assert c.gdzie_policzyc  # wskazówka "gdzie policzyć" dla użytkownika

    def test_unknown_indicator_rejected(self):
        with pytest.raises(ValueError, match="Nieznane wskaźniki"):
            ProjectCard(name="X", description="", indicators={"moc_sprawcza": 1.0})


class TestSaveLoad:
    def test_roundtrip(self):
        save_project(CARD_A)
        loaded = load_projects()
        assert "Ekspander_stacja_I" in loaded
        card = loaded["Ekspander_stacja_I"]
        assert card.indicators["lcox"] == 380.0
        assert card.description.startswith("Turboekspander")

    def test_delete(self):
        save_project(CARD_B)
        delete_project("Elektrolizer_PEM")
        assert "Elektrolizer_PEM" not in load_projects()
        with pytest.raises(FileNotFoundError):
            delete_project("Elektrolizer_PEM")

    def test_bad_name(self):
        with pytest.raises(ValueError, match="litery lub cyfry"):
            save_project(ProjectCard(name="???", description="", indicators={}))


class TestComparison:
    def test_requires_two(self):
        with pytest.raises(ValueError, match="dwóch projektów"):
            compare_projects([CARD_A])

    def test_directions_respected(self):
        """Niższy LCOx i wyższy NPV podnoszą ocenę."""
        result = compare_projects(
            [CARD_A, CARD_B],
            weights={"lcox": 1.0, "trl": 0, "npv": 0, "redukcja_emisji": 0},
        )
        assert result.ranked[0].card.name == "Elektrolizer PEM"  # niższy lcox
        result2 = compare_projects(
            [CARD_A, CARD_B],
            weights={"npv": 1.0, "trl": 0, "lcox": 0, "redukcja_emisji": 0},
        )
        assert result2.ranked[0].card.name == "Ekspander stacja I"  # wyższy npv

    def test_missing_criterion_skipped(self):
        """Kryterium bez wartości w którymś projekcie — pomijane z listą."""
        partial = ProjectCard(name="P", description="", indicators={"trl": 5})
        result = compare_projects([CARD_A, partial])
        assert "lcox" in result.skipped_criteria
        assert result.used_criteria == ["trl"]

    def test_scores_in_unit_range_and_sorted(self):
        result = compare_projects([CARD_A, CARD_B, CARD_C])
        scores = [r.score for r in result.ranked]
        assert scores == sorted(scores, reverse=True)
        assert all(0.0 <= s <= 1.0 for s in scores)


class TestExport:
    def test_xlsx_roundtrip(self, tmp_path):
        import pandas as pd

        comparison = compare_projects([CARD_A, CARD_B, CARD_C])
        blob = export_xlsx([CARD_A, CARD_B, CARD_C], comparison)
        path = tmp_path / "eksport.xlsx"
        path.write_bytes(blob)
        sheets = pd.read_excel(path, sheet_name=None)
        assert set(sheets) == {"Projekty", "Ranking", "Kryteria"}
        assert len(sheets["Projekty"]) == 3
        assert sheets["Ranking"].iloc[0]["Miejsce"] == 1

    def test_csv_polish_excel_friendly(self):
        blob = export_csv([CARD_A, CARD_B])
        assert blob.startswith("﻿".encode())  # BOM
        text = blob.decode("utf-8-sig")
        assert ";" in text.splitlines()[0]
        assert "Ekspander stacja I" in text

    def test_dataframe_has_all_criteria_columns(self):
        df = projects_dataframe([CARD_A])
        for crit in criteria_registry().values():
            assert any(crit.name_pl in col for col in df.columns)


class TestComparisonResultType:
    def test_result_fields(self):
        result = compare_projects([CARD_A, CARD_B])
        assert isinstance(result, ComparisonResult)
        assert set(result.used_criteria).isdisjoint(result.skipped_criteria)
