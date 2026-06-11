"""Testy składu gazu (core.composition)."""

import pytest

from core.composition import GasComposition, components_registry


class TestValidation:
    def test_sum_not_one_raises_polish(self):
        with pytest.raises(ValueError, match="Suma udziałów molowych"):
            GasComposition.from_fractions({"CH4": 0.9, "N2": 0.05})

    def test_unknown_component(self):
        with pytest.raises(ValueError, match="Nieznane składniki"):
            GasComposition.from_fractions({"XYZ": 1.0})

    def test_negative_fraction(self):
        with pytest.raises(ValueError, match="ujemne"):
            GasComposition.from_fractions({"CH4": 1.1, "N2": -0.1})

    def test_empty(self):
        with pytest.raises(ValueError, match="pusty"):
            GasComposition.from_fractions({"CH4": 0.0})

    def test_percent_input(self):
        comp = GasComposition.from_percent({"CH4": 95.0, "N2": 5.0})
        assert comp.fraction("CH4") == pytest.approx(0.95)

    def test_residual_renormalization(self):
        comp = GasComposition.from_fractions({"CH4": 0.95, "N2": 0.05 + 5e-5})
        assert sum(comp.as_dict().values()) == pytest.approx(1.0, abs=1e-12)


class TestProperties:
    def test_molar_mass_methane(self):
        assert GasComposition.pure("CH4").molar_mass_kg_per_kmol == pytest.approx(16.043, rel=1e-3)

    def test_molar_mass_mixture_linear(self):
        comp = GasComposition.from_fractions({"CH4": 0.5, "H2": 0.5})
        m_ch4 = GasComposition.pure("CH4").molar_mass_kg_per_kmol
        m_h2 = GasComposition.pure("H2").molar_mass_kg_per_kmol
        assert comp.molar_mass_kg_per_kmol == pytest.approx(0.5 * (m_ch4 + m_h2))

    def test_h2_mole_percent(self):
        comp = GasComposition.from_percent({"CH4": 90.0, "H2": 10.0})
        assert comp.h2_mole_percent == pytest.approx(10.0)


class TestBlending:
    def test_blend_endpoints(self):
        ng = GasComposition.predefined("gaz_E_typowy")
        assert ng.blend_with_hydrogen(0.0) == ng
        assert ng.blend_with_hydrogen(1.0) == GasComposition.pure("H2")

    def test_blend_h2_fraction(self):
        ng = GasComposition.predefined("gaz_E_typowy")
        blend = ng.blend_with_hydrogen(0.2)
        assert blend.h2_mole_percent == pytest.approx(20.0)
        # pozostałe składniki przeskalowane o (1 − y)
        assert blend.fraction("CH4") == pytest.approx(0.8 * ng.fraction("CH4"))

    def test_blend_out_of_range(self):
        ng = GasComposition.predefined("gaz_E_typowy")
        with pytest.raises(ValueError, match="0–1"):
            ng.blend_with_hydrogen(1.5)


class TestPredefined:
    def test_all_predefined_valid(self):
        from core.config import load_data_file

        for key in load_data_file("gas_compositions.yaml")["compositions"]:
            comp = GasComposition.predefined(key)
            assert sum(comp.as_dict().values()) == pytest.approx(1.0)

    def test_unknown_predefined(self):
        with pytest.raises(ValueError, match="Brak predefiniowanego składu"):
            GasComposition.predefined("nie_ma")

    def test_registry_has_required_components(self):
        required = {"CH4", "C2H6", "C3H8", "N2", "CO2", "O2", "He", "H2"}
        assert required <= set(components_registry())
