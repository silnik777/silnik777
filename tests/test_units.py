"""Testy jednostkowe modułu core.units."""

import math

import pytest

from core import units


class TestTemperature:
    def test_celsius_to_kelvin(self):
        assert units.celsius_to_kelvin(0.0) == pytest.approx(273.15)
        assert units.celsius_to_kelvin(-20.0) == pytest.approx(253.15)
        assert units.celsius_to_kelvin(60.0) == pytest.approx(333.15)

    def test_kelvin_to_celsius_roundtrip(self):
        assert units.kelvin_to_celsius(units.celsius_to_kelvin(15.0)) == pytest.approx(15.0)

    def test_below_absolute_zero_raises(self):
        with pytest.raises(ValueError, match="zera bezwzględnego"):
            units.celsius_to_kelvin(-300.0)
        with pytest.raises(ValueError):
            units.kelvin_to_celsius(-1.0)


class TestPressure:
    def test_bar_pa(self):
        assert units.bar_to_pa(1.0) == 1.0e5
        assert units.pa_to_bar(units.P_REFERENCE_PA) == pytest.approx(1.01325)

    def test_mpa_kpa(self):
        assert units.mpa_to_pa(10.0) == 1.0e7
        assert units.pa_to_mpa(1.0e7) == 10.0
        assert units.kpa_to_pa(101.325) == pytest.approx(units.P_REFERENCE_PA)


class TestEnergy:
    def test_kwh_mj(self):
        assert units.kwh_to_mj(1.0) == pytest.approx(3.6)
        assert units.mj_to_kwh(3.6) == pytest.approx(1.0)

    def test_j_kwh_roundtrip(self):
        assert units.j_to_kwh(units.kwh_to_j(2.5)) == pytest.approx(2.5)

    def test_j_to_mj(self):
        assert units.j_to_mj(1.0e6) == 1.0


class TestReferenceConditions:
    def test_molar_volume_normal(self):
        """Objętość molowa gazu doskonałego 0°C/101,325 kPa: 22,414 m³/kmol (CODATA)."""
        vm = units.NORMAL_0C.molar_volume_m3_per_kmol()
        assert vm == pytest.approx(22.41397, rel=1e-5)

    def test_molar_volume_15c(self):
        """V_m(288,15 K) = V_m(273,15 K) · 288,15/273,15 ≈ 23,645 m³/kmol."""
        vm = units.STANDARD_15C.molar_volume_m3_per_kmol()
        assert vm == pytest.approx(22.41397 * 288.15 / 273.15, rel=1e-5)

    def test_registry_keys(self):
        assert set(units.REFERENCE_CONDITIONS) == {"0C", "15C", "25C"}


class TestGasAmountConversions:
    M_CH4 = 16.043  # kg/kmol

    def test_nm3_to_kmol_roundtrip(self):
        n = units.volume_ref_to_kmol(1000.0)
        assert units.kmol_to_volume_ref(n) == pytest.approx(1000.0)

    def test_nm3_to_kg_methane(self):
        """1 Nm³ CH4 (gaz doskonały) = 16,043/22,414 ≈ 0,7158 kg."""
        mass = units.volume_ref_to_kg(1.0, self.M_CH4)
        assert mass == pytest.approx(0.71576, rel=1e-3)

    def test_kg_to_nm3_roundtrip(self):
        vol = units.kg_to_volume_ref(100.0, self.M_CH4)
        assert units.volume_ref_to_kg(vol, self.M_CH4) == pytest.approx(100.0)

    def test_reference_condition_matters(self):
        v0 = units.kg_to_volume_ref(1.0, self.M_CH4, units.NORMAL_0C)
        v15 = units.kg_to_volume_ref(1.0, self.M_CH4, units.STANDARD_15C)
        assert v15 / v0 == pytest.approx(288.15 / 273.15)

    def test_invalid_inputs_polish_messages(self):
        with pytest.raises(ValueError, match="musi być dodatnia"):
            units.volume_ref_to_kmol(-1.0)
        with pytest.raises(ValueError, match="Masa molowa"):
            units.volume_ref_to_kg(1.0, 0.0)

    def test_no_nan_propagation(self):
        with pytest.raises(ValueError):
            units.volume_ref_to_kmol(math.nan)
