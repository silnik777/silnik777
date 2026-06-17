"""Testy liczby metanowej (core.methane_number) — model liniowy."""

import pytest

from core.composition import GasComposition
from core.methane_number import methane_number, methane_number_assessment


class TestDefinitionAnchors:
    def test_pure_methane_is_100(self):
        """MN(CH4) = 100 — reper definicyjny."""
        assert methane_number(GasComposition.pure("CH4")) == pytest.approx(100.0)

    def test_pure_hydrogen_is_0(self):
        """MN(H2) = 0 — reper definicyjny."""
        assert methane_number(GasComposition.pure("H2")) == pytest.approx(0.0)

    def test_ch4_h2_blend_is_exact_vol_percent(self):
        """Na osi CH4/H2 model liniowy jest ścisły: MN = % mol CH4 (def. Leiker).

        50% mol CH4 / 50% H2 ⇒ MN = 50.
        """
        blend = GasComposition.from_percent({"CH4": 50.0, "H2": 50.0})
        assert methane_number(blend) == pytest.approx(50.0)


class TestBehaviour:
    def test_h2_blend_monotonic_decrease(self):
        base = GasComposition.predefined("gaz_E_typowy")
        values = [methane_number(base.blend_with_hydrogen(x / 100.0)) for x in (0, 10, 20, 40)]
        assert values == sorted(values, reverse=True)

    def test_e_gas_plausible_range(self):
        """Gaz E (chudy, ~96% CH4): MN wysoka, blisko 90–100."""
        mn = methane_number(GasComposition.predefined("gaz_E_typowy"))
        assert 88.0 < mn < 100.0

    def test_heavier_hydrocarbons_lower_mn(self):
        """Więcej propanu obniża MN (cięższe HC łatwiej stukają)."""
        rich = GasComposition.from_percent({"CH4": 85.0, "C3H8": 15.0})
        assert methane_number(rich) < 100.0

    def test_inert_neutral(self):
        """Inerty traktowane neutralnie (=100) — nie obniżają MN."""
        with_n2 = GasComposition.from_percent({"CH4": 90.0, "N2": 10.0})
        assert methane_number(with_n2) == pytest.approx(100.0)


class TestAssessment:
    def test_flag_ok_for_natural_gas(self):
        result = methane_number_assessment(GasComposition.predefined("gaz_E_typowy"))
        assert result.ok
        assert result.value > result.min_limit

    def test_flag_fails_for_high_h2(self):
        """Duża domieszka H2 zbija MN poniżej limitu silnikowego."""
        blend = GasComposition.predefined("gaz_E_typowy").blend_with_hydrogen(0.50)
        result = methane_number_assessment(blend)
        assert not result.ok

    def test_air_has_no_methane_number_meaning(self):
        """Powietrze: niepalne — MN liczona formalnie (inerty=100), ale gaz
        nie jest paliwem; sprawdzamy tylko, że nie wybucha wyjątkiem."""
        mn = methane_number(GasComposition.predefined("powietrze"))
        assert mn == pytest.approx(100.0)  # same inerty w modelu
