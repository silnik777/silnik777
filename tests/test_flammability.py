"""Testy granic wybuchowości (core.flammability) i przewodności cieplnej."""

import pytest

from core.composition import GasComposition
from core.flammability import flammability_limits
from core.gas_properties import compute_properties

E_GAS = GasComposition.predefined("gaz_E_typowy")


class TestFlammability:
    def test_pure_methane_reference(self):
        """CH4: LEL 5,0 / UEL 15,0 %obj (wartości referencyjne)."""
        f = flammability_limits(GasComposition.pure("CH4"))
        assert f.lel_vol_pct == pytest.approx(5.0, abs=0.01)
        assert f.uel_vol_pct == pytest.approx(15.0, abs=0.01)

    def test_pure_hydrogen_reference(self):
        f = flammability_limits(GasComposition.pure("H2"))
        assert f.lel_vol_pct == pytest.approx(4.0, abs=0.01)
        assert f.uel_vol_pct == pytest.approx(75.0, abs=0.01)

    def test_e_gas_near_methane(self):
        """Gaz E ≈ metan: LEL ~4,8–5,0; cięższe HC lekko obniżają LEL."""
        f = flammability_limits(E_GAS)
        assert 4.5 < f.lel_vol_pct < 5.0
        assert 14.0 < f.uel_vol_pct < 15.5

    def test_hydrogen_widens_uel(self):
        """Domieszka H2 (UEL 75%) podnosi górną granicę mieszaniny."""
        base = flammability_limits(E_GAS)
        blend = flammability_limits(E_GAS.blend_with_hydrogen(0.20))
        assert blend.uel_vol_pct > base.uel_vol_pct

    def test_le_chatelier_formula(self):
        """Weryfikacja wzoru: 50/50 CH4/C3H8 (molowo)."""
        mix = GasComposition.from_percent({"CH4": 50.0, "C3H8": 50.0})
        f = flammability_limits(mix)
        expected_lel = 1.0 / (0.5 / 5.0 + 0.5 / 2.1)
        assert f.lel_vol_pct == pytest.approx(expected_lel, rel=1e-6)

    def test_noncombustible_returns_none(self):
        assert flammability_limits(GasComposition.predefined("powietrze")) is None

    def test_inert_note_present(self):
        """Biometan (z CO2/N2) — nota o inertach zawężających zakres."""
        f = flammability_limits(GasComposition.predefined("biometan"))
        assert f.combustible_fraction < 1.0
        assert "niepalnych" in f.note


class TestThermalConductivity:
    def test_methane_conductivity_plausible(self):
        """λ metanu ~33 mW/(m·K) w warunkach zbliżonych do normalnych."""
        p = compute_properties(GasComposition.pure("CH4"), 101_325.0, 288.15)
        assert p.thermal_conductivity_w_per_m_k is not None
        assert 0.030 < p.thermal_conductivity_w_per_m_k < 0.037

    def test_conductivity_present_for_e_gas(self):
        p = compute_properties(E_GAS, 5e5, 288.15)
        assert p.thermal_conductivity_w_per_m_k is not None
        assert p.thermal_conductivity_w_per_m_k > 0.0
