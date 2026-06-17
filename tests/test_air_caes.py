"""Testy obsługi powietrza (M3) i trybu CAES w linepacku (M12)."""

import pytest

from core.composition import GasComposition
from core.gas_properties import compute_properties
from core.linepack import linepack
from core.pipeline import max_mass_flow_kg_per_s, pressure_profile
from core.units import bar_to_pa

AIR = GasComposition.predefined("powietrze")
E_GAS = GasComposition.predefined("gaz_E_typowy")


class TestAirComposition:
    def test_air_not_combustible(self):
        assert not AIR.is_combustible
        assert E_GAS.is_combustible

    def test_air_density_reference(self):
        """Gęstość suchego powietrza w war. normalnych ≈ 1,293 kg/m³."""
        rho = compute_properties(AIR, 101_325.0, 273.15).density_kg_per_m3
        assert rho == pytest.approx(1.293, rel=0.01)

    def test_air_molar_mass(self):
        """Masa molowa powietrza ≈ 28,96 kg/kmol."""
        assert AIR.molar_mass_kg_per_kmol == pytest.approx(28.96, rel=0.005)

    def test_argon_present(self):
        from core.composition import components_registry

        assert "Ar" in components_registry()


class TestAirPipeline:
    def test_air_flow_computable(self):
        """M3 liczy hydraulikę dla powietrza (mimo zerowej wartości opałowej)."""
        d, length, rough = 0.3, 10_000.0, 5e-5
        m_max = max_mass_flow_kg_per_s(AIR, d, length, rough, bar_to_pa(55), bar_to_pa(45), 283.15)
        res = pressure_profile(AIR, d, length, rough, m_max, bar_to_pa(55), 283.15)
        assert res.mass_flow_kg_per_s > 0
        assert res.max_velocity_m_per_s > 0
        assert res.energy_flow_mw() == 0.0  # niepalny


class TestCAES:
    ARGS = dict(
        diameter_m=0.5,
        length_m=50_000.0,
        pressure_min_pa=bar_to_pa(40),
        pressure_max_pa=bar_to_pa(70),
        temperature_k=283.15,
    )

    def test_air_caes_mode(self):
        res = linepack(AIR, **self.ARGS)
        assert not res.is_combustible
        assert res.buffer_energy_mwh == 0.0  # brak energii chemicznej
        assert res.caes_recovered_mwh > 0.0
        assert res.compression_kwh_el > 0.0

    def test_round_trip_below_one_and_plausible(self):
        """Round-trip diabatyczny CAES: dodatni, < 1, rozsądnie 30–80%."""
        res = linepack(AIR, **self.ARGS)
        assert 0.2 < res.caes_round_trip_efficiency < 1.0

    def test_recovered_less_than_input(self):
        """Energia odzyskana < energia napełnienia (II zasada)."""
        res = linepack(AIR, **self.ARGS)
        assert res.caes_recovered_mwh * 1e3 < res.compression_kwh_el

    def test_buffer_hours_uses_caes_energy_for_air(self):
        res = linepack(AIR, **self.ARGS)
        assert res.buffer_hours_at_load(10.0) == pytest.approx(res.caes_recovered_mwh / 10.0)

    def test_combustible_gas_keeps_chemical_buffer(self):
        res = linepack(E_GAS, **self.ARGS)
        assert res.is_combustible
        assert res.buffer_energy_mwh > 0.0
        # czas pokrycia liczony z energii chemicznej
        assert res.buffer_hours_at_load(10.0) == pytest.approx(res.buffer_energy_mwh / 10.0)
